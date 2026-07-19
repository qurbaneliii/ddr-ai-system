from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.config import Settings
from ddr_ai.db.models import SourceDocument, StoredAsset


def persist_asset_record(
    session: Session,
    source: SourceDocument,
    path: Path,
    settings: Settings,
) -> StoredAsset:
    """Persist bounded raw bytes when explicitly enabled, otherwise truthful metadata only."""

    backend = settings.asset_storage_backend.casefold().strip()
    limit = settings.asset_database_max_mb * 1024 * 1024
    content: bytes | None = None
    if backend == "database" and source.byte_size <= limit:
        content = path.read_bytes()
        status = "stored"
    elif backend == "database":
        status = "metadata_only_size_limit"
    else:
        backend = "metadata_only"
        status = "source_bytes_temporary"
    storage_key = f"sha256/{source.sha256[:2]}/{source.sha256}"
    record = session.scalar(
        select(StoredAsset).where(StoredAsset.source_document_id == source.id)
    )
    if record is None:
        record = StoredAsset(
            source_document_id=source.id,
            sha256=source.sha256,
            file_name=source.file_name,
            media_type=source.media_type,
            byte_size=source.byte_size,
            storage_backend=backend,
            storage_key=storage_key,
            storage_status=status,
            content_bytes=content,
        )
        session.add(record)
    else:
        record.file_name = source.file_name
        record.media_type = source.media_type
        record.byte_size = source.byte_size
        record.storage_backend = backend
        record.storage_key = storage_key
        record.storage_status = status
        record.content_bytes = content
    session.flush()
    return record


def load_persisted_asset(session: Session, source_document_id: int) -> bytes | None:
    return session.scalar(
        select(StoredAsset.content_bytes).where(
            StoredAsset.source_document_id == source_document_id,
            StoredAsset.storage_status == "stored",
        )
    )
