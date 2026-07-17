from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.db.models import Anomaly, Operation, Report, ReportSection


def _existing_keys(session: Session) -> set[tuple[str, str, int | None]]:
    return {
        (item.source_record_type, item.rule_or_model, item.source_record_id)
        for item in session.scalars(select(Anomaly)).all()
    }


def materialize_operational_candidates(session: Session) -> dict[str, int]:
    existing = _existing_keys(session)
    created: Counter[str] = Counter()
    operations = session.execute(select(Operation, Report).join(Report, Report.id == Operation.report_id)).all()
    for operation, report in operations:
        candidates: list[tuple[str, str, dict[str, Any], str]] = []
        if operation.state_normalized == "fail":
            candidates.append((
                "operation_state_fail",
                "medium",
                {"state": operation.state_raw, "wellbore": report.wellbore,
                 "period_end": report.period_end.isoformat() if report.period_end else None,
                 "operation_row": operation.row_index, "remark": operation.remark},
                "The source Operations State is fail; this is weak evidence, not ground truth.",
            ))
        subactivity = operation.sub_activity_normalized or ""
        remark = (operation.remark or "").casefold()
        signal_terms = {
            "lost_circulation": ("lost circulation", "high"),
            "well_control": ("well control", "high"),
            "repair": ("repair", "medium"),
        }
        for rule, (term, severity) in signal_terms.items():
            if rule == subactivity or term in remark:
                candidates.append((
                    f"operation_{rule}", severity,
                    {"subactivity": operation.sub_activity_raw, "wellbore": report.wellbore,
                     "period_end": report.period_end.isoformat() if report.period_end else None,
                     "operation_row": operation.row_index, "remark": operation.remark},
                    f"Operation text contains the configured weak-signal term {term!r}.",
                ))
        if operation.duration_hours is not None and operation.duration_hours < 0:
            candidates.append((
                "negative_operation_duration", "high",
                {"start": operation.start_time_raw, "end": operation.end_time_raw,
                 "duration_hours": operation.duration_hours},
                "Calculated operation duration is negative.",
            ))
        for rule, severity, evidence, explanation in candidates:
            key = ("operation", rule, operation.id)
            if key in existing:
                continue
            session.add(Anomaly(
                source_document_id=report.source_document_id, source_record_type="operation",
                source_record_id=operation.id, category="operational_weak_signal",
                rule_or_model=rule, evidence_json=evidence, score=1.0,
                severity_heuristic=severity, confidence=0.9, threshold_json={"term_rule": rule},
                validation_status="unreviewed", domain_validated=False, explanation=explanation,
            ))
            existing.add(key)
            created[rule] += 1

    failure_sections = session.execute(
        select(ReportSection, Report).join(Report, Report.id == ReportSection.report_id).where(
            ReportSection.section_type == "equipment_failure_information"
        )
    ).all()
    for section, report in failure_sections:
        key = ("report_section", "equipment_failure_section_present", section.id)
        if key in existing:
            continue
        session.add(Anomaly(
            source_document_id=report.source_document_id, source_record_type="report_section",
            source_record_id=section.id, category="operational_weak_signal",
            rule_or_model="equipment_failure_section_present",
            evidence_json={"wellbore": report.wellbore,
                           "period_end": report.period_end.isoformat() if report.period_end else None,
                           "page_number": section.page_number, "section_excerpt": section.text[:1000]},
            score=1.0, severity_heuristic="medium", confidence=1.0,
            threshold_json={"section_type": "equipment_failure_information"},
            validation_status="unreviewed", domain_validated=False,
            explanation="The source report contains Equipment Failure Information; candidate only.",
        ))
        existing.add(key)
        created["equipment_failure_section_present"] += 1
    return dict(sorted(created.items()))

