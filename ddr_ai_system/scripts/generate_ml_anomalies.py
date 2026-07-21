from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ddr_ai.analytics.anomaly_model import DurationAnomalyConfig, generate_duration_anomalies
from ddr_ai.config import PROJECT_ROOT, get_settings
from ddr_ai.db.session import session_scope, upgrade_schema


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate idempotent operation-duration ML candidates.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete/rebuild only this exact model version before generation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/processed/evaluations/anomaly_model.json",
    )
    args = parser.parse_args()
    settings = get_settings()
    upgrade_schema(settings.database_url)
    config = DurationAnomalyConfig()
    with session_scope(settings.database_url) as session:
        result = generate_duration_anomalies(
            session,
            config=config,
            dry_run=args.dry_run,
            rebuild=args.rebuild,
        )
    evaluation = {
        "evaluation_name": "operation_duration_isolation_forest_candidates",
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "parser_version": settings.parser_version,
        "model_version": config.model_version,
        "data_fingerprint": result["data_fingerprint"],
        "sample_count": result["actual_metrics"]["eligible_operations"],
        "parameters": result["parameters"],
        "actual_metrics": result["actual_metrics"],
        "limitations": [
            "Unsupervised candidates have no precision/recall claim without reviewer labels.",
            "Duration is compared only inside supported canonical activity groups.",
            "Candidates are not confirmed incidents or engineering recommendations.",
        ],
    }
    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()
