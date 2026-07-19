from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ddr_ai.analytics.summaries import build_daily_summary
from ddr_ai.analytics.trends import robust_sparse_trend
from ddr_ai.chat.grounding import (
    analyze_question,
    grounded_verbalize,
    localize_deterministic_answer,
)
from ddr_ai.db.models import (
    EquipmentFailure,
    FailureOperationMatch,
    IdentityMapping,
    Operation,
    Plot,
    PlotPoint,
    QueryAudit,
    Report,
    ReportSection,
    SourceDocument,
)
from ddr_ai.nlp.providers import BaseLLMProvider, LexicalFallbackProvider
from ddr_ai.retrieval.lexical import lexical_search


@dataclass(slots=True)
class ChatAnswer:
    answer: str
    route: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    data_scope: str = "local database"
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    sql: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    export_filename: str | None = None
    provider: str = "Lexical fallback"
    model: str | None = None
    detected_language: str = "en"
    selected_language: str = "en"
    retrieval_query: str | None = None
    fallback_reason: str | None = None
    model_metrics: dict[str, Any] = field(default_factory=dict)
    answer_type: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _audit(session: Session, question: str, answer: ChatAnswer, started: float) -> None:
    session.add(
        QueryAudit(
            route=answer.route,
            question_hash=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            generated_sql=answer.sql,
            status="complete",
            row_count=len(answer.rows),
            duration_seconds=round(time.perf_counter() - started, 4),
        )
    )


def _mapping_answer(session: Session, question: str) -> ChatAnswer | None:
    lower = question.casefold()
    if not any(
        token in lower
        for token in ("related", "mapping", "correspond", "same", "belong", "eyni", "uyğun")
    ):
        return None
    identifiers = re.findall(r"(?:well|plot)[_\s-]?(\d{1,2})", lower)
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
        assumptions=[
            f"Identifiers mentioned: {identifiers}"
            if identifiers
            else "No authoritative manifest supplied."
        ],
        limitations=[
            "All cross-namespace mappings remain unresolved until human-reviewed evidence is recorded."
        ],
        confidence=1.0,
    )


