from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

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
from ddr_ai.services.failure_correlations import ensure_failure_correlations


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify failure/activity citations against source PDFs."
    )
    parser.add_argument("--source-root", type=Path, default=get_settings().raw_dir / "ddr_pdfs")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "equipment_failure_source_verification.json",
    )
    return parser.parse_args()


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _evidence_prefix(value: str | None, length: int = 32) -> str:
    return _normalized(value)[:length]


def main() -> None:
    settings = get_settings()
    args = _arguments()
    source_files = {path.name: path for path in args.source_root.resolve().rglob("*.pdf")}
    upgrade_schema(settings.database_url)
    with session_scope(settings.database_url) as session:
        ensure_failure_correlations(session)
        sections = session.execute(
            select(ReportSection, Report, SourceDocument)
            .join(Report, Report.id == ReportSection.report_id)
            .join(SourceDocument, SourceDocument.id == Report.source_document_id)
            .where(ReportSection.section_type == "equipment_failure_information")
            .order_by(SourceDocument.file_name)
        ).all()
        evidence_rows = session.execute(
            select(
                EquipmentFailure,
                FailureOperationMatch,
                Operation,
                SourceDocument,
            )
            .join(SourceDocument, SourceDocument.id == EquipmentFailure.source_document_id)
            .join(
                FailureOperationMatch,
                FailureOperationMatch.equipment_failure_id == EquipmentFailure.id,
            )
            .outerjoin(Operation, Operation.id == FailureOperationMatch.operation_id)
            .order_by(SourceDocument.file_name, EquipmentFailure.row_index)
        ).all()

    readers: dict[str, PdfReader] = {}
    page_texts: dict[tuple[str, int], str] = {}
    failures: list[dict[str, object]] = []

    def page_text(file_name: str, page_number: int) -> str | None:
        source = source_files.get(file_name)
        if source is None:
            return None
        if file_name not in readers:
            readers[file_name] = PdfReader(source)
        key = (file_name, page_number)
        if key not in page_texts:
            reader = readers[file_name]
            if page_number < 1 or page_number > len(reader.pages):
                return None
            page_texts[key] = reader.pages[page_number - 1].extract_text() or ""
        return page_texts[key]

    for section, _report, document in sections:
        text = page_text(document.file_name, section.page_number)
        if text is None:
            failures.append(
                {
                    "file_name": document.file_name,
                    "page_number": section.page_number,
                    "reason": "source_or_page_missing",
                }
            )
        elif "equipmentfailureinformation" not in _normalized(text):
            failures.append(
                {
                    "file_name": document.file_name,
                    "page_number": section.page_number,
                    "reason": "section_heading_not_found",
                }
            )

    for failure, _match, operation, document in evidence_rows:
        failure_text = page_text(document.file_name, failure.page_number)
        prefix = _evidence_prefix(failure.failure_remark)
        if failure_text is None or (prefix and prefix not in _normalized(failure_text)):
            failures.append(
                {
                    "file_name": document.file_name,
                    "page_number": failure.page_number,
                    "failure_id": failure.id,
                    "reason": "failure_row_evidence_not_found",
                }
            )
        if operation is not None:
            operation_text = page_text(document.file_name, operation.page_number)
            operation_prefix = _evidence_prefix(operation.remark)
            if operation_text is None or "operations" not in operation_text.casefold():
                failures.append(
                    {
                        "file_name": document.file_name,
                        "page_number": operation.page_number,
                        "operation_id": operation.id,
                        "reason": "operations_section_not_found",
                    }
                )
            elif operation_prefix and operation_prefix not in _normalized(operation_text):
                failures.append(
                    {
                        "file_name": document.file_name,
                        "page_number": operation.page_number,
                        "operation_id": operation.id,
                        "reason": "operation_row_evidence_not_found",
                    }
                )

    status_counts = Counter()
    for _failure_id, status in {
        (failure.id, match.match_status) for failure, match, _operation, _doc in evidence_rows
    }:
        status_counts[status] += 1
    report_ids_with_failures = {
        failure.report_id for failure, _match, _operation, _doc in evidence_rows
    }
    section_pages = Counter(section.page_number for section, _report, _document in sections)
    result = {
        "reports_containing_section": len(sections),
        "reports_with_populated_failures": len(report_ids_with_failures),
        "populated_failure_records": len(
            {failure.id for failure, _match, _operation, _doc in evidence_rows}
        ),
        "match_status_counts": dict(sorted(status_counts.items())),
        "wellbores": len({report.wellbore for _section, report, _document in sections}),
        "section_page_counts": {str(page): count for page, count in sorted(section_pages.items())},
        "source_files_opened": len(readers),
        "source_verification_failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
