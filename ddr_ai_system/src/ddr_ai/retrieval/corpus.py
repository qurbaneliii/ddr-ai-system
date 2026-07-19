from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import islice
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ddr_ai.chat.query import QueryPlan
from ddr_ai.db.models import (
    EquipmentFailure,
    ExtractedValue,
    Operation,
    Plot,
    PlotPoint,
    Report,
    ReportSection,
    RetrievalChunk,
    SectionTableRow,
    SourceDocument,
)

MAX_CHUNK_TEXT = 6000
MAX_EXCERPT = 700
MAX_EVIDENCE_CHARS = 7000


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: int
    source_type: str
    source_record_id: int | None
    source_document_id: int
    report_id: int | None
    file_name: str
    wellbore: str | None
    report_date: str | None
    page_number: int | None
    section_type: str | None
    text: str
    score: float
    metadata: dict[str, Any]

    def evidence(self) -> dict[str, Any]:
        return {
            "evidence_id": f"retrieval_chunk:{self.chunk_id}",
            "source_type": self.source_type,
            "source_record_id": self.source_record_id,
            "source_document_id": self.source_document_id,
            "report_id": self.report_id,
            "file_name": self.file_name,
            "wellbore": self.wellbore,
            "report_date": self.report_date,
            "page_number": self.page_number,
            "section": self.section_type,
            "excerpt": self.text[:MAX_EXCERPT],
            "score": round(self.score, 4),
        }


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    corpus_status: str
    corpus_fingerprint: str
    index_chunk_count: int
    index_build_seconds: float
    stage: int
    candidate_count: int
    evidence_hit_count: int
    source_types: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidencePack:
    plan: QueryPlan
    deterministic_summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    diagnostics: RetrievalDiagnostics | None = None

    def bounded_evidence(self) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        total = 0
        seen: set[str] = set()
        for item in self.evidence:
            evidence_id = str(item.get("evidence_id") or "")
            if evidence_id and evidence_id in seen:
                continue
            excerpt = str(item.get("excerpt") or "")[:MAX_EXCERPT]
            if total + len(excerpt) > MAX_EVIDENCE_CHARS:
                break
            copy = {**item, "excerpt": excerpt}
            selected.append(copy)
            total += len(excerpt)
            if evidence_id:
                seen.add(evidence_id)
        return selected[:12]


