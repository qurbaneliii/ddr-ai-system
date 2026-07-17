from __future__ import annotations

import shutil
import stat
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    """Raised when an archive violates an ingestion safety rule."""


@dataclass(slots=True)
class ArchiveInspection:
    archive: str
    entries: int
    files: int
    compressed_bytes: int
    uncompressed_bytes: int
    suffix_counts: dict[str, int]
    max_entry_ratio: float
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


EXECUTABLE_SUFFIXES = {
    ".bat", ".cmd", ".com", ".dll", ".exe", ".jar", ".msi", ".ps1", ".scr",
}
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".zip"}


def _validated_relative_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise UnsafeArchiveError(f"Unsafe archive path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise UnsafeArchiveError(f"Drive-qualified archive path: {name!r}")
    if not path.parts:
        raise UnsafeArchiveError("Empty archive entry name")
    return Path(*path.parts)


def inspect_zip(
    archive_path: str | Path,
    *,
    max_files: int = 20_000,
    max_uncompressed_bytes: int = 5 * 1024**3,
    max_entry_bytes: int = 1024**3,
    max_ratio: float = 200.0,
) -> ArchiveInspection:
    archive = Path(archive_path)
    seen: set[str] = set()
    suffixes: Counter[str] = Counter()
    total_uncompressed = 0
    total_compressed = 0
    maximum_ratio = 0.0
    warnings: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        files = [info for info in infos if not info.is_dir()]
        if len(files) > max_files:
            raise UnsafeArchiveError(f"Archive contains {len(files)} files; limit is {max_files}")
        for info in infos:
            relative = _validated_relative_path(info.filename)
            collision_key = relative.as_posix().casefold().rstrip("/")
            if collision_key in seen:
                raise UnsafeArchiveError(f"Filename collision: {info.filename!r}")
            seen.add(collision_key)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise UnsafeArchiveError(f"Symbolic link rejected: {info.filename!r}")
            if info.is_dir():
                continue
            suffix = relative.suffix.lower()
            suffixes[suffix or "<none>"] += 1
            if suffix in EXECUTABLE_SUFFIXES:
                raise UnsafeArchiveError(f"Executable archive entry rejected: {info.filename!r}")
            if suffix not in SUPPORTED_SUFFIXES:
                warnings.append(f"Unsupported file type will not be extracted: {info.filename}")
            if info.file_size > max_entry_bytes:
                raise UnsafeArchiveError(f"Entry exceeds size limit: {info.filename!r}")
            ratio = info.file_size / max(info.compress_size, 1)
            maximum_ratio = max(maximum_ratio, ratio)
            if ratio > max_ratio and info.file_size > 1024 * 1024:
                raise UnsafeArchiveError(f"Suspicious compression ratio for {info.filename!r}: {ratio:.1f}")
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
        if total_uncompressed > max_uncompressed_bytes:
            raise UnsafeArchiveError("Archive exceeds total uncompressed size limit")
    return ArchiveInspection(
        archive=str(archive),
        entries=len(infos),
        files=len(files),
        compressed_bytes=total_compressed,
        uncompressed_bytes=total_uncompressed,
        suffix_counts=dict(sorted(suffixes.items())),
        max_entry_ratio=round(maximum_ratio, 2),
        warnings=warnings,
    )


def safe_extract_zip(archive_path: str | Path, destination: str | Path) -> ArchiveInspection:
    inspection = inspect_zip(archive_path)
    target_root = Path(destination).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as bundle:
        for info in bundle.infolist():
            relative = _validated_relative_path(info.filename)
            target = (target_root / relative).resolve()
            if target != target_root and target_root not in target.parents:
                raise UnsafeArchiveError(f"Extraction escaped destination: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if relative.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise UnsafeArchiveError(f"Refusing to overwrite existing file: {target}")
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    return inspection

