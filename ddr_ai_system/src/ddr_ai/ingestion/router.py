from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

import pdfplumber
from PIL import Image


class AssetKind(StrEnum):
    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"
    HYBRID_PDF = "hybrid_pdf"
    PRESSURE_PROFILE = "pressure_profile"
    PRESSURE_TIME = "pressure_time"
    UNKNOWN_IMAGE = "unknown_image"
    ZIP = "zip"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True)
class RouteDecision:
    kind: AssetKind
    confidence: float
    reason: str
    metrics: dict[str, object]
    pages: tuple[PageRouteDecision, ...] = ()


@dataclass(frozen=True, slots=True)
class PageRouteDecision:
    page_number: int
    native_character_count: int
    printable_text_ratio: float
    image_count: int
    image_coverage: float
    native_text_confidence: float
    route: str
    reason: str


def classify_pdf(path: str | Path) -> RouteDecision:
    with pdfplumber.open(path) as document:
        page_decisions: list[PageRouteDecision] = []
        for page_number, page in enumerate(document.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            characters = len(page.chars)
            printable = sum(character.isprintable() for character in text)
            printable_ratio = printable / max(len(text), 1)
            page_area = float(page.width * page.height) or 1.0
            image_area = sum(
                max(0.0, float(image["x1"] - image["x0"]))
                * max(0.0, float(image["bottom"] - image["top"]))
                for image in page.images
            )
            image_coverage = min(image_area / page_area, 1.0)
            if characters >= 80 and printable_ratio >= 0.75 and image_coverage < 0.95:
                route = "native"
                reason = "Selectable printable text is sufficient"
                confidence = min(1.0, 0.8 + characters / 4000)
            elif characters > 0 and not page.images and printable_ratio >= 0.6:
                route = "native"
                reason = "Short selectable-text page without raster content"
                confidence = 0.75
            else:
                route = "ocr"
                reason = "Native text is absent/weak or raster content dominates"
                confidence = max(0.0, min(0.65, characters / 120.0))
            page_decisions.append(
                PageRouteDecision(
                    page_number=page_number,
                    native_character_count=characters,
                    printable_text_ratio=round(printable_ratio, 4),
                    image_count=len(page.images),
                    image_coverage=round(image_coverage, 4),
                    native_text_confidence=round(confidence, 4),
                    route=route,
                    reason=reason,
                )
            )
    native_count = sum(item.route == "native" for item in page_decisions)
    ocr_count = len(page_decisions) - native_count
    metrics: dict[str, object] = {
        "page_count": len(page_decisions),
        "native_pages": native_count,
        "ocr_pages": ocr_count,
        "page_decisions": [asdict(item) for item in page_decisions],
    }
    pages = tuple(page_decisions)
    if native_count == len(page_decisions):
        return RouteDecision(
            AssetKind.DIGITAL_PDF, 0.98, "All pages use native extraction", metrics, pages
        )
    if ocr_count == len(page_decisions):
        return RouteDecision(
            AssetKind.SCANNED_PDF, 0.9, "All pages require OCR", metrics, pages
        )
    return RouteDecision(
        AssetKind.HYBRID_PDF,
        0.95,
        "Document contains both native-text and OCR-routed pages",
        metrics,
        pages,
    )


def route_asset(path: str | Path) -> RouteDecision:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".zip":
        return RouteDecision(AssetKind.ZIP, 1.0, "ZIP extension", {})
    if suffix == ".pdf":
        return classify_pdf(source)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        with Image.open(source) as image:
            metrics = {"width": image.width, "height": image.height, "mode": image.mode}
        name = source.name.lower()
        if "pressure_profile" in name:
            return RouteDecision(AssetKind.PRESSURE_PROFILE, 0.99, "Filename and dimensions", metrics)
        if "pressure_time" in name:
            return RouteDecision(AssetKind.PRESSURE_TIME, 0.99, "Filename and dimensions", metrics)
        return RouteDecision(AssetKind.UNKNOWN_IMAGE, 0.4, "Image type without recognized naming", metrics)
    return RouteDecision(AssetKind.UNSUPPORTED, 1.0, f"Unsupported extension {suffix!r}", {})
