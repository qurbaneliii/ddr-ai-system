from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ddr_ai.chat.query import QueryAnalyzer
from ddr_ai.db.models import (
    Anomaly,
    AnomalyReview,
    Report,
    ReportSection,
    RetrievalChunk,
    SourceDocument,
)
from ddr_ai.db.seeding import seed_database
from ddr_ai.db.session import dispose_engine, session_scope
from ddr_ai.nlp.providers import LexicalFallbackProvider
from ddr_ai.retrieval.corpus import CorpusRetriever, replace_document_chunks
from ddr_ai.services.anomaly_reviews import add_anomaly_review

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_DATABASE = PROJECT_ROOT / "data" / "processed" / "ddr_ai.db"


def _postgres_url() -> str:
    value = os.getenv("DDR_TEST_POSTGRES_URL", "").strip()
    if not value:
        pytest.skip("Dedicated PostgreSQL integration database is not configured")
    return value


def test_full_seed_idempotency_refusal_sequence_and_reconnect_persistence() -> None:
    target_url = _postgres_url()
    source_url = f"sqlite:///{COMMITTED_DATABASE.as_posix()}"
    version = "committed-ddr-v0006"

    first = seed_database(source_url, target_url, seed_version=version)
    second = seed_database(source_url, target_url, seed_version=version)
    assert first["status"] == "applied"
    assert first["source_documents"] == 1060
    assert first["retrieval_chunks"] == 18895
    assert second == {"seed_version": version, "status": "already_applied"}
    with pytest.raises(RuntimeError, match="target already contains documents"):
        seed_database(source_url, target_url, seed_version=f"{version}-different")

    with session_scope(target_url) as session:
        original_documents = session.scalar(select(func.count(SourceDocument.id)))
        original_chunks = session.scalar(select(func.count(RetrievalChunk.id)))
        document = SourceDocument(
            sha256="e" * 64,
            file_name="restart-persistence-fixture.pdf",
            source_path="temporary/restart-persistence-fixture.pdf",
            media_type="application/pdf",
            asset_kind="digital_pdf",
            byte_size=50,
            parser_version="integration-test",
            processing_status="complete",
        )
        session.add(document)
        session.flush()
        assert document.id > original_documents
        report = Report(
            source_document_id=document.id,
            wellbore="88/8-F-88",
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 2),
            summary_activities="Performed persistence verification circulation.",
            summary_planned="Verify PostgreSQL reconnect search.",
            data_quality_status="test_fixture",
        )
        session.add(report)
        session.flush()
        session.add(
            ReportSection(
                report_id=report.id,
                section_type="operations",
                heading_raw="Operations",
                page_number=2,
                text="Unique reconnect marker ddrpersistmarker was recorded after upload.",
            )
        )
        session.flush()
        inserted_chunks = replace_document_chunks(session, document.id)
        inserted_document_id = document.id
        assert inserted_chunks >= 2
        candidate = session.scalar(
            select(Anomaly).where(Anomaly.detector_type == "ml").order_by(Anomaly.id)
        )
        assert candidate is not None
        review = add_anomaly_review(
            session,
            candidate.id,
            decision="needs_more_evidence",
            reviewer="postgres-integration-reviewer",
            note="Reconnect persistence proof.",
        )
        inserted_review_id = review.id

    dispose_engine(target_url)

    with session_scope(target_url) as session:
        persisted = session.get(SourceDocument, inserted_document_id)
        assert persisted is not None
        assert persisted.file_name == "restart-persistence-fixture.pdf"
        persisted_review = session.get(AnomalyReview, inserted_review_id)
        assert persisted_review is not None
        assert persisted_review.reviewer == "postgres-integration-reviewer"
        assert session.scalar(select(func.count(RetrievalChunk.id))) == original_chunks + inserted_chunks
        plan = QueryAnalyzer().analyze(
            "Which report contains ddrpersistmarker?",
            "English",
            LexicalFallbackProvider("integration test"),
            history=[],
        )
        hits, diagnostics = CorpusRetriever().search(session, plan)
        assert diagnostics.evidence_hit_count > 0
        assert hits[0].file_name == "restart-persistence-fixture.pdf"
