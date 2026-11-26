"""Malformed binary ZIP header regressions for DOCX ingestion."""

import struct
import subprocess
import sys

import pytest
from docx_helpers import make_parts, package_bytes

from contract_analyzer_enterprise.documents.opc import (
    PackageError,
    read_package,
)

END_OF_DIRECTORY = b'PK\x05\x06'
CENTRAL_ENTRY = b'PK\x01\x02'
CENTRAL_HEADER_SIZE = 46
CLI_USAGE_ERROR = 2


def _central_directory(raw: bytearray) -> tuple[int, int]:
    end = raw.rindex(END_OF_DIRECTORY)
    (offset,) = struct.unpack_from('<I', raw, end + 16)
    assert raw[offset : offset + len(CENTRAL_ENTRY)] == CENTRAL_ENTRY
    return offset, end


def _excessive_extract_version(raw: bytes) -> bytes:
    archive = bytearray(raw)
    central, _ = _central_directory(archive)
    # "Version needed to extract" in the first central directory entry.
    struct.pack_into('<H', archive, central + 6, 255)
    return bytes(archive)


def _extreme_zip64_offset(raw: bytes) -> bytes:
    archive = bytearray(raw)
    central, end = _central_directory(archive)
    name_size, extra_size = struct.unpack_from('<HH', archive, central + 28)
    extra_offset = central + CENTRAL_HEADER_SIZE + name_size
    # ZIP64 extra field with only the relative local header offset.
    extra = struct.pack('<HHQ', 0x0001, 8, 2**63)
    archive[extra_offset:extra_offset] = extra
    struct.pack_into('<H', archive, central + 30, extra_size + len(extra))
    struct.pack_into('<I', archive, central + 42, 0xFFFFFFFF)
    # Insertion shifts the end record and grows the central directory.
    size_offset = end + len(extra) + 12
    (directory_size,) = struct.unpack_from('<I', archive, size_offset)
    struct.pack_into('<I', archive, size_offset, directory_size + len(extra))
    return bytes(archive)


@pytest.mark.parametrize(
    'mutate_zip',
    [_excessive_extract_version, _extreme_zip64_offset],
    ids=['extract-version', 'zip64-offset'],
)
def test_invalid_zip_header_is_reported_by_cli(tmp_path, mutate_zip):
    raw = mutate_zip(package_bytes(make_parts()))
    with pytest.raises(PackageError, match='malformados'):
        read_package(raw)

    source = tmp_path / 'invalid.docx'
    source.write_bytes(raw)
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
    assert result.returncode == CLI_USAGE_ERROR
    assert b'Pacote DOCX com ZIP' in result.stderr
    assert b'Traceback' not in result.stderr
    assert not output.exists()
    assert not storage.exists()
