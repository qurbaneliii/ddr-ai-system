from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = {
    "evaluation_name",
    "timestamp",
    "git_sha",
    "parser_version",
    "model_version",
    "data_fingerprint",
    "sample_count",
    "parameters",
    "actual_metrics",
    "limitations",
}


def test_committed_evaluation_artifacts_have_standard_contract() -> None:
    evaluation_root = PROJECT_ROOT / "data/processed/evaluations"
    for name in (
        "activity_classifier.json",
        "anomaly_model.json",
        "chat.json",
        "ocr_surrogate.json",
    ):
        payload = json.loads((evaluation_root / name).read_text(encoding="utf-8"))
        assert payload.keys() >= REQUIRED_FIELDS, name
        assert payload["sample_count"] >= 1
        assert payload["data_fingerprint"]
        assert payload["limitations"]


def test_ocr_evidence_is_truthfully_surrogate_and_real_manifest_is_ready() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "data/processed/evaluations/ocr_surrogate.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["parameters"]["real_scanned_inputs"] is False
    assert "surrogate" in payload["parameters"]["benchmark_type"]
    assert payload["target_results"]["operation_row_recall"] is False

    with (PROJECT_ROOT / "data/evaluation/ocr_manifest.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        reader = csv.DictReader(stream)
        assert {
            "source_id",
            "file_name",
            "page_number",
            "ground_truth_type",
            "expected_wellbore",
            "expected_date",
            "expected_section_headings",
            "expected_selected_operation_rows",
            "expected_selected_table_cells",
            "expected_numeric_fields",
            "annotation_source",
            "ground_truth_text_file",
        } <= set(reader.fieldnames or [])
        assert list(reader) == []
