from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.analytics.events import (
    CANONICAL_MAIN_ACTIVITIES,
    normalize_activity_result,
)
from ddr_ai.config import PROJECT_ROOT
from ddr_ai.db.models import Operation
from ddr_ai.models.schemas import ParsedReport

ACTIVITY_MODEL_VERSION = "activity-tfidf-logreg-v1"
DEFAULT_ACTIVITY_MODEL_PATH = PROJECT_ROOT / "data/models/activity_classifier.joblib"
DEFAULT_ACTIVITY_METADATA_PATH = PROJECT_ROOT / "data/models/activity_classifier.metadata.json"
RANDOM_STATE = 42
MIN_SUBACTIVITY_SUPPORT = 20
MAIN_MIN_MACRO_F1 = 0.50
SUB_MIN_MACRO_F1 = 0.25
DEFAULT_THRESHOLDS = {"main": 0.55, "sub": 0.40}

LabelKind = Literal["main", "sub"]


@dataclass(frozen=True, slots=True)
class ActivityPrediction:
    label: str
    confidence: float
    model_version: str


class ActivityPredictor(Protocol):
    model_version: str

    def predict(self, kind: LabelKind, remark: str) -> ActivityPrediction: ...


@dataclass(frozen=True, slots=True)
class OperationClassification:
    main_activity: str
    sub_activity: str
    method: str
    confidence: float
    model_version: str | None
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ActivityTrainingDataset:
    texts: list[str]
    main_labels: list[str]
    sub_labels: list[str]
    report_groups: list[int]
    operation_ids: list[int]
    fingerprint: str
    source_rows: int
    deduplicated_rows: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_remark(value: str) -> str:
    return " ".join(value.casefold().split())


def build_training_dataset(session: Session) -> ActivityTrainingDataset:
    rows = list(
        session.execute(
            select(
                Operation.id,
                Operation.report_id,
                Operation.remark,
                Operation.main_activity_raw,
                Operation.sub_activity_raw,
            ).order_by(Operation.id)
        )
    )
    grouped: dict[str, list[tuple[int, int, str, str, str]]] = defaultdict(list)
    for operation_id, report_id, remark, main_raw, sub_raw in rows:
        text = str(remark or "").strip()
        if not text:
            continue
        main, sub = normalize_activity_result(main_raw, sub_raw)
        if main.method == "unknown" or sub.method == "unknown":
            continue
        grouped[_normalized_remark(text)].append(
            (operation_id, report_id, text, main.canonical_label, sub.canonical_label)
        )

    selected: list[tuple[int, int, str, str, str]] = []
    for candidates in grouped.values():
        pair_counts = Counter((item[3], item[4]) for item in candidates)
        winning_pair = sorted(pair_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        selected.append(next(item for item in candidates if (item[3], item[4]) == winning_pair))
    selected.sort(key=lambda item: item[0])
    fingerprint_source = "\n".join(
        f"{item[0]}|{item[1]}|{_normalized_remark(item[2])}|{item[3]}|{item[4]}"
        for item in selected
    )
    return ActivityTrainingDataset(
        texts=[item[2] for item in selected],
        main_labels=[item[3] for item in selected],
        sub_labels=[item[4] for item in selected],
        report_groups=[item[1] for item in selected],
        operation_ids=[item[0] for item in selected],
        fingerprint=hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        source_rows=len(rows),
        deduplicated_rows=len(selected),
    )


def grouped_train_test_indices(
    labels: list[str], groups: list[int], *, random_state: int = RANDOM_STATE
) -> tuple[np.ndarray, np.ndarray]:
    label_array = np.asarray(labels)
    group_array = np.asarray(groups)
    try:
        splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=random_state)
        train, test = next(splitter.split(np.zeros(len(labels)), label_array, group_array))
    except ValueError:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=random_state)
        train, test = next(splitter.split(np.zeros(len(labels)), label_array, group_array))
    if set(group_array[train]) & set(group_array[test]):
        raise RuntimeError("Report-group leakage detected in the activity split.")
    return np.asarray(train), np.asarray(test)


def build_pipeline(*, random_state: int = RANDOM_STATE) -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=12_000,
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    max_features=18_000,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    classifier = LogisticRegression(
        class_weight="balanced",
        max_iter=600,
        random_state=random_state,
        solver="lbfgs",
    )
    return Pipeline([("features", features), ("classifier", classifier)])


