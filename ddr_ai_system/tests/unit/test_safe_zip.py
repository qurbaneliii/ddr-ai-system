from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from ddr_ai.ingestion.safe_zip import UnsafeArchiveError, inspect_zip, safe_extract_zip


def test_safe_zip_extracts_supported_file(tmp_path: Path) -> None:
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/report.pdf", b"%PDF-1.4\n")
    inspection = safe_extract_zip(archive, tmp_path / "out")
    assert inspection.files == 1
    assert (tmp_path / "out" / "nested" / "report.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("name", ["../escape.pdf", "/absolute.pdf", "C:/drive.pdf"])
def test_safe_zip_rejects_path_traversal(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, b"x")
    with pytest.raises(UnsafeArchiveError):
        inspect_zip(archive)


def test_safe_zip_rejects_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.pdf")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(info, "target")
    with pytest.raises(UnsafeArchiveError, match="Symbolic link"):
        inspect_zip(archive)


def test_safe_zip_rejects_executable(tmp_path: Path) -> None:
    archive = tmp_path / "exec.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("payload.exe", b"MZ")
    with pytest.raises(UnsafeArchiveError, match="Executable"):
        inspect_zip(archive)

