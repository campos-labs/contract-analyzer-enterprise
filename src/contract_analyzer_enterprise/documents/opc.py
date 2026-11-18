"""Read an inert, bounded subset of a Transitional DOCX package."""

import re
import stat
import zlib
from dataclasses import dataclass
from io import BytesIO
from string import ascii_lowercase, ascii_uppercase
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
OFFICE_REL = (
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
)
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
MAIN_TYPE = (
    'application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml'
)
REL_TYPE = 'application/vnd.openxmlformats-package.relationships+xml'
CONTENT_TYPES = '[Content_Types].xml'
ROOT_RELS = '_rels/.rels'
_ASCII_FOLD = str.maketrans(ascii_uppercase, ascii_lowercase)
_BAD_PERCENT = re.compile(r'%(?![a-fA-F0-9]{2})')
_INVALID_SEGMENT = re.compile(r'[\\/:?#\x00-\x1f\x7f]')
_BAD_CONTENT_TYPE = re.compile(r'[^\s/;]+/[^\s/;]+\Z')
_ACTIVE_TYPES = (
    'macroenabled',
    'vbaproject',
    'vbadata',
    'activex',
    'oleobject',
)
_ACTIVE_RELATIONS = frozenset({
    'afchunk',
    'altchunk',
    'attachedtemplate',
    'control',
    'oleobject',
    'package',
    'subdocument',
    'vbadata',
    'vbaproject',
    'activexcontrol',
    'activexcontrolbinary',
})
_ACTIVE_MARKUP = frozenset({
    f'{{{W}}}altChunk',
    f'{{{W}}}control',
    f'{{{W}}}object',
    f'{{{W}}}subDoc',
    '{urn:schemas-microsoft-com:office:office}OLEObject',
})
_CHUNK = 64 * 1024
_MAX_PART_NAME = 1024
_UNSUPPORTED_FLAGS = 0x0001 | 0x0020 | 0x0040 | 0x2000


class PackageError(ValueError):
    """Invalid, unsafe or unsupported DOCX package."""


@dataclass(frozen=True, slots=True)
class PackageLimits:
    max_input_bytes: int = 32 * 1024 * 1024
    max_expanded_bytes: int = 64 * 1024 * 1024
    max_member_bytes: int = 32 * 1024 * 1024
    max_entries: int = 2048
    max_xml_nodes: int = 250_000

    def __post_init__(self):
        caps = (
            self.max_input_bytes,
            self.max_expanded_bytes,
            self.max_member_bytes,
            self.max_entries,
            self.max_xml_nodes,
        )
        if any(type(cap) is not int or cap <= 0 for cap in caps):
            msg = 'Limites do pacote DOCX devem ser inteiros positivos.'
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExternalRelationship:
    source: str
    kind: str


@dataclass(frozen=True, slots=True)
class PartRelationship:
    source: str
    kind: str
    target: str


@dataclass(frozen=True, slots=True)
class DocxPackage:
    main_part: str
    trees: dict[str, etree._Element]
    names: tuple[str, ...]
    content_types: dict[str, str]
    relationships: tuple[PartRelationship, ...]
    external_relationships: tuple[ExternalRelationship, ...]
    xml_node_count: int

    def related_part(self, source: str, kind: str) -> str | None:
        """Look up a singleton relationship defined by WordprocessingML."""
        targets = [
            rel.target
            for rel in self.relationships
            if rel.source == source and rel.kind == OFFICE_REL + kind
        ]
        if len(targets) > 1:
            msg = f'Relação DOCX ambígua: {kind}.'
            raise PackageError(msg)
        return targets[0] if targets else None


def _decode_segment(segment: str) -> str:
    if _BAD_PERCENT.search(segment):
        msg = 'Nome de parte DOCX com escape inválido.'
        raise PackageError(msg)
    decoded = unquote(segment, errors='strict')
    if (
        not decoded
        or decoded.endswith('.')
        or _INVALID_SEGMENT.search(decoded)
    ):
        msg = 'Nome de parte DOCX inválido ou inseguro.'
        raise PackageError(msg)
    return decoded.translate(_ASCII_FOLD)


def _part_key(name: str) -> str:
    if len(name) > _MAX_PART_NAME:
        msg = 'Nome de parte DOCX excede o limite.'
        raise PackageError(msg)
    return '/'.join(_decode_segment(segment) for segment in name.split('/'))


