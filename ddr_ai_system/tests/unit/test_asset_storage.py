from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ddr_ai.config import Settings
from ddr_ai.db.models import Base, SourceDocument, StoredAsset
from ddr_ai.services.asset_storage import load_persisted_asset, persist_asset_record


def _session_and_source(size: int) -> tuple[Session, SourceDocument]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    source = SourceDocument(
        sha256="d" * 64,
        file_name="upload.pdf",
        source_path="temporary/upload.pdf",
        media_type="application/pdf",
        asset_kind="digital_pdf",
        byte_size=size,
        parser_version="test",
        processing_status="complete",
    )
    session.add(source)
    session.flush()
    return session, source


def test_default_asset_storage_is_truthful_metadata_only(tmp_path: Path) -> None:
    content = b"temporary bytes"
    path = tmp_path / "upload.pdf"
    path.write_bytes(content)
    session, source = _session_and_source(len(content))
    record = persist_asset_record(session, source, path, Settings(_env_file=None))
    assert record.storage_backend == "metadata_only"
    assert record.storage_status == "source_bytes_temporary"
    assert record.content_bytes is None
    assert load_persisted_asset(session, source.id) is None


def test_database_asset_storage_is_bounded_and_idempotent(tmp_path: Path) -> None:
    content = b"bounded bytes"
    path = tmp_path / "upload.pdf"
    path.write_bytes(content)
    session, source = _session_and_source(len(content))
    settings = Settings(asset_storage_backend="database", asset_database_max_mb=1, _env_file=None)
    first = persist_asset_record(session, source, path, settings)
    second = persist_asset_record(session, source, path, settings)
    assert first.id == second.id
    assert second.storage_status == "stored"
    assert load_persisted_asset(session, source.id) == content
    assert session.scalar(select(StoredAsset.storage_key)).startswith("sha256/")


def test_database_asset_storage_refuses_oversized_blob(tmp_path: Path) -> None:
    path = tmp_path / "large.pdf"
    path.write_bytes(b"small fixture; model size is authoritative")
    session, source = _session_and_source(2 * 1024 * 1024)
    settings = Settings(asset_storage_backend="database", asset_database_max_mb=1, _env_file=None)
    record = persist_asset_record(session, source, path, settings)
    assert record.storage_status == "metadata_only_size_limit"
    assert record.content_bytes is None
