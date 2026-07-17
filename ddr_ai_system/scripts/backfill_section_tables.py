from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

import pdfplumber
from sqlalchemy import delete, func, select

from ddr_ai.common.numbers import normalize_number
from ddr_ai.config import PROJECT_ROOT
from ddr_ai.db.models import Report, ReportSection, SectionTableRow, SourceDocument
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.document_ai.sections import SECTION_HEADINGS
from ddr_ai.pdf.parser import dedupe_page, reconstruct_wrapped_cell

OPTIONAL_SECTION_TYPES = set(SECTION_HEADINGS.values()) - {
    "summary_activities", "summary_planned_activities", "operations"
}
BACKFILL_VERSION = "0.2.0"


def _heading_positions(page: Any) -> list[tuple[float, str]]:
    positions: list[tuple[float, str]] = []
    for heading, section_type in SECTION_HEADINGS.items():
        try:
            matches = page.search(heading, regex=False, case=False)
        except TypeError:
            matches = page.search(heading, regex=False)
        for match in matches or []:
            positions.append((float(match["top"]), section_type))
    return sorted(positions)


def _section_for_table(
    headings: list[tuple[float, str]], table_top: float, carry: str | None
) -> str | None:
    above = [item for item in headings if item[0] <= table_top + 2]
    return above[-1][1] if above else carry


def _normalize_cells(cells: list[str | None]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for cell in cells:
        text = reconstruct_wrapped_cell(cell)
        number = normalize_number(text)
        normalized.append({
            "raw_value": text,
            "normalized_number": number.value,
            "missing_reason": number.missing_reason,
        })
    return normalized


def _process_document(document_row: SourceDocument, report: Report) -> dict[str, object]:
    started = time.perf_counter()
    if document_row.metadata_json.get("section_table_backfill_version") == BACKFILL_VERSION:
        return {"file": document_row.file_name, "status": "skipped_unchanged", "rows": 0}
    with session_scope() as session:
        existing = session.scalar(
            select(func.count(SectionTableRow.id)).where(
                SectionTableRow.source_document_id == document_row.id
            )
        ) or 0
        if existing:
            session.execute(delete(SectionTableRow).where(
                SectionTableRow.source_document_id == document_row.id
            ))
    output_rows: list[dict[str, object]] = []
    carry: str | None = None
    with pdfplumber.open(document_row.source_path) as pdf:
        for page_number, raw_page in enumerate(pdf.pages, start=1):
            page = dedupe_page(raw_page)
            headings = _heading_positions(page)
            found_tables = page.find_tables() or []
            for table_index, table in enumerate(found_tables):
                section_type = _section_for_table(headings, float(table.bbox[1]), carry)
                if section_type not in OPTIONAL_SECTION_TYPES:
                    continue
                data = table.extract() or []
                if len(data) < 2:
                    continue
                headers = [reconstruct_wrapped_cell(cell) for cell in data[0]]
                for row_index, row in enumerate(data[1:], start=1):
                    cells = [reconstruct_wrapped_cell(cell) for cell in row]
                    if not any(cell for cell in cells):
                        continue
                    output_rows.append({
                        "page_number": page_number,
                        "section_type": section_type,
                        "table_index": table_index,
                        "row_index": row_index,
                        "headers": headers,
                        "cells": cells,
                        "normalized": _normalize_cells(cells),
                        "bbox": {"x0": float(table.bbox[0]), "top": float(table.bbox[1]),
                                 "x1": float(table.bbox[2]), "bottom": float(table.bbox[3])},
                    })
            if headings:
                carry = headings[-1][1]
    with session_scope() as session:
        sections = session.scalars(
            select(ReportSection).where(ReportSection.report_id == report.id)
        ).all()
        section_lookup = {(item.page_number, item.section_type): item.id for item in sections}
        for item in output_rows:
            session.add(SectionTableRow(
                source_document_id=document_row.id, report_id=report.id,
                report_section_id=section_lookup.get((item["page_number"], item["section_type"])),
                page_number=item["page_number"], section_type=item["section_type"],
                table_index=item["table_index"], row_index=item["row_index"],
                header_cells_json=item["headers"], raw_cells_json=item["cells"],
                normalized_cells_json=item["normalized"], table_bbox_json=item["bbox"],
                confidence=0.92,
            ))
        stored = session.get(SourceDocument, document_row.id)
        metadata = dict(stored.metadata_json)
        metadata["section_table_backfill_version"] = BACKFILL_VERSION
        stored.metadata_json = metadata
    return {"file": document_row.file_name, "status": "complete", "rows": len(output_rows),
            "duration_seconds": round(time.perf_counter() - started, 3)}


def main() -> None:
    upgrade_schema()
    with session_scope() as session:
        documents = session.execute(
            select(SourceDocument, Report)
            .join(Report, Report.source_document_id == SourceDocument.id)
            .where(SourceDocument.asset_kind == "digital_pdf")
            .order_by(SourceDocument.file_name)
        ).all()
    counts: Counter[str] = Counter()
    total_rows = 0
    for index, (document, report) in enumerate(documents, start=1):
        try:
            result = _process_document(document, report)
        except Exception as exc:
            result = {"file": document.file_name, "status": "failed",
                      "error": f"{type(exc).__name__}: {str(exc)[:500]}", "rows": 0}
        counts[str(result["status"])] += 1
        total_rows += int(result.get("rows", 0))
        if index == 1 or index % 25 == 0 or index == len(documents):
            print(json.dumps({"processed": index, "total": len(documents),
                              "statuses": dict(counts), "rows": total_rows}), flush=True)
    with session_scope() as session:
        sentinel_cells = 0
        by_section: Counter[str] = Counter()
        for row in session.scalars(select(SectionTableRow)).all():
            by_section[row.section_type] += 1
            sentinel_cells += sum(
                cell.get("missing_reason") == "source_sentinel"
                for cell in row.normalized_cells_json
            )
    summary = {"documents": len(documents), "statuses": dict(counts), "rows": total_rows,
               "rows_by_section": dict(sorted(by_section.items())),
               "sentinel_cells_normalized": sentinel_cells}
    output = PROJECT_ROOT / "data" / "processed" / "section_table_summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