def _member_key(member: ZipInfo, limits: PackageLimits) -> str:
    name = member.orig_filename
    mode = stat.S_IFMT(member.external_attr >> 16)
    allowed_mode = stat.S_IFDIR if member.is_dir() else stat.S_IFREG
    if name != member.filename:
        raise PackageError('Entrada ZIP insegura ou não suportada.')
    if (
        member.flag_bits & _UNSUPPORTED_FLAGS
        or mode not in {0, allowed_mode}
        or member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
        or (member.is_dir() and member.file_size)
    ):
        msg = 'Entrada ZIP insegura ou não suportada.'
        raise PackageError(msg)
    if member.file_size > limits.max_member_bytes:
        msg = 'Limite de expansão por entrada ZIP excedido.'
        raise PackageError(msg)
    return _part_key(name.removesuffix('/') if member.is_dir() else name)


def _members(package: ZipFile, limits: PackageLimits) -> dict[str, ZipInfo]:
    entries = package.infolist()
    if len(entries) > limits.max_entries:
        msg = 'Limite de entradas ZIP excedido.'
        raise PackageError(msg)
    if sum(entry.file_size for entry in entries) > limits.max_expanded_bytes:
        msg = 'Limite de expansão total do ZIP excedido.'
        raise PackageError(msg)
    all_members: dict[str, ZipInfo] = {}
    for member in entries:
        key = _member_key(member, limits)
        if key in all_members:
            msg = 'Nomes de partes DOCX duplicados ou equivalentes.'
            raise PackageError(msg)
        all_members[key] = member
    files = {
        key: entry for key, entry in all_members.items() if not entry.is_dir()
    }
    for key in all_members:
        parent = key.rpartition('/')[0]
        while parent:
            if parent in files:
                msg = 'Uma parte DOCX também é prefixo de outra entrada.'
                raise PackageError(msg)
            parent = parent.rpartition('/')[0]
    return files


class _PackageReader:
    def __init__(self, package: ZipFile, limits: PackageLimits):
        self.package = package
        self.limits = limits
        self.xml_nodes = 0
        self.expanded_bytes = 0

    def _consume(self, member: ZipInfo, parser: etree.XMLPullParser | None):
        read_bytes = 0
        # Read to EOF even for binary parts so CRC is checked by zipfile.
        with self.package.open(member) as stream:
            while chunk := stream.read(_CHUNK):
                read_bytes += len(chunk)
                self.expanded_bytes += len(chunk)
                if (
                    read_bytes > self.limits.max_member_bytes
                    or self.expanded_bytes > self.limits.max_expanded_bytes
                ):
                    msg = (
                        'Limite de expansão do ZIP excedido durante a leitura.'
                    )
                    raise PackageError(msg)
                if parser is not None:
                    parser.feed(chunk)
                    self._count_nodes(parser)
        if read_bytes != member.file_size:
            msg = 'Tamanho de entrada ZIP difere do tamanho declarado.'
            raise PackageError(msg)

    def _count_nodes(self, parser: etree.XMLPullParser):
        for _, element in parser.read_events():
            if element.tag in _ACTIVE_MARKUP:
                msg = 'Conteúdo ativo DOCX não permitido.'
                raise PackageError(msg)
            self.xml_nodes += 1
            if self.xml_nodes > self.limits.max_xml_nodes:
                msg = 'Limite de elementos XML do DOCX excedido.'
                raise PackageError(msg)

    def xml(self, member: ZipInfo) -> etree._Element:
        parser = etree.XMLPullParser(
            events=('start',),
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            recover=False,
            huge_tree=False,
            collect_ids=False,
            remove_comments=True,
            remove_pis=True,
        )
        self._consume(member, parser)
        root = parser.close()
        self._count_nodes(parser)
        if root.getroottree().docinfo.doctype:
            msg = 'Declaração DTD não permitida no DOCX.'
            raise PackageError(msg)
        return root

    def binary(self, member: ZipInfo):
        self._consume(member, None)


