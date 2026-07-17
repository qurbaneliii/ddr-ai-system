from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

from ddr_ai.analytics.events import normalize_activity
from ddr_ai.common.hashing import sha256_file
from ddr_ai.common.numbers import normalize_number
from ddr_ai.document_ai.sections import extract_summary, split_page_sections
from ddr_ai.models.schemas import (
    ExtractedField,
    OperationExtraction,
    PageExtraction,
    ParsedReport,
    Provenance,
    SectionExtraction,
)
from ddr_ai.pdf.filename import canonicalize_wellbore, parse_ddr_filename

PERIOD_RE = re.compile(
    r"Wellbore:\s*(?P<wellbore>.+?)\s+Period:\s*(?P<start>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*-\s*(?P<end>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})"
)
STATUS_RE = re.compile(r"Status:\s*([^\s]+)")
REPORT_NUMBER_RE = re.compile(r"Report number:\s*(\d+)")
SPUD_RE = re.compile(r"Spud Date:\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?")
SENTINEL_RE = re.compile(r"(?<!\d)-999\.(?:99|9)(?!\d)")


def dedupe_page(page: Any) -> Any:
    try:
        return page.dedupe_chars(tolerance=1, extra_attrs=("fontname", "size"))
    except (TypeError, KeyError):
        return page.dedupe_chars(tolerance=1)


def reconstruct_wrapped_cell(value: str | None, *, compact: bool = False) -> str | None:
    if value is None:
        return None
    pieces = [part.strip() for part in value.splitlines() if part.strip()]
    if not pieces:
        return ""
    if compact:
        return "".join(pieces)
    output = pieces[0]
    for piece in pieces[1:]:
        if output.endswith("-") or output and output[-1].isalnum() and len(piece) <= 3 and piece.isalpha():
            output += piece
        else:
            output += " " + piece
    return " ".join(output.split())


def _parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def operation_duration_hours(start_raw: str | None, end_raw: str | None) -> float | None:
    try:
        start = datetime.combine(datetime.min.date(), time.fromisoformat(start_raw or ""))
        end = datetime.combine(datetime.min.date(), time.fromisoformat(end_raw or ""))
    except ValueError:
        return None
    if end <= start:
        end += timedelta(days=1)
    return round((end - start).total_seconds() / 3600, 4)


def _parse_operation_tables(page_tables: list[list[list[list[str | None]]]]) -> list[OperationExtraction]:
    operations: list[OperationExtraction] = []
    row_index = 0
    for page_number, tables in enumerate(page_tables, start=1):
        for table in tables:
            if not table:
                continue
            header = " ".join(str(cell or "") for cell in table[0]).casefold()
            if not all(token in header for token in ("start", "end", "state", "remark")):
                continue
            for row in table[1:]:
                padded = list(row) + [None] * max(0, 6 - len(row))
                start_raw = reconstruct_wrapped_cell(padded[0], compact=True)
                end_raw = reconstruct_wrapped_cell(padded[1], compact=True)
                if not start_raw and not end_raw:
                    continue
                activity = reconstruct_wrapped_cell(padded[3], compact=True) or ""
                parts = re.split(r"\s*--\s*", activity, maxsplit=1)
                main_raw = parts[0].strip() or None
                sub_raw = parts[1].strip() if len(parts) > 1 else None
                main_normalized, sub_normalized = normalize_activity(main_raw, sub_raw)
                depth = normalize_number(reconstruct_wrapped_cell(padded[2], compact=True))
                state_raw = reconstruct_wrapped_cell(padded[4], compact=True)
                state_normalized = state_raw.casefold() if state_raw else None
                operations.append(OperationExtraction(
                    row_index=row_index,
                    page_number=page_number,
                    start_time_raw=start_raw,
                    end_time_raw=end_raw,
                    duration_hours=operation_duration_hours(start_raw, end_raw),
                    end_depth_raw=depth.raw_value,
                    end_depth_mmd=depth.value,
                    end_depth_missing_reason=depth.missing_reason,
                    main_activity_raw=main_raw,
                    sub_activity_raw=sub_raw,
                    main_activity_normalized=main_normalized,
                    sub_activity_normalized=sub_normalized,
                    state_raw=state_raw,
                    state_normalized=state_normalized,
                    remark=reconstruct_wrapped_cell(padded[5]),
                    confidence=0.98,
                ))
                row_index += 1
    return operations


