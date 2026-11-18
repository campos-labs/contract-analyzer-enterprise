"""Sinaliza visibilidade incerta de runs com a propriedade OOXML vanish."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from lxml import etree

from .word_text import value, w

_OFF = {'0', 'false', 'off'}
_ON = {None, '1', 'true', 'on'}
_FORMATTING_STYLES = {'paragraph', 'character', 'table'}
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


@dataclass(slots=True)
class StyleVisibility:
    styles: dict[StyleKey, etree._Element | None] = field(default_factory=dict)
    defaults: dict[str, list[str]] = field(default_factory=dict)
    resolved: dict[StyleKey, bool] = field(default_factory=dict)
    document_may_hide: bool = False

    @classmethod
    def from_tree(cls, tree: etree._Element | None) -> StyleVisibility:
        result = cls()
        if tree is None:
            return result
        if tree.tag != w('styles'):
            result.document_may_hide = True
            return result
        default_run = '/'.join(
            w(name) for name in ('docDefaults', 'rPrDefault', 'rPr', 'vanish')
        )
        result.document_may_hide = any(
            _vanish_flag(item) is not False
            for item in tree.findall(default_run)
        )
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

    def _chain_may_hide(self, kind: str, identifier: str) -> bool:
        trail: set[StyleKey] = set()
        uncertain = False
        while identifier:
            key = (kind, identifier)
            if key in self.resolved:
                uncertain = self.resolved[key]
                break
            style = self.styles.get(key)
            if key in trail or style is None or _style_may_hide(style):
                # Style-level true can toggle and false retains the inherited
                # value. A reachable declaration is enough to flag uncertainty.
                trail.add(key)
                uncertain = True
                break
            trail.add(key)
            bases = style.findall(w('basedOn'))
            if not bases:
                break
            identifier = value(bases[0])
            if not identifier or len(bases) != 1:
                uncertain = True
                break
        self.resolved.update(dict.fromkeys(trail, uncertain))
        return uncertain

    def _applied_style_may_hide(
        self, kind: str, references: list[etree._Element]
    ) -> bool:
        if references:
            identifier = value(references[0])
            return (
                len(references) != 1
                or not identifier
                or self._chain_may_hide(kind, identifier)
            )
        defaults = self.defaults.get(kind, ())
        return len(defaults) > 1 or any(
            self._chain_may_hide(kind, identifier) for identifier in defaults
        )

    def for_paragraph(
        self, paragraph: etree._Element
    ) -> Callable[[etree._Element], str | None]:
        inherited = (
            self.document_may_hide
            or self._applied_style_may_hide(
                'paragraph', paragraph.findall(f'{w("pPr")}/{w("pStyle")}')
            )
            or any(
                self._applied_style_may_hide(
                    'table', table.findall(f'{w("tblPr")}/{w("tblStyle")}')
                )
                for table in paragraph.iterancestors(w('tbl'))
            )
        )
        return partial(self._run_limitation, inherited)

    def _run_limitation(
        self, inherited: bool, run: etree._Element
    ) -> str | None:
        properties = w('rPr')
        direct = run.findall(f'{properties}/{w("vanish")}')
        if len(direct) == 1:
            match _vanish_flag(direct[0]):
                case False:
                    return None
                case True:
                    return 'hidden_text'
                case None:
                    return 'unresolved_text_visibility'
        if (
            direct
            or inherited
            or self._applied_style_may_hide(
                'character', run.findall(f'{properties}/{w("rStyle")}')
            )
        ):
            return 'unresolved_text_visibility'
        return None
