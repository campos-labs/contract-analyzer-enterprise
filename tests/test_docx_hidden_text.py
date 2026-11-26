"""Regressões de visibilidade em projeções e âncoras DOCX."""

from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from test_document_inspection import inspect_primary, rewrite_body

from contract_analyzer_enterprise.documents.anchors import (
    AnchorError,
    make_anchor,
)
from contract_analyzer_enterprise.documents.model import Projection


def test_direct_hidden_text_is_preserved_but_cannot_be_anchored(tmp_path):
    path = tmp_path / 'hidden.docx'
    rewrite_body(
        path,
        '<w:p><w:r><w:t xml:space="preserve">Prazo: </w:t></w:r>'
        '<w:r><w:rPr><w:vanish/></w:rPr><w:t>30</w:t></w:r>'
        '<w:r><w:t>45</w:t></w:r></w:p><w:p><w:r><w:t>Normal</w:t></w:r></w:p>',
    )
    original = path.read_bytes()
    document = inspect_primary(tmp_path, path)
    affected, unaffected = document.units

    assert path.read_bytes() == original
    assert affected.proposed_view.text == 'Prazo: 3045'
    assert affected.baseline_view.text == 'Prazo: 3045'
    assert not document.coverage_complete
    assert any(
        item.code == 'hidden_text'
        and item.part == document.main_part
        and item.locator.startswith(f'{affected.locator}/w:r[2]')
        for item in document.limitations
    )
    assert not affected.proposed_view.complete
    assert not affected.baseline_view.complete
    for projection in Projection:
        with pytest.raises(AnchorError, match='incompleta'):
            make_anchor(document, affected.id, projection, 7, 11)
        anchor = make_anchor(document, unaffected.id, projection, 0, 6)
        assert anchor.text == 'Normal'


