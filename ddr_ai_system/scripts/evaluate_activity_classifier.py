from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ddr_ai.config import PROJECT_ROOT
from ddr_ai.nlp.activity_classifier import (
    DEFAULT_ACTIVITY_METADATA_PATH,
    load_activity_classifier,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the recorded grouped holdout evaluation.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/processed/evaluations/activity_classifier.json",
    )
    args = parser.parse_args()
    metadata = json.loads(DEFAULT_ACTIVITY_METADATA_PATH.read_text(encoding="utf-8"))
    classifier = load_activity_classifier()
    if classifier is None:
        raise SystemExit("The controlled activity artifact failed its hash/promotion contract.")
    result = {
        "evaluation_name": metadata["evaluation_name"],
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": metadata["git_sha"],
        "parser_version": metadata["parser_version"],
        "model_version": metadata["model_version"],
        "data_fingerprint": metadata["data_fingerprint"],
        "sample_count": metadata["sample_count"],
        "parameters": metadata["parameters"],
        "actual_metrics": metadata["actual_metrics"],
        "limitations": metadata["limitations"],
        "artifact_sha256": metadata["artifact_sha256"],
        "promoted": metadata["promoted"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "promoted": result["promoted"]}, indent=2))


if __name__ == "__main__":
    main()
