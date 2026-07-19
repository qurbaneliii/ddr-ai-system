from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ddr_ai.db.bootstrap import (
    DatabaseBootstrapError,
    prepare_runtime_database,
    sqlite_path,
    validate_sqlite,
)


def _valid_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0004')")
        connection.execute("CREATE TABLE facts (value TEXT NOT NULL)")
        connection.execute("INSERT INTO facts VALUES ('source-backed')")


def test_runtime_snapshot_is_valid_consistent_and_reused(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    runtime = tmp_path / "runtime"
    _valid_database(source)

    first_url = prepare_runtime_database(
        f"sqlite:///{source.as_posix()}", cloud_runtime=True, runtime_dir=runtime
    )
    second_url = prepare_runtime_database(
        f"sqlite:///{source.as_posix()}", cloud_runtime=True, runtime_dir=runtime
    )

    assert first_url == second_url
    target = sqlite_path(first_url)
    assert target is not None
    assert target != source
    assert validate_sqlite(target)["revision"] == "0004"
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM facts").fetchone() == ("source-backed",)


def test_invalid_sqlite_is_never_promoted(tmp_path: Path) -> None:
    source = tmp_path / "invalid.db"
    source.write_bytes(b"not a sqlite database")

    with pytest.raises(DatabaseBootstrapError):
        prepare_runtime_database(
            f"sqlite:///{source.as_posix()}",
            cloud_runtime=True,
            runtime_dir=tmp_path / "runtime",
        )

    assert not list((tmp_path / "runtime").glob("ddr_ai-*.db"))
