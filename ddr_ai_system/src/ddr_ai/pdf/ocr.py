from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageOps
from pypdf import PdfReader
from pytesseract import Output

from ddr_ai.analytics.failure_matching import normalize_failure_time, normalize_operation_interval
from ddr_ai.common.hashing import sha256_file
from ddr_ai.document_ai.sections import extract_summary, split_page_sections
from ddr_ai.models.schemas import PageExtraction, ParsedReport, SectionExtraction
from ddr_ai.pdf.filename import canonicalize_wellbore, parse_ddr_filename
from ddr_ai.pdf.ocr_contracts import OCRResult, OCRToken
from ddr_ai.pdf.ocr_tables import reconstruct_ddr_tables
from ddr_ai.pdf.parser import PERIOD_RE, REPORT_NUMBER_RE, SPUD_RE, STATUS_RE, _parse_datetime


class OCRUnavailableError(RuntimeError):
    """The optional local OCR runtime is not available."""


class BaseOCRBackend(ABC):
    name: str

    @abstractmethod
    def recognize(self, image: Image.Image) -> OCRResult:
        """Return page text and mean word confidence in the range 0..1."""


class TesseractOCRBackend(BaseOCRBackend):
    name = "tesseract"

    def __init__(self) -> None:
        try:
            pytesseract.get_tesseract_version()
        except (pytesseract.TesseractNotFoundError, OSError) as exc:
            raise OCRUnavailableError(
                "Scanned PDF OCR is unavailable because Tesseract is not installed."
            ) from exc

    def recognize(self, image: Image.Image) -> OCRResult:
        try:
            data = pytesseract.image_to_data(image, output_type=Output.DICT)
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError) as exc:
            raise OCRUnavailableError("Scanned PDF OCR could not be executed.") from exc
        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        tokens: list[OCRToken] = []
        for index, raw_word in enumerate(data.get("text", [])):
            word = str(raw_word).strip()
            if not word:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            lines.setdefault(key, []).append(word)
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence >= 0:
                confidences.append(confidence / 100.0)
                tokens.append(
                    OCRToken(
                        text=word,
                        confidence=confidence / 100.0,
                        x0=float(data["left"][index]),
                        y0=float(data["top"][index]),
                        x1=float(data["left"][index] + data["width"][index]),
                        y1=float(data["top"][index] + data["height"][index]),
                        block=int(data["block_num"][index]),
                        paragraph=int(data["par_num"][index]),
                        line=int(data["line_num"][index]),
                    )
                )
        text = "\n".join(" ".join(words) for words in lines.values())
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OCRResult(
            text=text,
            confidence=round(mean_confidence, 4),
            tokens=tuple(tokens),
        )


def _prepare_ocr_image(image: Image.Image, *, max_pixels: int) -> Image.Image:
    if image.width * image.height > max_pixels:
        raise ValueError("OCR page exceeds the configured safe pixel limit.")
    normalized = ImageOps.exif_transpose(image)
    grayscale = ImageOps.grayscale(normalized)
    return ImageOps.autocontrast(grayscale, cutoff=1)


