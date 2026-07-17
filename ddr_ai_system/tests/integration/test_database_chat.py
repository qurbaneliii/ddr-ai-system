from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ddr_ai.analytics.summaries import build_daily_summary
from ddr_ai.chat.service import answer_question
from ddr_ai.db.models import Base, IdentityMapping, Operation, Report, SourceDocument
from ddr_ai.nlp.providers import provider_status


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(session: Session) -> tuple[SourceDocument, Report]:
    document = SourceDocument(sha256="a" * 64, file_name="report.pdf", source_path="report.pdf",
        media_type="application/pdf", asset_kind="digital_pdf", byte_size=10,
        parser_version="test", processing_status="complete")
    session.add(document)
    session.flush()
    report = Report(source_document_id=document.id, wellbore="15/9-F-14",
        period_start=datetime(2008, 6, 13), period_end=datetime(2008, 6, 14),
        summary_activities="Drilled ahead.", summary_planned="Circulate clean.",
        filename_identity_match=True, filename_date_match=True, data_quality_status="passed_automated_checks")
    session.add(report)
    session.flush()
    session.add(Operation(report_id=report.id, row_index=0, page_number=1, start_time_raw="23:00",
        end_time_raw="00:00", duration_hours=1.0, main_activity_normalized="drilling",
        state_normalized="fail", remark="Test evidence", confidence=1.0))
    session.commit()
    return document, report


def test_database_constraints_and_summary_citations() -> None:
    db = session()
    _, report = seed(db)
    summary = build_daily_summary(db, report.id)
    assert "1 operation rows" in summary.text
    assert summary.citations[0]["file_name"] == "report.pdf"
    assert summary.citations[0]["page_number"] == 1


def test_chat_fail_query_and_unresolved_mapping_contract() -> None:
    db = session()
    seed(db)
    fail = answer_question(db, "How many operation rows were marked fail by wellbore?")
    assert fail.route == "structured_sql"
    assert fail.rows == [{"wellbore": "15/9-F-14", "fail_rows": 1}]
    mapping = answer_question(db, "Are pressure profile Well_15 and pressure_time_plot_15 related?")
    assert mapping.answer.startswith("Not established from available metadata")
    assert mapping.confidence == 1.0


def test_chat_main_activity_route_is_grounded() -> None:
    db = session()
    seed(db)
    answer = answer_question(
        db, "What was the main activity for wellbore 15/9-F-14 on 2008-06-14?"
    )
    assert answer.route == "structured_sql"
    assert answer.rows[0]["activity"] == "drilling"
    assert answer.rows[0]["duration_hours"] == 1.0
    assert answer.evidence[0]["file_name"] == "report.pdf"


def test_no_api_key_fallback_is_available(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = provider_status()
    assert status["active"] == "deterministic_no_key"
    assert status["external_calls_enabled"] is False


def test_verified_mapping_is_not_inferred_from_index() -> None:
    db = session()
    seed(db)
    db.add(IdentityMapping(source_namespace="pressure_profile", source_identifier="Well_15",
        target_namespace="pressure_time_plot", target_identifier="pressure_time_plot_03",
        mapping_status="verified", mapping_source="human_review", evidence="Reviewed manifest row 9",
        confidence=1.0, validation_status="validated"))
    db.commit()
    answer = answer_question(db, "Show mapping evidence")
    assert answer.rows[0]["target"].endswith("pressure_time_plot_03")