def _manifest(
    root: etree._Element,
    members: dict[str, ZipInfo],
) -> dict[str, str]:
    if root.tag != f'{{{TYPES}}}Types':
        msg = 'Manifesto de tipos DOCX inválido.'
        raise PackageError(msg)
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for node in root:
        content_type = node.get('ContentType', '').partition(';')[0].lower()
        if not _BAD_CONTENT_TYPE.fullmatch(content_type):
            msg = 'Tipo de conteúdo ausente ou inválido no manifesto DOCX.'
            raise PackageError(msg)
        if node.tag == f'{{{TYPES}}}Default':
            target = defaults
            key = node.get('Extension', '').translate(_ASCII_FOLD)
            if not key or not key.isascii() or not key.isalnum():
                msg = 'Extensão de conteúdo inválida no manifesto DOCX.'
                raise PackageError(msg)
        elif node.tag == f'{{{TYPES}}}Override':
            target = overrides
            name = node.get('PartName', '')
            if not name.startswith('/'):
                msg = 'Nome de parte ausente no manifesto DOCX.'
                raise PackageError(msg)
            key = _part_key(name[1:])
            if key not in members or key == _part_key(CONTENT_TYPES):
                msg = 'Manifesto aponta para uma parte DOCX inexistente.'
                raise PackageError(msg)
        else:
            msg = 'Elemento inválido no manifesto de tipos DOCX.'
            raise PackageError(msg)
        if key in target:
            msg = 'Tipos de conteúdo duplicados no manifesto DOCX.'
            raise PackageError(msg)
        target[key] = content_type
    return _resolve_content_types(members, defaults, overrides)


def _resolve_content_types(
    members: dict[str, ZipInfo],
    defaults: dict[str, str],
    overrides: dict[str, str],
) -> dict[str, str]:
    result = {}
    manifest_key = _part_key(CONTENT_TYPES)
    for key, member in members.items():
        if key == manifest_key:
            continue
        ext = key.rpartition('/')[2].rpartition('.')[2]
        content_type = overrides.get(key) or defaults.get(ext)
        if content_type is None:
            msg = 'Parte DOCX sem tipo de conteúdo declarado.'
            raise PackageError(msg)
        if (
            any(marker in content_type for marker in _ACTIVE_TYPES)
            or {'embeddings', 'activex'}.intersection(key.split('/'))
            or key.rpartition('/')[2].startswith(('vbaproject', 'vbadata'))
        ):
            msg = 'Parte DOCX com conteúdo ativo ou pacote incorporado.'
            raise PackageError(msg)
        result[member.filename] = content_type
    return result


def _xml_part(name: str, content_type: str) -> bool:
    return name.lower().endswith(('.xml', '.rels')) or content_type.endswith((
        '+xml',
        '/xml',
    ))


def _relationship_source(
    name: str,
    members: dict[str, ZipInfo],
    content_types: dict[str, str],
) -> str:
    key = _part_key(name)
    if key == ROOT_RELS:
        return ''
    path, _, tail = key.rpartition('/')
    directory, _, rels = path.rpartition('/')
    if rels != '_rels' or not tail.endswith('.rels'):
        msg = 'Localização de relações OPC inválida.'
        raise PackageError(msg)
    target = members.get((directory + '/' if directory else '') + tail[:-5])
    if target is None or content_types.get(target.filename) in {
        None,
        REL_TYPE,
    }:
        msg = 'Parte de relações DOCX sem parte de origem válida.'
        raise PackageError(msg)
    return target.filename


def _internal_target(
    source: str,
    target: str,
    members: dict[str, ZipInfo],
    content_types: dict[str, str],
) -> str:
    path = urlsplit(target)
    if path.scheme or path.netloc or path.query or not path.path:
        msg = 'Relação interna DOCX com destino inválido.'
        raise PackageError(msg)
    segments = _part_key(source).split('/')[:-1] if source else []
    relative = path.path
    if relative.startswith('/'):
        segments = []
        relative = relative[1:]
    for segment in relative.split('/'):
        if segment == '..':
            if not segments:
                msg = 'Relação DOCX escapa da raiz do pacote.'
                raise PackageError(msg)
            segments.pop()
        elif segment != '.':
            segments.append(_decode_segment(segment))
    member = members.get('/'.join(segments))
    if member is None or content_types.get(member.filename) in {
        None,
        REL_TYPE,
    }:
        msg = 'Relação DOCX aponta para uma parte inexistente ou inválida.'
        raise PackageError(msg)
    return member.filename


