from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ddr_ai.db.models import Anomaly, Base
from ddr_ai.services.anomaly_reviews import add_anomaly_review, review_history


def _session() -> tuple[Session, Anomaly]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    anomaly = Anomaly(
        source_record_type="operation",
        source_record_id=1,
        category="test_candidate",
        rule_or_model="test_rule",
        evidence_json={"source": "fixture"},
        severity_heuristic="low",
        confidence=0.8,
        explanation="Candidate only.",
        detector_type="rule",
    )
    session.add(anomaly)
    session.flush()
    return session, anomaly


def test_review_history_is_append_only_and_effective_status_is_latest() -> None:
    session, anomaly = _session()
    add_anomaly_review(
        session,
        anomaly.id,
        decision="needs_more_evidence",
        reviewer="Reviewer A",
        note="Need source page.",
    )
    add_anomaly_review(
        session,
        anomaly.id,
        decision="confirmed",
        reviewer="Reviewer B",
        note="Source page reviewed.",
    )
    add_anomaly_review(
        session,
        anomaly.id,
        decision="rejected",
        reviewer="Reviewer C",
    )

    history = review_history(session, anomaly.id)
    assert [item.decision for item in history] == [
        "needs_more_evidence",
        "confirmed",
        "rejected",
    ]
    assert history[-1].note is None
    assert anomaly.validation_status == "rejected"
    assert anomaly.domain_validated is False


def test_empty_reviewer_and_invalid_decision_are_rejected() -> None:
    session, anomaly = _session()
    with pytest.raises(ValueError, match="Reviewer"):
        add_anomaly_review(session, anomaly.id, decision="confirmed", reviewer=" ")
    with pytest.raises(ValueError, match="Unsupported"):
        add_anomaly_review(session, anomaly.id, decision="auto_confirmed", reviewer="A")
    assert review_history(session, anomaly.id) == []
