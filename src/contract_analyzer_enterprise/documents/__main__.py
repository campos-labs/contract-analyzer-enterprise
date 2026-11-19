"""Comando técnico de inspeção de DOCX local."""

import argparse
import json
import os
from dataclasses import fields
from pathlib import Path
from tempfile import NamedTemporaryFile

from .service import InspectionReport, inspect_documents
from .storage import LocalDocumentStorage


def _record(value: object) -> dict[str, object]:
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _write_report(path: Path, report: InspectionReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged: Path | None = None
    try:
        with NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            delete=False,
        ) as file:
            staged = Path(file.name)
            json.dump(
                report, file, ensure_ascii=False, indent=2, default=_record
            )
            file.write('\n')
        # Publica sem substituir o destino.
        os.link(staged, path)
    finally:
        if staged is not None:
            staged.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('principal', type=Path, help='DOCX principal')
    parser.add_argument('--anexo', type=Path, action='append', default=[])
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.path.lexists(args.output):
            raise ValueError(
                'Escolha um caminho de relatório que ainda não existe.'
            )
        report = inspect_documents(
            args.principal,
            args.anexo,
            LocalDocumentStorage(args.storage),
        )
        _write_report(args.output, report)
    except (ValueError, OSError) as error:
        parser.exit(2, f'Falha na inspeção: {error}\n')


if __name__ == '__main__':
    main()