@pytest.mark.parametrize('off', ['0', 'false', 'off'])
def test_direct_false_overrides_hidden_style(tmp_path, off):
    path = tmp_path / 'visible_override.docx'
    rewrite_body(
        path,
        f'<w:p><w:r><w:rPr><w:rStyle w:val="HiddenChar"/>'
        f'<w:vanish w:val="{off}"/></w:rPr><w:t>visível</w:t></w:r></w:p>',
        styles='<w:style w:type="character" w:styleId="HiddenChar">'
        '<w:rPr><w:vanish/></w:rPr></w:style>',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert document.coverage_complete
    assert unit.proposed_view.complete
    assert unit.baseline_view.complete
    assert make_anchor(document, unit.id, Projection.PROPOSED, 0, 7).text == (
        'visível'
    )


@pytest.mark.parametrize('style_type', ['paragraph', 'character'])
def test_false_in_style_does_not_cancel_hidden_ancestor(tmp_path, style_type):
    path = tmp_path / 'hidden_by_style.docx'
    if style_type == 'paragraph':
        properties = '<w:pPr><w:pStyle w:val="ChildHidden"/></w:pPr>'
        run = '<w:r><w:t>30</w:t></w:r>'
    else:
        properties = ''
        run = (
            '<w:r><w:rPr><w:rStyle w:val="ChildHidden"/></w:rPr>'
            '<w:t>30</w:t></w:r>'
        )
    rewrite_body(
        path,
        f'<w:p>{properties}{run}</w:p>',
        styles=f'<w:style w:type="{style_type}" w:styleId="ParentHidden">'
        '<w:rPr><w:vanish/></w:rPr></w:style>'
        f'<w:style w:type="{style_type}" w:styleId="ChildHidden">'
        '<w:basedOn w:val="ParentHidden"/>'
        '<w:rPr><w:vanish w:val="false"/></w:rPr></w:style>',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert unit.proposed_view.text == '30'
    assert not unit.proposed_view.complete
    assert not unit.baseline_view.complete
    assert not document.coverage_complete
    assert any(
        item.code == 'unresolved_text_visibility'
        for item in document.limitations
    )
    with pytest.raises(AnchorError, match='incompleta'):
        make_anchor(document, unit.id, Projection.PROPOSED, 0, 2)


def test_unknown_referenced_style_marks_the_run_as_uncertain(tmp_path):
    path = tmp_path / 'unknown_style.docx'
    rewrite_body(
        path,
        '<w:p><w:r><w:rPr><w:rStyle w:val="NotInPackage"/></w:rPr>'
        '<w:t>30</w:t></w:r></w:p>',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    assert unit.proposed_view.text == '30'
    assert not unit.proposed_view.complete
    assert not unit.baseline_view.complete
    assert not document.coverage_complete
    assert any(
        item.code == 'unresolved_text_visibility'
        for item in document.limitations
    )
    with pytest.raises(AnchorError, match='incompleta'):
        make_anchor(document, unit.id, Projection.PROPOSED, 0, 2)


def test_hidden_document_default_allows_direct_visible_override(tmp_path):
    template = tmp_path / 'body.docx'
    rewrite_body(
        template,
        '<w:p><w:r><w:t>Oculto</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:vanish w:val="off"/></w:rPr>'
        '<w:t>Visível</w:t></w:r></w:p>',
    )
    path = tmp_path / 'hidden_defaults.docx'
    with (
        ZipFile(template) as source,
        ZipFile(path, 'w', compression=ZIP_DEFLATED) as target,
    ):
        for name in source.namelist():
            payload = source.read(name)
            if name == 'word/styles.xml':
                boundary = b'</w:rPr></w:rPrDefault>'
                assert boundary in payload
                payload = payload.replace(boundary, b'<w:vanish/>' + boundary)
            target.writestr(name, payload)

    document = inspect_primary(tmp_path, path)
    hidden, visible = document.units
    assert hidden.proposed_view.text == 'Oculto'
    assert not hidden.proposed_view.complete
    assert not hidden.baseline_view.complete
    assert visible.proposed_view.complete
    assert visible.baseline_view.complete
    assert make_anchor(
        document, visible.id, Projection.PROPOSED, 0, 7
    ).text == ('Visível')


def test_conditional_table_style_marks_only_table_runs_uncertain(tmp_path):
    path = tmp_path / 'hidden_table.docx'
    rewrite_body(
        path,
        '<w:tbl><w:tblPr><w:tblStyle w:val="HiddenTable"/>'
        '<w:tblLook w:firstRow="1"/></w:tblPr>'
        '<w:tblGrid><w:gridCol/></w:tblGrid>'
        '<w:tr><w:tc><w:p><w:r><w:t>Dentro</w:t></w:r></w:p>'
        '</w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:t>Fora</w:t></w:r></w:p>',
        styles='<w:style w:type="table" w:styleId="HiddenTable">'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:vanish/></w:rPr>'
        '</w:tblStylePr></w:style>',
    )
    document = inspect_primary(tmp_path, path)
    inside, outside = [
        unit for unit in document.units if unit.proposed_view is not None
    ]
    assert inside.proposed_view.text == 'Dentro'
    assert not inside.proposed_view.complete
    assert outside.proposed_view.text == 'Fora'
    assert outside.proposed_view.complete
    assert make_anchor(
        document, outside.id, Projection.PROPOSED, 0, 4
    ).text == ('Fora')


@pytest.mark.parametrize(
    ('change', 'leaf', 'unsafe', 'safe'),
    [
        ('ins', 't', Projection.PROPOSED, Projection.BASELINE),
        ('del', 'delText', Projection.BASELINE, Projection.PROPOSED),
    ],
)
def test_hidden_revision_only_blocks_its_projection(
    tmp_path, change, leaf, unsafe, safe
):
    path = tmp_path / 'hidden_revision.docx'
    rewrite_body(
        path,
        '<w:p><w:r><w:t xml:space="preserve">Prazo: </w:t></w:r>'
        f'<w:{change} w:id="12" w:author="Revisor">'
        '<w:r><w:rPr><w:vanish w:val="true"/></w:rPr>'
        f'<w:{leaf}>30</w:{leaf}></w:r></w:{change}>'
        '<w:r><w:t>45</w:t></w:r></w:p>',
    )
    document = inspect_primary(tmp_path, path)
    [unit] = document.units
    affected = getattr(unit, unsafe.value)
    unaffected = getattr(unit, safe.value)
    assert affected.text == 'Prazo: 3045'
    assert not affected.complete
    assert unaffected.text == 'Prazo: 45'
    assert unaffected.complete
    [event] = document.events
    assert (event.after if change == 'ins' else event.before) == '30'
    assert not document.coverage_complete
    with pytest.raises(AnchorError, match='incompleta'):
        make_anchor(document, unit.id, unsafe, 7, 9)
    assert make_anchor(document, unit.id, safe, 7, 9).text == '45'
