from __future__ import annotations

import json
from pathlib import Path

import joblib

import ddr_ai.nlp.activity_classifier as classifier_module
from ddr_ai.nlp.activity_classifier import (
    ACTIVITY_MODEL_VERSION,
    ActivityPrediction,
    build_pipeline,
    classify_operation,
    grouped_train_test_indices,
    load_activity_classifier,
)


class FakePredictor:
    model_version = "fake-v1"

    def __init__(self, *, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.calls: list[str] = []

    def predict(self, kind: str, remark: str) -> ActivityPrediction:
        self.calls.append(kind)
        label = "drilling" if kind == "main" else "drill"
        return ActivityPrediction(
            label if self.confidence >= 0.5 else "unknown",
            self.confidence,
            self.model_version,
        )


def test_valid_source_labels_take_precedence_over_ml() -> None:
    predictor = FakePredictor()
    decision = classify_operation(
        "formationevaluation",
        "wire line",
        "remark text",
        predictor=predictor,
    )
    assert decision.main_activity == "formation_evaluation"
    assert decision.sub_activity == "wireline"
    assert decision.method == "source_rule"
    assert predictor.calls == []


def test_ml_fallback_is_used_only_for_unresolved_source_label() -> None:
    predictor = FakePredictor()
    decision = classify_operation(None, None, "Drilled ahead", predictor=predictor)
    assert decision.method == "ml"
    assert (decision.main_activity, decision.sub_activity) == ("drilling", "drill")
    assert predictor.calls == ["main", "sub"]


def test_low_confidence_ml_prediction_is_rejected() -> None:
    decision = classify_operation(
        None,
        None,
        "ambiguous remark",
        predictor=FakePredictor(confidence=0.2),
    )
    assert decision.method == "unknown"
    assert decision.main_activity == decision.sub_activity == "unknown"


def test_report_groups_never_cross_train_and_test() -> None:
    labels = ["a", "a", "b", "b", "a", "b", "a", "b", "a", "b"]
    groups = list(range(10))
    train, test = grouped_train_test_indices(labels, groups)
    assert set(groups[index] for index in train).isdisjoint(groups[index] for index in test)


def test_training_is_reproducible_for_fixed_random_state() -> None:
    texts = [
        "drilled ahead formation",
        "drilling hole interval",
        "repair top drive",
        "repair equipment failure",
    ] * 4
    labels = ["drilling", "drilling", "interruption", "interruption"] * 4
    first = build_pipeline()
    second = build_pipeline()
    first.fit(texts, labels)
    second.fit(texts, labels)
    assert list(first.predict(texts)) == list(second.predict(texts))


def test_missing_or_invalid_controlled_artifact_fails_safely(
    tmp_path: Path, monkeypatch
) -> None:
    model = tmp_path / "models" / "activity_classifier.joblib"
    metadata = tmp_path / "models" / "activity_classifier.metadata.json"
    model.parent.mkdir()
    monkeypatch.setattr(classifier_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(classifier_module, "DEFAULT_ACTIVITY_MODEL_PATH", model)
    monkeypatch.setattr(classifier_module, "DEFAULT_ACTIVITY_METADATA_PATH", metadata)
    load_activity_classifier.cache_clear()
    assert load_activity_classifier() is None

    joblib.dump({"model_version": ACTIVITY_MODEL_VERSION}, model)
    metadata.write_text(
        json.dumps(
            {
                "model_version": ACTIVITY_MODEL_VERSION,
                "artifact_sha256": "0" * 64,
                "promoted": True,
            }
        ),
        encoding="utf-8",
    )
    load_activity_classifier.cache_clear()
    assert load_activity_classifier() is None
