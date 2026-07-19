from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

LOGGER = logging.getLogger(__name__)


class DatabaseBootstrapError(RuntimeError):
    """Safe database preparation error for the UI boundary."""


def sqlite_path(database_url: str) -> Path | None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("sqlite") or not parsed.database:
        return None
    return Path(parsed.database).resolve()


def validate_sqlite(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise DatabaseBootstrapError("The SQLite database file is unavailable.")
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            connection.close()
    except (sqlite3.DatabaseError, OSError) as exc:
        LOGGER.exception("SQLite validation failed for %s", path)
        raise DatabaseBootstrapError("The demo database failed validation.") from exc
    if integrity != "ok" or quick != "ok" or foreign_keys or not revision_row:
        raise DatabaseBootstrapError("The demo database failed integrity checks.")
    return {
        "integrity": integrity,
        "quick_check": quick,
        "foreign_key_violations": len(foreign_keys),
        "revision": revision_row[0],
    }


def _backup_sqlite(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    target_connection = sqlite3.connect(target, timeout=30)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    # Windows rejects fsync on a descriptor opened read-only. The file has
    # already been committed by SQLite, so a writable binary handle is enough
    # to flush the completed snapshot without changing its contents.
    with target.open("r+b") as stream:
        os.fsync(stream.fileno())


def prepare_runtime_database(
    database_url: str,
    *,
    cloud_runtime: bool | None = None,
    runtime_dir: Path | None = None,
) -> str:
    """Create an atomic, validated SQLite snapshot for Streamlit Cloud.

    SQLite's backup API captures a consistent snapshot even if a source WAL is
    present. The target identity is derived from the completed snapshot, and a
    partial or corrupt target is never reused.
    """

    source = sqlite_path(database_url)
    if source is None:
        return database_url
    if cloud_runtime is None:
        cloud_runtime = bool(os.getenv("STREAMLIT_SHARING_MODE")) or source.as_posix().startswith(
            "/mount/src/"
        )
    if not cloud_runtime:
        return database_url

    validate_sqlite(source)
    destination_dir = runtime_dir or Path(tempfile.gettempdir()) / "ddr_ai_system_runtime"
    destination_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="snapshot-", suffix=".db", dir=destination_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        _backup_sqlite(source, temporary)
        validate_sqlite(temporary)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        target = destination_dir / f"ddr_ai-{digest[:20]}.db"
        if target.exists():
            try:
                validate_sqlite(target)
                temporary.unlink()
                return f"sqlite:///{target.as_posix()}"
            except DatabaseBootstrapError:
                LOGGER.warning("Replacing an invalid runtime snapshot: %s", target)
        os.replace(temporary, target)
        validate_sqlite(target)
        return f"sqlite:///{target.as_posix()}"
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