def _batches(values: Sequence[Any], size: int) -> Iterator[list[Any]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def _text(*values: Any) -> str:
    parts = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        else:
            rendered = str(value)
        rendered = " ".join(rendered.split())
        if rendered and rendered.casefold() not in {"none", "n/a", "not available"}:
            parts.append(rendered)
    return " | ".join(parts)[:MAX_CHUNK_TEXT]


def _chunk(
    *,
    key: str,
    source_type: str,
    source_record_id: int | None,
    document: SourceDocument,
    report: Report | None,
    page_number: int | None,
    section_type: str | None,
    text: str,
    metadata: dict[str, Any],
) -> RetrievalChunk | None:
    searchable = _text(text)
    if not searchable:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    return RetrievalChunk(
        chunk_key=key,
        source_type=source_type,
        source_record_id=source_record_id,
        source_document_id=document.id,
        report_id=report.id if report else None,
        wellbore=report.wellbore if report else None,
        period_end=report.period_end if report else None,
        page_number=page_number,
        section_type=section_type,
        searchable_text=searchable,
        metadata_json={"file_name": document.file_name, **metadata},
        content_hash=hashlib.sha256(searchable.encode("utf-8")).hexdigest(),
        created_at=now,
        updated_at=now,
    )


def _document_chunks(session: Session, document: SourceDocument) -> list[RetrievalChunk]:
    chunks: list[RetrievalChunk | None] = []
    report = session.scalar(select(Report).where(Report.source_document_id == document.id))
    if report:
        chunks.append(
            _chunk(
                key=f"report_summary:{report.id}",
                source_type="report_summary",
                source_record_id=report.id,
                document=document,
                report=report,
                page_number=1,
                section_type="summary_report",
                text=_text(
                    "wellbore", report.wellbore, "completed activities", report.summary_activities,
                    "planned activities", report.summary_planned, "status", report.status_raw,
                ),
                metadata={"report_number": report.report_number},
            )
        )
        sections = list(
            session.scalars(
                select(ReportSection)
                .where(ReportSection.report_id == report.id)
                .order_by(ReportSection.page_number, ReportSection.id)
            )
        )
        for item in sections:
            chunks.append(
                _chunk(
                    key=f"report_section:{item.id}",
                    source_type="report_section",
                    source_record_id=item.id,
                    document=document,
                    report=report,
                    page_number=item.page_number,
                    section_type=item.section_type,
                    text=_text(item.heading_raw, item.text),
                    metadata={"heading": item.heading_raw},
                )
            )
        operations = list(
            session.scalars(
                select(Operation)
                .where(Operation.report_id == report.id)
                .order_by(Operation.page_number, Operation.row_index)
            )
        )
        for page_number in sorted({item.page_number for item in operations}):
            page_rows = [item for item in operations if item.page_number == page_number]
            for group_index, group in enumerate(_batches(page_rows, 5)):
                chunks.append(
                    _chunk(
                        key=f"operation:{report.id}:{page_number}:{group_index}",
                        source_type="operation",
                        source_record_id=group[0].id,
                        document=document,
                        report=report,
                        page_number=page_number,
                        section_type="operations",
                        text=_text(
                            [
                                {
                                    "time": [row.start_time_raw, row.end_time_raw],
                                    "activity": row.main_activity_raw or row.main_activity_normalized,
                                    "subactivity": row.sub_activity_raw or row.sub_activity_normalized,
                                    "state": row.state_raw or row.state_normalized,
                                    "remark": row.remark,
                                    "depth_mmd": row.end_depth_mmd,
                                }
                                for row in group
                            ]
                        ),
                        metadata={"record_ids": [row.id for row in group]},
                    )
                )
        values = list(
            session.scalars(
                select(ExtractedValue)
                .where(ExtractedValue.source_document_id == document.id)
                .order_by(ExtractedValue.page_number, ExtractedValue.id)
            )
        )
        value_groups: dict[tuple[int, str | None], list[ExtractedValue]] = {}
        for value_item in values:
            value_groups.setdefault((value_item.page_number, value_item.section_type), []).append(value_item)
        for (page_number, section_type), value_rows in value_groups.items():
            for group_index, group in enumerate(_batches(value_rows, 20)):
                chunks.append(
                    _chunk(
                        key=f"extracted_value:{document.id}:{page_number}:{section_type}:{group_index}",
                        source_type="extracted_value",
                        source_record_id=group[0].id,
                        document=document,
                        report=report,
                        page_number=page_number,
                        section_type=section_type,
                        text=_text(
                            [
                                {
                                    "field": row.field_name,
                                    "raw": row.raw_value,
                                    "value": row.normalized_text or row.normalized_number,
                                    "unit": row.unit_normalized or row.unit_raw,
                                }
                                for row in group
                            ]
                        ),
                        metadata={"record_ids": [row.id for row in group]},
                    )
                )
        table_rows = list(
            session.scalars(
                select(SectionTableRow)
                .where(SectionTableRow.report_id == report.id)
                .order_by(
                    SectionTableRow.page_number,
                    SectionTableRow.section_type,
                    SectionTableRow.table_index,
                    SectionTableRow.row_index,
                )
            )
        )
        table_groups: dict[tuple[int, str, int], list[SectionTableRow]] = {}
        for table_item in table_rows:
            table_groups.setdefault((table_item.page_number, table_item.section_type, table_item.table_index), []).append(table_item)
        for (page_number, section_type, table_index), grouped_table_rows in table_groups.items():
            for group_index, group in enumerate(_batches(grouped_table_rows, 12)):
                chunks.append(
                    _chunk(
                        key=f"section_table:{report.id}:{page_number}:{table_index}:{group_index}",
                        source_type="section_table_row",
                        source_record_id=group[0].id,
                        document=document,
                        report=report,
                        page_number=page_number,
                        section_type=section_type,
                        text=_text(
                            [
                                {
                                    "headers": row.header_cells_json,
                                    "cells": row.raw_cells_json,
                                    "normalized": row.normalized_cells_json,
                                }
                                for row in group
                            ]
                        ),
                        metadata={"record_ids": [row.id for row in group], "table_index": table_index},
                    )
                )
        failures = list(
            session.scalars(
                select(EquipmentFailure)
                .where(EquipmentFailure.report_id == report.id)
                .order_by(EquipmentFailure.page_number, EquipmentFailure.table_index, EquipmentFailure.row_index)
            )
        )
        for failure_item in failures:
            chunks.append(
                _chunk(
                    key=f"equipment_failure:{failure_item.id}",
                    source_type="equipment_failure",
                    source_record_id=failure_item.id,
                    document=document,
                    report=report,
                    page_number=failure_item.page_number,
                    section_type=failure_item.section_type,
                    text=_text(
                        "equipment failure", failure_item.failed_equipment_raw, failure_item.system_class_raw,
                        "downtime", failure_item.operational_downtime_minutes, "remark", failure_item.failure_remark,
                        "depth", failure_item.depth_mmd, failure_item.depth_mtvd,
                    ),
                    metadata={"table_index": failure_item.table_index, "row_index": failure_item.row_index},
                )
            )
    plot = session.scalar(select(Plot).where(Plot.source_document_id == document.id))
    if plot:
        points = list(session.scalars(select(PlotPoint).where(PlotPoint.plot_id == plot.id)))
        x_values = [point_item.x_value for point_item in points if point_item.x_value is not None]
        y_values = [point_item.y_value for point_item in points if point_item.y_value is not None]
        bands: dict[str, int] = {}
        for point_item in points:
            if point_item.band_classification:
                bands[point_item.band_classification] = bands.get(point_item.band_classification, 0) + 1
        chunks.append(
            _chunk(
                key=f"plot:{plot.id}",
                source_type="plot_fact",
                source_record_id=plot.id,
                document=document,
                report=None,
                page_number=None,
                section_type=plot.plot_type,
                text=_text(
                    plot.plot_identifier, plot.plot_type, "point count", len(points),
                    "series", sorted({point_item.series_identifier for point_item in points}),
                    "x range", [min(x_values), max(x_values)] if x_values else None,
                    "y range", [min(y_values), max(y_values)] if y_values else None,
                    "bands", bands, "unit status", plot.unit_status,
                    "warnings", plot.warnings_json,
                ),
                metadata={"unit_status": plot.unit_status, "point_count": len(points)},
            )
        )
    return [item for item in chunks if item is not None]


def replace_document_chunks(session: Session, source_document_id: int) -> int:
    document = session.get(SourceDocument, source_document_id)
    if document is None:
        return 0
    session.execute(delete(RetrievalChunk).where(RetrievalChunk.source_document_id == document.id))
    chunks = _document_chunks(session, document)
    session.add_all(chunks)
    session.flush()
    invalidate_retrieval_cache()
    return len(chunks)


def backfill_retrieval_chunks(
    session: Session,
    *,
    source_document_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    if source_document_ids is None:
        documents = list(session.scalars(select(SourceDocument).order_by(SourceDocument.id)))
    else:
        identifiers = list(source_document_ids)
        documents = list(
            session.scalars(
                select(SourceDocument).where(SourceDocument.id.in_(identifiers)).order_by(SourceDocument.id)
            )
        )
    counts: dict[str, int] = {}
    total = 0
    for document in documents:
        session.execute(delete(RetrievalChunk).where(RetrievalChunk.source_document_id == document.id))
        chunks = _document_chunks(session, document)
        session.add_all(chunks)
        for chunk in chunks:
            counts[chunk.source_type] = counts.get(chunk.source_type, 0) + 1
        total += len(chunks)
    session.flush()
    invalidate_retrieval_cache()
    return {"documents": len(documents), "chunks": total, "source_types": counts}


@dataclass(slots=True)
class _CorpusIndex:
    fingerprint: str
    chunks: list[RetrievalChunk]
    word_vectorizer: TfidfVectorizer
    word_matrix: csr_matrix
    build_seconds: float
    char_vectorizer: TfidfVectorizer | None = None
    char_matrix: csr_matrix | None = None


_INDEX_CACHE: dict[tuple[str, str], _CorpusIndex] = {}


def invalidate_retrieval_cache() -> None:
    _INDEX_CACHE.clear()


def _fingerprint(session: Session) -> str:
    count, maximum_id, maximum_updated = session.execute(
        select(
            func.count(RetrievalChunk.id),
            func.max(RetrievalChunk.id),
            func.max(RetrievalChunk.updated_at),
        )
    ).one()
    raw = f"{count}:{maximum_id}:{maximum_updated}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _index(session: Session) -> _CorpusIndex | None:
    fingerprint = _fingerprint(session)
    identity = str(session.get_bind().engine.url.render_as_string(hide_password=True))
    key = (identity, fingerprint)
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    chunks = list(session.scalars(select(RetrievalChunk).order_by(RetrievalChunk.id)))
    if not chunks:
        return None
    started = time.perf_counter()
    texts = [item.searchable_text for item in chunks]
    word = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, 2),
        min_df=1,
        max_features=25000,
        sublinear_tf=True,
    )
    word_matrix = word.fit_transform(texts)
    built = _CorpusIndex(
        fingerprint=fingerprint,
        chunks=chunks,
        word_vectorizer=word,
        word_matrix=normalize(word_matrix.tocsr()),
        build_seconds=time.perf_counter() - started,
    )
    _INDEX_CACHE.clear()
    _INDEX_CACHE[key] = built
    return built


