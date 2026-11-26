"""Regressões de cobertura para estruturas WordprocessingML."""

from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx_helpers import (
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
)
from contract_analyzer_enterprise.documents.model import Projection
from contract_analyzer_enterprise.documents.storage import LocalDocumentStorage

COMMENT_PART = 'word/comments.xml'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'


def _replace_part(source, target, part, original, replacement):
    with (
        ZipFile(source) as base,
        ZipFile(target, 'w', compression=ZIP_DEFLATED) as updated,
    ):
        for name in base.namelist():
            payload = base.read(name)
            if name == part:
                assert original in payload
                payload = payload.replace(original, replacement, 1)
            updated.writestr(name, payload)


def test_comment_revision_reports_partial_coverage_and_preserves_original(
    tmp_path,
):
    path = tmp_path / 'comment-with-revision.docx'
    markup = (
        f'<w:comments xmlns:w="{W}"><w:comment w:id="0" w:author="R">'
        '<w:p><w:del w:id="31" w:author="R">'
        '<w:r><w:delText>30 dias</w:delText></w:r></w:del>'
        '<w:ins w:id="32" w:author="R">'
        '<w:r><w:t>45 dias</w:t></w:r></w:ins></w:p></w:comment></w:comments>'
    )
    with ZipFile(PRIMARY) as source:
        original_comments = source.read(COMMENT_PART)
    _replace_part(
        PRIMARY, path, COMMENT_PART, original_comments, markup.encode()
    )

    original = path.read_bytes()
    document = inspect_primary(tmp_path, path)
    [comment] = [event for event in document.events if event.kind == 'comment']
    assert comment.after == '45 dias'
    assert path.read_bytes() == original
    storage = LocalDocumentStorage(tmp_path / 'originals')
    assert storage.read(document.revision) == original
    assert not document.coverage_complete
    limits = [
        item
        for item in document.limitations
        if item.code == 'unsupported_comment_revision'
    ]
    comment_xml = etree.fromstring(markup.encode())
    revision_tags = set()
    for item in limits:
        assert item.part == COMMENT_PART
        assert item.affects_coverage
        [node] = comment_xml.xpath(item.locator, namespaces=NS)
        revision_tags.add(node.tag)
    assert revision_tags == {f'{{{W}}}del', f'{{{W}}}ins'}


def test_rendered_page_break_preserves_offsets_inside_and_outside_revisions(
    tmp_path,
):
    path = tmp_path / 'pagination.docx'
    rewrite_body(
        path,
        '<w:p><w:r><w:t>A</w:t><w:lastRenderedPageBreak/><w:t>B</w:t></w:r>'
        '<w:del w:id="3" w:author="R"><w:r>'
        '<w:delText>C</w:delText><w:lastRenderedPageBreak/>'
        '<w:delText>D</w:delText></w:r></w:del>'
        '<w:ins w:id="4" w:author="R"><w:r><w:t>E</w:t>'
        '<w:lastRenderedPageBreak/><w:t>F</w:t></w:r></w:ins>'
        '<w:r><w:br/><w:t>G</w:t></w:r></w:p>',
    )
    document = inspect_primary(tmp_path, path)
    assert document.coverage_complete
    [unit] = document.units
    for projection, expected in (
        (Projection.PROPOSED, 'ABEF\nG'),
        (Projection.BASELINE, 'ABCD\nG'),
    ):
        view = getattr(unit, projection.value)
        assert view.text == expected
        assert view.complete
        anchor = make_anchor(document, unit.id, projection, 1, len(expected))
        assert anchor.text == expected[1:]
        with ZipFile(path) as package:
            xml = etree.fromstring(package.read(anchor.part))
        slices = []
        for span in anchor.source_slices:
            [node] = xml.xpath(span.locator, namespaces=NS)
            text = '\n' if node.tag == f'{{{W}}}br' else node.text
            slices.append(text[span.start : span.end])
        assert ''.join(slices) == expected[1:]


def _alternate(choice):
    return (
        f'<mc:AlternateContent xmlns:mc="{MC}" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        f'<mc:Choice Requires="w14">{choice}</mc:Choice>'
        '<mc:Fallback/></mc:AlternateContent>'
    )


