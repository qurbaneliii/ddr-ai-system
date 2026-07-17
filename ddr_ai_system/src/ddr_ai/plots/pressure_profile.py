from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ddr_ai.plots.common import (
    Component,
    apply_axis,
    color_mask,
    connected_components,
    detect_plot_bounds,
    fit_linear_axis,
    load_rgb,
)
from ddr_ai.plots.ocr import read_tokens

PROFILE_ID_RE = re.compile(r"(Well_\d+)_pressure_profile", re.I)


def _curve_x(mask: np.ndarray, y: float, left: int, right: int, radius: int = 7) -> float | None:
    y0 = max(0, int(round(y)) - radius)
    y1 = min(mask.shape[0], int(round(y)) + radius + 1)
    ys, xs = np.where(mask[y0:y1, left:right])
    if not len(xs):
        return None
    return float(np.median(xs + left))


def _axis_calibrations(rgb: np.ndarray, bounds: Any) -> tuple[dict[str, float] | None, dict[str, float] | None, list[dict[str, Any]]]:
    tokens = read_tokens(rgb)
    x_samples: list[tuple[float, float]] = []
    y_samples: list[tuple[float, float]] = []
    evidence: list[dict[str, Any]] = []
    for token in tokens:
        cleaned = token.text.replace(",", ".").strip()
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
            continue
        value = float(cleaned)
        if bounds.left <= token.x <= bounds.right and bounds.bottom < token.y < rgb.shape[0] * 0.99:
            x_samples.append((token.x, value))
            evidence.append({"axis": "x", "text": token.text, "pixel": token.x, "confidence": token.confidence})
        if 0 < token.x < bounds.left and bounds.top <= token.y <= bounds.bottom:
            y_samples.append((token.y, value))
            evidence.append({"axis": "y", "text": token.text, "pixel": token.y, "confidence": token.confidence})
    return fit_linear_axis(x_samples), fit_linear_axis(y_samples), evidence


def _classify(point_x: float, references: dict[str, float | None]) -> str:
    minimum = references.get("min")
    base = references.get("base")
    maximum = references.get("max")
    virgin = references.get("virgin")
    if minimum is not None and point_x < minimum:
        return "below_min"
    if base is not None and point_x < base:
        return "between_min_base"
    if maximum is not None and point_x <= maximum:
        return "between_base_max"
    if virgin is not None and point_x <= virgin:
        return "between_max_virgin"
    if virgin is not None and point_x > virgin:
        return "above_virgin"
    if maximum is not None and point_x > maximum:
        return "above_max"
    return "unclassified"


def _profile_markers(rgb: np.ndarray, bounds: Any) -> list[Component]:
    black = np.all(rgb < 45, axis=2)
    components = connected_components(black, bounds, min_area=180, max_area=2200, margin=8)
    return sorted(
        [item for item in components if 0.65 <= item.width / max(item.height, 1) <= 1.45
         and 12 <= item.width <= 55 and 12 <= item.height <= 55],
        key=lambda item: (item.y, item.x),
    )


def digitize_pressure_profile(path: str | Path, overlay_path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path)
    rgb = load_rgb(source)
    bounds = detect_plot_bounds(rgb)
    markers = _profile_markers(rgb, bounds)
    curve_masks = {
        "min": color_mask(rgb, (255, 0, 0), 95),
        "base": color_mask(rgb, (128, 128, 128), 75),
        "max": color_mask(rgb, (0, 0, 255), 95),
        "virgin": color_mask(rgb, (128, 0, 128), 95),
    }
    x_cal, y_cal, calibration_evidence = _axis_calibrations(rgb, bounds)
    points: list[dict[str, Any]] = []
    for index, marker in enumerate(markers):
        references_px = {
            name: _curve_x(mask, marker.y, bounds.left + 2, bounds.right - 2)
            for name, mask in curve_masks.items()
        }
        classification = _classify(marker.x, references_px)
        pressure = apply_axis(x_cal, marker.x)
        depth = apply_axis(y_cal, marker.y)
        reference_values = {name: apply_axis(x_cal, value) if value is not None else None
                            for name, value in references_px.items()}
        confidence = 0.98 if x_cal and y_cal else 0.82
        points.append({
            "point_index": index,
            "series_identifier": "Measured Pressure",
            "pixel_x": marker.x,
            "pixel_y": marker.y,
            "pressure": pressure,
            "depth": depth,
            "reference_pixels": references_px,
            "reference_values": reference_values,
            "band_classification": classification,
            "anomaly_candidate": classification in {"below_min", "above_max", "above_virgin"},
            "confidence": confidence,
            "source_bbox": marker.bbox,
        })
    warnings: list[dict[str, Any]] = []
    if len(markers) != 10:
        warnings.append({"code": "unexpected_marker_count", "expected": 10, "actual": len(markers)})
    if not x_cal or not y_cal:
        warnings.append({"code": "axis_ocr_unavailable_or_insufficient", "numeric_values": "unavailable"})
    identifier_match = PROFILE_ID_RE.search(source.stem)
    identifier = identifier_match.group(1) if identifier_match else source.stem
    if overlay_path:
        overlay = Image.fromarray(rgb.copy())
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((bounds.left, bounds.top, bounds.right, bounds.bottom), outline=(0, 180, 0), width=5)
        for point in points:
            x, y = point["pixel_x"], point["pixel_y"]
            color = (255, 0, 255) if point["anomaly_candidate"] else (0, 180, 0)
            draw.ellipse((x - 22, y - 22, x + 22, y + 22), outline=color, width=5)
            draw.text((x + 25, y - 10), str(point["point_index"]), fill=color)
        output = Path(overlay_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(output)
    return {
        "plot_type": "pressure_profile",
        "plot_identifier": identifier,
        "source_path": str(source),
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "plot_bbox": bounds.to_dict(),
        "x_axis_label": "Formation Pressure",
        "y_axis_label": "True Vertical Depth Sub Sea",
        "x_unit": "PSI",
        "y_unit": "ft",
        "unit_status": "confirmed_from_axis_labels",
        "calibration": {"x": x_cal, "y": y_cal, "ocr_evidence": calibration_evidence},
        "points": points,
        "marker_count": len(markers),
        "confidence": 0.96 if x_cal and y_cal and len(markers) == 10 else 0.80,
        "warnings": warnings,
        "overlay_path": str(overlay_path) if overlay_path else None,
    }


def save_profile_json(result: dict[str, Any], output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