def _relation(
    node: etree._Element,
    source: str,
    members: dict[str, ZipInfo],
    content_types: dict[str, str],
) -> PartRelationship | ExternalRelationship:
    kind = node.get('Type', '')
    target = node.get('Target', '')
    if (
        not urlsplit(kind).scheme
        or not target
        or len(target) > _MAX_PART_NAME
        or re.search(r'[\\\x00-\x1f\x7f]', target)
        or target.startswith('//')
    ):
        msg = 'Relação DOCX com tipo ou destino inválido.'
        raise PackageError(msg)
    mode = node.get('TargetMode', 'Internal')
    if kind.rpartition('/')[2].lower() in _ACTIVE_RELATIONS:
        msg = 'Relação DOCX de conteúdo ativo ou incorporado não permitida.'
        raise PackageError(msg)
    if mode == 'Internal':
        return PartRelationship(
            source,
            kind,
            _internal_target(source, target, members, content_types),
        )
    if (
        mode == 'External'
        and kind == OFFICE_REL + 'hyperlink'
        and urlsplit(target).scheme in {'http', 'https', 'mailto'}
    ):
        return ExternalRelationship(source, kind)
    msg = 'Modo ou relação externa DOCX não permitido.'
    raise PackageError(msg)


def _read_relationships(
    trees: dict[str, etree._Element],
    members: dict[str, ZipInfo],
    content_types: dict[str, str],
) -> tuple[tuple[PartRelationship, ...], tuple[ExternalRelationship, ...]]:
    relationships = []
    external = []
    for name, root in trees.items():
        content_type = content_types.get(name)
        if content_type != REL_TYPE and not name.lower().endswith('.rels'):
            continue
        if content_type != REL_TYPE or root.tag != f'{{{REL}}}Relationships':
            msg = 'Parte de relações OPC inválida.'
            raise PackageError(msg)
        source = _relationship_source(name, members, content_types)
        ids = set()
        for node in root:
            identifier = node.get('Id')
            if (
                node.tag != f'{{{REL}}}Relationship'
                or not identifier
                or identifier in ids
            ):
                msg = 'Relação DOCX inválida ou com identificador duplicado.'
                raise PackageError(msg)
            ids.add(identifier)
            relationship = _relation(node, source, members, content_types)
            if isinstance(relationship, PartRelationship):
                relationships.append(relationship)
            else:
                external.append(relationship)
    return tuple(relationships), tuple(external)


def _main_part(
    trees: dict[str, etree._Element],
    content_types: dict[str, str],
    relationships: tuple[PartRelationship, ...],
) -> str:
    main_parts = [
        rel.target
        for rel in relationships
        if not rel.source and rel.kind == OFFICE_REL + 'officeDocument'
    ]
    if len(main_parts) != 1 or content_types.get(main_parts[0]) != MAIN_TYPE:
        msg = 'DOCX Transitional requer uma única parte principal declarada.'
        raise PackageError(msg)
    main = main_parts[0]
    root = trees.get(main)
    if (
        root is None
        or root.tag != f'{{{W}}}document'
        or len(root.findall(f'{{{W}}}body')) != 1
    ):
        msg = 'Parte principal DOCX inválida ou sem corpo único.'
        raise PackageError(msg)
    return main


def _read_open_package(package: ZipFile, limits: PackageLimits) -> DocxPackage:
    members = _members(package, limits)
    manifest = members.get(_part_key(CONTENT_TYPES))
    if manifest is None or manifest.filename != CONTENT_TYPES:
        msg = 'DOCX sem manifesto [Content_Types].xml.'
        raise PackageError(msg)
    reader = _PackageReader(package, limits)
    content_types = _manifest(reader.xml(manifest), members)
    trees = {}
    for member in members.values():
        name = member.filename
        if member is manifest:
            continue
        if _xml_part(name, content_types[name]):
            trees[name] = reader.xml(member)
        else:
            reader.binary(member)
    relationships, external = _read_relationships(
        trees, members, content_types
    )
    main = _main_part(trees, content_types, relationships)
    return DocxPackage(
        main,
        trees,
        tuple(entry.filename for entry in members.values()),
        content_types,
        relationships,
        external,
        reader.xml_nodes,
    )


def read_package(
    raw: bytes, limits: PackageLimits = PackageLimits()
) -> DocxPackage:
    """Validate ZIP/OPC and parse XML without extraction or dereference."""
    if len(raw) > limits.max_input_bytes:
        msg = 'Limite de tamanho do DOCX comprimido excedido.'
        raise PackageError(msg)
    try:
        with ZipFile(BytesIO(raw)) as package:
            return _read_open_package(package, limits)
    except PackageError:
        raise
    except (
        BadZipFile,
        etree.XMLSyntaxError,
        EOFError,
        UnicodeError,
        ValueError,
        zlib.error,
    ) as exc:
        # Parser exceptions may contain document text or relationship targets.
        msg = 'Pacote DOCX com ZIP, XML ou relações malformados.'
        raise PackageError(msg) from exc
