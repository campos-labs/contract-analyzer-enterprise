"""Read-only structural map for a validated DOCX package."""

from collections import Counter
from dataclasses import dataclass, field, replace

from lxml import etree

from .model import (
    DocumentEvent,
    DocumentMap,
    DocumentRevision,
    DocumentUnit,
    EventKind,
    EventRange,
    Limitation,
    Projection,
    UnitKind,
)
from .opc import DocxPackage
from .word_fields import field_limitations
from .word_text import (
    ALTERNATE_PROPERTIES,
    HARMLESS_MARKERS,
    MOVES,
    STRUCTURAL_REVISIONS,
    CommentRanges,
    ParagraphText,
    children,
    has_alternate_content,
    value,
    w,
    w_names,
)
from .word_visibility import StyleVisibility

OUTLINE_BODY = 9
CONTAINER_KINDS = {
    w('tbl'): UnitKind.TABLE,
    w('tr'): UnitKind.ROW,
    w('tc'): UnitKind.CELL,
}
CONTAINER_CHILDREN = {
    w('tbl'): w_names('tr'),
    w('tr'): w_names('tc'),
    w('tc'): w_names('p tbl'),
}
CONTAINER_PROPERTIES = w_names('tblPr tblGrid tblPrEx trPr tcPr')
MERGE_PROPERTIES = w_names('vMerge hMerge')
STORY_ROOTS = w_names('hdr ftr footnotes endnotes glossaryDocument')
MODERN_COMMENT_TYPES = frozenset({
    'commentsextended',
    'commentsids',
    'commentsextensible',
    'people',
})
UNSUPPORTED_BLOCK_MARKERS = w_names(
    'customXmlInsRangeStart customXmlInsRangeEnd customXmlDelRangeStart '
    'customXmlDelRangeEnd customXmlMoveFromRangeStart '
    'customXmlMoveFromRangeEnd '
    'customXmlMoveToRangeStart customXmlMoveToRangeEnd'
)
UNSUPPORTED_RANGE_MARKERS = UNSUPPORTED_BLOCK_MARKERS | w_names(
    'moveFromRangeStart moveFromRangeEnd moveToRangeStart moveToRangeEnd'
)


@dataclass(frozen=True, slots=True)
class _Properties:
    outline: str | None = None
    num_id: str | None = None
    num_level: str | None = None

    @classmethod
    def from_node(cls, props: etree._Element | None) -> _Properties:
        if props is None:
            return cls()
        num = props.find(w('numPr'))
        return cls(
            value(props.find(w('outlineLvl'))),
            value(num.find(w('numId'))) if num is not None else None,
            value(num.find(w('ilvl'))) if num is not None else None,
        )

    def over(self, parent: _Properties) -> _Properties:
        return _Properties(
            self.outline if self.outline is not None else parent.outline,
            self.num_id if self.num_id is not None else parent.num_id,
            self.num_level if self.num_level is not None else parent.num_level,
        )


@dataclass(slots=True)
class _Styles:
    styles: dict[str, etree._Element] = field(default_factory=dict)
    default_id: str | None = None
    defaults: _Properties = field(default_factory=_Properties)
    resolved: dict[str, tuple[_Properties, bool]] = field(default_factory=dict)

    @classmethod
    def from_tree(cls, tree: etree._Element | None) -> _Styles:
        state = cls()
        if tree is None or tree.tag != w('styles'):
            return state
        defaults = '/'.join(
            w(name) for name in ('docDefaults', 'pPrDefault', 'pPr')
        )
        state.defaults = _Properties.from_node(tree.find(defaults))
        for style in tree.findall(w('style')):
            style_id = value(style, 'styleId')
            if not style_id or value(style, 'type') != 'paragraph':
                continue
            if style_id in state.styles:
                state.resolved[style_id] = (state.defaults, False)
            else:
                state.styles[style_id] = style
            if value(style, 'default') in {'1', 'true', 'on'}:
                state.default_id = style_id
        return state

    def for_id(self, style_id: str | None) -> tuple[_Properties, bool]:
        trail: list[tuple[str, _Properties]] = []
        seen: set[str] = set()
        inherited, complete = self.defaults, True
        while style_id is not None:
            if cached := self.resolved.get(style_id):
                inherited, complete = cached
                break
            node = self.styles.get(style_id)
            if style_id in seen or node is None:
                inherited, complete = self.defaults, False
                break
            seen.add(style_id)
            trail.append((
                style_id,
                _Properties.from_node(node.find(w('pPr'))),
            ))
            style_id = value(node.find(w('basedOn')))
        for item, properties in reversed(trail):
            inherited = properties.over(inherited)
            self.resolved[item] = inherited, complete
        return inherited, complete


