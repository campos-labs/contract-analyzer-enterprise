"""Armazenamento local de originais imutáveis, identificados por SHA-256."""

import os
import re
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from .model import DocumentRevision

_SHA256 = re.compile(r'[a-f0-9]{64}')


class StorageError(ValueError):
    """A identidade ou a integridade do objeto local não confere."""


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def _key(revision: DocumentRevision) -> str:
        if not _SHA256.fullmatch(revision.sha256) or revision.byte_size < 0:
            raise StorageError('Identidade de revisão inválida.')
        return f'originals/{revision.sha256}.docx'

    def read(self, revision: DocumentRevision) -> bytes:
        path = self._root / self._key(revision)
        if path.is_symlink() or not path.is_file():
            raise StorageError('Original da revisão não é um arquivo local.')
        with path.open('rb') as file:
            raw = file.read(revision.byte_size + 1)
        if len(raw) != revision.byte_size or (
            sha256(raw).hexdigest() != revision.sha256
        ):
            raise StorageError('Original armazenado diverge da revisão.')
        return raw

    def save(self, revision: DocumentRevision, raw: bytes) -> str:
        key = self._key(revision)
        if len(raw) != revision.byte_size or (
            sha256(raw).hexdigest() != revision.sha256
        ):
            raise StorageError('Original diverge da revisão informada.')
        destination = self._root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as file:
                staged = Path(file.name)
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            # Publica sem substituir um arquivo já confirmado por outro leitor.
            try:
                os.link(staged, destination)
            except FileExistsError:
                self.read(revision)
        finally:
            if staged is not None:
                staged.unlink()
        return key
