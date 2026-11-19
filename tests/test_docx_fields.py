"""Regressões para campos que afetam âncoras de mais de um parágrafo."""

import pytest
from test_document_inspection import inspect_primary, rewrite_body

from contract_analyzer_enterprise.documents.anchors import (
    AnchorError,
    make_anchor,
)
from contract_analyzer_enterprise.documents.model import Projection


def _marker(kind):
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def _text(value):
    return f'<w:r><w:t>{value}</w:t></w:r>'


def _paragraph(*runs):
    return f'<w:p>{"".join(runs)}</w:p>'


def _read_fields(tmp_path, *paragraphs):
    path = tmp_path / 'fields.docx'
    rewrite_body(path, ''.join(paragraphs))
    original = path.read_bytes()
    document = inspect_primary(tmp_path, path)
    assert path.read_bytes() == original
    return document


def _assert_projections(document, expected):
    units = [unit for unit in document.units if unit.proposed_view is not None]
    for unit, (text, complete) in zip(units, expected, strict=True):
        for projection in Projection:
            view = getattr(unit, projection.value)
            assert view.text == text
            assert view.complete is complete
            if complete:
                assert (
                    make_anchor(
                        document, unit.id, projection, 0, len(text)
                    ).text
                    == text
                )
            else:
                with pytest.raises(AnchorError, match='incompleta'):
                    make_anchor(document, unit.id, projection, 0, 1)


def test_complex_field_blocks_intermediate_units_and_preserves_cached_text(
    tmp_path,
):
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(
            _marker('begin'),
            '<w:r><w:instrText>TOC</w:instrText></w:r>',
            _marker('separate'),
        ),
        _paragraph(_text('Resultado')),
        _paragraph(_text('Fim do campo'), _marker('end')),
        _paragraph(_text('Depois')),
    )

    _assert_projections(
        document,
        [
            ('Antes', True),
            ('', False),
            ('Resultado', False),
            ('Fim do campo', False),
            ('Depois', True),
        ],
    )
    assert not document.coverage_complete
    assert any(
        item.code == 'unsupported_complex_field'
        and item.part == document.main_part
        and item.locator
        for item in document.limitations
    )


def test_nested_field_close_does_not_complete_outer_field(tmp_path):
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(_marker('begin'), _marker('separate')),
        _paragraph(_marker('begin'), _marker('separate')),
        _paragraph(_text('Resultado interno')),
        _paragraph(_marker('end')),
        _paragraph(_text('Resultado externo')),
        _paragraph(_marker('end')),
        _paragraph(_text('Depois')),
    )

    _assert_projections(
        document,
        [
            ('Antes', True),
            ('', False),
            ('', False),
            ('Resultado interno', False),
            ('', False),
            ('Resultado externo', False),
            ('', False),
            ('Depois', True),
        ],
    )


def test_unclosed_field_keeps_later_units_incomplete(tmp_path):
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(_marker('begin'), _marker('separate')),
        _paragraph(_text('Resultado')),
        _paragraph(_text('Fim da parte')),
    )
    _assert_projections(
        document,
        [
            ('Antes', True),
            ('', False),
            ('Resultado', False),
            ('Fim da parte', False),
        ],
    )
    assert any(
        item.code == 'malformed_field_boundary'
        and item.part == document.main_part
        and item.locator
        for item in document.limitations
    )


@pytest.mark.parametrize('kind', ['end', 'separate', 'unknown'])
def test_invalid_field_marker_signals_incomplete_at_its_location(
    tmp_path, kind
):
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(_marker(kind), _text('Texto no parágrafo')),
        _paragraph(_text('Depois')),
    )
    unit = document.units[1]
    assert unit.proposed_view.text == 'Texto no parágrafo'
    assert not unit.proposed_view.complete
    assert not unit.baseline_view.complete
    assert any(
        item.code == 'malformed_field_boundary'
        and item.part == document.main_part
        and item.locator
        for item in document.limitations
    )


def test_complex_field_without_separator_has_a_bounded_affected_range(
    tmp_path,
):
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(
            _marker('begin'), '<w:r><w:instrText>DATE</w:instrText></w:r>'
        ),
        _paragraph(_marker('end')),
        _paragraph(_text('Depois')),
    )
    _assert_projections(
        document,
        [('Antes', True), ('', False), ('', False), ('Depois', True)],
    )
    assert not any(
        item.code == 'malformed_field_boundary'
        for item in document.limitations
    )


def test_textbox_field_delimiters_do_not_close_the_main_story_field(tmp_path):
    textbox = (
        '<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
        '<v:textbox><w:txbxContent>'
        + _paragraph(_marker('end'), _text('Caixa'))
        + '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>'
    )
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        _paragraph(_marker('begin'), _marker('separate')),
        _paragraph(_text('Resultado com caixa'), textbox),
        _paragraph(_text('Resultado seguinte')),
        _paragraph(_marker('end')),
        _paragraph(_text('Depois')),
    )
    _assert_projections(
        document,
        [
            ('Antes', True),
            ('', False),
            ('Resultado com caixa', False),
            ('Resultado seguinte', False),
            ('', False),
            ('Depois', True),
        ],
    )


def test_alternative_paragraphs_cannot_form_a_trusted_field_interval(tmp_path):
    alternatives = (
        '<mc:AlternateContent '
        'xmlns:mc="http://schemas.openxmlformats.org/'
        'markup-compatibility/2006" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        '<mc:Choice Requires="w14">'
        + _paragraph(_marker('begin'), _marker('separate'))
        + '</mc:Choice><mc:Fallback>'
        + _paragraph(_marker('end'))
        + '</mc:Fallback></mc:AlternateContent>'
    )
    document = _read_fields(
        tmp_path,
        _paragraph(_text('Antes')),
        alternatives,
        _paragraph(_text('Depois das alternativas')),
    )
    _assert_projections(
        document,
        [('Antes', False), ('Depois das alternativas', False)],
    )
    assert any(
        item.code == 'malformed_field_boundary'
        for item in document.limitations
    )