def _keyword_baseline(train_labels: list[str], test_texts: list[str], labels: set[str]) -> list[str]:
    most_common = Counter(train_labels).most_common(1)[0][0]
    ordered = sorted(labels, key=lambda value: (-len(value), value))
    predictions: list[str] = []
    for text in test_texts:
        normalized = _normalized_remark(text).replace("-", " ")
        match = next(
            (
                label
                for label in ordered
                if label.replace("_", " ") in normalized
            ),
            most_common,
        )
        predictions.append(match)
    return predictions


def _metrics(labels: list[str], predictions: list[str]) -> dict[str, Any]:
    report = classification_report(labels, predictions, output_dict=True, zero_division=0)
    vocabulary = sorted(set(labels) | set(predictions))
    matrix = confusion_matrix(labels, predictions, labels=vocabulary)
    confusions: list[dict[str, Any]] = []
    for row_index, actual in enumerate(vocabulary):
        for column_index, predicted in enumerate(vocabulary):
            count = int(matrix[row_index, column_index])
            if actual != predicted and count:
                confusions.append({"actual": actual, "predicted": predicted, "count": count})
    confusions.sort(key=lambda item: (-item["count"], item["actual"], item["predicted"]))
    per_class = {
        label: {
            "precision": float(report[label]["precision"]),
            "recall": float(report[label]["recall"]),
            "f1": float(report[label]["f1-score"]),
            "support": int(report[label]["support"]),
        }
        for label in vocabulary
        if label in report
    }
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_f1": float(report["macro avg"]["f1-score"]),
        "weighted_f1": float(report["weighted avg"]["f1-score"]),
        "per_class": per_class,
        "top_confusions": confusions[:20],
    }


def train_and_evaluate(dataset: ActivityTrainingDataset) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact: dict[str, Any] = {"model_version": ACTIVITY_MODEL_VERSION}
    metrics: dict[str, Any] = {}
    for kind, all_labels in (("main", dataset.main_labels), ("sub", dataset.sub_labels)):
        support = Counter(all_labels)
        eligible = (
            set(CANONICAL_MAIN_ACTIVITIES)
            if kind == "main"
            else {label for label, count in support.items() if count >= MIN_SUBACTIVITY_SUPPORT}
        )
        positions = [index for index, label in enumerate(all_labels) if label in eligible]
        texts = [dataset.texts[index] for index in positions]
        labels = [all_labels[index] for index in positions]
        groups = [dataset.report_groups[index] for index in positions]
        train_index, test_index = grouped_train_test_indices(labels, groups)
        train_texts = [texts[index] for index in train_index]
        test_texts = [texts[index] for index in test_index]
        train_labels = [labels[index] for index in train_index]
        test_labels = [labels[index] for index in test_index]
        model = build_pipeline()
        model.fit(train_texts, train_labels)
        predictions = [str(value) for value in model.predict(test_texts)]
        baseline = _keyword_baseline(train_labels, test_texts, set(labels))
        model_metrics = _metrics(test_labels, predictions)
        baseline_metrics = _metrics(test_labels, baseline)
        metrics[kind] = {
            "eligible_rows": len(positions),
            "train_rows": len(train_index),
            "test_rows": len(test_index),
            "eligible_classes": sorted(eligible),
            "excluded_rare_classes": sorted(set(all_labels) - eligible),
            "class_support": dict(sorted(support.items())),
            "model": model_metrics,
            "remark_keyword_baseline": baseline_metrics,
            "report_group_overlap": 0,
        }
        artifact[f"{kind}_model"] = model
    main_ok = (
        metrics["main"]["model"]["macro_f1"] >= MAIN_MIN_MACRO_F1
        and metrics["main"]["model"]["macro_f1"]
        > metrics["main"]["remark_keyword_baseline"]["macro_f1"]
    )
    sub_ok = (
        metrics["sub"]["model"]["macro_f1"] >= SUB_MIN_MACRO_F1
        and metrics["sub"]["model"]["macro_f1"]
        > metrics["sub"]["remark_keyword_baseline"]["macro_f1"]
    )
    metrics["promotion"] = {
        "promoted": bool(main_ok and sub_ok),
        "main_min_macro_f1": MAIN_MIN_MACRO_F1,
        "sub_min_macro_f1": SUB_MIN_MACRO_F1,
        "must_beat_remark_keyword_baseline": True,
        "main_passed": bool(main_ok),
        "sub_passed": bool(sub_ok),
    }
    return artifact, metrics


