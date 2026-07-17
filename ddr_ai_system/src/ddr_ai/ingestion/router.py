from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pdfplumber
from PIL import Image


class AssetKind(StrEnum):
    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"
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


def classify_pdf(path: str | Path) -> RouteDecision:
    with pdfplumber.open(path) as document:
        sampled = document.pages[: min(3, len(document.pages))]
        characters = sum(len(page.chars) for page in sampled)
        images = sum(len(page.images) for page in sampled)
        area = sum(float(page.width * page.height) for page in sampled) or 1.0
        image_area = sum(
            max(0.0, float(image["x1"] - image["x0"]))
            * max(0.0, float(image["bottom"] - image["top"]))
            for page in sampled
            for image in page.images
        )
    image_coverage = min(image_area / area, 1.0)
    metrics: dict[str, object] = {
        "sampled_pages": len(sampled),
        "characters": characters,
        "images": images,
        "image_coverage": round(image_coverage, 4),
    }
    if characters >= 80 and image_coverage < 0.8:
        return RouteDecision(AssetKind.DIGITAL_PDF, 0.98, "Selectable text dominates sample", metrics)
    return RouteDecision(AssetKind.SCANNED_PDF, 0.75, "Insufficient native text or image-heavy pages", metrics)


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
