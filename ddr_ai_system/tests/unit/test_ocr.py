from __future__ import annotations

from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select

from ddr_ai.config import Settings
from ddr_ai.db.models import Page
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.pdf.ocr import BaseOCRBackend, OCRResult, parse_scanned_pdf
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
