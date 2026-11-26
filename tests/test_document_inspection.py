from dataclasses import replace
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx_helpers import (
    ATTACHMENT,
    NS,
    PRIMARY,
    W,
    inspect_primary,
    rewrite_body,
)
from lxml import etree

from contract_analyzer_enterprise.documents.anchors import (
    AnchorError,
    make_anchor,
    validate_anchor,
)
from contract_analyzer_enterprise.documents.model import Projection
from contract_analyzer_enterprise.documents.opc import PackageError
from contract_analyzer_enterprise.documents.service import inspect_documents
from contract_analyzer_enterprise.documents.storage import LocalDocumentStorage


def test_reference_documents_are_preserved_and_inspection_is_repeatable(
    tmp_path,
):
    storage = LocalDocumentStorage(tmp_path / 'originals')
    initial = {path: path.read_bytes() for path in (PRIMARY, ATTACHMENT)}
    report = inspect_documents(PRIMARY, (ATTACHMENT,), storage)
    primary, attachment = report.documents

    checks = (
        (PRIMARY, primary, 'primary'),
        (ATTACHMENT, attachment, 'attachment'),
    )
    for path, inspected, role in checks:
        revision = inspected.document.revision
        assert inspected.role == role
        assert revision.sha256 == sha256(initial[path]).hexdigest()
        assert revision.byte_size == len(initial[path])
        assert storage.read(revision) == initial[path] == path.read_bytes()
    assert primary.stored_as != attachment.stored_as
    assert inspect_documents(PRIMARY, (ATTACHMENT,), storage) == report
    assert primary.document.revision.sha256 == (
        'ebbc464d1834edf76f3411f7b06116ade8b02a75076bc38eaf00e13d14e453f0'
    )
    assert attachment.document.revision.sha256 == (
        'a85881ba5d7c4f9b4e8aaee2655fcf46ad16f373ca19bc9c80ca9410b941ca0d'
    )


def test_reference_capture_contains_real_table_and_revision_events(tmp_path):
    document = inspect_primary(tmp_path, PRIMARY)
    # O comentário referencia CommentText, ausente na parte de estilos.
    assert not document.coverage_complete
    assert [(item.part, item.code) for item in document.limitations] == [
        ('word/comments.xml', 'unresolved_text_visibility')
    ]
    assert all(
        unit.proposed_view is None or unit.proposed_view.complete
        for unit in document.units
    )
    kinds = [unit.kind for unit in document.units]
    expected = {'heading': 9, 'table': 1, 'row': 3, 'cell': 12}
    assert {kind: kinds.count(kind) for kind in expected} == expected

    prefix = 'Prazo de pagamento: '
    suffix = ' contados do recebimento da nota fiscal.'
    payment = next(
        unit
        for unit in document.units
        if unit.proposed_view and unit.proposed_view.text.startswith(prefix)
    )
    assert payment.baseline_view.text == prefix + '30 dias' + suffix
    assert payment.proposed_view.text == prefix + '45 dias' + suffix
    events = {event.kind: event for event in document.events}
    assert events['delete'].before == '30 dias'
    assert events['insert'].after == '45 dias'
    comment = events['comment']
    assert comment.author == 'Revisora sintética'
    assert comment.after == 'Conferir a ordem de serviço vigente.'
    units = {unit.id: unit for unit in document.units}
    marked_text = [
        units[span.unit_id].proposed_view.text[span.start : span.end]
        for span in comment.ranges
        if span.projection is Projection.PROPOSED
    ]
    assert marked_text == [
        'A ordem de serviço relacionada integra o contrato.'
    ]


