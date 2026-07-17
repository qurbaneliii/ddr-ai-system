from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ddr_ai.db.models import Report, ReportSection, SourceDocument


@dataclass(frozen=True, slots=True)
class SearchHit:
    section_id: int
    report_id: int
    file_name: str
    wellbore: str | None
    period_end: str | None
    page_number: int
    section_type: str
    text: str
    score: float


def _terms(query: str) -> list[str]:
    return [token for token in re.findall(r"[\wÆØÅæøå]{3,}", query.casefold()) if token]


def lexical_search(session: Session, query: str, limit: int = 10) -> list[SearchHit]:
    terms = _terms(query)
    if not terms:
        return []
    predicates = [ReportSection.text.ilike(f"%{term}%") for term in terms]
    statement = (
        select(ReportSection, Report, SourceDocument)
        .join(Report, Report.id == ReportSection.report_id)
        .join(SourceDocument, SourceDocument.id == Report.source_document_id)
        .where(or_(*predicates))
        .limit(max(limit * 5, limit))
    )
    scored: list[SearchHit] = []
    for section, report, document in session.execute(statement):
        text = section.text.casefold()
        score = sum(text.count(term) for term in terms) / max(len(terms), 1)
        scored.append(SearchHit(
            section_id=section.id, report_id=report.id, file_name=document.file_name,
            wellbore=report.wellbore, period_end=report.period_end.isoformat() if report.period_end else None,
            page_number=section.page_number, section_type=section.section_type,
            text=section.text, score=float(score),
        ))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

