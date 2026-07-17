from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrade_creates_failure_correlation_schema(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DDR_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        operation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(operations)")
        }
    assert version == "0003"
    assert {"equipment_failures", "failure_operation_matches"} <= tables
    assert {"start_datetime", "end_datetime", "temporal_status"} <= operation_columns
