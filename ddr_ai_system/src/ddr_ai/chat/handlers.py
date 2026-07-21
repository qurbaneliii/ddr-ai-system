from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ddr_ai.analytics.summaries import build_daily_summary
from ddr_ai.analytics.trends import robust_sparse_trend
from ddr_ai.chat.contracts import ChatAnswer
from ddr_ai.chat.query import QueryPlan
from ddr_ai.db.models import (
    Anomaly,
    EquipmentFailure,
    FailureOperationMatch,
    IdentityMapping,
    Operation,
    Plot,
    PlotPoint,
    Report,
    SourceDocument,
)

IntentHandler = Callable[[Session, QueryPlan], ChatAnswer | None]


def _mapping(session: Session, plan: QueryPlan) -> ChatAnswer:
    mappings = session.scalars(
        select(IdentityMapping).where(IdentityMapping.mapping_status == "verified")
    ).all()
    if mappings:
        rows = [
            {
                "source": f"{item.source_namespace}:{item.source_identifier}",
                "target": f"{item.target_namespace}:{item.target_identifier}",
                "evidence": item.evidence,
                "confidence": item.confidence,
            }
            for item in mappings
        ]
        return ChatAnswer(
            "Only the verified mappings listed in evidence are established.",
            "hybrid_mapping",
            evidence=rows,
            rows=rows,
            confidence=0.95,
        )
    return ChatAnswer(
        "Not established from available metadata. Matching numeric indices do not prove that a pressure profile, pressure-time filename, displayed series, or DDR wellbore are the same asset.",
        "hybrid_mapping",
        limitations=[
            "All cross-namespace mappings remain unresolved until human-reviewed evidence is recorded."
        ],
        confidence=1.0,
    )


def _report_lookup(session: Session, plan: QueryPlan) -> ChatAnswer | None:
    if not plan.wellbore:
        return None
    statement = (
        select(Report, SourceDocument)
        .join(SourceDocument, SourceDocument.id == Report.source_document_id)
        .where(Report.wellbore == plan.wellbore)
        .order_by(Report.period_end.desc())
        .limit(plan.limit)
    )
    rows = []
    evidence = []
    for report, document in session.execute(statement):
        report_date = report.filename_date or (report.period_end.date() if report.period_end else None)
        rows.append(
            {
                "wellbore": report.wellbore,
                "report_date": report_date.isoformat() if report_date else None,
                "completed_activities": report.summary_activities,
                "planned_activities": report.summary_planned,
                "file_name": document.file_name,
                "page_number": 1,
            }
        )
        evidence.append(
            {
                "evidence_id": f"report:{report.id}",
                "source_type": "report_summary",
                "file_name": document.file_name,
                "wellbore": report.wellbore,
                "report_date": report_date.isoformat() if report_date else None,
                "page_number": 1,
                "section": "summary_report",
            }
        )
    if not rows:
        return ChatAnswer(
            f"The answer was not found in the processed DDR corpus: no stored report matches wellbore {plan.wellbore}.",
            "not_found_corpus",
            limitations=["The requested wellbore is not present in the processed DDR corpus."],
            confidence=1.0,
        )
    return ChatAnswer(
        f"Found {len(rows)} recent report summaries for {plan.wellbore}; completed and planned activities are listed in the deterministic rows.",
        "structured_report_lookup",
        rows=rows,
        evidence=evidence,
        confidence=1.0,
        sql=str(statement.compile(compile_kwargs={"literal_binds": True})),
    )


def _daily_summary(session: Session, plan: QueryPlan) -> ChatAnswer:
    report_id = plan.report_id
    if report_id is None:
        statement = select(Report.id)
        if plan.wellbore:
            statement = statement.where(Report.wellbore == plan.wellbore)
        report_id = session.scalar(statement.order_by(Report.period_end.desc()))
    if report_id is None:
        return ChatAnswer(
            "No reports are available to summarize.",
            "not_found_corpus",
            limitations=["No matching report exists in the processed DDR corpus."],
            confidence=1.0,
        )
    summary = build_daily_summary(session, report_id)
    return ChatAnswer(
        summary.text,
        "hybrid_summary",
        evidence=summary.citations,
        rows=[summary.facts],
        limitations=summary.limitations,
        confidence=0.95,
    )


