from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ddr_ai.common.hashing import sha256_file
from ddr_ai.ingestion.safe_zip import inspect_zip, safe_extract_zip

ASSETS = {
    "Task Description.docx": None,
    "PDF_version_1000.zip": "ddr_pdfs",
    "pressure_plots.zip": "pressure_profiles",
    "pressure_time_plots.zip": "pressure_time_plots",
}


def bootstrap(source_dir: Path, raw_dir: Path) -> dict[str, object]:
    source_store = raw_dir / "source_archives"
    source_store.mkdir(parents=True, exist_ok=True)
    baseline: dict[str, object] = {"source_directory": str(source_dir.resolve()), "files": {}}
    for name, destination_name in ASSETS.items():
        source = source_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"Required source asset not found: {source}")
        digest = sha256_file(source)
        copied = source_store / name
        if copied.exists():
            if sha256_file(copied) != digest:
                raise ValueError(f"Existing preserved source has a different hash: {copied}")
        else:
            shutil.copy2(source, copied)
        entry: dict[str, object] = {"sha256": digest, "bytes": source.stat().st_size,
                                   "preserved_copy": str(copied)}
        if destination_name:
            inspection = inspect_zip(copied)
            destination = raw_dir / destination_name
            existing_files = [path for path in destination.rglob("*") if path.is_file()] if destination.exists() else []
            if existing_files:
                if len(existing_files) != inspection.files:
                    raise ValueError(f"Partial extraction detected in {destination}")
                extraction_status = "skipped_existing_complete"
            else:
                safe_extract_zip(copied, destination)
                extraction_status = "extracted"
            entry.update({"archive": inspection.to_dict(), "destination": str(destination),
                          "extraction_status": extraction_status})
        baseline["files"][name] = entry
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "source_baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return baseline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    result = bootstrap(args.source_dir, args.raw_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

