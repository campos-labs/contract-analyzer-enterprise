"""Detecta propriedades que deixam a interpretação de runs incerta."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from lxml import etree

from .word_text import (
    ALTERNATE_CONTENT,
    ALTERNATE_PROPERTIES,
    has_alternate_content,
    value,
    w,
)

_OFF = {'0', 'false', 'off'}
_ON = {None, '1', 'true', 'on'}
_FORMATTING_STYLES = {'paragraph', 'character', 'table'}
_UNKNOWN = 'unresolved_text_visibility'
StyleKey = tuple[str, str]


def _vanish_flag(node: etree._Element) -> bool | None:
    raw = value(node)
    if raw in _OFF:
        return False
    return True if raw in _ON else None


def _style_may_hide(node: etree._Element) -> bool:
    direct = node.findall(f'{w("rPr")}/{w("vanish")}')
    conditional = node.findall(f'{w("tblStylePr")}/{w("rPr")}/{w("vanish")}')
    return any(
        _vanish_flag(item) is not False for item in direct + conditional
    )


def _merge_limitations(*codes: str | None) -> str | None:
    if ALTERNATE_PROPERTIES in codes:
        return ALTERNATE_PROPERTIES
    return next((code for code in codes if code is not None), None)


def _style_limitation(node: etree._Element) -> str | None:
    if has_alternate_content(node):
        return ALTERNATE_PROPERTIES
    return _UNKNOWN if _style_may_hide(node) else None


@dataclass(slots=True)
class StyleVisibility:
    styles: dict[StyleKey, etree._Element | None] = field(default_factory=dict)
    defaults: dict[str, list[str]] = field(default_factory=dict)
    resolved: dict[StyleKey, str | None] = field(default_factory=dict)
    document_limitation: str | None = None

    @classmethod
    def from_tree(cls, tree: etree._Element | None) -> StyleVisibility:
        result = cls()
        if tree is None:
            return result
        if tree.tag != w('styles'):
            result.document_limitation = _UNKNOWN
            return result
        default_run = '/'.join(
            w(name) for name in ('docDefaults', 'rPrDefault', 'rPr', 'vanish')
        )
        if tree.find(ALTERNATE_CONTENT) is not None or any(
            has_alternate_content(node)
            for node in tree.findall(w('docDefaults'))
        ):
            result.document_limitation = ALTERNATE_PROPERTIES
        elif any(
            _vanish_flag(item) is not False
            for item in tree.findall(default_run)
        ):
            result.document_limitation = _UNKNOWN
        for style in tree.findall(w('style')):
            kind = value(style, 'type')
            identifier = value(style, 'styleId')
            if kind not in _FORMATTING_STYLES or not identifier:
                continue
            key = (kind, identifier)
            result.styles[key] = None if key in result.styles else style
            if value(style, 'default') in {'1', 'true', 'on'}:
                result.defaults.setdefault(kind, []).append(identifier)
        return result

    def _chain_limitation(self, kind: str, identifier: str) -> str | None:
        trail: dict[StyleKey, str | None] = {}
        inherited = None
        while identifier:
            key = (kind, identifier)
            if key in self.resolved:
                inherited = self.resolved[key]
                break
            if key in trail:
                cycle_start = list(trail).index(key)
                inherited = _merge_limitations(
                    _UNKNOWN, *list(trail.values())[cycle_start:]
                )
                break
            style = self.styles.get(key)
            if style is None:
                inherited = _UNKNOWN
                break
            # True can toggle a style property; false retains its inheritance.
            trail[key] = _style_limitation(style)
            bases = style.findall(w('basedOn'))
            if not bases:
                break
            identifier = value(bases[0])
            if not identifier or len(bases) != 1:
                inherited = _UNKNOWN
                break
        for key, code in reversed(trail.items()):
            inherited = _merge_limitations(code, inherited)
            self.resolved[key] = inherited
        return inherited

    def _applied_style_limitation(
        self, kind: str, references: list[etree._Element]
    ) -> str | None:
        if references:
            identifier = value(references[0])
            return (
                self._chain_limitation(kind, identifier)
                if len(references) == 1 and identifier
                else _UNKNOWN
            )
        defaults = self.defaults.get(kind, ())
        if len(defaults) > 1:
            return _UNKNOWN
        return self._chain_limitation(kind, defaults[0]) if defaults else None

    def for_paragraph(
        self, paragraph: etree._Element
    ) -> Callable[[etree._Element], str | None]:
        inherited = _merge_limitations(
            self.document_limitation,
            self._applied_style_limitation(
                'paragraph', paragraph.findall(f'{w("pPr")}/{w("pStyle")}')
            ),
            *(
                self._applied_style_limitation(
                    'table', table.findall(f'{w("tblPr")}/{w("tblStyle")}')
                )
                for table in paragraph.iterancestors(w('tbl'))
            ),
        )
        return partial(self._run_limitation, inherited)

    def _run_limitation(
        self, inherited: str | None, run: etree._Element
    ) -> str | None:
        properties = w('rPr')
        inherited = _merge_limitations(
            inherited,
            self._applied_style_limitation(
                'character', run.findall(f'{properties}/{w("rStyle")}')
            ),
        )
        if inherited == ALTERNATE_PROPERTIES:
            return inherited
        direct = run.findall(f'{properties}/{w("vanish")}')
        if len(direct) == 1:
            match _vanish_flag(direct[0]):
                case False:
                    return None
                case True:
                    return 'hidden_text'
                case None:
                    return _UNKNOWN
        return _UNKNOWN if direct else inherited
