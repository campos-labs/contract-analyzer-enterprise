import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import pytest

from contract_analyzer_enterprise.documents.model import DocumentRevision
from contract_analyzer_enterprise.documents.storage import (
    LocalDocumentStorage,
    StorageError,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'docx'
USAGE_ERROR = 2


def test_inspection_cli_reports_and_preserves_originals(tmp_path):
    output = tmp_path / 'outputs' / 'map.json'
    storage = tmp_path / 'store'
    command = [
        sys.executable,
        '-m',
        'contract_analyzer_enterprise.documents',
        str(FIXTURES / 'contract_reference.docx'),
        '--anexo',
        str(FIXTURES / 'related_reference.docx'),
        '--storage',
        str(storage),
        '--output',
        str(output),
    ]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['operation'] == 'read'
    assert report['offsets'] == 'unicode_code_points_half_open'
    primary, attachment = report['documents']
    assert (primary['role'], attachment['role']) == ('primary', 'attachment')
    assert primary['document']['units'][0]['proposed_view']['text']
    assert (storage / primary['stored_as']).read_bytes() == (
        FIXTURES / 'contract_reference.docx'
    ).read_bytes()

    original_report = output.read_bytes()
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == USAGE_ERROR
    assert output.read_bytes() == original_report


def test_invalid_cli_input_produces_no_report_or_stored_original(tmp_path):
    source = tmp_path / 'invalid.docx'
    source.write_bytes(b'not a package')
    output = tmp_path / 'map.json'
    storage = tmp_path / 'store'
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'contract_analyzer_enterprise.documents',
            str(source),
            '--storage',
            str(storage),
            '--output',
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == USAGE_ERROR
    assert b'Traceback' not in result.stderr
    assert not output.exists()
    assert not storage.exists()


def test_publication_is_idempotent_and_refuses_corrupt_existing_object(
    tmp_path,
):
    raw = b'immutable original'
    revision = DocumentRevision(sha256(raw).hexdigest(), len(raw))
    storage = LocalDocumentStorage(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as workers:
        a = workers.submit(storage.save, revision, raw)
        b = workers.submit(storage.save, revision, raw)
        key = a.result()
        assert b.result() == key
    assert storage.read(revision) == raw
    assert list((tmp_path / 'originals').iterdir()) == [tmp_path / key]

    corrupted = b'x' * len(raw)
    (tmp_path / key).write_bytes(corrupted)
    with pytest.raises(StorageError, match='diverge'):
        storage.save(revision, raw)
    assert (tmp_path / key).read_bytes() == corrupted