def parse_scanned_pdf(
    path: str | Path,
    *,
    backend: BaseOCRBackend | None = None,
    dpi: int = 300,
    page_numbers: set[int] | None = None,
    max_pixels: int = 40_000_000,
) -> ParsedReport:
    source = Path(path)
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDF is not supported: {source.name}")
    active_backend = backend or TesseractOCRBackend()
    pages: list[PageExtraction] = []
    sections: list[SectionExtraction] = []
    page_texts: list[str] = []
    confidences: list[float] = []
    operations = []
    equipment_failures = []
    fields = []
    structured_warnings: list[dict[str, object]] = []

    document = fitz.open(source)
    try:
        scale = dpi / 72.0
        for page_index, page in enumerate(document, start=1):
            if page_numbers is not None and page_index not in page_numbers:
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            prepared = _prepare_ocr_image(image, max_pixels=max_pixels)
            result = active_backend.recognize(prepared)
            page_tokens = tuple(
                OCRToken(
                    text=item.text,
                    confidence=item.confidence,
                    x0=item.x0,
                    y0=item.y0,
                    x1=item.x1,
                    y1=item.y1,
                    block=item.block,
                    paragraph=item.paragraph,
                    line=item.line,
                    page_number=page_index,
                )
                for item in result.tokens
            )
            structured = reconstruct_ddr_tables(
                page_tokens,
                result.text,
                page_number=page_index,
                source_path=str(source),
            )
            pages.append(
                PageExtraction(
                    page_number=page_index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    native_character_count=0,
                    deduplicated_character_count=0,
                    text=result.text,
                    table_count=structured.table_count,
                    extraction_method="ocr",
                    confidence=result.confidence,
                )
            )
            page_texts.append(result.text)
            confidences.append(result.confidence)
            operations.extend(structured.operations)
            equipment_failures.extend(structured.equipment_failures)
            fields.extend(structured.fields)
            structured_warnings.extend(structured.warnings)
            for entry in split_page_sections(result.text, page_index):
                sections.append(
                    SectionExtraction(
                        section_type=str(entry["section_type"]),
                        heading_raw=str(entry["heading_raw"]),
                        page_number=int(str(entry["page_number"])),
                        text=str(entry["text"]),
                        confidence=result.confidence,
                    )
                )
    finally:
        document.close()

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
    for operation in operations:
        start, end, status, ambiguity = normalize_operation_interval(
            operation.start_time_raw, operation.end_time_raw, period_start
        )
        operation.start_datetime = start
        operation.end_datetime = end
        operation.temporal_status = status
        operation.temporal_ambiguity = ambiguity
    for failure in equipment_failures:
        start, status, ambiguity = normalize_failure_time(failure.start_time_raw, period_start)
        failure.start_datetime = start
        failure.temporal_status = status
        failure.temporal_ambiguity = ambiguity
    spud_match = SPUD_RE.search(first_text)
    spud_date = (
        _parse_datetime(f"{spud_match.group(1)} {spud_match.group(2) or '00:00'}")
        if spud_match
        else None
    )
    status_match = STATUS_RE.search(first_text)
    report_match = REPORT_NUMBER_RE.search(first_text)
    filename_match = (
        canonicalize_wellbore(wellbore) == filename_identity.wellbore
        if wellbore and filename_identity
        else None
    )
    date_match = (
        period_end.date() == filename_identity.report_date
        if period_end and filename_identity
        else None
    )
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    warnings: list[dict[str, object]] = [
        {
            "code": "ocr_extraction_requires_review",
            "severity": "medium",
            "mean_confidence": round(mean_confidence, 4),
        },
        *structured_warnings,
    ]
    return ParsedReport(
        source_path=str(source.resolve()),
        file_name=source.name,
        sha256=sha256_file(source),
        pdf_version=getattr(reader, "pdf_header", None),
        metadata={
            "ocr_backend": active_backend.name,
            "ocr_mean_confidence": round(mean_confidence, 4),
            "source_metadata": {
                str(key).lstrip("/"): str(value) for key, value in (reader.metadata or {}).items()
            },
        },
        pages=pages,
        wellbore=wellbore,
        filename_wellbore=filename_identity.wellbore if filename_identity else None,
        period_start=period_start,
        period_end=period_end,
        filename_date=filename_identity.report_date if filename_identity else None,
        spud_date=spud_date,
        report_number=int(report_match.group(1)) if report_match else None,
        status_raw=status_match.group(1).strip() if status_match else None,
        summary_activities=extract_summary(full_text, "Summary of activities (24 Hours)"),
        summary_planned=extract_summary(full_text, "Summary of planned activities (24 Hours)"),
        filename_identity_match=filename_match,
        filename_date_match=date_match,
        excluded_from_default_trends=False,
        sections=sections,
        operations=operations,
        equipment_failures=equipment_failures,
        fields=fields,
        warnings=warnings,
    )
