from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.config import Settings
from ddr_ai.db.models import SourceDocument, StoredAsset


class AssetIntegrityError(ValueError):
    """Stored bytes do not match their source-backed metadata."""


def _validate_image(content: bytes) -> None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AssetIntegrityError("Stored image bytes failed format validation.") from exc


def _validate_content(
    content: bytes,
    *,
    expected_sha256: str,
    expected_size: int,
    media_type: str,
) -> None:
    if len(content) != expected_size:
        raise AssetIntegrityError("Stored asset byte size does not match metadata.")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise AssetIntegrityError("Stored asset hash does not match metadata.")
    if media_type.startswith("image/"):
        _validate_image(content)
    elif media_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise AssetIntegrityError("Stored PDF bytes failed signature validation.")


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
    if backend == "database" and source.byte_size > limit:
        raise ValueError("Asset exceeds the configured persistent database byte limit.")
    if backend == "database":
        content = path.read_bytes()
        _validate_content(
            content,
            expected_sha256=source.sha256,
            expected_size=source.byte_size,
            media_type=source.media_type,
        )
        status = "stored"
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
    record = session.scalar(
        select(StoredAsset).where(StoredAsset.source_document_id == source_document_id)
    )
    if record is None or record.storage_status != "stored" or record.content_bytes is None:
        return None
    _validate_content(
        record.content_bytes,
        expected_sha256=record.sha256,
        expected_size=record.byte_size,
        media_type=record.media_type,
    )
    return record.content_bytes
