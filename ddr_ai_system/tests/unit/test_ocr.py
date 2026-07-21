from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.errors import PdfStreamError
from sqlalchemy import select

from ddr_ai.config import Settings
from ddr_ai.db.models import Page
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.pdf.ocr import (
    BaseOCRBackend,
    OCRResult,
    OCRToken,
    OCRUnavailableError,
    TesseractOCRBackend,
    parse_scanned_pdf,
)
from ddr_ai.pdf.ocr_tables import reconstruct_ddr_tables
from ddr_ai.services.processor import process_file


class FakeOCRBackend(BaseOCRBackend):
    name = "fake-test-ocr"

    def recognize(self, image: Image.Image) -> OCRResult:
        assert image.width > 0
        return OCRResult(
            text=(
                "Wellbore: 15/9-F-99 Period: 2026-01-01 00:00 - 2026-01-02 00:00\n"
                "Summary of activities (24 Hours)\nDrilled ahead."
            ),
            confidence=0.91,
        )


def _blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)


def test_scanned_pdf_uses_injected_ocr_and_preserves_provenance(tmp_path: Path) -> None:
    path = tmp_path / "15_9_F_99_2026_01_02.pdf"
    _blank_pdf(path)

    report = parse_scanned_pdf(path, backend=FakeOCRBackend(), dpi=72)

    assert report.pages[0].extraction_method == "ocr"
    assert report.pages[0].confidence == 0.91
    assert report.metadata["ocr_backend"] == "fake-test-ocr"
    assert report.wellbore == "15/9-F-99"
    assert report.summary_activities == "Drilled ahead."
    assert any(item["code"] == "ocr_extraction_requires_review" for item in report.warnings)


def test_scanned_pdf_processing_route_persists_ocr_page(tmp_path: Path) -> None:
    path = tmp_path / "15_9_F_99_2026_01_02.pdf"
    database = tmp_path / "ocr.db"
    database_url = f"sqlite:///{database.as_posix()}"
    _blank_pdf(path)
    upgrade_schema(database_url)
    settings = Settings(
        database_url=database_url,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        cache_dir=tmp_path / "cache",
        _env_file=None,
    )

    result = process_file(
        path,
        database_url=database_url,
        settings=settings,
        ocr_backend=FakeOCRBackend(),
    )

    assert result["status"] == "complete"
    with session_scope(database_url) as session:
        page = session.scalar(select(Page))
        assert page is not None
        assert page.extraction_method == "ocr"
        assert page.confidence == 0.91


def _token(text: str, x: float, y: float, line: int) -> OCRToken:
    return OCRToken(
        text=text,
        confidence=0.92,
        x0=x,
        y0=y,
        x1=x + max(20, len(text) * 8),
        y1=y + 16,
        block=1,
        paragraph=1,
        line=line,
        page_number=1,
    )


def test_ocr_operation_table_reconstruction_uses_layout_tokens() -> None:
    tokens = (
        _token("Start", 0, 10, 1),
        _token("End", 90, 10, 1),
        _token("Depth", 180, 10, 1),
        _token("Activity", 300, 10, 1),
        _token("State", 520, 10, 1),
        _token("Remark", 640, 10, 1),
        _token("08:00", 0, 40, 2),
        _token("12:00", 90, 40, 2),
        _token("1250", 180, 40, 2),
        _token("drilling", 300, 40, 2),
        _token("--", 390, 40, 2),
        _token("drill", 420, 40, 2),
        _token("ok", 520, 40, 2),
        _token("Drilled", 640, 40, 2),
        _token("ahead", 710, 40, 2),
    )

    structured = reconstruct_ddr_tables(
        tokens,
        "Operations",
        page_number=1,
        source_path="scan.pdf",
    )

    assert structured.table_count == 1
    assert len(structured.operations) == 1
    operation = structured.operations[0]
    assert operation.main_activity_normalized == "drilling"
    assert operation.sub_activity_normalized == "drill"
    assert operation.duration_hours == 4.0
    assert operation.bbox is not None
    assert operation.raw_values["extraction_method"] == "ocr_layout"


class EmptyOCRBackend(BaseOCRBackend):
    name = "empty-test-ocr"

    def recognize(self, image: Image.Image) -> OCRResult:
        assert image.width > 0
        return OCRResult(text="", confidence=0.0)


class FailedOCRBackend(BaseOCRBackend):
    name = "failed-test-ocr"

    def recognize(self, image: Image.Image) -> OCRResult:
        del image
        raise OCRUnavailableError("test-safe OCR failure")


def test_empty_low_confidence_and_landscape_ocr_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "landscape.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=842, height=595)
    with path.open("wb") as stream:
        writer.write(stream)

    report = parse_scanned_pdf(path, backend=EmptyOCRBackend(), dpi=72)

    assert report.pages[0].width == 842
    assert report.pages[0].height == 595
    assert report.pages[0].confidence == 0.0
    assert report.operations == []
    assert any(item["code"] == "ocr_extraction_requires_review" for item in report.warnings)


def test_ocr_backend_failure_and_missing_tesseract_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "scan.pdf"
    _blank_pdf(path)
    with pytest.raises(OCRUnavailableError, match="test-safe"):
        parse_scanned_pdf(path, backend=FailedOCRBackend(), dpi=72)

    import pytesseract

    def missing() -> None:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", missing)
    with pytest.raises(OCRUnavailableError, match="not installed"):
        TesseractOCRBackend()


def test_malformed_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "malformed.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(PdfStreamError):
        parse_scanned_pdf(path, backend=EmptyOCRBackend(), dpi=72)