def _main_activity(session: Session, plan: QueryPlan) -> ChatAnswer | None:
    if not plan.wellbore or not plan.date_to:
        return None
    statement = (
        select(
            Operation.main_activity_normalized,
            func.sum(Operation.duration_hours).label("duration_hours"),
            SourceDocument.file_name,
            func.min(Operation.page_number).label("first_page"),
        )
        .join(Report, Report.id == Operation.report_id)
        .join(SourceDocument, SourceDocument.id == Report.source_document_id)
        .where(Report.wellbore == plan.wellbore, func.date(Report.period_end) == plan.date_to.isoformat())
        .group_by(Operation.main_activity_normalized, SourceDocument.file_name)
        .order_by(func.sum(Operation.duration_hours).desc())
    )
    rows = [
        {
            "activity": row[0],
            "duration_hours": round(row[1] or 0.0, 3),
            "file_name": row[2],
            "page_number": row[3],
        }
        for row in session.execute(statement)
    ]
    if not rows:
        return ChatAnswer(
            f"No operation rows were found for {plan.wellbore} on {plan.date_to.isoformat()}.",
            "not_found_corpus",
            confidence=1.0,
            limitations=["The report may be absent or may not contain an Operations table."],
        )
    return ChatAnswer(
        f"The main activity was {rows[0]['activity']} with {rows[0]['duration_hours']:.3f} recorded hours.",
        "structured_sql",
        rows=rows,
        evidence=rows,
        confidence=1.0,
        sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
    )


def _activity_aggregation(session: Session, plan: QueryPlan) -> ChatAnswer:
    lower = plan.standalone_question.casefold()
    if "fail" in lower:
        fail_statement = (
            select(Report.wellbore, func.count(Operation.id).label("fail_rows"))
            .join(Operation, Operation.report_id == Report.id)
            .where(Operation.state_normalized == "fail")
            .group_by(Report.wellbore)
            .order_by(func.count(Operation.id).desc())
        )
        rows = [{"wellbore": row[0], "fail_rows": row[1]} for row in session.execute(fail_statement)]
        return ChatAnswer(
            f"Found {sum(row['fail_rows'] for row in rows)} operation rows marked fail across {len(rows)} wellbores.",
            "structured_sql",
            rows=rows,
            evidence=rows,
            limitations=["Fail states are weak anomaly evidence, not validated ground truth."],
            confidence=1.0,
            sql=str(fail_statement.compile(compile_kwargs={"literal_binds": False})),
        )
    aggregation_statement = (
        select(
            Report.wellbore,
            Operation.main_activity_normalized,
            func.count(Operation.id).label("operation_rows"),
            func.sum(Operation.duration_hours).label("duration_hours"),
        )
        .join(Operation, Operation.report_id == Report.id)
        .where(Operation.main_activity_normalized.is_not(None))
        .group_by(Report.wellbore, Operation.main_activity_normalized)
        .order_by(func.count(Operation.id).desc())
        .limit(min(plan.limit * 5, 100))
    )
    rows = [
        {
            "wellbore": row[0],
            "activity": row[1],
            "operation_rows": row[2],
            "duration_hours": round(row[3] or 0.0, 2),
        }
        for row in session.execute(aggregation_statement)
    ]
    return ChatAnswer(
        f"Ranked {len(rows)} wellbore/activity groups using stored operation rows.",
        "structured_sql",
        rows=rows,
        evidence=rows[:20],
        limitations=["Operation-row frequency is not the same as engineering significance."],
        confidence=1.0,
        sql=str(aggregation_statement.compile(compile_kwargs={"literal_binds": False})),
    )


