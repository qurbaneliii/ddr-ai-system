from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import select

from ddr_ai.config import Settings
from ddr_ai.db.models import Page, SourceDocument
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.ingestion.router import AssetKind, classify_pdf
from ddr_ai.pdf.document import parse_document_pdf
from ddr_ai.pdf.ocr import BaseOCRBackend, OCRResult
from ddr_ai.services.processor import process_file


class HybridOCRBackend(BaseOCRBackend):
    name = "hybrid-test-ocr"

    def recognize(self, image: Image.Image) -> OCRResult:
        assert image.width > 0 and image.height > 0
        return OCRResult(
            text="Equipment Failure Information\nNo populated failure rows.",
            confidence=0.88,
        )


def _hybrid_pdf(path: Path) -> None:
    image_buffer = io.BytesIO()
    Image.new("RGB", (600, 800), color="white").save(image_buffer, format="PNG")
    document = fitz.open()
    native = document.new_page(width=595, height=842)
    native.insert_textbox(
        fitz.Rect(40, 40, 555, 300),
        (
            "Wellbore: 15/9-F-99 Period: 2026-01-01 00:00 - 2026-01-02 00:00\n"
            "Summary of activities (24 Hours)\nDrilled ahead with sufficient selectable text "
            "for deterministic native-page classification and report identity extraction."
        ),
        fontsize=11,
    )
    scanned = document.new_page(width=595, height=842)
    scanned.insert_image(scanned.rect, stream=image_buffer.getvalue())
    document.save(path)
    document.close()


def test_page_aware_hybrid_route_and_unified_parse(tmp_path: Path) -> None:
    path = tmp_path / "15_9_F_99_2026_01_02.pdf"
    _hybrid_pdf(path)

    decision = classify_pdf(path)
    assert decision.kind == AssetKind.HYBRID_PDF
    assert [item.route for item in decision.pages] == ["native", "ocr"]

    report = parse_document_pdf(path, decision=decision, ocr_backend=HybridOCRBackend())
    assert report.wellbore == "15/9-F-99"
    assert [item.extraction_method for item in report.pages] == ["native_pdf", "ocr"]
    assert report.metadata["document_extraction"] == "hybrid_native_ocr"
    assert any(item.page_number == 2 for item in report.sections)


def test_hybrid_process_file_persists_page_methods(tmp_path: Path) -> None:
    path = tmp_path / "15_9_F_99_2026_01_02.pdf"
    database_url = f"sqlite:///{(tmp_path / 'hybrid.db').as_posix()}"
    _hybrid_pdf(path)
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
        ocr_backend=HybridOCRBackend(),
    )

    assert result["status"] == "complete"
    with session_scope(database_url) as session:
        source = session.scalar(select(SourceDocument))
        pages = list(session.scalars(select(Page).order_by(Page.page_number)))
        assert source is not None and source.asset_kind == "hybrid_pdf"
        assert [item.extraction_method for item in pages] == ["native_pdf", "ocr"]