def _header_fields(tables: list[list[list[str | None]]], source_path: str) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    for table in tables:
        for row in table:
            if not row:
                continue
            cells = list(row)
            for index in range(0, len(cells) - 1):
                label = reconstruct_wrapped_cell(cells[index])
                if not label or not label.endswith(":"):
                    continue
                raw = reconstruct_wrapped_cell(cells[index + 1])
                number = normalize_number(raw)
                fields.append(ExtractedField(
                    field_name=label[:-1].strip(),
                    raw_value=raw,
                    normalized_text=raw,
                    normalized_number=number.value,
                    missing_reason=number.missing_reason if number.missing_reason == "source_sentinel" else None,
                    provenance=Provenance(source_path=source_path, page_number=1, section="summary_report"),
                    confidence=0.95,
                ))
    unique: dict[str, ExtractedField] = {}
    for field in fields:
        if field.field_name not in unique or field.raw_value:
            unique[field.field_name] = field
    return list(unique.values())


def parse_ddr_pdf(path: str | Path) -> ParsedReport:
    source = Path(path)
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDF is not supported: {source.name}")
    pdf_version = getattr(reader, "pdf_header", None)
    metadata = {str(key).lstrip("/"): str(value) for key, value in (reader.metadata or {}).items()}
    pages: list[PageExtraction] = []
    sections: list[SectionExtraction] = []
    page_texts: list[str] = []
    page_tables: list[list[list[list[str | None]]]] = []
    with pdfplumber.open(source) as document:
        for page_number, raw_page in enumerate(document.pages, start=1):
            page = dedupe_page(raw_page)
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            tables = page.extract_tables() or []
            page_tables.append(tables)
            pages.append(PageExtraction(
                page_number=page_number,
                width=float(page.width),
                height=float(page.height),
                native_character_count=len(raw_page.chars),
                deduplicated_character_count=len(page.chars),
                text=text,
                table_count=len(tables),
            ))
            page_texts.append(text)
            for entry in split_page_sections(text, page_number):
                sections.append(SectionExtraction(
                    section_type=str(entry["section_type"]),
                    heading_raw=str(entry["heading_raw"]),
                    page_number=int(str(entry["page_number"])),
                    text=str(entry["text"]),
                ))
        operations = _parse_operation_tables(page_tables)
        fields = _header_fields(page_tables[0], str(source)) if page_tables else []

    full_text = "\n".join(page_texts)
    first_text = page_texts[0] if page_texts else ""
    filename_identity = parse_ddr_filename(source)
    wellbore = None
    period_start = None
    period_end = None
    period_match = PERIOD_RE.search(first_text)
    if period_match:
        wellbore = canonicalize_wellbore(period_match.group("wellbore"))
        period_start = _parse_datetime(period_match.group("start"))
        period_end = _parse_datetime(period_match.group("end"))
    status_match = STATUS_RE.search(first_text)
    report_match = REPORT_NUMBER_RE.search(first_text)
    spud_match = SPUD_RE.search(first_text)
    spud_date = None
    if spud_match:
        spud_date = _parse_datetime(f"{spud_match.group(1)} {spud_match.group(2) or '00:00'}")
    filename_match = (
        canonicalize_wellbore(wellbore) == filename_identity.wellbore
        if wellbore and filename_identity else None
    )
    date_match = period_end.date() == filename_identity.report_date if period_end and filename_identity else None
    warnings: list[dict[str, Any]] = []
    excluded = False
    if filename_match is False:
        warnings.append({"code": "filename_header_identity_mismatch", "severity": "high"})
    if date_match is False:
        warnings.append({"code": "filename_period_end_mismatch", "severity": "high"})
    if period_end and spud_date and period_end < spud_date - timedelta(days=1):
        excluded = True
        warnings.append({
            "code": "period_precedes_spud_date",
            "severity": "high",
            "period_end": period_end.isoformat(),
            "spud_date": spud_date.isoformat(),
            "action": "excluded_from_default_trends",
        })
    return ParsedReport(
        source_path=str(source),
        file_name=source.name,
        sha256=sha256_file(source),
        pdf_version=pdf_version,
        metadata=metadata,
        pages=pages,
        wellbore=wellbore,
        filename_wellbore=filename_identity.wellbore if filename_identity else None,
        period_start=period_start,
        period_end=period_end,
        filename_date=filename_identity.report_date if filename_identity else None,
        spud_date=spud_date,
        report_number=int(report_match.group(1)) if report_match else None,
        status_raw=status_match.group(1) if status_match else None,
        summary_activities=extract_summary(full_text, "Summary of activities (24 Hours)"),
        summary_planned=extract_summary(full_text, "Summary of planned activities (24 Hours)"),
        filename_identity_match=filename_match,
        filename_date_match=date_match,
        excluded_from_default_trends=excluded,
        sections=sections,
        operations=operations,
        fields=fields,
        warnings=warnings,
        sentinel_count=len(SENTINEL_RE.findall(full_text)),
    )
