from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PlotImageContext:
    plot_id: int
    source_document_id: int
    plot_identifier: str
    plot_type: str
    source_filename: str
    image_selection: str
    mime_type: str
    image_bytes: bytes = field(repr=False)
    point_count: int = 0
    calibration_facts: dict[str, Any] = field(default_factory=dict)
    band_counts: dict[str, int] = field(default_factory=dict)
    trend_facts: dict[str, Any] = field(default_factory=dict)
    unit_status: str = "unknown"
    x_unit: str | None = None
    y_unit: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    allowed_citation: dict[str, Any] = field(default_factory=dict)

    def deterministic_facts(self) -> dict[str, Any]:
        return {
            "plot_id": self.plot_id,
            "plot_identifier": self.plot_identifier,
            "plot_type": self.plot_type,
            "source_filename": self.source_filename,
            "image_selection": self.image_selection,
            "point_count": self.point_count,
            "calibration": self.calibration_facts,
            "band_counts": self.band_counts,
            "trend_facts": self.trend_facts,
            "unit_status": self.unit_status,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class ChatAnswer:
    answer: str
    route: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    data_scope: str = "processed DDR corpus"
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    sql: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    export_filename: str | None = None
    provider: str = "Lexical fallback"
    model: str | None = None
    detected_language: str = "en"
    selected_language: str = "en"
    retrieval_query: str | None = None
    fallback_reason: str | None = None
    model_metrics: dict[str, Any] = field(default_factory=dict)
    answer_type: str = "deterministic"
    evidence_hit_count: int = 0
    retrieval_source_types: list[str] = field(default_factory=list)
    corpus_status: str = "ready"
    rewritten_query: str | None = None
    query_plan: dict[str, Any] = field(default_factory=dict)
    retrieval_diagnostics: dict[str, Any] = field(default_factory=dict)
    selected_plot_identifier: str | None = None
    visual_analysis_used: bool = False
    visual_provider: str | None = None
    visual_model: str | None = None
    visual_validation_status: str = "not_requested"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
