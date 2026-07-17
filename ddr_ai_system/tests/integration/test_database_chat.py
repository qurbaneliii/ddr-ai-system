from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ddr_ai.analytics.summaries import build_daily_summary
from ddr_ai.chat.service import answer_question
from ddr_ai.chat.sql_safety import validate_select_sql
from ddr_ai.db.models import (
    Base,
    EquipmentFailure,
    FailureOperationMatch,
    IdentityMapping,
    Operation,
    Report,
    ReportSection,
    SectionTableRow,
    SourceDocument,
)
from ddr_ai.nlp.providers import provider_status
from ddr_ai.services.failure_correlations import backfill_failure_correlations


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


def seed_failure(session: Session, document: SourceDocument, report: Report) -> None:
    section = ReportSection(report_id=report.id, section_type="equipment_failure_information",
        heading_raw="Equipment Failure Information", page_number=1, text="failure row")
    session.add(section)
    session.flush()
    operation = session.scalar(select(Operation).where(Operation.report_id == report.id))
    failure = EquipmentFailure(report_id=report.id, source_document_id=document.id,
        report_section_id=section.id, page_number=1, table_index=5, row_index=1,
        start_time_raw="23:00", start_datetime=datetime(2008, 6, 13, 23),
        failed_equipment_raw="top drive", failed_equipment_normalized="top drive",
        system_class_raw="hoisting equipment", system_class_normalized="hoisting equipment",
        operational_downtime_raw="15", operational_downtime_minutes=15,
        failure_remark="Top drive stopped", temporal_status="valid",
        raw_values_json={}, normalized_values_json={}, confidence=0.97)
    session.add(failure)
    session.flush()
    session.add(FailureOperationMatch(equipment_failure_id=failure.id, operation_id=operation.id,
        match_status="exact", match_confidence=0.98,
        matching_rule="failure_start_inside_operation_interval",
        evidence_json={"failure": {"id": failure.id}, "operation": {"id": operation.id}}))
    session.commit()


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


def test_failure_activity_answer_has_dual_citations_and_complete_csv_columns() -> None:
    db = session()
    document, report = seed(db)
    seed_failure(db, document, report)
    answer = answer_question(
        db,
        "Which wellbores had equipment failures and what operational activities were being performed?",
    )
    assert answer.route == "structured_failure_activity"
    assert answer.rows[0]["failed_equipment"] == "top drive"
    assert answer.rows[0]["concurrent_main_activity"] == "drilling"
    assert answer.evidence[0]["failure"]["page_number"] == 1
    assert answer.evidence[0]["operation"]["page_number"] == 1
    assert list(answer.rows[0]) == [
        "wellbore", "report_date", "failure_start_time", "failure_end_time",
        "failed_equipment", "equipment_system_class", "downtime_minutes",
        "failure_remark", "concurrent_main_activity", "concurrent_sub_activity",
        "operation_start_time", "operation_end_time", "match_status",
        "match_confidence", "source_file", "failure_page", "operation_page",
    ]
    assert answer.export_filename == "equipment_failures_with_operational_activities.csv"
    validated = validate_select_sql(answer.sql or "", allowed_tables={
        "equipment_failures", "failure_operation_matches", "operations", "reports",
        "source_documents",
    })
    assert validated.tables == (
        "equipment_failures", "failure_operation_matches", "operations", "reports",
        "source_documents",
    )


def test_failure_answer_refuses_to_invent_activity_for_unmatched_record() -> None:
    db = session()
    document, report = seed(db)
    section = ReportSection(report_id=report.id, section_type="equipment_failure_information",
        heading_raw="Equipment Failure Information", page_number=1, text="failure row")
    db.add(section)
    db.flush()
    failure = EquipmentFailure(report_id=report.id, source_document_id=document.id,
        report_section_id=section.id, page_number=1, table_index=5, row_index=1,
        start_time_raw="05:00", start_datetime=datetime(2008, 6, 13, 5),
        failed_equipment_raw="pump", failure_remark="No supported operation",
        temporal_status="valid", raw_values_json={}, normalized_values_json={}, confidence=0.97)
    db.add(failure)
    db.flush()
    db.add(FailureOperationMatch(equipment_failure_id=failure.id, operation_id=None,
        match_status="unmatched", match_confidence=0.95,
        matching_rule="no_supported_temporal_match", evidence_json={"failure": {"id": failure.id}}))
    db.commit()
    answer = answer_question(db, "Show equipment failures and activities")
    assert answer.rows[0]["match_status"] == "unmatched"
    assert answer.rows[0]["concurrent_main_activity"] is None
    assert answer.rows[0]["operation_page"] is None
    assert answer.evidence[0]["operation"] is None


def test_reprocessing_failure_rows_is_idempotent_and_prevents_duplicates() -> None:
    db = session()
    document, report = seed(db)
    db.add(ReportSection(report_id=report.id, section_type="equipment_failure_information",
        heading_raw="Equipment Failure Information", page_number=1, text="failure row"))
    db.add(SectionTableRow(source_document_id=document.id, report_id=report.id,
        page_number=1, section_type="equipment_failure_information", table_index=5, row_index=1,
        header_cells_json=["Start time", "Depth mMD", "Depth mTVD",
            "Sub Equip - Syst Class", "Operation Downtime (min)", "Equipment Repaired", "Remark"],
        raw_cells_json=["23:00", "100", "", "hoisting equ -- top drive", "15", "23:15", "Stopped"],
        normalized_cells_json=[], table_bbox_json={"x0": 1, "top": 2, "x1": 3, "bottom": 4},
        confidence=0.92))
    db.commit()
    first = backfill_failure_correlations(db)
    db.commit()
    second = backfill_failure_correlations(db)
    db.commit()
    assert first.populated_failure_records == second.populated_failure_records == 1
    assert db.scalar(select(func.count(EquipmentFailure.id))) == 1
    assert db.scalar(select(func.count(FailureOperationMatch.id))) == 1
