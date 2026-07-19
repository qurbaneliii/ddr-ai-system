from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ddr_ai.chat.query import QueryAnalyzer
from ddr_ai.nlp.providers import LexicalFallbackProvider
from ddr_ai.retrieval.corpus import CorpusRetriever


@dataclass(frozen=True, slots=True)
class SearchHit:
    source_type: str
    source_record_id: int | None
    report_id: int | None
    file_name: str
    wellbore: str | None
    period_end: str | None
    page_number: int | None
    section_type: str | None
    text: str
    score: float


def lexical_search(session: Session, query: str, limit: int = 10) -> list[SearchHit]:
    """Compatibility wrapper over multi-source TF-IDF/character retrieval."""

    plan = QueryAnalyzer().analyze(
        query,
        "Auto",
        LexicalFallbackProvider("Deterministic corpus retrieval."),
    )
    plan.limit = max(1, min(limit, 20))
    hits, _ = CorpusRetriever().search(session, plan)
    return [
        SearchHit(
            source_type=item.source_type,
            source_record_id=item.source_record_id,
            report_id=item.report_id,
            file_name=item.file_name,
            wellbore=item.wellbore,
            period_end=item.report_date,
            page_number=item.page_number,
            section_type=item.section_type,
            text=item.text,
            score=item.score,
        )
        for item in hits
    ]