@dataclass(slots=True)
class ActivityClassifier(ActivityPredictor):
    artifact: dict[str, Any]
    metadata: dict[str, Any]

    @property
    def model_version(self) -> str:
        return str(self.artifact["model_version"])

    def predict(self, kind: LabelKind, remark: str) -> ActivityPrediction:
        model = self.artifact[f"{kind}_model"]
        probabilities = model.predict_proba([remark])[0]
        classes = model.named_steps["classifier"].classes_
        best = int(np.argmax(probabilities))
        confidence = float(probabilities[best])
        threshold = float(self.metadata.get("thresholds", DEFAULT_THRESHOLDS)[kind])
        label = str(classes[best]) if confidence >= threshold else "unknown"
        return ActivityPrediction(label, confidence, self.model_version)


def load_activity_classifier() -> ActivityClassifier | None:
    model_path = DEFAULT_ACTIVITY_MODEL_PATH.resolve()
    metadata_path = DEFAULT_ACTIVITY_METADATA_PATH.resolve()
    controlled_root = (PROJECT_ROOT / "data/models").resolve()
    if model_path.parent != controlled_root or metadata_path.parent != controlled_root:
        return None
    if not model_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not metadata.get("promoted") or metadata.get("artifact_sha256") != _sha256(model_path):
        return None
    try:
        artifact = joblib.load(model_path)
    except Exception:
        return None
    if not isinstance(artifact, dict) or artifact.get("model_version") != metadata.get(
        "model_version"
    ):
        return None
    return ActivityClassifier(artifact=artifact, metadata=metadata)


load_activity_classifier = lru_cache(maxsize=1)(load_activity_classifier)


def classify_operation(
    main_raw: str | None,
    sub_raw: str | None,
    remark: str | None,
    *,
    predictor: ActivityPredictor | None = None,
) -> OperationClassification:
    main_source, sub_source = normalize_activity_result(main_raw, sub_raw)
    evidence: dict[str, Any] = {
        "main_source": asdict(main_source),
        "sub_source": asdict(sub_source),
    }
    if main_source.method != "unknown" and sub_source.method != "unknown":
        return OperationClassification(
            main_source.canonical_label,
            sub_source.canonical_label,
            "source_rule",
            min(main_source.confidence, sub_source.confidence),
            None,
            evidence,
        )
    active = predictor or load_activity_classifier()
    if active is None or not (remark or "").strip():
        return OperationClassification(
            main_source.canonical_label,
            sub_source.canonical_label,
            "unknown",
            0.0,
            None,
            {**evidence, "fallback": "model_unavailable_or_empty_remark"},
        )
    predictions: dict[str, ActivityPrediction] = {}
    if main_source.method == "unknown":
        predictions["main"] = active.predict("main", remark or "")
    if sub_source.method == "unknown":
        predictions["sub"] = active.predict("sub", remark or "")
    main = predictions.get("main")
    sub = predictions.get("sub")
    main_label = main.label if main else main_source.canonical_label
    sub_label = sub.label if sub else sub_source.canonical_label
    confidences = [item.confidence for item in predictions.values()]
    evidence["ml_predictions"] = {key: asdict(value) for key, value in predictions.items()}
    accepted = main_label != "unknown" and sub_label != "unknown"
    return OperationClassification(
        main_label,
        sub_label,
        "ml" if accepted else "unknown",
        min(confidences) if confidences else 0.0,
        active.model_version,
        evidence,
    )


def enrich_operation_classifications(
    report: ParsedReport, *, predictor: ActivityPredictor | None = None
) -> ParsedReport:
    for operation in report.operations:
        decision = classify_operation(
            operation.main_activity_raw,
            operation.sub_activity_raw,
            operation.remark,
            predictor=predictor,
        )
        operation.main_activity_normalized = decision.main_activity
        operation.sub_activity_normalized = decision.sub_activity
        operation.classification_method = decision.method
        operation.classification_confidence = decision.confidence
        operation.classification_model_version = decision.model_version
        operation.classification_evidence = decision.evidence
        operation.normalized_values.update(
            {
                "main_activity": decision.main_activity,
                "sub_activity": decision.sub_activity,
                "classification_method": decision.method,
                "classification_confidence": decision.confidence,
                "classification_model_version": decision.model_version,
            }
        )
    return report
