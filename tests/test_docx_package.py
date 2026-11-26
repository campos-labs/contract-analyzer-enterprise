"""Exercise DOCX package validation with small, independent OPC documents."""

import stat
from zipfile import ZipInfo

import pytest
from docx_helpers import MAIN, OFFICE_REL, REL, W, make_parts, package_bytes

from contract_analyzer_enterprise.documents.opc import (
    ExternalRelationship,
    PackageError,
    PackageLimits,
    read_package,
)

PAYLOAD = b'opaque-media-used-to-trigger-crc'


def test_opc_discovers_relocated_xml_parts_and_keeps_external_links_inert():
    parts = make_parts('parts/content/doc.xml')
    parts['parts/_rels/'] = b''
    parts['parts/styles.xml'] = f'<w:styles xmlns:w="{W}"/>'
    parts['parts/content/_rels/doc.xml.rels'] = (
        f'<Relationships xmlns="{REL}">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL}styles" '
        'Target="../styles.xml"/>'
        f'<Relationship Id="rId2" Type="{OFFICE_REL}hyperlink" '
        'TargetMode="External" Target="https://example.invalid/?token=abc"/>'
        '</Relationships>'
    )

    package = read_package(package_bytes(parts))

    assert package.main_part == 'parts/content/doc.xml'
    assert (
        package.related_part(package.main_part, 'styles') == 'parts/styles.xml'
    )
    assert package.external_relationships == (
        ExternalRelationship(package.main_part, OFFICE_REL + 'hyperlink'),
    )
    assert 'parts/_rels/' not in package.names


@pytest.mark.parametrize('removed', ['[Content_Types].xml', '_rels/.rels'])
def test_metadata_parts_required(removed):
    parts = make_parts()
    del parts[removed]
    with pytest.raises(PackageError, match='DOCX'):
        read_package(package_bytes(parts))


@pytest.mark.parametrize(
    'bad_name',
    [
        'word/DOCUMENT.xml',
        'word/%64ocument.xml',
        '../../../../x.xml',
        'a/%2f.xml',
        'a/%5c.xml',
        'a/%00.xml',
        '/x.xml',
        'word/document.xml/child.xml',
    ],
)
def test_unsafe_or_colliding_member_rejected(bad_name):
    parts = make_parts()
    parts[bad_name] = '<placeholder/>'
    with pytest.raises(PackageError, match=r'partes? DOCX'):
        read_package(package_bytes(parts))


def test_backslash_in_raw_zip_name_is_rejected():
    parts = make_parts()
    parts['word!x.xml'] = '<placeholder/>'
    malformed = package_bytes(parts).replace(b'word!x.xml', b'word\\x.xml')
    with pytest.raises(PackageError, match=r'Entrada ZIP|parte DOCX'):
        read_package(malformed)


def test_symbolic_link_member_rejected():
    parts = make_parts()
    link = ZipInfo('link.xml')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    parts[link] = 'word/document.xml'
    with pytest.raises(PackageError, match='Entrada ZIP insegura'):
        read_package(package_bytes(parts))


def test_nul_hidden_from_normalized_zipinfo_filename_is_rejected():
    parts = make_parts()
    parts['partXX.xml'] = '<anotherPart/>'
    malformed = package_bytes(parts).replace(b'partXX.xml', b'part\x00X.xml')
    with pytest.raises(PackageError, match='Entrada ZIP insegura'):
        read_package(malformed)


def test_utf16_doctype_is_rejected():
    parts = make_parts()
    parts[MAIN] = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE w:document [<!ENTITY embedded "test">]>'
        f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&embedded;'
        '</w:t></w:r></w:p></w:body></w:document>'
    ).encode('utf-16')

    with pytest.raises(PackageError, match='DTD'):
        read_package(package_bytes(parts))


def test_broken_xml_is_rejected_in_unrelated_parts_too():
    parts = make_parts()
    parts['unrelated.xml'] = '<mismatched></broken>'
    with pytest.raises(PackageError, match='malformados'):
        read_package(package_bytes(parts))


@pytest.mark.parametrize('target', ['../../word/document.xml', 'missing.xml'])
def test_relationship_cannot_escape_or_reference_missing_part(target):
    parts = make_parts()
    parts['_rels/.rels'] = str(parts['_rels/.rels']).replace(MAIN, target)
    with pytest.raises(PackageError, match='Relação DOCX'):
        read_package(package_bytes(parts))


@pytest.mark.parametrize(
    ('kind', 'target'),
    [
        ('image', 'https://example.invalid/external.png'),
        ('attachedTemplate', 'https://example.invalid/template.dotm'),
        ('hyperlink', 'file:///privado.txt'),
    ],
)
def test_external_materialization_and_other_schemes_are_rejected(kind, target):
    parts = make_parts()
    parts['word/_rels/document.xml.rels'] = (
        f'<Relationships xmlns="{REL}"><Relationship Id="a" '
        f'Type="{OFFICE_REL}{kind}" '
        f'TargetMode="External" Target="{target}"/></Relationships>'
    )
    with pytest.raises(PackageError, match='DOCX'):
        read_package(package_bytes(parts))


def test_active_payload_rejected_even_without_relationship():
    parts = make_parts()
    parts['word/vbaProject.bin'] = PAYLOAD
    with pytest.raises(PackageError, match='conteúdo ativo'):
        read_package(package_bytes(parts))


def test_binary_part_crc_is_checked():
    parts = make_parts()
    parts['word/opaque.bin'] = PAYLOAD
    broken = package_bytes(parts).replace(PAYLOAD, b'X' + PAYLOAD[1:])
    with pytest.raises(PackageError, match='malformados'):
        read_package(broken)


@pytest.mark.parametrize(
    ('limit', 'value', 'message'),
    [
        ('max_input_bytes', 20, 'comprimido'),
        ('max_expanded_bytes', 20, 'expansão total'),
        ('max_member_bytes', 20, 'por entrada'),
        ('max_entries', 2, 'entradas ZIP'),
        ('max_xml_nodes', 2, 'elementos XML'),
    ],
)
def test_untrusted_package_size_and_structure_are_bounded(
    limit, value, message
):
    with pytest.raises(PackageError, match=message):
        read_package(
            package_bytes(make_parts()), PackageLimits(**{limit: value})
        )
