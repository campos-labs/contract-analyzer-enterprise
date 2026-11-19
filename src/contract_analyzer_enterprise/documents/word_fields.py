"""Delimita campos complexos sem interpretar instruções ou resultados."""

from collections.abc import Iterator
from dataclasses import dataclass, field

from lxml import etree

from .word_text import value, w

FIELD_LIMITATION = 'unsupported_complex_field'
MALFORMED_FIELD = 'malformed_field_boundary'


@dataclass(slots=True)
class _FieldRanges:
    affected: dict[etree._Element, str] = field(default_factory=dict)
    paragraphs: list[etree._Element] = field(default_factory=list)
    # Cada frame registra o início e se já houve separação código/resultado.
    stack: list[tuple[etree._Element, bool]] = field(default_factory=list)
    boundary: int = 0
    ambiguous: bool = False
    current: etree._Element | None = None

    def paragraph(self, node: etree._Element) -> None:
        self.current = node
        self.paragraphs.append(node)
        if self.stack:
            self.affected[node] = FIELD_LIMITATION

    def marker(self, node: etree._Element) -> None:
        current = self.current
        if current is None or not _plain_marker(node, current):
            # Um delimitador dentro de alternativas/revisões pode existir em
            # apenas uma visão. Não inferir um intervalo comum às duas.
            self.ambiguous = True
            return
        self.affected.setdefault(current, FIELD_LIMITATION)
        kind = value(node, 'fldCharType')
        if kind == 'begin':
            self.stack.append((current, False))
        elif kind == 'separate' and self.stack and not self.stack[-1][1]:
            self.stack[-1] = (self.stack[-1][0], True)
        elif kind == 'end' and self.stack:
            self.stack.pop()
            if not self.stack:
                self.boundary = len(self.paragraphs)
        else:
            self.affected[current] = MALFORMED_FIELD
            if kind == 'separate' and self.stack:
                return
            if kind not in {'end', 'separate'}:
                self.ambiguous = True
                return
            # Sem begin, o trecho anterior pode pertencer ao campo.
            self.affected.update(
                dict.fromkeys(
                    self.paragraphs[self.boundary :], MALFORMED_FIELD
                )
            )
            if kind == 'separate':
                self.stack.append((current, True))
            else:
                self.boundary = len(self.paragraphs)


def field_limitations(
    story: etree._Element,
) -> dict[etree._Element, str]:
    state = _FieldRanges()
    for node in _field_content(story):
        if node.tag == w('p'):
            state.paragraph(node)
        else:
            state.marker(node)
    for start, _separated in state.stack:
        state.affected[start] = MALFORMED_FIELD
    if state.ambiguous:
        return dict.fromkeys(state.paragraphs, MALFORMED_FIELD)
    return state.affected


def _field_content(story: etree._Element) -> Iterator[etree._Element]:
    walker = etree.iterwalk(
        story,
        events=('start',),
        tag=(w('p'), w('fldChar'), w('txbxContent')),
    )
    for _event, node in walker:
        if node.tag == w('txbxContent'):
            # Caixas de texto são outra story, já inventariada pelo leitor.
            walker.skip_subtree()
        else:
            yield node


def _plain_marker(marker: etree._Element, paragraph: etree._Element) -> bool:
    parent = marker.getparent()
    if parent is None or parent.tag != w('r'):
        return False
    while parent is not paragraph:
        if parent.tag not in {w('r'), w('hyperlink')}:
            return False
        parent = parent.getparent()
        if parent is None:
            return False
    return all(
        ancestor.tag in {w('document'), w('body'), w('tbl'), w('tr'), w('tc')}
        for ancestor in paragraph.iterancestors()
    )
