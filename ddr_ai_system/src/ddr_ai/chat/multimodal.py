from __future__ import annotations

import io
import json
import math
from collections import Counter
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.assets import resolve_asset_path
from ddr_ai.chat.contracts import PlotImageContext
from ddr_ai.db.models import Plot, PlotPoint, SourceDocument
from ddr_ai.services.asset_storage import load_persisted_asset


class PlotContextError(ValueError):
    """Safe selected-plot loading error."""


def _load_candidate_bytes(
    session: Session,
    document: SourceDocument,
    plot: Plot,
    selection: str,
) -> bytes:
    if selection == "source":
        persisted = load_persisted_asset(session, document.id)
        if persisted is not None:
            return persisted
        stored_path = document.source_path
    elif selection == "overlay":
        stored_path = plot.overlay_path
    else:
        raise PlotContextError("Unsupported plot image selection.")
    resolved = resolve_asset_path(stored_path)
    if resolved is None:
        raise PlotContextError("The selected plot image is unavailable in this deployment.")
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise PlotContextError("The selected plot image could not be read.") from exc


def _normalized_image(
    content: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
) -> tuple[bytes, str]:
    if not content:
        raise PlotContextError("The selected plot image is empty.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > max_pixels * 4:
                raise PlotContextError("The selected plot image exceeds the safe pixel limit.")
            image.load()
            normalized = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PlotContextError("The selected asset is not a valid bounded image.") from exc
    if width * height > max_pixels:
        scale = math.sqrt(max_pixels / (width * height))
        normalized.thumbnail((max(1, int(width * scale)), max(1, int(height * scale))))
    for quality in (90, 82, 72, 60):
        output = io.BytesIO()
        normalized.save(output, format="JPEG", quality=quality, optimize=True)
        result = output.getvalue()
        if len(result) <= max_bytes:
            return result, "image/jpeg"
    raise PlotContextError("The selected plot image cannot be reduced to the configured byte limit.")


def load_plot_image_context(
    session: Session,
    plot_id: int,
    *,
    selection: str = "source",
    max_image_mb: int = 4,
    max_pixels: int = 12_000_000,
) -> PlotImageContext:
    row = session.execute(
        select(Plot, SourceDocument)
        .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
        .where(Plot.id == plot_id)
    ).first()
    if row is None:
        raise PlotContextError("The selected plot was not found.")
    plot, document = row
    points = list(
        session.scalars(
            select(PlotPoint).where(PlotPoint.plot_id == plot.id).order_by(PlotPoint.point_index)
        )
    )
    content = _load_candidate_bytes(session, document, plot, selection)
    image_bytes, mime_type = _normalized_image(
        content,
        max_bytes=max_image_mb * 1024 * 1024,
        max_pixels=max_pixels,
    )
    bands = Counter(
        item.band_classification for item in points if item.band_classification is not None
    )
    dated = [item for item in points if item.observed_date and item.y_value is not None]
    dated.sort(key=lambda item: item.observed_date)
    trend: dict[str, Any] = {
        "series": sorted({item.series_identifier for item in points}),
    }
    if dated:
        first, last = dated[0], dated[-1]
        delta = float(last.y_value or 0) - float(first.y_value or 0)
        trend.update(
            {
                "date_start": first.observed_date.isoformat(),
                "date_end": last.observed_date.isoformat(),
                "stored_value_direction": "increasing"
                if delta > 0
                else "decreasing"
                if delta < 0
                else "stable",
            }
        )
    return PlotImageContext(
        plot_id=plot.id,
        source_document_id=document.id,
        plot_identifier=plot.plot_identifier,
        plot_type=plot.plot_type,
        source_filename=document.file_name,
        image_selection=selection,
        mime_type=mime_type,
        image_bytes=image_bytes,
        point_count=len(points),
        calibration_facts=plot.calibration_json,
        band_counts=dict(sorted(bands.items())),
        trend_facts=trend,
        unit_status=plot.unit_status,
        x_unit=plot.x_unit,
        y_unit=plot.y_unit,
        warnings=plot.warnings_json,
        allowed_citation={
            "file_name": document.file_name,
            "plot_identifier": plot.plot_identifier,
            "source_type": "selected_plot",
        },
    )


def deterministic_plot_description(context: PlotImageContext, *, language: str) -> str:
    facts = context.deterministic_facts()
    if language == "az":
        unit = context.y_unit if context.y_unit else "naməlum"
        return (
            f"Seçilmiş {context.plot_identifier} ({context.plot_type}) qrafikində "
            f"{context.point_count} saxlanmış nöqtə var. Vahid statusu {context.unit_status}, "
            f"y vahidi {unit}-dur. Deterministik faktlar: "
            f"{json.dumps(facts, ensure_ascii=False, default=str)}"
        )
    unit = context.y_unit or "unknown"
    return (
        f"Selected {context.plot_identifier} ({context.plot_type}) contains "
        f"{context.point_count} stored points. Unit status is {context.unit_status}; "
        f"the y unit is {unit}. Deterministic facts: "
        f"{json.dumps(facts, ensure_ascii=False, default=str)}"
    )


def vlm_prompt(context: PlotImageContext, *, question: str) -> str:
    return (
        "Describe only qualitative visual features of this user-selected drilling plot. "
        "You may describe visible layout, relative direction, clustering, curve shape, legend, "
        "qualitative changes, and image-quality limitations. Do not introduce numeric values, "
        "units, well mappings, operational/geological causes, confirmed anomalies, thresholds, "
        "or recommendations. Preserve unknown units as unknown.\n\n"
        f"QUESTION: {question}\n"
        f"SELECTED_PLOT_FACTS: {json.dumps(context.deterministic_facts(), default=str)}\n"
        f"ALLOWED_CITATION: {json.dumps(context.allowed_citation)}"
    )