def test_anchor_maps_repeated_text_and_fragments_to_exact_xml(tmp_path):
    paragraph = """<w:p>
        <w:r><w:t xml:space="preserve">Repete 😀 </w:t></w:r>
        <w:r><w:t>Re</w:t></w:r><w:r><w:t>pete</w:t></w:r>
        <w:r><w:tab/><w:t>fim</w:t><w:br/><w:t>.</w:t></w:r>
    </w:p>"""
    path = tmp_path / 'repeated.docx'
    rewrite_body(path, paragraph)
    document = inspect_primary(tmp_path, path)
    unit = document.units[0]
    assert unit.proposed_view.text == 'Repete 😀 Repete\tfim\n.'
    assert unit.baseline_view.text == unit.proposed_view.text

    # Independent expectations use code points, counting the emoji once.
    anchor = make_anchor(document, unit.id, Projection.PROPOSED, 9, 19)
    assert anchor.text == 'Repete\tfim'
    assert anchor.part == 'word/document.xml'
    assert anchor.revision_sha256 == sha256(path.read_bytes()).hexdigest()
    obtain_text = {f'{{{W}}}tab': '\t', f'{{{W}}}br': '\n'}
    with ZipFile(path) as package:
        root = etree.fromstring(package.read(anchor.part))
    source_text = []
    for span in anchor.source_slices:
        [node] = root.xpath(span.locator, namespaces=NS)
        value = obtain_text.get(node.tag, node.text)
        source_text.append(value[span.start : span.end])
    assert source_text == ['Re', 'pete', '\t', 'fim']
    assert validate_anchor(document, anchor) == anchor

    altered = tmp_path / 'different_revision.docx'
    rewrite_body(altered, paragraph + '<w:p/>')
    revised = inspect_primary(tmp_path, altered)
    assert revised.units[0].proposed_view.text == unit.proposed_view.text
    with pytest.raises(AnchorError):
        validate_anchor(revised, anchor)
    with pytest.raises(AnchorError):
        validate_anchor(document, replace(anchor, text='Repete 😀'))


def test_outline_uses_inherited_style_and_direct_override(tmp_path):
    path = tmp_path / 'styles.docx'
    rewrite_body(
        path,
        """<w:p><w:pPr><w:pStyle w:val="Clausula"/></w:pPr>
          <w:r><w:t>Título</w:t></w:r></w:p>
        <w:p><w:pPr><w:pStyle w:val="Clausula"/>
          <w:outlineLvl w:val="9"/></w:pPr>
          <w:r><w:t>Corpo</w:t></w:r></w:p>""",
        styles="""<w:style w:type="paragraph" w:styleId="Clausula">
          <w:basedOn w:val="Heading2"/></w:style>""",
    )
    document = inspect_primary(tmp_path, path)
    heading, paragraph = document.units
    assert (heading.kind, heading.proposed_view.text) == ('heading', 'Título')
    assert heading.heading_level == 1
    assert (paragraph.kind, paragraph.proposed_view.text) == (
        'paragraph',
        'Corpo',
    )
    assert paragraph.parent_id == heading.id


def test_outline_uses_document_defaults(tmp_path):
    path = tmp_path / 'defaults.docx'
    rewrite_body(
        path,
        '<w:p><w:r><w:t>Capítulo</w:t></w:r></w:p>',
        defaults='<w:outlineLvl w:val="0"/>',
    )
    document = inspect_primary(tmp_path, path)
    unit = document.units[0]
    assert unit.kind == 'heading'
    assert unit.heading_level == 0


def test_unsupported_structure_affects_coverage_without_duplicate_text(
    tmp_path,
):
    path = tmp_path / 'complex_table.docx'
    rewrite_body(
        path,
        """<w:tbl><w:tblPr/><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>
          <w:p><w:r><w:t>Externo</w:t></w:r></w:p>
          <w:tbl><w:tblPr/><w:tblGrid><w:gridCol/></w:tblGrid>
          <w:tr><w:tc><w:p><w:r><w:t>Interno</w:t></w:r></w:p>
          </w:tc></w:tr></w:tbl><w:p/>
        </w:tc></w:tr></w:tbl>""",
    )
    document = inspect_primary(tmp_path, path)
    texts = [
        unit.proposed_view.text
        for unit in document.units
        if unit.proposed_view
    ]
    assert texts.count('Externo') == 1
    assert texts.count('Interno') == 1
    physical_cells = 2
    cells = [unit.locator for unit in document.units if unit.kind == 'cell']
    assert len(set(cells)) == len(cells) == physical_cells
    assert any(item.affects_coverage for item in document.limitations)


