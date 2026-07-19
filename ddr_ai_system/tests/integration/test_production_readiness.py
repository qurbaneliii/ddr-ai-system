from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import select

from ddr_ai.db.models import SeedVersion, SourceDocument
from ddr_ai.db.seeding import seed_database
from ddr_ai.db.session import session_scope, upgrade_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_DATABASE = PROJECT_ROOT / "data" / "processed" / "ddr_ai.db"


def test_committed_database_is_integral_current_and_source_backed() -> None:
    with sqlite3.connect(COMMITTED_DATABASE) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_documents",
                "reports",
                "operations",
                "plots",
                "plot_points",
                "anomalies",
                "equipment_failures",
                "failure_operation_matches",
                "retrieval_chunks",
            )
        }
        matched = connection.execute(
            "SELECT COUNT(*) FROM failure_operation_matches WHERE match_status = 'exact'"
        ).fetchone()[0]

    assert counts == {
        "source_documents": 1060,
        "reports": 1000,
        "operations": 10983,
        "plots": 60,
        "plot_points": 1009,
        "anomalies": 1291,
        "equipment_failures": 244,
        "failure_operation_matches": 244,
        "retrieval_chunks": 18895,
    }
    assert matched == 242


def test_seed_database_is_explicit_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "seed-source.db"
    target = tmp_path / "seed-target.db"
    source_url = f"sqlite:///{source.as_posix()}"
    target_url = f"sqlite:///{target.as_posix()}"
    upgrade_schema(source_url)
    with session_scope(source_url) as session:
        session.add(
            SourceDocument(
                sha256="a" * 64,
                file_name="seed.pdf",
                source_path="seed.pdf",
                media_type="application/pdf",
                asset_kind="digital_pdf",
                byte_size=1,
                parser_version="test",
                processing_status="complete",
            )
        )

    first = seed_database(source_url, target_url, seed_version="test-v1")
    second = seed_database(source_url, target_url, seed_version="test-v1")

    assert first["status"] == "applied"
    assert first["source_documents"] == 1
    assert second == {"seed_version": "test-v1", "status": "already_applied"}
    with session_scope(target_url) as session:
        assert session.scalar(select(SeedVersion.version)) == "test-v1"
        assert session.scalar(select(SourceDocument.file_name)) == "seed.pdf"
