from __future__ import annotations

import re
from datetime import date
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

SERIES_COLORS = {
    "Well_01": (31, 119, 180),
    "Well_02": (255, 127, 14),
    "Well_03": (44, 160, 44),
    "Well_04": (214, 39, 40),
}
DATE_RE = re.compile(r"(20\d{2})[-/.](0?[1-9]|1[0-2])")


def _axis_calibrations(rgb: np.ndarray, bounds: Any) -> tuple[dict[str, float] | None, dict[str, float] | None, list[dict[str, Any]]]:
    tokens = read_tokens(rgb)
    x_samples: list[tuple[float, float]] = []
    y_samples: list[tuple[float, float]] = []
    evidence: list[dict[str, Any]] = []
    for token in tokens:
        date_match = DATE_RE.search(token.text.replace(" ", ""))
        if date_match and bounds.left <= token.x <= bounds.right and token.y > bounds.bottom:
            ordinal_value = date(int(date_match.group(1)), int(date_match.group(2)), 1).toordinal()
            x_samples.append((token.x, float(ordinal_value)))
            evidence.append({"axis": "x", "text": token.text, "pixel": token.x, "confidence": token.confidence})
            continue
        cleaned = token.text.replace(",", "").strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned) and token.x < bounds.left and bounds.top <= token.y <= bounds.bottom:
            numeric_value = float(cleaned)
            if 100 <= numeric_value <= 100_000:
                y_samples.append((token.y, numeric_value))
                evidence.append({"axis": "y", "text": token.text, "pixel": token.y, "confidence": token.confidence})
    return fit_linear_axis(x_samples), fit_linear_axis(y_samples), evidence


def _find_components(rgb: np.ndarray, bounds: Any) -> dict[str, list[Component]]:
    result: dict[str, list[Component]] = {}
    image_area = rgb.shape[0] * rgb.shape[1]
    scale = image_area / (2700 * 1500)
    for series, color in SERIES_COLORS.items():
        mask = color_mask(rgb, color, 85)
        components = connected_components(
            mask, bounds, min_area=max(80, int(250 * scale)),
            max_area=max(2000, int(5000 * scale)), margin=8,
        )
        result[series] = [item for item in components if 0.55 <= item.width / max(item.height, 1) <= 1.8]
    return result


def _detect_legend(components: dict[str, list[Component]], bounds: Any) -> tuple[dict[str, Component], dict[str, float] | None]:
    candidates = [(series, item) for series, items in components.items() for item in items]
    best: list[tuple[str, Component]] = []
    for _, anchor in candidates:
        cluster: list[tuple[str, Component]] = []
        used: set[str] = set()
        for series, item in candidates:
            if series not in used and abs(item.x - anchor.x) <= max(12, bounds.width * 0.008):
                cluster.append((series, item))
                used.add(series)
        if len(cluster) > len(best):
            best = cluster
    if len(best) < 3:
        return {}, None
    ys = sorted(item.y for _, item in best)
    gaps = np.diff(ys)
    if len(gaps) and np.std(gaps) > max(12, float(np.mean(gaps)) * 0.4):
        return {}, None
    legend = {series: item for series, item in best}
    return legend, {
        "x0": min(item.x - item.width for item in legend.values()),
        "x1": max(item.x + item.width for item in legend.values()),
        "y0": min(item.y - item.height for item in legend.values()),
        "y1": max(item.y + item.height for item in legend.values()),
    }


def digitize_pressure_time(path: str | Path, overlay_path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path)
    rgb = load_rgb(source)
    bounds = detect_plot_bounds(rgb)
    components = _find_components(rgb, bounds)
    legend, legend_bbox = _detect_legend(components, bounds)
    x_cal, y_cal, evidence = _axis_calibrations(rgb, bounds)
    points: list[dict[str, Any]] = []
    index = 0
    for series, items in components.items():
        for item in sorted(items, key=lambda value: (value.x, value.y)):
            legend_item = legend.get(series)
            if legend_item and abs(item.x - legend_item.x) < 2 and abs(item.y - legend_item.y) < 2:
                continue
            ordinal = apply_axis(x_cal, item.x)
            observed_date = date.fromordinal(round(ordinal)).isoformat() if ordinal else None
            points.append({
                "point_index": index,
                "series_identifier": series,
                "pixel_x": item.x,
                "pixel_y": item.y,
                "observed_date": observed_date,
                "pressure": apply_axis(y_cal, item.y),
                "pressure_unit": None,
                "unit_status": "unknown",
                "confidence": 0.96 if x_cal and y_cal else 0.80,
                "source_bbox": item.bbox,
            })
            index += 1
    warnings: list[dict[str, Any]] = [{
        "code": "pressure_unit_unresolved",
        "message": "The source y-axis does not state a pressure unit.",
    }]
    if len(legend) < 4:
        warnings.append({"code": "legend_detection_uncertain", "detected_series": sorted(legend)})
    if not x_cal or not y_cal:
        warnings.append({"code": "axis_ocr_unavailable_or_insufficient", "numeric_values": "unavailable"})
    if overlay_path:
        overlay = Image.fromarray(rgb.copy())
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((bounds.left, bounds.top, bounds.right, bounds.bottom), outline=(0, 180, 0), width=5)
        if legend_bbox:
            draw.rectangle(tuple(legend_bbox[key] for key in ("x0", "y0", "x1", "y1")),
                           outline=(255, 0, 255), width=5)
        for point in points:
            x, y = point["pixel_x"], point["pixel_y"]
            draw.ellipse((x - 20, y - 20, x + 20, y + 20), outline=(0, 0, 0), width=4)
        output = Path(overlay_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(output)
    counts = {series: sum(point["series_identifier"] == series for point in points) for series in SERIES_COLORS}
    return {
        "plot_type": "pressure_time",
        "plot_identifier": source.stem,
        "source_path": str(source),
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "plot_bbox": bounds.to_dict(),
        "legend_bbox": legend_bbox,
        "legend_series_detected": sorted(legend),
        "legend_markers_excluded": len(legend),
        "x_axis_label": "DATE",
        "y_axis_label": "Pressure",
        "x_unit": "date",
        "y_unit": None,
        "unit_status": "unknown",
        "calibration": {"x": x_cal, "y": y_cal, "ocr_evidence": evidence},
        "points": points,
        "point_count": len(points),
        "series_counts": counts,
        "confidence": 0.95 if x_cal and y_cal and len(legend) == 4 else 0.79,
        "warnings": warnings,
        "overlay_path": str(overlay_path) if overlay_path else None,
    }