def test_malformed_attachment_is_rejected_before_storing_originals(tmp_path):
    storage = LocalDocumentStorage(tmp_path / 'originals')
    malformed = tmp_path / 'malformed.docx'
    malformed.write_bytes(b'not a ZIP')
    with pytest.raises(PackageError):
        inspect_documents(PRIMARY, (malformed,), storage)
    assert list((tmp_path / 'originals').rglob('*.docx')) == []


def test_moved_range_cannot_produce_a_confident_anchor(tmp_path):
    path = tmp_path / 'moved.docx'
    rewrite_body(
        path,
        """<w:moveFromRangeStart w:id="4" w:name="moved"/>
        <w:p><w:r><w:t>Origem</w:t></w:r></w:p>
        <w:moveFromRangeEnd w:id="4"/>
        <w:moveToRangeStart w:id="5" w:name="moved"/>
        <w:p><w:r><w:t>Destino</w:t></w:r></w:p>
        <w:moveToRangeEnd w:id="5"/>""",
    )
    document = inspect_primary(tmp_path, path)
    assert not document.coverage_complete
    assert any(
        item.code == 'unsupported_revision_range'
        for item in document.limitations
    )
    for unit in document.units:
        assert not unit.proposed_view.complete
        assert not unit.baseline_view.complete
        with pytest.raises(AnchorError, match='incompleta'):
            make_anchor(document, unit.id, Projection.PROPOSED, 0, 1)


def test_excess_overlapping_comments_report_a_coverage_limit(tmp_path):
    path = tmp_path / 'overlapping.docx'
    starts = ''.join(
        f'<w:commentRangeStart w:id="{index}"/>' for index in range(33)
    )
    ends = ''.join(
        f'<w:commentRangeEnd w:id="{index}"/>' for index in range(33)
    )
    rewrite_body(path, f'<w:p>{starts}<w:r><w:t>Texto</w:t></w:r>{ends}</w:p>')
    document = inspect_primary(tmp_path, path)
    assert document.units[0].proposed_view.text == 'Texto'
    assert not document.coverage_complete
    assert any(
        item.code == 'active_comment_limit' for item in document.limitations
    )


def test_modern_comments_metadata_marks_document_coverage_partial(tmp_path):
    path = tmp_path / 'modern_comment.docx'
    part = 'word/commentsExtended.xml'
    namespace = 'http://schemas.microsoft.com/office/word/2012/wordml'
    with (
        ZipFile(PRIMARY) as base,
        ZipFile(path, 'w', compression=ZIP_DEFLATED) as target,
    ):
        for entry in base.namelist():
            data = base.read(entry)
            if entry == '[Content_Types].xml':
                data = data.replace(
                    b'</Types>',
                    f'<Override PartName="/{part}" ContentType="application/'
                    'vnd.ms-word.commentsExtended+xml"/></Types>'.encode(),
                )
            elif entry == 'word/_rels/document.xml.rels':
                data = data.replace(
                    b'</Relationships>',
                    b'<Relationship Id="rId99" Type="http://schemas.microsoft'
                    b'.com/office/2011/relationships/commentsExtended" '
                    b'Target="commentsExtended.xml"/></Relationships>',
                )
            target.writestr(entry, data)
        target.writestr(part, f'<w15:commentsEx xmlns:w15="{namespace}"/>')
    document = inspect_primary(tmp_path, path)
    assert not document.coverage_complete
    assert any(
        item.code == 'modern_comments_metadata' and item.part == part
        for item in document.limitations
    )
    assert any(event.kind == 'comment' for event in document.events)