def _anomaly_candidates(session: Session, plan: QueryPlan) -> ChatAnswer:
    lower = plan.standalone_question.casefold()
    validated_only = any(term in lower for term in ("validated", "confirmed", "reviewed"))
    statement = select(
        Anomaly.detector_type,
        Anomaly.category,
        Anomaly.validation_status,
        Anomaly.domain_validated,
        func.count(Anomaly.id).label("candidate_count"),
    )
    if validated_only:
        statement = statement.where(Anomaly.domain_validated.is_(True))
    statement = statement.group_by(
        Anomaly.detector_type,
        Anomaly.category,
        Anomaly.validation_status,
        Anomaly.domain_validated,
    ).order_by(Anomaly.detector_type, Anomaly.category, Anomaly.validation_status)
    rows = [
        {
            "detector_type": detector,
            "category": category,
            "validation_status": status,
            "domain_validated": validated,
            "candidate_count": count,
        }
        for detector, category, status, validated, count in session.execute(statement)
    ]
    if validated_only and not rows:
        return ChatAnswer(
            "No human-confirmed anomaly is stored. Automated rule and ML records remain candidates until domain review.",
            "anomaly_candidates",
            rows=[],
            evidence=[],
            limitations=["An empty validated result must not be interpreted as evidence that no anomaly exists."],
            confidence=1.0,
            sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
        )
    by_detector: dict[str, int] = {}
    for row in rows:
        detector = str(row["detector_type"])
        by_detector[detector] = by_detector.get(detector, 0) + int(row["candidate_count"])
    breakdown = ", ".join(f"{key}: {value}" for key, value in sorted(by_detector.items()))
    return ChatAnswer(
        f"Automated anomaly candidates by detector are {breakdown}. These records are candidates, not confirmed incidents.",
        "anomaly_candidates",
        rows=rows,
        evidence=rows,
        limitations=[
            "Rule, data-quality, and ML signals use different evidence and must be reviewed separately.",
            "Unreviewed candidates are not domain-validated facts or engineering recommendations.",
        ],
        confidence=1.0,
        sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
        export_filename="anomaly-candidate-breakdown.csv",
    )
