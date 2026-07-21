from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.db.models import Anomaly, AnomalyReview
from ddr_ai.retrieval.corpus import replace_document_chunks

REVIEW_DECISIONS = frozenset({"confirmed", "rejected", "needs_more_evidence"})


def add_anomaly_review(
    session: Session,
    anomaly_id: int,
    *,
    decision: str,
    reviewer: str,
    note: str | None = None,
) -> AnomalyReview:
    normalized_decision = decision.casefold().strip()
    normalized_reviewer = reviewer.strip()
    normalized_note = (note or "").strip() or None
    if normalized_decision not in REVIEW_DECISIONS:
        raise ValueError("Unsupported anomaly-review decision.")
    if not normalized_reviewer:
        raise ValueError("Reviewer is required.")
    anomaly = session.scalar(select(Anomaly).where(Anomaly.id == anomaly_id))
    if anomaly is None:
        raise LookupError(f"Anomaly {anomaly_id} was not found.")
    review = AnomalyReview(
        anomaly_id=anomaly.id,
        decision=normalized_decision,
        reviewer=normalized_reviewer,
        note=normalized_note,
    )
    session.add(review)
    anomaly.validation_status = normalized_decision
    anomaly.domain_validated = normalized_decision == "confirmed"
    session.flush()
    if anomaly.source_document_id is not None:
        replace_document_chunks(session, anomaly.source_document_id)
    return review


def review_history(session: Session, anomaly_id: int) -> list[AnomalyReview]:
    return list(
        session.scalars(
            select(AnomalyReview)
            .where(AnomalyReview.anomaly_id == anomaly_id)
            .order_by(AnomalyReview.created_at, AnomalyReview.id)
        )
    )
