"""Inspeção local de um principal e anexos pela mesma fronteira de leitura."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from .model import DocumentMap, DocumentRevision, DocumentRole
from .opc import PackageError, PackageLimits, read_package
from .storage import LocalDocumentStorage
from .word import map_document

MAX_ATTACHMENTS = 8
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InspectedDocument:
    role: DocumentRole
    stored_as: str
    document: DocumentMap
    coverage_complete: bool


@dataclass(frozen=True, slots=True)
class InspectionReport:
    documents: tuple[InspectedDocument, ...]
    schema_version: int = 1
    operation: str = 'read'
    offsets: str = 'unicode_code_points_half_open'


def _inspect_one(
    path: Path,
    limits: PackageLimits,
    remaining: int,
) -> tuple[bytes, DocumentMap, int]:
    if path.suffix.lower() != '.docx' or not path.is_file():
        raise PackageError(f'Entrada deve ser um arquivo DOCX: {path.name}')
    cap = min(limits.max_input_bytes, remaining)
    with path.open('rb') as source:
        raw = source.read(cap + 1)
    if len(raw) > cap:
        raise PackageError(f'Limite de entrada excedido: {path.name}')

    revision = DocumentRevision(sha256(raw).hexdigest(), len(raw))
    package = read_package(raw, limits)
    return raw, map_document(package, revision), package.xml_node_count


def inspect_documents(
    primary: Path,
    attachments: Sequence[Path],
    storage: LocalDocumentStorage,
    *,
    limits: PackageLimits = PackageLimits(),
) -> InspectionReport:
    if len(attachments) > MAX_ATTACHMENTS:
        raise PackageError(f'Máximo de {MAX_ATTACHMENTS} anexos por inspeção.')
    inputs = [(DocumentRole.PRIMARY, primary)]
    inputs.extend((DocumentRole.ATTACHMENT, path) for path in attachments)
    remaining = MAX_TOTAL_INPUT_BYTES
    remaining_nodes = limits.max_xml_nodes
    validated: list[tuple[DocumentRole, bytes, DocumentMap]] = []
    for role, path in inputs:
        if remaining_nodes <= 0:
            raise PackageError('Limite de nós XML da inspeção excedido.')
        raw, document, nodes = _inspect_one(
            path,
            replace(limits, max_xml_nodes=remaining_nodes),
            remaining,
        )
        validated.append((role, raw, document))
        remaining -= len(raw)
        remaining_nodes -= nodes

    return InspectionReport(
        tuple(
            InspectedDocument(
                role,
                storage.save(document.revision, raw),
                document,
                document.coverage_complete,
            )
            for role, raw, document in validated
        )
    )