def _equipment_failures(session: Session, plan: QueryPlan) -> ChatAnswer:
    statement = (
        select(EquipmentFailure, FailureOperationMatch, Operation, Report, SourceDocument)
        .join(Report, Report.id == EquipmentFailure.report_id)
        .join(SourceDocument, SourceDocument.id == EquipmentFailure.source_document_id)
        .outerjoin(FailureOperationMatch, FailureOperationMatch.equipment_failure_id == EquipmentFailure.id)
        .outerjoin(Operation, Operation.id == FailureOperationMatch.operation_id)
    )
    equipment_terms = [
        item for item in plan.equipment_names if item.casefold() not in {"equipment", "failure", "equipment failure"}
    ]
    if equipment_terms:
        predicates = []
        for term in equipment_terms:
            pattern = f"%{term}%"
            predicates.extend(
                [
                    EquipmentFailure.failed_equipment_raw.ilike(pattern),
                    EquipmentFailure.system_class_raw.ilike(pattern),
                    EquipmentFailure.failure_remark.ilike(pattern),
                ]
            )
        statement = statement.where(or_(*predicates))
    if plan.wellbore:
        statement = statement.where(Report.wellbore == plan.wellbore)
    statement = statement.order_by(Report.period_end.desc(), SourceDocument.file_name, EquipmentFailure.id).limit(500)
    rows = []
    evidence = []
    for failure, match, operation, report, document in session.execute(statement):
        report_date = report.filename_date or (report.period_end.date() if report.period_end else None)
        match_status = match.match_status if match else "unmatched"
        rows.append(
            {
                "wellbore": report.wellbore,
                "report_date": report_date.isoformat() if report_date else None,
                "failure_start_time": failure.start_time_raw,
                "failure_end_time": failure.end_time_raw,
                "failed_equipment": failure.failed_equipment_raw,
                "equipment_system_class": failure.system_class_raw,
                "downtime_minutes": failure.operational_downtime_minutes,
                "failure_remark": failure.failure_remark,
                "concurrent_main_activity": operation.main_activity_normalized if operation else None,
                "concurrent_sub_activity": operation.sub_activity_normalized if operation else None,
                "operation_start_time": operation.start_time_raw if operation else None,
                "operation_end_time": operation.end_time_raw if operation else None,
                "match_status": match_status,
                "match_confidence": match.match_confidence if match else None,
                "source_file": document.file_name,
                "failure_page": failure.page_number,
                "operation_page": operation.page_number if operation else None,
            }
        )
        evidence.append(
            {
                "evidence_id": f"equipment_failure:{failure.id}",
                "source_type": "equipment_failure",
                "file_name": document.file_name,
                "wellbore": report.wellbore,
                "report_date": report_date.isoformat() if report_date else None,
                "page_number": failure.page_number,
                "section": failure.section_type,
                "operation_page": operation.page_number if operation else None,
                "match_status": match_status,
                "failure": {
                    "id": failure.id,
                    "file_name": document.file_name,
                    "page_number": failure.page_number,
                    "section": failure.section_type,
                },
                "operation": (
                    {
                        "id": operation.id,
                        "file_name": document.file_name,
                        "page_number": operation.page_number,
                        "section": "operations",
                    }
                    if operation
                    else None
                ),
            }
        )
    if not rows:
        return ChatAnswer(
            "No matching equipment-failure record was found in the processed DDR corpus.",
            "not_found_corpus",
            limitations=["No equipment-failure evidence matched the requested filters."],
            confidence=1.0,
        )
    exact = sum(row["match_status"] in {"exact", "overlap"} for row in rows)
    return ChatAnswer(
        f"Found {len(rows)} populated equipment-failure records; {exact} have a supported concurrent-operation match.",
        "structured_failure_activity",
        rows=rows,
        evidence=evidence,
        confidence=0.97,
        sql=str(statement.compile(compile_kwargs={"literal_binds": True})),
        limitations=[
            "Activities are reported only for supported same-report temporal matches.",
            "Missing or ambiguous activity is not inferred.",
        ],
        export_filename="equipment_failures_with_operational_activities.csv",
    )


def _plot_facts(session: Session, plan: QueryPlan) -> ChatAnswer | None:
    lower = plan.standalone_question.casefold()
    if "below" in lower and "min" in lower:
        point_statement = (
            select(
                Plot.plot_identifier,
                PlotPoint.point_index,
                PlotPoint.x_value,
                PlotPoint.y_value,
                PlotPoint.confidence,
                SourceDocument.file_name,
                Plot.x_unit,
                Plot.y_unit,
            )
            .join(PlotPoint, PlotPoint.plot_id == Plot.id)
            .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
            .where(Plot.plot_type == "pressure_profile", PlotPoint.band_classification == "below_min")
            .order_by(Plot.plot_identifier, PlotPoint.point_index)
        )
        rows = [
            {
                "profile": row[0], "point_index": row[1], "pressure": row[2], "depth": row[3],
                "confidence": row[4], "file_name": row[5], "pressure_unit": row[6], "depth_unit": row[7],
            }
            for row in session.execute(point_statement)
        ]
        return ChatAnswer(
            f"Found {len(rows)} measured profile points classified below the MIN curve.",
            "plot_sql",
            rows=rows,
            evidence=rows,
            confidence=0.95,
            limitations=["These are visual candidates, not confirmed operational anomalies; SoR is undefined."],
            sql=str(point_statement.compile(compile_kwargs={"literal_binds": False})),
        )
    identifier = next(iter(re.findall(r"pressure_time_plot_\d{2}", lower)), None)
    if identifier and any(term in lower for term in ("unit", "vahid", "limitation", "məhdud")):
        plot_statement = (
            select(Plot, SourceDocument)
            .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
            .where(Plot.plot_identifier == identifier)
        )
        row = session.execute(plot_statement).first()
        if not row:
            return ChatAnswer("The requested plot is unavailable in the processed corpus.", "not_found_corpus", confidence=1.0)
        plot, document = row
        facts = {
            "plot_identifier": plot.plot_identifier,
            "plot_type": plot.plot_type,
            "x_unit": plot.x_unit,
            "y_unit": plot.y_unit,
            "unit_status": plot.unit_status,
            "confidence": plot.confidence,
            "source_file": document.file_name,
        }
        return ChatAnswer(
            f"{plot.plot_identifier} has unit status '{plot.unit_status}'. The stored pressure unit is {plot.y_unit or 'unknown'}.",
            "plot_limitations",
            rows=[facts],
            evidence=[{"file_name": document.file_name, "plot_identifier": plot.plot_identifier}],
            limitations=["Unknown units are preserved and are not inferred from visual scale alone."],
            confidence=1.0,
            sql=str(plot_statement.compile(compile_kwargs={"literal_binds": False})),
        )
    return None


