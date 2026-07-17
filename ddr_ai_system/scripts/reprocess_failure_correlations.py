from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from ddr_ai.config import PROJECT_ROOT, get_settings
from ddr_ai.db.models import (
    EquipmentFailure,
    FailureOperationMatch,
    Operation,
    Report,
    ReportSection,
    SourceDocument,
)
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.pdf.parser import parse_ddr_pdf
from ddr_ai.services.failure_correlations import replace_report_correlations


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reparse source-backed failure reports and rebuild deterministic operation matches."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=get_settings().raw_dir / "ddr_pdfs",
        help="Directory containing the extracted DDR PDFs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "equipment_failure_reconciliation.json",
    )
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    source_root = args.source_root.resolve()
    source_files = {path.name: path for path in source_root.rglob("*.pdf")}
    upgrade_schema()
    with session_scope() as session:
        report_rows = session.execute(
            select(Report, SourceDocument)
            .join(SourceDocument, SourceDocument.id == Report.source_document_id)
            .where(Report.id.in_(
                select(ReportSection.report_id).where(
                    ReportSection.section_type == "equipment_failure_information"
                )
            ))
            .order_by(SourceDocument.file_name)
        ).all()

    failures: list[dict[str, str]] = []
    empty_sections: list[str] = []
    operation_mismatches: list[dict[str, object]] = []
    for index, (detached_report, document) in enumerate(report_rows, start=1):
        source = source_files.get(document.file_name)
        if source is None:
            failures.append({"file_name": document.file_name, "reason": "source_pdf_missing"})
            continue
        try:
            parsed = parse_ddr_pdf(source)
            with session_scope() as session:
                report = session.get(Report, detached_report.id)
                stored_operations = session.scalars(
                    select(Operation).where(Operation.report_id == report.id)
                    .order_by(Operation.row_index)
                ).all()
                parsed_by_index = {item.row_index: item for item in parsed.operations}
                if len(stored_operations) != len(parsed.operations):
                    operation_mismatches.append({
                        "file_name": document.file_name,
                        "stored": len(stored_operations),
                        "parsed": len(parsed.operations),
                    })
                for operation in stored_operations:
                    extracted = parsed_by_index.get(operation.row_index)
                    if extracted is None:
                        continue
                    operation.start_datetime = extracted.start_datetime
                    operation.end_datetime = extracted.end_datetime
                    operation.temporal_status = extracted.temporal_status
                    operation.temporal_ambiguity = extracted.temporal_ambiguity
                    operation.raw_values_json = extracted.raw_values
                    operation.normalized_values_json = extracted.normalized_values
                    operation.bbox_json = None if extracted.bbox is None else dict(zip(
                        ("x0", "top", "x1", "bottom"), extracted.bbox, strict=True
                    ))
                replace_report_correlations(session, report, parsed.equipment_failures)
            if not parsed.equipment_failures:
                empty_sections.append(document.file_name)
        except Exception as exc:
            failures.append({
                "file_name": document.file_name,
                "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
            })
        if index == 1 or index % 10 == 0 or index == len(report_rows):
            print(json.dumps({
                "processed": index,
                "total": len(report_rows),
                "parser_failures": len(failures),
            }), flush=True)

    with session_scope() as session:
        status_counts = {
            status: count for status, count in session.execute(
                select(FailureOperationMatch.match_status, func.count(FailureOperationMatch.id))
                .group_by(FailureOperationMatch.match_status)
            )
        }
        result = {
            "reports_containing_section": len(report_rows),
            "reports_source_verified": len(report_rows) - len(failures),
            "reports_with_populated_failures": session.scalar(
                select(func.count(func.distinct(EquipmentFailure.report_id)))
            ) or 0,
            "populated_failure_records": session.scalar(
                select(func.count(EquipmentFailure.id))
            ) or 0,
            "match_status_counts": status_counts,
            "empty_section_reports": empty_sections,
            "operation_row_count_mismatches": operation_mismatches,
            "parser_failures": failures,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
