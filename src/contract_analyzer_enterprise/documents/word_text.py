"""WordprocessingML names and read-only text projection."""

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from lxml import etree

from .model import (
    DocumentEvent,
    EventKind,
    EventRange,
    Limitation,
    Projection,
    TextSegment,
    TextView,
)

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ALTERNATE_CONTENT = (
    '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
    'AlternateContent'
)
ALTERNATE_PROPERTIES = 'unsupported_alternate_properties'


def has_alternate_content(node: etree._Element) -> bool:
    return next(node.iter(ALTERNATE_CONTENT), None) is not None


def w(local: str) -> str:
    return f'{{{W}}}{local}'


def value(node: etree._Element | None, name: str = 'val') -> str | None:
    return node.get(w(name)) if node is not None else None


def children(
    node: etree._Element, path: str
) -> Iterator[tuple[etree._Element, str]]:
    """XPath with per-QName ordinals, counted once in document order."""
    counts: Counter[str] = Counter()
    position = 0
    for child in node:
        if not isinstance(child.tag, str):
            continue
        position += 1
        counts[child.tag] += 1
        if child.tag.startswith(f'{{{W}}}'):
            local = etree.QName(child).localname
            yield child, f'{path}/w:{local}[{counts[child.tag]}]'
        else:
            yield child, f'{path}/*[{position}]'


def w_names(names: str) -> frozenset[str]:
    return frozenset(map(w, names.split()))


# Property elements are not projected. These markers alter the structure or
# record a revision that this feature cannot reverse.
STRUCTURAL_REVISIONS = w_names(
    'cellIns cellDel cellMerge numberingChange numberChange pPrChange '
    'rPrChange tblPrChange tblGridChange trPrChange tcPrChange '
    'sectPrChange tblPrExChange ins del moveFrom moveTo'
)
RANGE_MARKERS = w_names('commentRangeStart commentRangeEnd commentReference')
TEXT_REVISIONS = w_names('ins del')
MOVES = w_names(
    'moveFrom moveTo moveFromRangeStart moveFromRangeEnd '
    'moveToRangeStart moveToRangeEnd'
)
HARMLESS_MARKERS = w_names('bookmarkStart bookmarkEnd proofErr annotationRef')
MAX_ACTIVE_COMMENTS = 32
MAX_COMMENT_SPANS = 50_000
RUN_SEPARATORS = {
    w('tab'): '\t',
    w('cr'): '\n',
    w('noBreakHyphen'): '\u2011',
    w('softHyphen'): '\u00ad',
}
RUN_TEXT = w_names('t delText tab br cr noBreakHyphen softHyphen')
RENDERED_PAGE_BREAK = w('lastRenderedPageBreak')


@dataclass(slots=True)
class _Projection:
    segments: list[TextSegment] = field(default_factory=list)
    offset: int = 0
    complete: bool = True

    def append(self, text: str, path: str) -> None:
        if text:
            end = self.offset + len(text)
            self.segments.append(TextSegment(self.offset, end, path, text))
            self.offset = end

    def view(self, *, complete: bool) -> TextView:
        return TextView(
            ''.join(segment.text for segment in self.segments),
            tuple(self.segments),
            complete and self.complete,
        )


@dataclass(slots=True)
class _CommentRange:
    starts: int = 0
    ends: int = 0
    references: int = 0
    spans: list[EventRange] = field(default_factory=list)
    invalid: bool = False


@dataclass(slots=True)
class CommentRanges:
    records: dict[str, _CommentRange] = field(default_factory=dict)
    active: set[str] = field(default_factory=set)
    remaining_spans: int = MAX_COMMENT_SPANS

    def gap(self) -> None:
        for comment_id in self.active:
            self.records[comment_id].invalid = True


