from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.db.models import Operation, Report, ReportSection, SourceDocument


@dataclass(slots=True)
class GroundedSummary:
    text: str
    facts: dict[str, Any]
    citations: list[dict[str, Any]]
    limitations: list[str]


def _meaningful_summary(value: str | None) -> str | None:
    if value is None or value.strip().casefold() in {"", "none", "n/a", "not available"}:
        return None
    return value.strip()


def build_daily_summary(session: Session, report_id: int) -> GroundedSummary:
    row = session.execute(
        select(Report, SourceDocument).join(SourceDocument, SourceDocument.id == Report.source_document_id)
        .where(Report.id == report_id)
    ).first()
    if not row:
        raise LookupError(f"Report {report_id} was not found")
    report, document = row
    operations = session.scalars(select(Operation).where(Operation.report_id == report.id)
                                 .order_by(Operation.row_index)).all()
    failures = session.scalars(select(ReportSection).where(
        ReportSection.report_id == report.id,
        ReportSection.section_type == "equipment_failure_information",
    )).all()
    durations: dict[str, float] = {}
    for operation in operations:
        category = operation.main_activity_normalized or "unknown"
        durations[category] = durations.get(category, 0.0) + (operation.duration_hours or 0.0)
    depths = [item.end_depth_mmd for item in operations if item.end_depth_mmd is not None]
    fail_rows = [item for item in operations if item.state_normalized == "fail"]
    summary_activities = _meaningful_summary(report.summary_activities)
    summary_planned = _meaningful_summary(report.summary_planned)
    facts = {
        "wellbore": report.wellbore,
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "operation_count": len(operations),
        "activity_duration_hours": {key: round(value, 2) for key, value in sorted(durations.items())},
        "depth_start_mmd": depths[0] if depths else None,
        "depth_end_mmd": depths[-1] if depths else None,
        "depth_change_m": round(depths[-1] - depths[0], 3) if len(depths) >= 2 else None,
        "fail_operation_count": len(fail_rows),
        "equipment_failure_section_count": len(failures),
        "summary_activities": summary_activities,
        "summary_planned": summary_planned,
        "excluded_from_default_trends": report.excluded_from_default_trends,
    }
    lead = f"{report.wellbore or 'Unknown wellbore'} for {facts['period_end'] or 'unknown period'}"
    clauses = [f"contains {len(operations)} extracted operation rows"]
    if durations:
        primary = max(durations, key=lambda key: durations[key])
        clauses.append(f"with {primary} as the largest recorded activity duration ({durations[primary]:.2f} h)")
    if facts["depth_change_m"] is not None:
        clauses.append(f"and a row-end depth change of {facts['depth_change_m']:.3f} m")
    clauses.append(f"{len(fail_rows)} operation rows are marked fail")
    text = lead + " " + "; ".join(clauses) + "."
    if summary_activities:
        text += f" Source activity summary: {summary_activities}"
    if summary_planned:
        text += f" Planned: {summary_planned}"
    citations = [{"file_name": document.file_name, "page_number": 1,
                  "section": "summary_report", "report_id": report.id}]
    citations.extend({"file_name": document.file_name, "page_number": item.page_number,
                      "section": "operations", "operation_row": item.row_index} for item in operations[:5])
    limitations = ["Automated summary; extracted source facts should be reviewed for engineering use."]
    if report.excluded_from_default_trends:
        limitations.append("This report is excluded from default trends due to a data-quality candidate.")
    return GroundedSummary(text=text, facts=facts, citations=citations, limitations=limitations)
