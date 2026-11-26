"""Helpers compartilhados para montar e inspecionar DOCX de teste."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from contract_analyzer_enterprise.documents.service import inspect_documents
from contract_analyzer_enterprise.documents.storage import LocalDocumentStorage

FIXTURES = Path(__file__).parent / 'fixtures' / 'docx'
PRIMARY = FIXTURES / 'contract_reference.docx'
ATTACHMENT = FIXTURES / 'related_reference.docx'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def rewrite_body(path, body, *, styles='', defaults=''):
    document = (
        f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    )
    with (
        ZipFile(ATTACHMENT) as source,
        ZipFile(path, 'w', compression=ZIP_DEFLATED) as target,
    ):
        for entry in source.namelist():
            payload = source.read(entry)
            if entry == 'word/document.xml':
                payload = document.encode()
            elif entry == 'word/styles.xml':
                payload = payload.replace(
                    b'</w:styles>', styles.encode() + b'</w:styles>'
                )
                payload = payload.replace(
                    b'</w:pPr></w:pPrDefault>',
                    defaults.encode() + b'</w:pPr></w:pPrDefault>',
                )
            target.writestr(entry, payload)


def inspect_primary(tmp_path, filename):
    report = inspect_documents(
        filename, (), LocalDocumentStorage(tmp_path / 'originals')
    )
    return report.documents[0].document


OFFICE_REL = (
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
)
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
MAIN = 'word/document.xml'


def make_parts(main: str = MAIN) -> dict[str, str | bytes]:
    return {
        '[Content_Types].xml': (
            f'<Types xmlns="{TYPES}">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="bin" ContentType="application/octet-stream"/>'
            '<Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/>'
            f'<Override PartName="/{main}" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        ),
        '_rels/.rels': (
            f'<Relationships xmlns="{REL}">'
            f'<Relationship Id="rId1" Type="{OFFICE_REL}officeDocument" '
            f'Target="{main}"/></Relationships>'
        ),
        main: (
            f'<w:document xmlns:w="{W}"><w:body><w:p/></w:body></w:document>'
        ),
    }


def package_bytes(parts: dict[str | ZipInfo, str | bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode='w', compression=ZIP_STORED) as archive:
        for name, item in parts.items():
            archive.writestr(name, item)
    return buffer.getvalue()