@dataclass(slots=True)
class ParagraphText:
    part: str
    unit_id: str
    comments: CommentRanges
    events: list[DocumentEvent]
    limitations: set[Limitation]
    complete: bool = True
    run_limitation: Callable[[etree._Element], str | None] | None = None
    projections: dict[Projection, _Projection] = field(
        default_factory=lambda: {
            projection: _Projection() for projection in Projection
        }
    )
    local_comment_starts: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )

    def read(
        self, paragraph: etree._Element, path: str
    ) -> tuple[TextView, TextView]:
        self.local_comment_starts.update({
            comment_id: (0, 0) for comment_id in self.comments.active
        })
        self._content(paragraph, path)
        for comment_id in sorted(self.comments.active):
            self._capture(comment_id)
        return tuple(
            self.projections[p].view(complete=self.complete)
            for p in (Projection.PROPOSED, Projection.BASELINE)
        )

    def _gap(
        self, code: str, path: str, projection: Projection | None = None
    ) -> None:
        if projection is None:
            self.complete = False
        else:
            self.projections[projection].complete = False
        self.limitations.add(Limitation(code, self.part, path))
        self.comments.gap()

    def _offsets(self) -> tuple[int, int]:
        return (
            self.projections[Projection.PROPOSED].offset,
            self.projections[Projection.BASELINE].offset,
        )

    def _capture(self, comment_id: str) -> None:
        record = self.comments.records[comment_id]
        if not self.complete:
            record.invalid = True
        starts = self.local_comment_starts.pop(comment_id, None)
        if starts is None:
            record.invalid = True
            return
        for projection, start, end in zip(
            (Projection.PROPOSED, Projection.BASELINE),
            starts,
            self._offsets(),
            strict=True,
        ):
            if start < end:
                if not self.comments.remaining_spans:
                    record.invalid = True
                    self.limitations.add(
                        Limitation('comment_span_limit', self.part)
                    )
                    return
                record.spans.append(
                    EventRange(self.unit_id, projection, start, end)
                )
                self.comments.remaining_spans -= 1

    def _comment(self, node: etree._Element, path: str) -> None:
        comment_id = value(node, 'id')
        if comment_id is None:
            self.limitations.add(
                Limitation('invalid_comment_range', self.part, path)
            )
            return
        record = self.comments.records.setdefault(comment_id, _CommentRange())
        if not self.complete:
            record.invalid = True
        if node.tag == w('commentRangeStart'):
            record.starts += 1
            if comment_id in self.comments.active:
                record.invalid = True
            elif len(self.comments.active) >= MAX_ACTIVE_COMMENTS:
                record.invalid = True
                self.limitations.add(
                    Limitation('active_comment_limit', self.part, path)
                )
                return
            self.comments.active.add(comment_id)
            self.local_comment_starts[comment_id] = self._offsets()
        elif node.tag == w('commentRangeEnd'):
            record.ends += 1
            if comment_id not in self.comments.active:
                record.invalid = True
                return
            self._capture(comment_id)
            self.comments.active.remove(comment_id)
        else:
            record.references += 1

    def _content(self, node: etree._Element, path: str) -> None:
        for child, child_path in children(node, path):
            if child.tag == w('r'):
                self._run(child, child_path)
            elif child.tag == w('pPr') and node.tag == w('p'):
                self._properties(child, child_path)
            elif child.tag == w('hyperlink') and node.tag == w('p'):
                self._content(child, child_path)
            elif child.tag in TEXT_REVISIONS and node.tag == w('p'):
                self._revision(child, child_path)
            elif child.tag in RANGE_MARKERS:
                self._comment(child, child_path)
            elif child.tag in MOVES:
                self._gap('unsupported_move', child_path)
            elif child.tag not in HARMLESS_MARKERS:
                self._gap('unsupported_paragraph_content', child_path)

    def _properties(
        self,
        node: etree._Element,
        path: str,
        projection: Projection | None = None,
    ) -> None:
        if has_alternate_content(node):
            self._gap(ALTERNATE_PROPERTIES, path, projection)
        if any(
            child.tag in STRUCTURAL_REVISIONS
            for child in node.iterdescendants()
        ):
            self._gap('unsupported_structural_revision', path)

    def _run(
        self,
        node: etree._Element,
        path: str,
        *,
        revision: Projection | None = None,
    ) -> None:
        start = self._offsets()
        for child, child_path in children(node, path):
            if child.tag in RUN_TEXT:
                self._leaf(child, child_path, revision)
            elif child.tag == RENDERED_PAGE_BREAK and not len(child):
                # Paginação calculada pelo Word não faz parte do texto.
                continue
            elif child.tag == w('rPr'):
                self._properties(child, child_path, revision)
            elif child.tag == w('commentReference'):
                self._comment(child, child_path)
            elif child.tag in MOVES:
                self._gap('unsupported_move', child_path)
            elif child.tag not in HARMLESS_MARKERS:
                self._gap('unsupported_run_content', child_path)
        if (
            self.run_limitation is not None
            and self._offsets() != start
            and (code := self.run_limitation(node))
        ):
            self._gap(code, path, revision)

    def _leaf(
        self,
        node: etree._Element,
        path: str,
        revision: Projection | None,
    ) -> None:
        if len(node):
            self._gap('unsupported_text_node', path)
            return
        if node.tag == w('delText') and revision is not Projection.BASELINE:
            self._gap('unpaired_deleted_text', path)
            return
        if node.tag == w('t') and revision is Projection.BASELINE:
            self._gap('unsupported_revision_content', path)
            return
        if node.tag == w('br') and value(node, 'type') not in {
            None,
            'textWrapping',
        }:
            self._gap('unsupported_break', path)
            return
        text = RUN_SEPARATORS.get(
            node.tag, '\n' if node.tag == w('br') else node.text or ''
        )
        for projection, builder in self.projections.items():
            if revision is None or projection is revision:
                builder.append(text, path)

    def _revision(self, node: etree._Element, path: str) -> None:
        word_id = value(node, 'id')
        if word_id is None or not _supports_text_revision(node):
            self._gap('unsupported_text_revision', path)
            return
        deleted = node.tag == w('del')
        projection = Projection.BASELINE if deleted else Projection.PROPOSED
        builder = self.projections[projection]
        start, first_segment = builder.offset, len(builder.segments)
        for run, run_path in children(node, path):
            if run.tag == w('r'):
                self._run(run, run_path, revision=projection)
        end = builder.offset
        text = ''.join(
            segment.text for segment in builder.segments[first_segment:]
        )
        self.events.append(
            DocumentEvent(
                kind=EventKind.DELETE if deleted else EventKind.INSERT,
                id=word_id,
                part=self.part,
                locator=path,
                author=value(node, 'author'),
                date=value(node, 'date'),
                before=text if deleted else '',
                after='' if deleted else text,
                ranges=(
                    (EventRange(self.unit_id, projection, start, end),)
                    if start < end
                    else ()
                ),
            )
        )


def _supports_text_revision(node: etree._Element) -> bool:
    """Support only direct inline run changes with understood children."""
    text_tag = w('delText') if node.tag == w('del') else w('t')
    permissible = {
        text_tag,
        w('rPr'),
        w('br'),
        RENDERED_PAGE_BREAK,
        *RUN_SEPARATORS,
    }
    return bool(len(node)) and all(
        run.tag == w('r')
        and all(
            child.tag in permissible
            and (
                not len(child)
                or (
                    child.tag == w('rPr')
                    and not any(
                        descendant.tag in STRUCTURAL_REVISIONS
                        for descendant in child.iterdescendants()
                    )
                )
            )
            and (
                child.tag != w('br')
                or value(child, 'type') in {None, 'textWrapping'}
            )
            for child in run
        )
        for run in node
    )