_CASES = {
    'run': (
        f'<w:p><w:r><w:rPr>{_alternate("<w:vanish/>")}</w:rPr>'
        '<w:t>30</w:t></w:r></w:p>',
        '',
    ),
    'paragraph': (
        f'<w:p><w:pPr>{_alternate("<w:keepNext/>")}</w:pPr>'
        '<w:r><w:t>30</w:t></w:r></w:p>',
        '',
    ),
    'inherited_character': (
        '<w:p><w:r><w:rPr><w:rStyle w:val="Child"/></w:rPr>'
        '<w:t>30</w:t></w:r></w:p>',
        '<w:style w:type="character" w:styleId="Base">'
        f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr></w:style>'
        '<w:style w:type="character" w:styleId="Child">'
        '<w:basedOn w:val="Base"/></w:style>',
    ),
    'inherited_paragraph': (
        '<w:p><w:pPr><w:pStyle w:val="Child"/></w:pPr>'
        '<w:r><w:t>30</w:t></w:r></w:p>',
        '<w:style w:type="paragraph" w:styleId="Base">'
        f'<w:pPr>{_alternate("<w:keepNext/>")}</w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Child">'
        '<w:basedOn w:val="Base"/></w:style>',
    ),
    'conditional_table': (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableWithAlternates"/>'
        '<w:tblLook w:firstRow="1"/></w:tblPr>'
        '<w:tblGrid><w:gridCol/></w:tblGrid>'
        '<w:tr><w:tc><w:p><w:r><w:t>30</w:t></w:r></w:p>'
        '</w:tc></w:tr></w:tbl>',
        '<w:style w:type="table" w:styleId="TableWithAlternates">'
        '<w:tblStylePr w:type="firstRow">'
        f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr>'
        '</w:tblStylePr></w:style>',
    ),
}


@pytest.mark.parametrize('case', list(_CASES))
def test_alternate_properties_block_anchors_only_on_affected_units(
    tmp_path, case
):
    affected_body, styles = _CASES[case]
    path = tmp_path / 'alternate.docx'
    rewrite_body(
        path,
        affected_body + '<w:p><w:r><w:t>Normal</w:t></w:r></w:p>',
        styles=styles,
    )
    original = path.read_bytes()
    document = inspect_primary(tmp_path, path)
    affected, unaffected = [
        unit for unit in document.units if unit.proposed_view is not None
    ]
    assert path.read_bytes() == original
    assert not document.coverage_complete
    assert any(
        item.code == 'unsupported_alternate_properties'
        and item.affects_coverage
        for item in document.limitations
    )
    for projection in Projection:
        view = getattr(affected, projection.value)
        assert view.text == '30'
        assert not view.complete
        with pytest.raises(AnchorError, match='incompleta'):
            make_anchor(document, affected.id, projection, 0, 2)
        anchor = make_anchor(document, unaffected.id, projection, 0, 6)
        assert anchor.text == 'Normal'


