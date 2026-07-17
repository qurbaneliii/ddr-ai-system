from __future__ import annotations

from pathlib import Path

from conftest import find_raw
from pypdf import PdfWriter

from ddr_ai.ingestion.router import AssetKind, classify_pdf
from ddr_ai.pdf.parser import parse_ddr_pdf


def test_valid_digital_pdf_routes_native(raw_dir: Path) -> None:
    path = find_raw(raw_dir, "ddr_pdfs", "15_9_19_A_1980_01_01.pdf")
    assert classify_pdf(path).kind == AssetKind.DIGITAL_PDF


def test_blank_pdf_routes_to_ocr_fallback(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as output:
        writer.write(output)
    assert classify_pdf(path).kind == AssetKind.SCANNED_PDF


def test_duplicate_glyphs_deduplicated_and_suspicious_report_quarantined(raw_dir: Path) -> None:
    path = find_raw(raw_dir, "ddr_pdfs", "15_9_19_A_1980_01_01.pdf")
    report = parse_ddr_pdf(path)
    assert report.pages[0].deduplicated_character_count < report.pages[0].native_character_count
    assert report.wellbore == "15/9-19 A"
    assert report.filename_identity_match is True
    assert report.filename_date_match is True
    assert report.excluded_from_default_trends is True
    assert any(item["code"] == "period_precedes_spud_date" for item in report.warnings)


def test_report_without_operations_and_optional_sections_is_valid(raw_dir: Path) -> None:
    path = find_raw(raw_dir, "ddr_pdfs", "15_9_19_A_1980_01_01.pdf")
    report = parse_ddr_pdf(path)
    assert report.operations == []
    assert not any(item.section_type == "operations" for item in report.sections)

