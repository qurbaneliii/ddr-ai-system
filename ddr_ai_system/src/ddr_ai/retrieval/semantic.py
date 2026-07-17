from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.db.models import Report, ReportSection, SourceDocument
from ddr_ai.nlp.providers import OllamaProvider
from ddr_ai.retrieval.lexical import SearchHit, lexical_search


@dataclass(frozen=True, slots=True)
class SemanticBuildResult:
    model: str
    dimension: int
    embedded: int
    unchanged: int
    cache_path: str


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS embeddings (
            section_id INTEGER PRIMARY KEY,
            content_hash TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            vector BLOB NOT NULL
        )"""
    )
    return connection


def _batched(items: list[tuple[int, str, str]], size: int) -> Iterable[list[tuple[int, str, str]]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def build_embedding_cache(
    session: Session,
    provider: OllamaProvider,
    cache_path: Path,
    *,
    batch_size: int = 16,
) -> SemanticBuildResult:
    """Explicit one-time/index-refresh operation; never called during Streamlit startup."""
    records = session.execute(
        select(ReportSection.id, ReportSection.text).where(ReportSection.text != "")
    ).all()
    pending: list[tuple[int, str, str]] = []
    unchanged = 0
    dimension = 0
    with _connect(cache_path) as connection:
        active_model_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'model'"
        ).fetchone()
        active_model = active_model_row[0] if active_model_row else None
        if active_model and active_model != provider.settings.ollama_embed_model:
            connection.execute("DELETE FROM embeddings")
            connection.execute("DELETE FROM metadata")
        cached_hashes = {
            int(section_id): content_hash
            for section_id, content_hash in connection.execute(
                "SELECT section_id, content_hash FROM embeddings"
            )
        }
        for section_id, text in records:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if cached_hashes.get(section_id) == digest:
                unchanged += 1
            else:
                pending.append((section_id, text, digest))
        for batch in _batched(pending, batch_size):
            result = provider.embed([text for _, text, _ in batch])
            dimension = result.dimension
            connection.executemany(
                """INSERT INTO embeddings(section_id, content_hash, dimension, vector)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(section_id) DO UPDATE SET
                     content_hash=excluded.content_hash,
                     dimension=excluded.dimension,
                     vector=excluded.vector""",
                [
                    (
                        section_id,
                        digest,
                        result.dimension,
                        np.asarray(vector, dtype=np.float32).tobytes(),
                    )
                    for (section_id, _, digest), vector in zip(batch, result.embeddings, strict=True)
                ],
            )
        if not dimension:
            dimension_row = connection.execute(
                "SELECT dimension FROM embeddings LIMIT 1"
            ).fetchone()
            dimension = int(dimension_row[0]) if dimension_row else 0
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('model', ?)",
            (provider.settings.ollama_embed_model,),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('dimension', ?)",
            (str(dimension),),
        )
    return SemanticBuildResult(
        provider.settings.ollama_embed_model,
        dimension,
        len(pending),
        unchanged,
        str(cache_path),
    )


def semantic_search(
    session: Session,
    provider: OllamaProvider,
    cache_path: Path,
    query: str,
    *,
    limit: int = 10,
) -> list[SearchHit]:
    if not cache_path.exists():
        return []
    query_result = provider.embed([query])
    query_vector = np.asarray(query_result.embeddings[0], dtype=np.float32)
    with _connect(cache_path) as connection:
        model_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'model'"
        ).fetchone()
        dimension_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'dimension'"
        ).fetchone()
        if not model_row or model_row[0] != provider.settings.ollama_embed_model:
            return []
        if not dimension_row or int(dimension_row[0]) != query_vector.size:
            return []
        similarities: list[tuple[int, float]] = []
        query_norm = float(np.linalg.norm(query_vector))
        if query_norm == 0:
            return []
        for section_id, vector_blob in connection.execute(
            "SELECT section_id, vector FROM embeddings"
        ):
            vector = np.frombuffer(vector_blob, dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.size == query_vector.size and norm:
                similarities.append((int(section_id), float(np.dot(query_vector, vector) / (query_norm * norm))))
    top = sorted(similarities, key=lambda item: item[1], reverse=True)[:limit]
    if not top:
        return []
    scores = dict(top)
    statement = (
        select(ReportSection, Report, SourceDocument)
        .join(Report, Report.id == ReportSection.report_id)
        .join(SourceDocument, SourceDocument.id == Report.source_document_id)
        .where(ReportSection.id.in_(scores))
    )
    hits = []
    for section, report, document in session.execute(statement):
        hits.append(
            SearchHit(
                section.id,
                report.id,
                document.file_name,
                report.wellbore,
                report.period_end.isoformat() if report.period_end else None,
                section.page_number,
                section.section_type,
                section.text,
                scores[section.id],
            )
        )
    return sorted(hits, key=lambda item: item.score, reverse=True)


def hybrid_search(
    session: Session,
    provider: OllamaProvider | None,
    cache_path: Path,
    query: str,
    *,
    limit: int = 10,
) -> list[SearchHit]:
    lexical = lexical_search(session, query, limit=max(limit, 10))
    semantic = semantic_search(session, provider, cache_path, query, limit=max(limit, 10)) if provider else []
    combined: dict[int, tuple[SearchHit, float]] = {}
    for rank, hit in enumerate(lexical, start=1):
        combined[hit.section_id] = (hit, 0.55 / (20 + rank))
    for rank, hit in enumerate(semantic, start=1):
        previous = combined.get(hit.section_id)
        score = (previous[1] if previous else 0.0) + 0.45 / (20 + rank)
        combined[hit.section_id] = (previous[0] if previous else hit, score)
    return [item[0] for item in sorted(combined.values(), key=lambda item: item[1], reverse=True)[:limit]]