@pytest.mark.parametrize(
    ('change', 'leaf', 'affected', 'unaffected'),
    [
        ('ins', 't', Projection.PROPOSED, Projection.BASELINE),
        ('del', 'delText', Projection.BASELINE, Projection.PROPOSED),
    ],
)
def test_alternate_run_properties_inside_revision_only_affect_its_view(
    tmp_path, change, leaf, affected, unaffected
):
    path = tmp_path / 'alternate-inside-revision.docx'
    rewrite_body(
        path,
        f'<w:p><w:{change} w:id="3" w:author="R"><w:r>'
        f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr>'
        f'<w:{leaf}>30</w:{leaf}></w:r></w:{change}>'
        '<w:r><w:t>45</w:t></w:r></w:p>',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert getattr(unit, affected.value).text == '3045'
    with pytest.raises(AnchorError, match='incompleta'):
        make_anchor(document, unit.id, affected, 0, 4)
    assert make_anchor(document, unit.id, unaffected, 0, 2).text == '45'


@pytest.mark.parametrize(
    ('boundary', 'choice'),
    [
        (b'</w:rPr></w:rPrDefault>', '<w:vanish/>'),
        (b'</w:pPr></w:pPrDefault>', '<w:keepNext/>'),
    ],
    ids=['run', 'paragraph'],
)
def test_alternate_defaults_make_projections_uncertain(
    tmp_path, boundary, choice
):
    template = tmp_path / 'body.docx'
    path = tmp_path / 'alternate-defaults.docx'
    rewrite_body(template, '<w:p><w:r><w:t>30</w:t></w:r></w:p>')
    _replace_part(
        template,
        path,
        'word/styles.xml',
        boundary,
        _alternate(choice).encode() + boundary,
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert unit.proposed_view.text == '30'
    assert not document.coverage_complete
    assert any(
        item.code == 'unsupported_alternate_properties'
        for item in document.limitations
    )
    for projection in Projection:
        assert not getattr(unit, projection.value).complete
        with pytest.raises(AnchorError, match='incompleta'):
            make_anchor(document, unit.id, projection, 0, 2)


@pytest.mark.parametrize('origin', ['style', 'document_defaults'])
def test_direct_vanish_false_cannot_clear_unprocessed_alternate_properties(
    tmp_path, origin
):
    path = tmp_path / 'alternate-with-visible-override.docx'
    reference = '<w:rStyle w:val="Unresolved"/>' if origin == 'style' else ''
    rewrite_body(
        path,
        f'<w:p><w:r><w:rPr>{reference}<w:vanish w:val="false"/></w:rPr>'
        '<w:t>30</w:t></w:r></w:p>',
        styles=(
            '<w:style w:type="character" w:styleId="Unresolved">'
            f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr></w:style>'
            if origin == 'style'
            else ''
        ),
        defaults=_alternate('<w:keepNext/>') if origin != 'style' else '',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert unit.proposed_view.text == '30'
    assert any(
        item.code == 'unsupported_alternate_properties'
        for item in document.limitations
    )
    for projection in Projection:
        with pytest.raises(AnchorError, match='incompleta'):
            make_anchor(document, unit.id, projection, 0, 2)


@pytest.mark.parametrize('order', [('A', 'B'), ('B', 'A')])
def test_cyclic_style_resolution_keeps_alternate_limitations_in_both_orders(
    tmp_path, order
):
    path = tmp_path / 'cyclic-styles.docx'
    body = ''.join(
        f'<w:p><w:r><w:rPr><w:rStyle w:val="{identifier}"/></w:rPr>'
        '<w:t>30</w:t></w:r></w:p>'
        for identifier in order
    )
    rewrite_body(
        path,
        body + '<w:p><w:r><w:t>Normal</w:t></w:r></w:p>',
        styles='<w:style w:type="character" w:styleId="A">'
        '<w:basedOn w:val="B"/></w:style>'
        '<w:style w:type="character" w:styleId="B">'
        '<w:basedOn w:val="A"/>'
        f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr></w:style>',
    )
    document = inspect_primary(tmp_path, path)
    first, second, normal = document.units
    limited_locators = {
        item.locator
        for item in document.limitations
        if item.code == 'unsupported_alternate_properties'
    }
    for affected in (first, second):
        assert any(
            locator.startswith(affected.locator + '/')
            for locator in limited_locators
        )
        for projection in Projection:
            assert getattr(affected, projection.value).text == '30'
            with pytest.raises(AnchorError, match='incompleta'):
                make_anchor(document, affected.id, projection, 0, 2)
    for projection in Projection:
        assert (
            make_anchor(document, normal.id, projection, 0, 6).text == 'Normal'
        )


def test_unused_alternate_styles_do_not_degrade_plain_document(tmp_path):
    path = tmp_path / 'unused-alternate-style.docx'
    styles = ''.join(
        f'<w:style w:type="{kind}" w:styleId="Unused{kind}">'
        f'<w:rPr>{_alternate("<w:vanish/>")}</w:rPr></w:style>'
        for kind in ('paragraph', 'character', 'table')
    )
    rewrite_body(
        path,
        '<w:p><w:r><w:t>Normal</w:t></w:r></w:p>',
        styles=styles,
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert document.coverage_complete
    for projection in Projection:
        assert (
            make_anchor(document, unit.id, projection, 0, 6).text == 'Normal'
        )
