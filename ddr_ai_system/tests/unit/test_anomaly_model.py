from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ddr_ai.analytics.anomaly_model import generate_duration_anomalies
from ddr_ai.db.models import Anomaly, Base, Operation, Report, SourceDocument


def _session_with_duration_outlier() -> tuple[Session, int]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    document = SourceDocument(
        sha256="f" * 64,
        file_name="duration.pdf",
        source_path="duration.pdf",
        media_type="application/pdf",
        asset_kind="digital_pdf",
        byte_size=1,
        parser_version="test",
        processing_status="complete",
    )
    session.add(document)
    session.flush()
    report = Report(
        source_document_id=document.id,
        wellbore="15/9-F-99",
        period_end=datetime(2026, 1, 1),
        data_quality_status="test",
    )
    session.add(report)
    session.flush()
    outlier_id = 0
    for index in range(100):
        operation = Operation(
            report_id=report.id,
            row_index=index,
            page_number=1,
            duration_hours=24.0 if index == 99 else 1.0 + (index % 3) * 0.05,
            main_activity_normalized="drilling",
            sub_activity_normalized="drill",
            remark=f"operation {index}",
            classification_method="source_rule",
            classification_confidence=1.0,
        )
        session.add(operation)
        session.flush()
        if index == 99:
            outlier_id = operation.id
    session.commit()
    return session, outlier_id


def test_isolation_forest_persists_clear_within_group_outlier_idempotently() -> None:
    session, outlier_id = _session_with_duration_outlier()
    first = generate_duration_anomalies(session)
    session.commit()
    first_count = session.scalar(
        select(func.count(Anomaly.id)).where(Anomaly.detector_type == "ml")
    )
    second = generate_duration_anomalies(session)
    session.commit()
    second_count = session.scalar(
        select(func.count(Anomaly.id)).where(Anomaly.detector_type == "ml")
    )

    candidates = list(
        session.scalars(select(Anomaly).where(Anomaly.detector_type == "ml"))
    )
    assert any(item.source_record_id == outlier_id for item in candidates)
    assert first_count == second_count == first["actual_metrics"]["candidate_count"]
    assert first["candidate_keys"] == second["candidate_keys"]
    assert all(item.domain_validated is False for item in candidates)


def test_dry_run_does_not_persist_candidates() -> None:
    session, _ = _session_with_duration_outlier()
    result = generate_duration_anomalies(session, dry_run=True)
    assert result["actual_metrics"]["candidate_count"] >= 1
    assert session.scalar(select(func.count(Anomaly.id))) == 0
