"""Contratos imutáveis do mapa documental."""

from dataclasses import dataclass
from enum import StrEnum


class DocumentRole(StrEnum):
    PRIMARY = 'primary'
    ATTACHMENT = 'attachment'


class UnitKind(StrEnum):
    PARAGRAPH = 'paragraph'
    HEADING = 'heading'
    TABLE = 'table'
    ROW = 'row'
    CELL = 'cell'


class Projection(StrEnum):
    PROPOSED = 'proposed_view'
    BASELINE = 'baseline_view'


class EventKind(StrEnum):
    INSERT = 'insert'
    DELETE = 'delete'
    COMMENT = 'comment'


@dataclass(frozen=True, slots=True)
class DocumentRevision:
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class TextSegment:
    start: int
    end: int
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class TextView:
    text: str
    segments: tuple[TextSegment, ...]
    complete: bool = True


@dataclass(frozen=True, slots=True)
class DocumentUnit:
    id: str
    part: str
    locator: str
    kind: UnitKind
    parent_id: str | None = None
    heading_level: int | None = None
    style_id: str | None = None
    numbering_id: str | None = None
    numbering_level: int | None = None
    proposed_view: TextView | None = None
    baseline_view: TextView | None = None


@dataclass(frozen=True, slots=True)
class Limitation:
    code: str
    part: str
    locator: str | None = None
    affects_coverage: bool = True


@dataclass(frozen=True, slots=True)
class EventRange:
    unit_id: str
    projection: Projection
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class DocumentEvent:
    kind: EventKind
    id: str
    part: str
    locator: str
    author: str | None = None
    date: str | None = None
    before: str = ''
    after: str = ''
    ranges: tuple[EventRange, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentMap:
    revision: DocumentRevision
    main_part: str
    parts: tuple[str, ...]
    units: tuple[DocumentUnit, ...]
    events: tuple[DocumentEvent, ...] = ()
    limitations: tuple[Limitation, ...] = ()

    @property
    def coverage_complete(self) -> bool:
        return not any(item.affects_coverage for item in self.limitations)