def _level(raw: str | None, maximum: int) -> int | None:
    if raw is None:
        return None
    try:
        level = int(raw)
    except ValueError:
        return None
    return level if 0 <= level <= maximum else None


def _related_tree(package: DocxPackage, kind: str) -> etree._Element | None:
    part = package.related_part(package.main_part, kind)
    return package.trees.get(part) if part is not None else None


@dataclass(slots=True)
class _Map:
    package: DocxPackage
    styles: _Styles
    visibility: StyleVisibility
    units: list[DocumentUnit] = field(default_factory=list)
    events: list[DocumentEvent] = field(default_factory=list)
    limitations: set[Limitation] = field(default_factory=set)
    comments: CommentRanges = field(default_factory=CommentRanges)
    headings: list[tuple[int, str]] = field(default_factory=list)
    field_paragraphs: dict[etree._Element, str] = field(default_factory=dict)

    @property
    def part(self) -> str:
        return self.package.main_part

    def walk(self) -> None:
        body = self.package.trees[self.part].find(w('body'))
        if body is None:
            raise ValueError('A parte principal DOCX não contém w:body.')
        body_path = '/w:document[1]/w:body[1]'
        self.field_paragraphs = field_limitations(body)
        # Revisões por intervalo podem atravessar parágrafos e tabelas.
        complete = not any(
            node.tag in UNSUPPORTED_RANGE_MARKERS for node in body.iter()
        )
        if not complete:
            self.limitations.add(
                Limitation('unsupported_revision_range', self.part, body_path)
            )
        for child, path in children(body, body_path):
            if child.tag == w('p'):
                self.paragraph(child, path, complete=complete)
            elif child.tag == w('tbl'):
                self.container(
                    child, path, self.heading_id(), complete=complete
                )
            elif child.tag == w('sectPr'):
                if has_alternate_content(child):
                    self.limitations.add(
                        Limitation(ALTERNATE_PROPERTIES, self.part, path)
                    )
                if _has_structural_revision(child):
                    self.limitations.add(
                        Limitation(
                            'unsupported_structural_revision', self.part, path
                        )
                    )
            elif child.tag not in HARMLESS_MARKERS:
                self._omit_block(child, path)
        self._collect_comments()
        self._audit_events()
        self._inventory_parts()

    def heading_id(self) -> str | None:
        return self.headings[-1][1] if self.headings else None

    def _next_id(self) -> str:
        return f'u{len(self.units) + 1:06d}'

    def paragraph(
        self,
        node: etree._Element,
        path: str,
        *,
        parent: str | None = None,
        complete: bool = True,
    ) -> None:
        if code := self.field_paragraphs.get(node):
            self.limitations.add(Limitation(code, self.part, path))
            complete = False
        props = node.find(w('pPr'))
        style = value(props.find(w('pStyle'))) if props is not None else None
        inherited, style_complete = self.styles.for_id(
            style if style is not None else self.styles.default_id
        )
        if not style_complete:
            self.limitations.add(
                Limitation('unresolved_paragraph_style', self.part, path)
            )
        properties = _Properties.from_node(props).over(inherited)
        level = _level(properties.outline, OUTLINE_BODY)
        num_level = _level(properties.num_level, OUTLINE_BODY - 1)
        if (properties.outline is not None and level is None) or (
            properties.num_level is not None and num_level is None
        ):
            self.limitations.add(
                Limitation('invalid_paragraph_level', self.part, path)
            )
        if level == OUTLINE_BODY:
            level = None
        unit_id = self._next_id()
        proposed, baseline = ParagraphText(
            self.part,
            unit_id,
            self.comments,
            self.events,
            self.limitations,
            complete=complete,
            run_limitation=self.visibility.for_paragraph(node),
        ).read(node, path)
        if parent is None:
            if level is not None:
                while self.headings and self.headings[-1][0] >= level:
                    self.headings.pop()
                parent = self.heading_id()
                self.headings.append((level, unit_id))
            else:
                parent = self.heading_id()
        self.units.append(
            DocumentUnit(
                id=unit_id,
                part=self.part,
                locator=path,
                kind=UnitKind.HEADING
                if level is not None
                else UnitKind.PARAGRAPH,
                parent_id=parent,
                heading_level=level,
                style_id=style,
                numbering_id=properties.num_id,
                numbering_level=num_level,
                proposed_view=proposed,
                baseline_view=baseline,
            )
        )

    def container(
        self,
        node: etree._Element,
        path: str,
        parent: str | None,
        *,
        complete: bool = True,
        inside_cell: bool = False,
    ) -> None:
        unit_id = self._next_id()
        self.units.append(
            DocumentUnit(
                unit_id, self.part, path, CONTAINER_KINDS[node.tag], parent
            )
        )
        if inside_cell and node.tag == w('tbl'):
            self.limitations.add(Limitation('nested_table', self.part, path))
            complete = False
        block_children = tuple(children(node, path))
        allowed = CONTAINER_CHILDREN[node.tag]
        for child, child_path in block_children:
            if child.tag in CONTAINER_PROPERTIES:
                if has_alternate_content(child):
                    self.limitations.add(
                        Limitation(ALTERNATE_PROPERTIES, self.part, child_path)
                    )
                    complete = False
                if _has_structural_revision(child):
                    self.limitations.add(
                        Limitation(
                            'unsupported_structural_revision',
                            self.part,
                            child_path,
                        )
                    )
                    complete = False
                if child.tag == w('tcPr') and _is_merged(child):
                    self.limitations.add(
                        Limitation('merged_table_cell', self.part, path)
                    )
                    complete = False
            elif child.tag not in allowed | HARMLESS_MARKERS:
                complete = False

        for child, child_path in block_children:
            if child.tag not in allowed:
                if child.tag not in CONTAINER_PROPERTIES | HARMLESS_MARKERS:
                    self._omit_block(child, child_path)
            elif child.tag == w('p'):
                self.paragraph(
                    child, child_path, parent=unit_id, complete=complete
                )
            else:
                self.container(
                    child,
                    child_path,
                    unit_id,
                    complete=complete,
                    inside_cell=inside_cell or node.tag == w('tc'),
                )

    def _omit_block(self, node: etree._Element, path: str) -> None:
        if node.tag in MOVES:
            code = 'unsupported_move'
        elif node.tag in STRUCTURAL_REVISIONS | UNSUPPORTED_BLOCK_MARKERS:
            code = 'unsupported_structural_revision'
        else:
            code = 'unsupported_block'
        self.limitations.add(Limitation(code, self.part, path))
        self.comments.gap()

    def _collect_comments(self) -> None:
        part = self.package.related_part(self.part, 'comments')
        root = self.package.trees.get(part) if part else None
        if root is None or root.tag != w('comments'):
            if self.comments.records or part:
                self.limitations.add(
                    Limitation(
                        'unresolved_classic_comments', part or self.part
                    )
                )
            return
        nodes = [
            (node, path)
            for node, path in children(root, '/w:comments[1]')
            if node.tag == w('comment')
        ]
        counts = Counter(value(node, 'id') for node, _path in nodes)
        for node, path in nodes:
            comment_id = value(node, 'id')
            if comment_id is None or counts[comment_id] != 1:
                self.limitations.add(
                    Limitation('invalid_comment_id', part, path)
                )
                continue
            record = self.comments.records.get(comment_id)
            anchored = (
                record is not None
                and not record.invalid
                and record.starts == record.ends == record.references == 1
                and bool(record.spans)
            )
            if not anchored:
                self.limitations.add(
                    Limitation('unresolved_comment_range', part, path)
                )
            self.events.append(
                DocumentEvent(
                    kind=EventKind.COMMENT,
                    id=comment_id,
                    part=part,
                    locator=path,
                    author=value(node, 'author'),
                    date=value(node, 'date'),
                    after=self._comment_text(node, part, path),
                    ranges=tuple(record.spans) if anchored else (),
                )
            )
        if any(
            counts[comment_id] != 1 for comment_id in self.comments.records
        ):
            self.limitations.add(
                Limitation('unresolved_classic_comments', self.part)
            )

    def _comment_text(self, node: etree._Element, part: str, path: str) -> str:
        paragraphs: list[str] = []
        for child, child_path in children(node, path):
            if child.tag != w('p'):
                self.limitations.add(
                    Limitation('unsupported_comment_content', part, child_path)
                )
                continue
            revisions: list[DocumentEvent] = []
            text, _baseline = ParagraphText(
                part,
                '',
                CommentRanges(),
                revisions,
                self.limitations,
                run_limitation=self.visibility.for_paragraph(child),
            ).read(child, child_path)
            self.limitations.update(
                Limitation(
                    'unsupported_comment_revision', part, revision.locator
                )
                for revision in revisions
            )
            paragraphs.append(text.text)
        return '\n'.join(paragraphs)

    def _audit_events(self) -> None:
        units = {unit.id: unit for unit in self.units}
        counts = Counter(
            (event.part, event.id)
            for event in self.events
            if event.kind is not EventKind.COMMENT
        )
        for index, event in enumerate(self.events):
            duplicate = counts[event.part, event.id] > 1
            if duplicate and event.kind is not EventKind.COMMENT:
                self.limitations.add(
                    Limitation(
                        'duplicate_revision_id', event.part, event.locator
                    )
                )
            if duplicate or any(
                not _range_is_complete(span, units) for span in event.ranges
            ):
                self.events[index] = replace(event, ranges=())
                if event.kind is EventKind.COMMENT:
                    self.limitations.add(
                        Limitation(
                            'unresolved_comment_range',
                            event.part,
                            event.locator,
                        )
                    )

    def _inventory_parts(self) -> None:
        for name, root in self.package.trees.items():
            if root.tag in STORY_ROOTS:
                self.limitations.add(Limitation('unsupported_story', name))
        for relationship in self.package.relationships:
            kind = relationship.kind.rsplit('/', 1)[-1].lower()
            if kind in MODERN_COMMENT_TYPES:
                self.limitations.add(
                    Limitation('modern_comments_metadata', relationship.target)
                )
        for relationship in self.package.external_relationships:
            self.limitations.add(
                Limitation(
                    'external_hyperlink_not_fetched',
                    relationship.source or '_rels/.rels',
                    affects_coverage=False,
                )
            )


def _range_is_complete(
    span: EventRange, units: dict[str, DocumentUnit]
) -> bool:
    unit = units[span.unit_id]
    view = (
        unit.proposed_view
        if span.projection is Projection.PROPOSED
        else unit.baseline_view
    )
    return view is not None and view.complete


def _has_structural_revision(properties: etree._Element) -> bool:
    return any(
        node.tag in STRUCTURAL_REVISIONS
        for node in properties.iterdescendants()
    )


def _is_merged(properties: etree._Element) -> bool:
    return any(
        child.tag in MERGE_PROPERTIES
        or (child.tag == w('gridSpan') and value(child) != '1')
        for child in properties
    )


def map_document(
    package: DocxPackage, revision: DocumentRevision
) -> DocumentMap:
    styles = _related_tree(package, 'styles')
    state = _Map(
        package, _Styles.from_tree(styles), StyleVisibility.from_tree(styles)
    )
    state.walk()
    return DocumentMap(
        revision=revision,
        main_part=package.main_part,
        parts=package.names,
        units=tuple(state.units),
        events=tuple(state.events),
        limitations=tuple(
            sorted(
                state.limitations,
                key=lambda x: (x.part, x.locator or '', x.code),
            )
        ),
    )
