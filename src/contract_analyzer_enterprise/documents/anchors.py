"""Âncoras usam intervalos semiabertos em pontos de código Unicode."""

from dataclasses import dataclass

from .model import DocumentMap, Projection


class AnchorError(ValueError):
    """O intervalo ou a origem de uma âncora não pôde ser confirmado."""


@dataclass(frozen=True, slots=True)
class XmlSlice:
    locator: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Anchor:
    revision_sha256: str
    part: str
    unit_id: str
    projection: Projection
    start: int
    end: int
    text: str
    source_slices: tuple[XmlSlice, ...]


def make_anchor(
    document: DocumentMap,
    unit_id: str,
    projection: Projection,
    start: int,
    end: int,
) -> Anchor:
    if not isinstance(projection, Projection):
        raise AnchorError('Projeção desconhecida.')
    unit = next((item for item in document.units if item.id == unit_id), None)
    if unit is None:
        raise AnchorError('Unidade inexistente nesta revisão.')
    view = getattr(unit, projection.value)
    if view is None or not view.complete:
        raise AnchorError('Projeção indisponível ou incompleta nesta unidade.')
    if type(start) is not int or type(end) is not int:
        raise AnchorError('Offsets devem ser inteiros.')
    if not 0 <= start < end <= len(view.text):
        raise AnchorError('Intervalo deve ser não vazio e estar na projeção.')

    slices: list[XmlSlice] = []
    position = start
    for segment in view.segments:
        left = max(start, segment.start)
        right = min(end, segment.end)
        if left >= right:
            continue
        source_start = left - segment.start
        source_end = right - segment.start
        if position != left or (
            segment.text[source_start:source_end] != view.text[left:right]
        ):
            raise AnchorError('Intervalo sem correspondência exata no XML.')
        slices.append(XmlSlice(segment.locator, source_start, source_end))
        position = right

    if position != end:
        raise AnchorError('Intervalo sem correspondência exata no XML.')
    return Anchor(
        document.revision.sha256,
        unit.part,
        unit_id,
        projection,
        start,
        end,
        view.text[start:end],
        tuple(slices),
    )


def validate_anchor(document: DocumentMap, anchor: Anchor) -> Anchor:
    if anchor.revision_sha256 != document.revision.sha256:
        raise AnchorError('Âncora pertence a outra revisão.')
    expected = make_anchor(
        document,
        anchor.unit_id,
        anchor.projection,
        anchor.start,
        anchor.end,
    )
    if anchor != expected:
        raise AnchorError('Âncora diverge do texto ou da localização no XML.')
    return expected
