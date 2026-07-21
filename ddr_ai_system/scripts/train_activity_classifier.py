from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sqlalchemy import select, update

from ddr_ai.config import get_settings
from ddr_ai.db.models import ModelRun
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.nlp.activity_classifier import (
    ACTIVITY_MODEL_VERSION,
    DEFAULT_ACTIVITY_METADATA_PATH,
    DEFAULT_ACTIVITY_MODEL_PATH,
    DEFAULT_THRESHOLDS,
    MIN_SUBACTIVITY_SUPPORT,
    RANDOM_STATE,
    _sha256,
    build_training_dataset,
    load_activity_classifier,
    train_and_evaluate,
)


def _git_sha(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the grouped DDR activity classifiers.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Required when controlled model artifacts already exist.",
    )
    args = parser.parse_args()
    settings = get_settings()
    upgrade_schema(settings.database_url)
    model_path = DEFAULT_ACTIVITY_MODEL_PATH
    metadata_path = DEFAULT_ACTIVITY_METADATA_PATH
    if (model_path.exists() or metadata_path.exists()) and not args.overwrite:
        raise SystemExit("Controlled artifacts exist; pass --overwrite to retrain deliberately.")

    with session_scope(settings.database_url) as session:
        dataset = build_training_dataset(session)
    artifact, actual_metrics = train_and_evaluate(dataset)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    artifact_hash = _sha256(model_path)
    promoted = bool(actual_metrics["promotion"]["promoted"])
    metadata = {
        "evaluation_name": "ddr_activity_classifier_grouped_holdout",
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(settings.processed_dir.parents[1]),
        "parser_version": settings.parser_version,
        "model_version": ACTIVITY_MODEL_VERSION,
        "data_fingerprint": dataset.fingerprint,
        "sample_count": dataset.deduplicated_rows,
        "source_operation_count": dataset.source_rows,
        "parameters": {
            "random_state": RANDOM_STATE,
            "split": "StratifiedGroupKFold by report_id with deterministic group fallback",
            "features": "word (1,2) and char_wb (3,5) TF-IDF",
            "classifier": "class-weighted LogisticRegression",
            "minimum_subactivity_support": MIN_SUBACTIVITY_SUPPORT,
        },
        "actual_metrics": actual_metrics,
        "thresholds": DEFAULT_THRESHOLDS,
        "artifact_sha256": artifact_hash,
        "promoted": promoted,
        "limitations": [
            "Labels are source-derived and the model is a shadow/fallback classifier.",
            "Rare subactivities remain source-only and are excluded from fallback prediction.",
            "Metrics are report-grouped holdout results, not domain validation.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    with session_scope(settings.database_url) as session:
        session.execute(
            update(ModelRun)
            .where(ModelRun.model_type == "activity_classifier")
            .values(is_active=False)
        )
        record = session.scalar(
            select(ModelRun).where(
                ModelRun.model_type == "activity_classifier",
                ModelRun.model_version == ACTIVITY_MODEL_VERSION,
            )
        )
        values = {
            "artifact_sha256": artifact_hash,
            "training_data_sha256": dataset.fingerprint,
            "parameters_json": metadata["parameters"],
            "metrics_json": actual_metrics,
            "is_active": promoted,
        }
        if record is None:
            session.add(
                ModelRun(
                    model_type="activity_classifier",
                    model_version=ACTIVITY_MODEL_VERSION,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(record, key, value)
    load_activity_classifier.cache_clear()
    print(
        json.dumps(
            {
                "model_version": ACTIVITY_MODEL_VERSION,
                "promoted": promoted,
                "sample_count": dataset.deduplicated_rows,
                "artifact_sha256": artifact_hash,
                "main_macro_f1": actual_metrics["main"]["model"]["macro_f1"],
                "sub_macro_f1": actual_metrics["sub"]["model"]["macro_f1"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