def _plot_trend(session: Session, plan: QueryPlan) -> ChatAnswer | None:
    lower = plan.standalone_question.casefold()
    series_match = re.search(r"well_\d{2}", lower)
    if not series_match:
        return None
    series_digits = re.search(r"\d{2}", series_match.group(0))
    if series_digits is None:
        return None
    series = f"Well_{series_digits.group(0)}"
    plot_match = re.search(r"pressure_time_plot_\d{2}", lower)
    statement = (
        select(PlotPoint, Plot, SourceDocument)
        .join(Plot, Plot.id == PlotPoint.plot_id)
        .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
        .where(
            Plot.plot_type == "pressure_time",
            PlotPoint.series_identifier == series,
            PlotPoint.observed_date.is_not(None),
            PlotPoint.y_value.is_not(None),
        )
    )
    if plot_match:
        statement = statement.where(Plot.plot_identifier == plot_match.group(0))
    points = list(session.execute(statement.order_by(PlotPoint.observed_date)))
    x = [float(point.observed_date.toordinal()) for point, _, _ in points]
    y = [float(point.y_value) for point, _, _ in points]
    trend = robust_sparse_trend(x, y)
    plots = sorted({plot.plot_identifier for _, plot, _ in points})
    files = sorted({document.file_name for _, _, document in points})
    dates = [point.observed_date for point, _, _ in points if point.observed_date]
    values = [float(point.y_value) for point, _, _ in points if point.y_value is not None]
    facts = {
        **trend,
        "plot_identifiers": plots,
        "series_identifier": series,
        "point_count": len(points),
        "date_start": min(dates).isoformat() if dates else None,
        "date_end": max(dates).isoformat() if dates else None,
        "measured_min": min(values) if values else None,
        "measured_max": max(values) if values else None,
        "unit_status": sorted({plot.unit_status for _, plot, _ in points}),
    }
    return ChatAnswer(
        f"Trend for {series} uses {len(points)} stored points. "
        + (
            f"Theil-Sen slope {trend['slope']:.4f} unknown pressure-units/day; Spearman rho {trend['spearman_rho']:.3f}."
            if trend.get("applicable")
            else str(trend.get("reason"))
        ),
        "plot_analytics",
        rows=[facts],
        evidence=[{"file_name": name, "plot_identifiers": plots} for name in files],
        limitations=[
            "Pressure unit is unknown and must not be relabeled.",
            "Displayed series identity is not an authoritative DDR-wellbore mapping.",
            "Trend statistics are descriptive candidate-level evidence.",
        ],
        confidence=0.9 if trend.get("applicable") else 0.6,
    )


HANDLER_REGISTRY: dict[str, IntentHandler] = {
    "identity_mapping": _mapping,
    "daily_summary": _daily_summary,
    "report_lookup": _report_lookup,
    "count_aggregation": _activity_aggregation,
    "compare_wellbores": _activity_aggregation,
    "activity_analysis": _main_activity,
    "anomaly_candidates": _anomaly_candidates,
    "equipment_failures": _equipment_failures,
    "plot_facts": _plot_facts,
    "plot_trends": _plot_trend,
}