def _date_text(chunk: RetrievalChunk) -> str | None:
    return chunk.period_end.date().isoformat() if chunk.period_end else None


class CorpusRetriever:
    def search(self, session: Session, plan: QueryPlan) -> tuple[list[RetrievalHit], RetrievalDiagnostics]:
        index = _index(session)
        if index is None:
            diagnostics = RetrievalDiagnostics("not_backfilled", _fingerprint(session), 0, 0.0, 2, 0, 0, [])
            return [], diagnostics
        query = plan.retrieval_query or plan.standalone_question
        word_query = index.word_vectorizer.transform([query])
        scores = (index.word_matrix @ normalize(word_query).T).toarray().reshape(-1)

        stage_one = self._eligible(index.chunks, plan, relaxed=False)
        ranked = self._rank(index.chunks, scores, stage_one, plan, threshold=0.035)
        stage = 1
        candidates = len(stage_one)
        if not ranked:
            stage_two = self._eligible(index.chunks, plan, relaxed=True)
            if stage_two:
                scores = self._stage_two_scores(index, query, scores)
            ranked = self._rank(index.chunks, scores, stage_two, plan, threshold=0.012)
            stage = 2
            candidates = len(stage_two)
        hits = [self._hit(index.chunks[position], score) for position, score in ranked[: plan.limit]]
        source_types = sorted({item.source_type for item in hits})
        diagnostics = RetrievalDiagnostics(
            corpus_status="ready",
            corpus_fingerprint=index.fingerprint,
            index_chunk_count=len(index.chunks),
            index_build_seconds=round(index.build_seconds, 3),
            stage=stage,
            candidate_count=candidates,
            evidence_hit_count=len(hits),
            source_types=source_types,
        )
        return hits, diagnostics

    @staticmethod
    def _stage_two_scores(index: _CorpusIndex, query: str, word_scores: np.ndarray) -> np.ndarray:
        if index.char_vectorizer is None or index.char_matrix is None:
            started = time.perf_counter()
            char = TfidfVectorizer(
                lowercase=True,
                strip_accents="unicode",
                analyzer="char_wb",
                ngram_range=(3, 4),
                min_df=3,
                max_features=12000,
                sublinear_tf=True,
            )
            index.char_matrix = normalize(char.fit_transform([item.searchable_text for item in index.chunks]))
            index.char_vectorizer = char
            index.build_seconds += time.perf_counter() - started
        char_query = normalize(index.char_vectorizer.transform([query]))
        char_scores = (index.char_matrix @ char_query.T).toarray().reshape(-1)
        return (word_scores * 0.65) + (char_scores * 0.35)

    @staticmethod
    def _eligible(chunks: list[RetrievalChunk], plan: QueryPlan, *, relaxed: bool) -> list[int]:
        positions = []
        for position, chunk in enumerate(chunks):
            if plan.wellbore and (chunk.wellbore or "").casefold() != plan.wellbore.casefold():
                continue
            chunk_date = chunk.period_end.date() if chunk.period_end else None
            if plan.date_from and (chunk_date is None or chunk_date < plan.date_from):
                continue
            if plan.date_to and (chunk_date is None or chunk_date > plan.date_to):
                continue
            if not relaxed and plan.section_types and chunk.section_type not in plan.section_types:
                continue
            positions.append(position)
        return positions

    @staticmethod
    def _rank(
        chunks: list[RetrievalChunk],
        scores: np.ndarray,
        positions: list[int],
        plan: QueryPlan,
        *,
        threshold: float,
    ) -> list[tuple[int, float]]:
        identifiers = [term.casefold() for term in plan.search_terms if "/" in term or "_" in term]
        high_signal_terms = {
            term.casefold()
            for term in plan.search_terms
            if len(term) >= 8 or any(character in term for character in ("/", "_", "-"))
        }
        activity_terms = [item.casefold() for item in plan.activity_names]
        equipment_terms = [item.casefold() for item in plan.equipment_names]
        ranked: list[tuple[int, float]] = []
        for position in positions:
            chunk = chunks[position]
            text = chunk.searchable_text.casefold()
            score = float(scores[position])
            if plan.wellbore and chunk.wellbore and plan.wellbore.casefold() == chunk.wellbore.casefold():
                score += 0.18
            if plan.section_types and chunk.section_type in plan.section_types:
                score += 0.12
            if any(value in text or value in str(chunk.metadata_json).casefold() for value in identifiers):
                score += 0.18
            score += min(
                0.3,
                0.2 * sum(value in text for value in high_signal_terms),
            )
            if any(value in text for value in activity_terms):
                score += 0.1
            if any(value in text for value in equipment_terms):
                score += 0.1
            if score >= threshold:
                ranked.append((position, score))
        ranked.sort(
            key=lambda item: (
                item[1],
                chunks[item[0]].period_end or datetime.min,
                -chunks[item[0]].id,
            ),
            reverse=True,
        )
        if plan.sort_direction == "desc":
            ranked.sort(
                key=lambda item: (
                    chunks[item[0]].period_end or datetime.min,
                    item[1],
                ),
                reverse=True,
            )
        return ranked

    @staticmethod
    def _hit(chunk: RetrievalChunk, score: float) -> RetrievalHit:
        return RetrievalHit(
            chunk_id=chunk.id,
            source_type=chunk.source_type,
            source_record_id=chunk.source_record_id,
            source_document_id=chunk.source_document_id,
            report_id=chunk.report_id,
            file_name=str(chunk.metadata_json.get("file_name") or "unknown source"),
            wellbore=chunk.wellbore,
            report_date=_date_text(chunk),
            page_number=chunk.page_number,
            section_type=chunk.section_type,
            text=chunk.searchable_text,
            score=score,
            metadata=chunk.metadata_json,
        )
