from __future__ import annotations

from pathlib import Path
from typing import Any

from ddr_ai.ingestion.router import AssetKind, RouteDecision, classify_pdf
from ddr_ai.models.schemas import ParsedReport
from ddr_ai.pdf.ocr import BaseOCRBackend, parse_scanned_pdf
from ddr_ai.pdf.parser import parse_ddr_pdf


def _value(native: ParsedReport, ocr: ParsedReport, name: str, *, prefer_ocr: bool) -> Any:
    first, second = (ocr, native) if prefer_ocr else (native, ocr)
    return getattr(first, name) if getattr(first, name) is not None else getattr(second, name)


def parse_document_pdf(
    path: str | Path,
    *,
    decision: RouteDecision | None = None,
    ocr_backend: BaseOCRBackend | None = None,
    ocr_dpi: int = 300,
) -> ParsedReport:
    """Parse one native, scanned, or mixed PDF through a page-aware orchestration boundary."""

    source = Path(path)
    route = decision or classify_pdf(source)
    if route.kind == AssetKind.DIGITAL_PDF:
        parsed = parse_ddr_pdf(source)
        parsed.metadata["page_routing"] = route.metrics
        return parsed
    if route.kind == AssetKind.SCANNED_PDF:
        parsed = parse_scanned_pdf(source, backend=ocr_backend, dpi=ocr_dpi)
        parsed.metadata["page_routing"] = route.metrics
        return parsed
    if route.kind != AssetKind.HYBRID_PDF:
        raise ValueError(f"PDF route is unsupported: {route.kind.value}")

    ocr_pages = {item.page_number for item in route.pages if item.route == "ocr"}
    native = parse_ddr_pdf(source)
    ocr = parse_scanned_pdf(
        source,
        backend=ocr_backend,
        dpi=ocr_dpi,
        page_numbers=ocr_pages,
    )
    prefer_ocr = 1 in ocr_pages
    pages = {item.page_number: item for item in native.pages}
    pages.update({item.page_number: item for item in ocr.pages})
    native_sections = [item for item in native.sections if item.page_number not in ocr_pages]
    native_operations = [item for item in native.operations if item.page_number not in ocr_pages]
    native_failures = [item for item in native.equipment_failures if item.page_number not in ocr_pages]
    native_fields = [
        item for item in native.fields if item.provenance.page_number not in ocr_pages
    ]
    return ParsedReport(
        source_path=native.source_path,
        file_name=native.file_name,
        sha256=native.sha256,
        pdf_version=native.pdf_version,
        metadata={
            **native.metadata,
            "ocr": ocr.metadata,
            "page_routing": route.metrics,
            "document_extraction": "hybrid_native_ocr",
        },
        pages=[pages[index] for index in sorted(pages)],
        wellbore=_value(native, ocr, "wellbore", prefer_ocr=prefer_ocr),
        filename_wellbore=_value(native, ocr, "filename_wellbore", prefer_ocr=prefer_ocr),
        period_start=_value(native, ocr, "period_start", prefer_ocr=prefer_ocr),
        period_end=_value(native, ocr, "period_end", prefer_ocr=prefer_ocr),
        filename_date=_value(native, ocr, "filename_date", prefer_ocr=prefer_ocr),
        spud_date=_value(native, ocr, "spud_date", prefer_ocr=prefer_ocr),
        report_number=_value(native, ocr, "report_number", prefer_ocr=prefer_ocr),
        status_raw=_value(native, ocr, "status_raw", prefer_ocr=prefer_ocr),
        summary_activities=_value(native, ocr, "summary_activities", prefer_ocr=prefer_ocr),
        summary_planned=_value(native, ocr, "summary_planned", prefer_ocr=prefer_ocr),
        filename_identity_match=_value(
            native, ocr, "filename_identity_match", prefer_ocr=prefer_ocr
        ),
        filename_date_match=_value(native, ocr, "filename_date_match", prefer_ocr=prefer_ocr),
        excluded_from_default_trends=(
            native.excluded_from_default_trends or ocr.excluded_from_default_trends
        ),
        sections=sorted(
            [*native_sections, *ocr.sections], key=lambda item: item.page_number
        ),
        operations=sorted(
            [*native_operations, *ocr.operations],
            key=lambda item: (item.page_number, item.row_index),
        ),
        equipment_failures=sorted(
            [*native_failures, *ocr.equipment_failures],
            key=lambda item: (item.page_number, item.table_index, item.row_index),
        ),
        fields=[*native_fields, *ocr.fields],
        warnings=[*native.warnings, *ocr.warnings],
        sentinel_count=native.sentinel_count + ocr.sentinel_count,
    )
