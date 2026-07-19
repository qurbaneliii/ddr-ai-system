from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
