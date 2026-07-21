from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ddr_ai.db.models import Anomaly, ModelRun, Operation, Report

ANOMALY_MODEL_VERSION = "isolation-forest-duration-v1"


@dataclass(frozen=True, slots=True)
class DurationAnomalyConfig:
    model_version: str = ANOMALY_MODEL_VERSION
    minimum_group_size: int = 30
    contamination: float = 0.02
    robust_z_threshold: float = 3.5
    random_state: int = 42


def _candidate_key(model_version: str, operation_id: int) -> str:
    return hashlib.sha256(f"{model_version}:operation:{operation_id}".encode()).hexdigest()


def _robust_values(values: np.ndarray) -> tuple[float, float, np.ndarray]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = max(mad * 1.4826, 1e-6)
    return median, mad, (values - median) / scale


def _severity(robust_z: float) -> str:
    magnitude = abs(robust_z)
    if magnitude >= 8:
        return "high"
    if magnitude >= 5:
        return "medium"
    return "low"


def generate_duration_anomalies(
    session: Session,
    *,
    config: DurationAnomalyConfig | None = None,
    dry_run: bool = False,
    rebuild: bool = False,
) -> dict[str, Any]:
    active = config or DurationAnomalyConfig()
    rows = list(
        session.execute(
            select(Operation, Report)
            .join(Report, Report.id == Operation.report_id)
            .where(
                Operation.duration_hours.is_not(None),
                Operation.main_activity_normalized.is_not(None),
            )
            .order_by(Operation.id)
        )
    )
    pair_support = Counter(
        (operation.main_activity_normalized, operation.sub_activity_normalized)
        for operation, _ in rows
    )
    groups: dict[tuple[str, str], list[tuple[Operation, Report]]] = defaultdict(list)
    for operation, report in rows:
        pair = (operation.main_activity_normalized or "unknown", operation.sub_activity_normalized or "unknown")
        group_key = pair if pair_support[pair] >= active.minimum_group_size else (pair[0], "*")
        groups[group_key].append((operation, report))

    if rebuild and not dry_run:
        session.execute(
            delete(Anomaly).where(
                Anomaly.detector_type == "ml",
                Anomaly.model_version == active.model_version,
            )
        )
        session.flush()
    existing = set(
        session.scalars(
            select(Anomaly.candidate_key).where(
                Anomaly.detector_type == "ml",
                Anomaly.model_version == active.model_version,
                Anomaly.candidate_key.is_not(None),
            )
        )
    )
    rule_operation_ids = set(
        session.scalars(
            select(Anomaly.source_record_id).where(
                Anomaly.source_record_type == "operation",
                Anomaly.detector_type != "ml",
                Anomaly.source_record_id.is_not(None),
            )
        )
    )
    candidates: list[dict[str, Any]] = []
    excluded_groups: dict[str, int] = {}
    score_values: list[float] = []
    fingerprint_rows: list[str] = []
    for group_key, group_rows in sorted(groups.items()):
        if len(group_rows) < active.minimum_group_size:
            excluded_groups["/".join(group_key)] = len(group_rows)
            continue
        durations = np.asarray(
            [float(item.duration_hours or 0.0) for item, _ in group_rows]
        ).reshape(-1, 1)
        median, mad, robust_z = _robust_values(durations[:, 0])
        model = IsolationForest(
            contamination=active.contamination,
            random_state=active.random_state,
            n_estimators=200,
        )
        model.fit(robust_z.reshape(-1, 1))
        raw_scores = -model.decision_function(robust_z.reshape(-1, 1))
        flags = model.predict(robust_z.reshape(-1, 1))
        q1, q3 = (float(value) for value in np.percentile(durations[:, 0], [25, 75]))
        iqr = q3 - q1
        for index, (operation, report) in enumerate(group_rows):
            fingerprint_rows.append(
                f"{operation.id}|{group_key}|{float(operation.duration_hours or 0):.6f}"
            )
            score_values.append(float(raw_scores[index]))
            if flags[index] != -1 or abs(float(robust_z[index])) < active.robust_z_threshold:
                continue
            key = _candidate_key(active.model_version, operation.id)
            evidence = {
                "operation_id": operation.id,
                "wellbore": report.wellbore,
                "period_end": report.period_end.isoformat() if report.period_end else None,
                "main_activity": operation.main_activity_normalized,
                "sub_activity": operation.sub_activity_normalized,
                "duration_hours": operation.duration_hours,
                "group": {"main": group_key[0], "sub": group_key[1]},
                "group_size": len(group_rows),
                "group_statistics": {
                    "median_hours": median,
                    "mad_hours": mad,
                    "q1_hours": q1,
                    "q3_hours": q3,
                    "iqr_hours": iqr,
                },
                "raw_score": float(raw_scores[index]),
                "robust_z": float(robust_z[index]),
                "overlaps_rule_candidate": operation.id in rule_operation_ids,
            }
            candidates.append(
                {
                    "candidate_key": key,
                    "operation": operation,
                    "report": report,
                    "score": float(raw_scores[index]),
                    "robust_z": float(robust_z[index]),
                    "evidence": evidence,
                }
            )
            if not dry_run and key not in existing:
                session.add(
                    Anomaly(
                        source_document_id=report.source_document_id,
                        source_record_type="operation",
                        source_record_id=operation.id,
                        category="unusual_operation_duration",
                        rule_or_model="isolation_forest_duration",
                        evidence_json=evidence,
                        score=float(raw_scores[index]),
                        severity_heuristic=_severity(float(robust_z[index])),
                        confidence=min(0.99, 0.70 + min(abs(float(robust_z[index])), 10) / 40),
                        threshold_json={
                            "isolation_forest_contamination": active.contamination,
                            "robust_z_minimum": active.robust_z_threshold,
                        },
                        validation_status="unreviewed",
                        domain_validated=False,
                        explanation=(
                            "Operation duration is unusual within its canonical activity group by "
                            "both deterministic robust scaling and Isolation Forest; candidate only."
                        ),
                        detector_type="ml",
                        model_version=active.model_version,
                        candidate_key=key,
                    )
                )
                existing.add(key)
    session.flush()
    fingerprint = hashlib.sha256("\n".join(fingerprint_rows).encode()).hexdigest()
    persisted_count = len(
        session.scalars(
            select(Anomaly.id).where(
                Anomaly.detector_type == "ml",
                Anomaly.model_version == active.model_version,
            )
        ).all()
    )
    overlap = sum(bool(item["evidence"]["overlaps_rule_candidate"]) for item in candidates)
    metrics = {
        "eligible_operations": len(fingerprint_rows),
        "excluded_small_groups": excluded_groups,
        "candidate_count": len(candidates),
        "candidate_rate": len(candidates) / max(len(fingerprint_rows), 1),
        "persisted_candidate_count": persisted_count,
        "overlap_with_rule_candidates": overlap,
        "score_distribution": {
            "min": min(score_values) if score_values else None,
            "median": float(np.median(score_values)) if score_values else None,
            "max": max(score_values) if score_values else None,
        },
        "candidates_by_activity": dict(
            sorted(Counter(item["evidence"]["main_activity"] for item in candidates).items())
        ),
    }
    if not dry_run:
        session.execute(
            update(ModelRun)
            .where(ModelRun.model_type == "duration_anomaly")
            .values(is_active=False)
        )
        record = session.scalar(
            select(ModelRun).where(
                ModelRun.model_type == "duration_anomaly",
                ModelRun.model_version == active.model_version,
            )
        )
        values = {
            "training_data_sha256": fingerprint,
            "parameters_json": asdict(active),
            "metrics_json": metrics,
            "is_active": True,
        }
        if record is None:
            session.add(
                ModelRun(
                    model_type="duration_anomaly",
                    model_version=active.model_version,
                    artifact_sha256=None,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(record, key, value)
    return {
        "model_version": active.model_version,
        "data_fingerprint": fingerprint,
        "parameters": asdict(active),
        "actual_metrics": metrics,
        "candidate_keys": sorted(item["candidate_key"] for item in candidates),
        "dry_run": dry_run,
    }