def _answer_deterministic(
    session: Session,
    question: str,
    *,
    retrieval_query: str | None = None,
) -> ChatAnswer:
    started = time.perf_counter()
    normalized = " ".join(question.strip().split())
    lower = normalized.casefold()
    answer = _mapping_answer(session, normalized)
    if answer:
        _audit(session, question, answer, started)
        return answer

    statement: Any
    well_match = re.search(r"\b\d{2}/\d-(?:f-)?\d{2}(?:\s+(?:a|b|bt2|st2|s|t2))?\b", lower)
    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", lower)
    if "main activity" in lower and well_match and date_match:
        wellbore = well_match.group(0).upper()
        requested_date = date.fromisoformat(date_match.group(0))
        statement = (
            select(
                Operation.main_activity_normalized,
                func.sum(Operation.duration_hours).label("duration_hours"),
                SourceDocument.file_name,
                func.min(Operation.page_number).label("first_page"),
            )
            .join(Report, Report.id == Operation.report_id)
            .join(SourceDocument, SourceDocument.id == Report.source_document_id)
            .where(
                Report.wellbore == wellbore,
                func.date(Report.period_end) == requested_date.isoformat(),
            )
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
        if rows:
            answer = ChatAnswer(
                f"The main activity was {rows[0]['activity']} with {rows[0]['duration_hours']:.3f} recorded hours.",
                "structured_sql",
                rows=rows,
                evidence=rows,
                confidence=1.0,
                sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
            )
        else:
            answer = ChatAnswer(
                f"No operation rows were found for {wellbore} on {requested_date.isoformat()}.",
                "structured_sql",
                confidence=1.0,
                sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
                limitations=[
                    "The date may fall outside a supplied campaign or the report may lack Operations."
                ],
            )
    elif "fail" in lower and ("how many" in lower or "count" in lower or "by wellbore" in lower):
        statement = (
            select(Report.wellbore, func.count(Operation.id).label("fail_rows"))
            .join(Operation, Operation.report_id == Report.id)
            .where(Operation.state_normalized == "fail")
            .group_by(Report.wellbore)
            .order_by(func.count(Operation.id).desc())
        )
        rows = [{"wellbore": item[0], "fail_rows": item[1]} for item in session.execute(statement)]
        answer = ChatAnswer(
            f"Found {sum(row['fail_rows'] for row in rows)} operation rows marked fail across {len(rows)} wellbores.",
            "structured_sql",
            sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
            rows=rows,
            evidence=rows,
            limitations=["Fail states are weak anomaly evidence, not validated ground truth."],
            confidence=1.0,
        )
    elif "equipment failure" in lower or ("nasaz" in lower and "avadan" in lower):
        statement = (
            select(
                EquipmentFailure,
                FailureOperationMatch,
                Operation,
                Report,
                SourceDocument,
            )
            .join(Report, Report.id == EquipmentFailure.report_id)
            .join(SourceDocument, SourceDocument.id == EquipmentFailure.source_document_id)
            .join(
                FailureOperationMatch,
                FailureOperationMatch.equipment_failure_id == EquipmentFailure.id,
            )
            .outerjoin(Operation, Operation.id == FailureOperationMatch.operation_id)
            .order_by(
                Report.period_end,
                SourceDocument.file_name,
                EquipmentFailure.page_number,
                EquipmentFailure.table_index,
                EquipmentFailure.row_index,
                Operation.row_index,
            )
        )
        rows = []
        evidence = []
        for failure, match, operation, report, document in session.execute(statement):
            report_date = report.filename_date or (
                report.period_end.date() if report.period_end else None
            )
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
                    "concurrent_main_activity": operation.main_activity_normalized
                    if operation
                    else None,
                    "concurrent_sub_activity": operation.sub_activity_normalized
                    if operation
                    else None,
                    "operation_start_time": operation.start_time_raw if operation else None,
                    "operation_end_time": operation.end_time_raw if operation else None,
                    "match_status": match.match_status,
                    "match_confidence": match.match_confidence,
                    "source_file": document.file_name,
                    "failure_page": failure.page_number,
                    "operation_page": operation.page_number if operation else None,
                }
            )
            evidence.append(
                {
                    "failure": {
                        "evidence_id": f"equipment_failure:{failure.id}",
                        "file_name": document.file_name,
                        "page_number": failure.page_number,
                        "section": failure.section_type,
                        "table_index": failure.table_index,
                        "row_index": failure.row_index,
                    },
                    "operation": None
                    if operation is None
                    else {
                        "evidence_id": f"operation:{operation.id}",
                        "file_name": document.file_name,
                        "page_number": operation.page_number,
                        "section": "operations",
                        "row_index": operation.row_index,
                    },
                    "match_status": match.match_status,
                    "matching_rule": match.matching_rule,
                    "confidence": match.match_confidence,
                }
            )
        statuses = func.count(func.distinct(FailureOperationMatch.equipment_failure_id))
        status_counts = {
            status: count
            for status, count in session.execute(
                select(FailureOperationMatch.match_status, statuses).group_by(
                    FailureOperationMatch.match_status
                )
            )
        }
        report_count = (
            session.scalar(
                select(func.count(ReportSection.id)).where(
                    ReportSection.section_type == "equipment_failure_information"
                )
            )
            or 0
        )
        populated_reports = (
            session.scalar(select(func.count(func.distinct(EquipmentFailure.report_id)))) or 0
        )
        failure_count = session.scalar(select(func.count(EquipmentFailure.id))) or 0
        missing_operation_count = status_counts.get("missing_operation_time", 0)
        missing_operation_summary = (
            f"{missing_operation_count} record lacks a valid Operations interval."
            if missing_operation_count == 1
            else f"{missing_operation_count} records lack a valid Operations interval."
        )
        answer = ChatAnswer(
            f"Found {failure_count} populated equipment-failure records across {populated_reports} of "
            f"{report_count} reports containing the section. Concurrent operational activity was "
            f"established for {status_counts.get('exact', 0) + status_counts.get('overlap', 0)} "
            f"records; {status_counts.get('ambiguous', 0)} are ambiguous and "
            f"{status_counts.get('unmatched', 0)} are unmatched. {missing_operation_summary}",
            "structured_failure_activity",
            rows=rows,
            evidence=evidence,
            confidence=0.97,
            sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
            limitations=[
                "Section presence is not treated as a populated failure record.",
                "Activities are reported only from same-report temporal matches; missing or ambiguous activity is not inferred.",
                "The source 'Equipment Repaired' clock is preserved raw but is not treated as a failure end time without supporting semantics.",
            ],
            export_filename="equipment_failures_with_operational_activities.csv",
        )
    elif "below" in lower and "min" in lower and "profile" in lower:
        statement = (
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
            .where(
                Plot.plot_type == "pressure_profile", PlotPoint.band_classification == "below_min"
            )
            .order_by(Plot.plot_identifier, PlotPoint.point_index)
        )
        rows = [
            {
                "profile": row[0],
                "point_index": row[1],
                "pressure": row[2],
                "depth": row[3],
                "confidence": row[4],
                "file_name": row[5],
                "pressure_unit": row[6],
                "depth_unit": row[7],
            }
            for row in session.execute(statement)
        ]
        answer = ChatAnswer(
            f"Found {len(rows)} measured profile points classified below the MIN curve.",
            "plot_sql",
            rows=rows,
            evidence=rows,
            confidence=0.95,
            limitations=[
                "These are visual candidates, not confirmed operational anomalies; SoR is undefined."
            ],
            sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
        )
    elif "summarize" in lower or "summary" in lower or "xülas" in lower:
        report_id_match = re.search(r"report\s*(?:id)?\s*#?(\d+)", lower)
        report_id = (
            int(report_id_match.group(1))
            if report_id_match
            else session.scalar(select(Report.id).order_by(Report.period_end.desc()))
        )
        if report_id is None:
            answer = ChatAnswer(
                "No reports are available to summarize.",
                "narrative_retrieval",
                limitations=["Run ingestion first."],
                confidence=1.0,
            )
        else:
            summary = build_daily_summary(session, report_id)
            answer = ChatAnswer(
                summary.text,
                "hybrid_summary",
                evidence=summary.citations,
                rows=[summary.facts],
                limitations=summary.limitations,
                confidence=0.95,
            )
    elif "trend" in lower and "well_" in lower:
        series_match = re.search(r"well_\d{2}", lower)
        plot_match = re.search(r"pressure_time_plot_\d{2}", lower)
        series_digits = re.search(r"\d{2}", series_match.group(0)) if series_match else None
        series = f"Well_{series_digits.group(0) if series_digits else '03'}"
        statement = (
            select(PlotPoint, Plot)
            .join(Plot, Plot.id == PlotPoint.plot_id)
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
        x = [float(point.observed_date.toordinal()) for point, _ in points]
        y = [float(point.y_value) for point, _ in points]
        trend = robust_sparse_trend(x, y)
        plots = sorted({plot.plot_identifier for _, plot in points})
        dates = [point.observed_date for point, _ in points if point.observed_date]
        values = [float(point.y_value) for point, _ in points if point.y_value is not None]
        unit_statuses = sorted({plot.unit_status for _, plot in points})
        fact_row = {
            **trend,
            "plot_identifiers": plots,
            "series_identifier": series,
            "point_count": len(points),
            "date_start": min(dates).isoformat() if dates else None,
            "date_end": max(dates).isoformat() if dates else None,
            "measured_min": min(values) if values else None,
            "measured_max": max(values) if values else None,
            "unit_status": unit_statuses,
        }
        answer = ChatAnswer(
            f"Trend for {series} in {', '.join(plots) or 'the selected plot'} uses {len(points)} stored points: "
            + (
                f"Theil-Sen slope {trend['slope']:.4f} unknown pressure-units/day; "
                f"Spearman rho {trend['spearman_rho']:.3f}."
                if trend.get("applicable")
                else trend["reason"]
            ),
            "plot_analytics",
            rows=[fact_row],
            evidence=[
                {"plot_identifier": plot_id, "source": "stored plot points"} for plot_id in plots
            ],
            limitations=[
                "Pressure unit is unknown; values and slope must not be labeled PSI, kPa, MPa, or bar.",
                "Displayed series identity is not an authoritative mapping to a DDR wellbore.",
                "Trend statistics are descriptive candidate-level evidence.",
            ],
            confidence=0.9 if trend.get("applicable") else 0.6,
        )
    elif (
        "unit" in lower or "vahid" in lower or "limitation" in lower
    ) and "pressure_time_plot_" in lower:
        plot_match = re.search(r"pressure_time_plot_\d{2}", lower)
        statement = (
            select(Plot, SourceDocument)
            .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
            .where(Plot.plot_identifier == (plot_match.group(0) if plot_match else ""))
        )
        row = session.execute(statement).first()
        if row:
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
            answer = ChatAnswer(
                f"{plot.plot_identifier} has unit status '{plot.unit_status}'. The stored pressure unit is "
                f"{plot.y_unit or 'unknown'}.",
                "plot_limitations",
                rows=[facts],
                evidence=[
                    {"file_name": document.file_name, "plot_identifier": plot.plot_identifier}
                ],
                limitations=[
                    "Unknown units are preserved and are not inferred from visual scale alone."
                ],
                confidence=1.0,
                sql=str(statement.compile(compile_kwargs={"literal_binds": False})),
            )
        else:
            answer = ChatAnswer(
                "The requested plot is unavailable in the stored data.",
                "plot_limitations",
                confidence=1.0,
            )
    else:
        hits = lexical_search(session, retrieval_query or normalized, limit=8)
        if hits:
            top = hits[0]
            answer = ChatAnswer(
                top.text[:1200],
                "narrative_retrieval",
                evidence=[
                    {
                        "file_name": hit.file_name,
                        "page_number": hit.page_number,
                        "section": hit.section_type,
                        "score": hit.score,
                    }
                    for hit in hits
                ],
                limitations=["Lexical local retrieval supplied the factual evidence."],
                confidence=min(0.9, 0.5 + top.score / 10),
            )
        else:
            answer = ChatAnswer(
                "The requested information is unavailable in the currently processed data.",
                "narrative_retrieval",
                limitations=["Try a supported structured question or process the source corpus."],
                confidence=1.0,
            )
    _audit(session, question, answer, started)
    return answer


def answer_question(
    session: Session,
    question: str,
    *,
    provider: BaseLLMProvider | None = None,
    language: str = "Auto",
) -> ChatAnswer:
    """Route deterministically, retrieve verified facts, then optionally verbalize with the configured LLM."""
    active_provider = provider or LexicalFallbackProvider("No reachable LLM provider was supplied.")
    analysis = analyze_question(question, language, active_provider)
    answer = _answer_deterministic(
        session,
        question,
        retrieval_query=analysis.retrieval_query,
    )
    deterministic_text = localize_deterministic_answer(
        answer.answer,
        answer.route,
        analysis.target_language,
        rows=answer.rows,
    )
    generated_text, result, fallback_reason = grounded_verbalize(
        active_provider,
        original_question=question,
        target_language=analysis.target_language,
        deterministic_answer=deterministic_text,
        route=answer.route,
        rows=answer.rows,
        evidence=answer.evidence,
        limitations=answer.limitations,
    )
    answer.answer = generated_text
    answer.detected_language = analysis.detected_language
    answer.selected_language = analysis.target_language
    answer.retrieval_query = analysis.retrieval_query
    if result is not None and fallback_reason is None:
        answer.provider = active_provider.mode_label
        answer.model = result.model
        answer.answer_type = "OpenAI-verbalized"
        answer.model_metrics = {
            "total_duration_ns": result.total_duration_ns,
            "prompt_eval_count": result.prompt_eval_count,
            "eval_count": result.eval_count,
        }
    else:
        answer.provider = "Lexical fallback"
        answer.model = None
        answer.answer_type = (
            "lexical fallback" if answer.route == "narrative_retrieval" else "deterministic"
        )
        answer.fallback_reason = fallback_reason or analysis.fallback_reason
        fallback_limitation = "This answer is deterministic/lexical and was not LLM-generated."
        if fallback_limitation not in answer.limitations:
            answer.limitations.append(fallback_limitation)
    return answer
