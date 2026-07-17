from __future__ import annotations

import argparse
import csv
import json

from ddr_ai.analytics.candidates import materialize_operational_candidates
from ddr_ai.config import get_settings
from ddr_ai.db.session import create_schema, session_scope
from ddr_ai.services.processor import process_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Optional representative subset limit per asset type")
    args = parser.parse_args()
    settings = get_settings()
    create_schema()
    groups = [
        sorted((settings.raw_dir / "ddr_pdfs").rglob("*.pdf")),
        sorted((settings.raw_dir / "pressure_profiles").rglob("*.png")),
        sorted((settings.raw_dir / "pressure_time_plots").rglob("*.png")),
    ]
    paths = [path for group in groups for path in (group[: args.limit] if args.limit else group)]
    manifest_path = settings.processed_dir / "processing_manifest.csv"
    fieldnames = ["path", "status", "sha256", "duration_seconds", "error"]
    results = []
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for index, path in enumerate(paths, start=1):
            result = process_file(path)
            results.append(result)
            writer.writerow(result)
            output.flush()
            if index == 1 or index % 25 == 0 or index == len(paths):
                progress = {
                    "processed": index,
                    "total": len(paths),
                    "complete": sum(item["status"] == "complete" for item in results),
                    "skipped_unchanged": sum(
                        item["status"] == "skipped_unchanged" for item in results
                    ),
                    "failed": sum(item["status"] == "failed" for item in results),
                }
                print(json.dumps(progress), flush=True)
    summary = {
        "total": len(results),
        "complete": sum(item["status"] == "complete" for item in results),
        "skipped_unchanged": sum(item["status"] == "skipped_unchanged" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "manifest": str(manifest_path),
    }
    with session_scope() as session:
        summary["analytics_candidates_created"] = materialize_operational_candidates(session)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
