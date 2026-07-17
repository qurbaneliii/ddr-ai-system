from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ddr_ai.analytics.failure_matching import (
    TimedOperation,
    match_failure_to_operations,
    normalize_failure_time,
    normalize_operation_interval,
)
from ddr_ai.db.models import (
    EquipmentFailure,
    FailureOperationMatch,
    Operation,
    Report,
    ReportSection,
    SectionTableRow,
)
from ddr_ai.models.schemas import EquipmentFailureExtraction
from ddr_ai.pdf.parser import equipment_failure_from_cells, is_equipment_failure_header

CORRELATION_VERSION = "1.0.0"


@dataclass(slots=True)
class Reconciliation:
    reports_containing_section: int = 0
    reports_with_populated_failures: int = 0
    populated_failure_records: int = 0
    exact_matches: int = 0
    overlap_matches: int = 0
    ambiguous_matches: int = 0
    inferred_nearest_matches: int = 0
    unmatched_records: int = 0
    missing_failure_timestamps: int = 0
    missing_operation_timestamps: int = 0
    parser_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _bbox_dict(bbox: tuple[float, float, float, float] | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    return dict(zip(("x0", "top", "x1", "bottom"), bbox, strict=True))


def _normalize_operations(report: Report, operations: Iterable[Operation]) -> list[TimedOperation]:
    timed: list[TimedOperation] = []
    for operation in operations:
        start, end, status, ambiguity = normalize_operation_interval(
            operation.start_time_raw, operation.end_time_raw, report.period_start
        )
        operation.start_datetime = start
        operation.end_datetime = end
        operation.temporal_status = status
        operation.temporal_ambiguity = ambiguity
        operation.raw_values_json = {
            "start_time": operation.start_time_raw,
            "end_time": operation.end_time_raw,
            "end_depth_mmd": operation.end_depth_mmd_raw,
            "main_activity": operation.main_activity_raw,
            "sub_activity": operation.sub_activity_raw,
            "state": operation.state_raw,
            "remark": operation.remark,
        }
        operation.normalized_values_json = {
            "start_datetime": start.isoformat() if start else None,
            "end_datetime": end.isoformat() if end else None,
            "end_depth_mmd": operation.end_depth_mmd,
            "main_activity": operation.main_activity_normalized,
            "sub_activity": operation.sub_activity_normalized,
            "state": operation.state_normalized,
            "temporal_status": status,
        }
        timed.append(TimedOperation(operation.id, start, end, operation.confidence))
    return timed


def replace_report_correlations(
    session: Session,
    report: Report,
    failures: Iterable[EquipmentFailureExtraction],
) -> Counter[str]:
    """Replace one report's derived failures and matches in one idempotent transaction."""
    existing_ids = session.scalars(
        select(EquipmentFailure.id).where(EquipmentFailure.report_id == report.id)
    ).all()
    if existing_ids:
        session.execute(
            delete(FailureOperationMatch).where(
                FailureOperationMatch.equipment_failure_id.in_(existing_ids)
            )
        )
        session.execute(delete(EquipmentFailure).where(EquipmentFailure.id.in_(existing_ids)))

    operations = session.scalars(
        select(Operation).where(Operation.report_id == report.id).order_by(Operation.row_index)
    ).all()
    timed_operations = _normalize_operations(report, operations)
    operation_lookup = {operation.id: operation for operation in operations}
    section_lookup = {
        item.page_number: item.id
        for item in session.scalars(
            select(ReportSection).where(
                ReportSection.report_id == report.id,
                ReportSection.section_type == "equipment_failure_information",
            )
        ).all()
    }

    counts: Counter[str] = Counter()
    for extraction in failures:
        start, temporal_status, ambiguity = normalize_failure_time(
            extraction.start_time_raw, report.period_start
        )
        failure = EquipmentFailure(
            report_id=report.id,
            source_document_id=report.source_document_id,
            report_section_id=section_lookup.get(extraction.page_number),
            page_number=extraction.page_number,
            section_type="equipment_failure_information",
            table_index=extraction.table_index,
            row_index=extraction.row_index,
            start_time_raw=extraction.start_time_raw,
            end_time_raw=extraction.end_time_raw,
            start_datetime=start,
            end_datetime=extraction.end_datetime,
            depth_mmd_raw=extraction.depth_mmd_raw,
            depth_mmd=extraction.depth_mmd,
            depth_mtvd_raw=extraction.depth_mtvd_raw,
            depth_mtvd=extraction.depth_mtvd,
            failed_equipment_raw=extraction.failed_equipment_raw,
            failed_equipment_normalized=extraction.failed_equipment_normalized,
            system_class_raw=extraction.system_class_raw,
            system_class_normalized=extraction.system_class_normalized,
            operational_downtime_raw=extraction.operational_downtime_raw,
            operational_downtime_minutes=extraction.operational_downtime_minutes,
            equipment_repaired_raw=extraction.equipment_repaired_raw,
            failure_remark=extraction.failure_remark,
            temporal_status=temporal_status,
            temporal_ambiguity=ambiguity,
            raw_values_json=extraction.raw_values,
            normalized_values_json={
                **extraction.normalized_values,
                "start_datetime": start.isoformat() if start else None,
                "temporal_status": temporal_status,
            },
            bbox_json=_bbox_dict(extraction.bbox),
            confidence=extraction.confidence,
        )
        session.add(failure)
        session.flush()
        decisions = match_failure_to_operations(start, extraction.end_datetime, timed_operations)
        for decision in decisions:
            operation = (
                operation_lookup.get(decision.operation_key)
                if isinstance(decision.operation_key, int)
                else None
            )
            session.add(FailureOperationMatch(
                equipment_failure_id=failure.id,
                operation_id=operation.id if operation else None,
                match_status=decision.status,
                match_confidence=decision.confidence,
                matching_rule=decision.rule,
                time_difference_minutes=decision.time_difference_minutes,
                evidence_json={
                    "failure": {
                        "id": failure.id,
                        "page_number": failure.page_number,
                        "table_index": failure.table_index,
                        "row_index": failure.row_index,
                    },
                    "operation": None if operation is None else {
                        "id": operation.id,
                        "page_number": operation.page_number,
                        "row_index": operation.row_index,
                    },
                },
            ))
        for status in {decision.status for decision in decisions}:
            counts[status] += 1
        counts["failure_records"] += 1
    return counts


def backfill_failure_correlations(session: Session) -> Reconciliation:
    report_ids = session.scalars(
        select(ReportSection.report_id).where(
            ReportSection.section_type == "equipment_failure_information"
        ).distinct()
    ).all()
    result = Reconciliation(reports_containing_section=len(report_ids))
    for report_id in report_ids:
        report = session.get(Report, report_id)
        if report is None:
            result.parser_failures += 1
            continue
        extractions: list[EquipmentFailureExtraction] = []
        rows = session.scalars(
            select(SectionTableRow).where(
                SectionTableRow.report_id == report.id,
                SectionTableRow.section_type == "equipment_failure_information",
            ).order_by(
                SectionTableRow.page_number,
                SectionTableRow.table_index,
                SectionTableRow.row_index,
            )
        ).all()
        for row in rows:
            if not is_equipment_failure_header(row.header_cells_json):
                continue
            bbox = row.table_bbox_json
            extraction = equipment_failure_from_cells(
                row.header_cells_json,
                row.raw_cells_json,
                table_index=row.table_index,
                row_index=row.row_index,
                page_number=row.page_number,
                bbox=(bbox["x0"], bbox["top"], bbox["x1"], bbox["bottom"]),
            )
            if extraction is None:
                result.parser_failures += 1
            else:
                extractions.append(extraction)
        counts = replace_report_correlations(session, report, extractions)
        if extractions:
            result.reports_with_populated_failures += 1
        result.populated_failure_records += counts["failure_records"]
        result.exact_matches += counts["exact"]
        result.overlap_matches += counts["overlap"]
        result.ambiguous_matches += counts["ambiguous"]
        result.inferred_nearest_matches += counts["inferred_nearest"]
        result.unmatched_records += counts["unmatched"]
        result.missing_failure_timestamps += counts["missing_failure_time"]
        result.missing_operation_timestamps += counts["missing_operation_time"]
    return result


def ensure_failure_correlations(session: Session) -> Reconciliation | None:
    sections = session.scalar(
        select(func.count(ReportSection.id)).where(
            ReportSection.section_type == "equipment_failure_information"
        )
    ) or 0
    failures = session.scalar(select(func.count(EquipmentFailure.id))) or 0
    if sections and not failures:
        return backfill_failure_correlations(session)
    return None
