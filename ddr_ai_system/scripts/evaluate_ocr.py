from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import fitz
import numpy as np
from PIL import Image
from sqlalchemy import select

from ddr_ai.common.hashing import sha256_file
from ddr_ai.config import PROJECT_ROOT, get_settings
from ddr_ai.db.models import EquipmentFailure, Operation, Report, SourceDocument
from ddr_ai.db.session import session_scope
from ddr_ai.ingestion.router import AssetKind, classify_pdf
from ddr_ai.pdf.ocr import (
    BaseOCRBackend,
    OCRUnavailableError,
    TesseractOCRBackend,
    parse_scanned_pdf,
)
from ddr_ai.pdf.ocr_contracts import OCRResult, OCRToken
from ddr_ai.pdf.parser import parse_ddr_pdf

TARGETS: dict[str, dict[str, float | str]] = {
    "routing_accuracy": {"operator": ">=", "value": 0.90},
    "page_method_accuracy": {"operator": ">=", "value": 0.90},
    "token_f1": {"operator": ">=", "value": 0.75},
    "word_error_rate": {"operator": "<=", "value": 0.25},
    "wellbore_exact_match": {"operator": ">=", "value": 0.80},
    "date_exact_match": {"operator": ">=", "value": 0.80},
    "section_recall": {"operator": ">=", "value": 0.75},
    "operation_row_recall": {"operator": ">=", "value": 0.70},
    "equipment_failure_row_recall": {"operator": ">=", "value": 0.60},
    "selected_table_cell_accuracy": {"operator": ">=", "value": 0.70},
    "numeric_exact_match": {"operator": ">=", "value": 0.75},
    "failure_rate": {"operator": "<=", "value": 0.10},
}


class RapidOCRBackend(BaseOCRBackend):
    name = "rapidocr-onnxruntime"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self.reader = RapidOCR()

    def recognize(self, image: Image.Image) -> OCRResult:
        result, _ = self.reader(np.asarray(image.convert("RGB")))
        entries: list[dict[str, float | str]] = []
        scores: list[float] = []
        for item in result or []:
            box, text, score = item
            value = str(text).strip()
            if not value:
                continue
            points = np.asarray(box, dtype=float)
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            confidence = float(score)
            scores.append(confidence)
            words = value.split()
            total_characters = sum(len(word) for word in words) + max(len(words) - 1, 0)
            cursor = float(x0)
            for word in words:
                width = float(x1 - x0) * len(word) / max(total_characters, 1)
                entries.append(
                    {
                        "text": word,
                        "confidence": confidence,
                        "x0": cursor,
                        "y0": float(y0),
                        "x1": min(cursor + width, float(x1)),
                        "y1": float(y1),
                        "center_y": float((y0 + y1) / 2),
                        "height": float(y1 - y0),
                    }
                )
                cursor += width + float(x1 - x0) / max(total_characters, 1)
        clustered: list[list[dict[str, float | str]]] = []
        for entry in sorted(entries, key=lambda value: (float(value["center_y"]), float(value["x0"]))):
            if not clustered:
                clustered.append([entry])
                continue
            current_y = mean(float(value["center_y"]) for value in clustered[-1])
            tolerance = max(8.0, float(entry["height"]) * 0.65)
            if abs(float(entry["center_y"]) - current_y) <= tolerance:
                clustered[-1].append(entry)
            else:
                clustered.append([entry])
        tokens: list[OCRToken] = []
        lines: list[str] = []
        for line_number, line_entries in enumerate(clustered, start=1):
            ordered = sorted(line_entries, key=lambda value: float(value["x0"]))
            lines.append(" ".join(str(value["text"]) for value in ordered))
            for entry in ordered:
                tokens.append(
                    OCRToken(
                        text=str(entry["text"]),
                        confidence=float(entry["confidence"]),
                        x0=float(entry["x0"]),
                        y0=float(entry["y0"]),
                        x1=float(entry["x1"]),
                        y1=float(entry["y1"]),
                        block=1,
                        paragraph=1,
                        line=line_number,
                    )
                )
        return OCRResult(
            text="\n".join(lines),
            confidence=round(mean(scores), 4) if scores else 0.0,
            tokens=tuple(tokens),
        )


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _backend(name: str) -> BaseOCRBackend:
    if name in {"auto", "tesseract"}:
        try:
            return TesseractOCRBackend()
        except OCRUnavailableError:
            if name == "tesseract":
                raise
    return RapidOCRBackend()


def _words(value: str) -> list[str]:
    return re.findall(r"[\w/.-]+", value.casefold(), flags=re.UNICODE)


def _text_metrics(expected: str, actual: str) -> dict[str, float]:
    expected_words = _words(expected)
    actual_words = _words(actual)
    expected_counts = Counter(expected_words)
    actual_counts = Counter(actual_words)
    matches = sum((expected_counts & actual_counts).values())
    precision = matches / max(len(actual_words), 1)
    recall = matches / max(len(expected_words), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    matcher = difflib.SequenceMatcher(a=expected_words, b=actual_words, autojunk=False)
    errors = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    return {
        "token_precision": precision,
        "token_recall": recall,
        "token_f1": f1,
        "word_error_rate": errors / max(len(expected_words), 1),
    }


def _recall(expected: int, actual: int) -> float:
    return 1.0 if expected == 0 else min(actual / expected, 1.0)


def _operation_cells(items: list[Any]) -> set[str]:
    values: set[str] = set()
    for item in items:
        for value in (
            item.start_time_raw,
            item.end_time_raw,
            item.main_activity_normalized,
            item.sub_activity_normalized,
        ):
            if value:
                values.add(str(value).casefold().strip())
    return values


def _json_list(value: str) -> list[Any]:
    if not value.strip():
        return []
    parsed = json.loads(value)
    if isinstance(parsed, dict):
        return list(parsed.values())
    if not isinstance(parsed, list):
        raise ValueError("Manifest JSON fields must contain a list or object.")
    return parsed


def _resolve_under(root: Path, value: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / value).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError("Manifest path is missing or outside the authorized input root.")
    return resolved


def _numeric_values(items: list[Any]) -> set[float]:
    values: set[float] = set()
    for item in items:
        for value in (item.duration_hours, item.end_depth_mmd):
            if value is not None:
                values.add(round(float(value), 6))
    return values


def _raster_page(source: Path, destination: Path, page_number: int, dpi: int) -> None:
    document = fitz.open(source)
    output = fitz.open()
    try:
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        target = output.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=pixmap.tobytes("png"))
        output.save(destination)
    finally:
        output.close()
        document.close()


def _representative_sources(limit: int) -> list[SourceDocument]:
    settings = get_settings()
    with session_scope(settings.database_url) as session:
        failure_ids = list(
            session.scalars(
                select(SourceDocument.id)
                .join(Report, Report.source_document_id == SourceDocument.id)
                .join(EquipmentFailure, EquipmentFailure.report_id == Report.id)
                .distinct()
                .order_by(SourceDocument.id)
                .limit(max(1, limit // 2))
            )
        )
        operation_ids = list(
            session.scalars(
                select(SourceDocument.id)
                .join(Report, Report.source_document_id == SourceDocument.id)
                .join(Operation, Operation.report_id == Report.id)
                .where(SourceDocument.id.not_in(failure_ids or [-1]))
                .distinct()
                .order_by(SourceDocument.id)
                .limit(limit - len(failure_ids))
            )
        )
        identifiers = [*failure_ids, *operation_ids]
        return list(
            session.scalars(
                select(SourceDocument)
                .where(SourceDocument.id.in_(identifiers))
                .order_by(SourceDocument.id)
            )
        )


def _source_path(document: SourceDocument) -> Path:
    path = Path(document.source_path)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _score_surrogate(
    document: SourceDocument,
    backend: BaseOCRBackend,
    workdir: Path,
    dpi: int,
) -> dict[str, Any]:
    source = _source_path(document)
    native = parse_ddr_pdf(source)
    counts = Counter(
        [item.page_number for item in native.operations]
        + [item.page_number for item in native.equipment_failures]
        + [item.provenance.page_number for item in native.fields]
    )
    page_number = counts.most_common(1)[0][0] if counts else 1
    destination = workdir / f"{document.id}-{source.name}"
    _raster_page(source, destination, page_number, dpi)
    started = time.perf_counter()
    parsed = parse_scanned_pdf(destination, backend=backend, dpi=dpi)
    latency = time.perf_counter() - started
    expected_page = next(item for item in native.pages if item.page_number == page_number)
    expected_operations = [item for item in native.operations if item.page_number == page_number]
    expected_failures = [item for item in native.equipment_failures if item.page_number == page_number]
    expected_sections = {
        item.section_type for item in native.sections if item.page_number == page_number
    }
    actual_sections = {item.section_type for item in parsed.sections}
    expected_cells = _operation_cells(expected_operations)
    actual_cells = _operation_cells(parsed.operations)
    expected_numbers = _numeric_values(expected_operations)
    actual_numbers = _numeric_values(parsed.operations)
    text_metrics = _text_metrics(expected_page.text, parsed.pages[0].text)
    return {
        "source_id": str(document.id),
        "sample_id": f"surrogate-{document.id}-p{page_number}",
        "file_name": document.file_name,
        "page_number": page_number,
        "ground_truth_type": "native_parser_derived_surrogate",
        "expected_text_available": 1,
        "expected_wellbore_available": int(native.wellbore is not None),
        "expected_date_available": int(native.period_end is not None),
        "expected_section_count": len(expected_sections),
        "routing_accuracy": float(classify_pdf(destination).kind == AssetKind.SCANNED_PDF),
        "page_method_accuracy": float(parsed.pages[0].extraction_method == "ocr"),
        **text_metrics,
        "wellbore_exact_match": float(parsed.wellbore == native.wellbore),
        "date_exact_match": float(parsed.period_end == native.period_end),
        "section_recall": (
            len(expected_sections & actual_sections) / len(expected_sections)
            if expected_sections
            else 1.0
        ),
        "operation_row_recall": _recall(len(expected_operations), len(parsed.operations)),
        "equipment_failure_row_recall": _recall(
            len(expected_failures), len(parsed.equipment_failures)
        ),
        "selected_table_cell_accuracy": (
            len(expected_cells & actual_cells) / len(expected_cells) if expected_cells else 1.0
        ),
        "numeric_exact_match": (
            len(expected_numbers & actual_numbers) / len(expected_numbers)
            if expected_numbers
            else 1.0
        ),
        "mean_confidence": parsed.pages[0].confidence,
        "processing_latency_seconds": round(latency, 4),
        "expected_operation_rows": len(expected_operations),
        "actual_operation_rows": len(parsed.operations),
        "expected_failure_rows": len(expected_failures),
        "actual_failure_rows": len(parsed.equipment_failures),
        "expected_table_cell_count": len(expected_cells),
        "expected_numeric_count": len(expected_numbers),
    }


def _score_real(
    row: dict[str, str],
    backend: BaseOCRBackend,
    input_root: Path,
    annotation_root: Path,
    dpi: int,
) -> dict[str, Any]:
    source = _resolve_under(input_root, row["file_name"])
    page_number = int(row["page_number"])
    expected_text_path = _resolve_under(annotation_root, row["ground_truth_text_file"])
    expected_text = expected_text_path.read_text(encoding="utf-8")
    expected_sections = {str(item) for item in _json_list(row["expected_section_headings"])}
    expected_operations = _json_list(row["expected_selected_operation_rows"])
    expected_cells = {
        str(item).casefold().strip() for item in _json_list(row["expected_selected_table_cells"])
    }
    expected_numbers = {
        round(float(item), 6) for item in _json_list(row["expected_numeric_fields"])
    }
    started = time.perf_counter()
    route = classify_pdf(source)
    parsed = parse_scanned_pdf(
        source,
        backend=backend,
        dpi=dpi,
        page_numbers={page_number},
    )
    latency = time.perf_counter() - started
    actual_sections = {item.section_type for item in parsed.sections}
    actual_cells = _operation_cells(parsed.operations)
    for failure in parsed.equipment_failures:
        actual_cells.update(
            str(value).casefold().strip()
            for value in (
                failure.start_time_raw,
                failure.failed_equipment_normalized,
                failure.system_class_normalized,
            )
            if value
        )
    actual_cells.update(
        str(value).casefold().strip()
        for field in parsed.fields
        for value in (field.raw_value, field.normalized_text)
        if value
    )
    actual_numbers = _numeric_values(parsed.operations)
    actual_numbers.update(
        round(float(item.operational_downtime_minutes), 6)
        for item in parsed.equipment_failures
        if item.operational_downtime_minutes is not None
    )
    actual_numbers.update(
        round(float(item.normalized_number), 6)
        for item in parsed.fields
        if item.normalized_number is not None
    )
    expected_failure_rows = sum(
        str(item.get("table", "")).casefold() == "equipment_failure"
        for item in expected_operations
        if isinstance(item, dict)
    )
    expected_operation_rows = len(expected_operations) - expected_failure_rows
    expected_wellbore = row["expected_wellbore"].strip() or None
    expected_date = row["expected_date"].strip() or None
    text_metrics = _text_metrics(expected_text, parsed.pages[0].text)
    expected_page_route = next(
        (item.route for item in route.pages if item.page_number == page_number), None
    )
    return {
        "source_id": row["source_id"],
        "sample_id": f"real-{row['source_id']}-p{page_number}",
        "file_name": Path(row["file_name"]).name,
        "page_number": page_number,
        "ground_truth_type": row["ground_truth_type"],
        "expected_text_available": 1,
        "expected_wellbore_available": int(expected_wellbore is not None),
        "expected_date_available": int(expected_date is not None),
        "expected_section_count": len(expected_sections),
        "routing_accuracy": float(expected_page_route == "ocr"),
        "page_method_accuracy": float(parsed.pages[0].extraction_method == "ocr"),
        **text_metrics,
        "wellbore_exact_match": float(
            expected_wellbore is not None and parsed.wellbore == expected_wellbore
        ),
        "date_exact_match": float(
            expected_date is not None
            and parsed.period_end is not None
            and parsed.period_end.date().isoformat() == expected_date
        ),
        "section_recall": (
            len(expected_sections & actual_sections) / len(expected_sections)
            if expected_sections
            else 0.0
        ),
        "operation_row_recall": _recall(expected_operation_rows, len(parsed.operations)),
        "equipment_failure_row_recall": _recall(
            expected_failure_rows, len(parsed.equipment_failures)
        ),
        "selected_table_cell_accuracy": (
            len(expected_cells & actual_cells) / len(expected_cells) if expected_cells else 0.0
        ),
        "numeric_exact_match": (
            len(expected_numbers & actual_numbers) / len(expected_numbers)
            if expected_numbers
            else 0.0
        ),
        "mean_confidence": parsed.pages[0].confidence,
        "processing_latency_seconds": round(latency, 4),
        "expected_operation_rows": expected_operation_rows,
        "actual_operation_rows": len(parsed.operations),
        "expected_failure_rows": expected_failure_rows,
        "actual_failure_rows": len(parsed.equipment_failures),
        "expected_table_cell_count": len(expected_cells),
        "expected_numeric_count": len(expected_numbers),
        "annotation_source": row["annotation_source"],
    }


def _aggregate(samples: list[dict[str, Any]], attempted: int) -> dict[str, Any]:
    metrics = [
        "routing_accuracy",
        "page_method_accuracy",
        "token_precision",
        "token_recall",
        "token_f1",
        "word_error_rate",
        "wellbore_exact_match",
        "date_exact_match",
        "section_recall",
        "operation_row_recall",
        "equipment_failure_row_recall",
        "selected_table_cell_accuracy",
        "numeric_exact_match",
        "mean_confidence",
        "processing_latency_seconds",
    ]
    conditional_support = {
        "token_precision": "expected_text_available",
        "token_recall": "expected_text_available",
        "token_f1": "expected_text_available",
        "word_error_rate": "expected_text_available",
        "wellbore_exact_match": "expected_wellbore_available",
        "date_exact_match": "expected_date_available",
        "section_recall": "expected_section_count",
        "operation_row_recall": "expected_operation_rows",
        "equipment_failure_row_recall": "expected_failure_rows",
        "selected_table_cell_accuracy": "expected_table_cell_count",
        "numeric_exact_match": "expected_numeric_count",
    }
    result: dict[str, Any] = {}
    metric_sample_counts: dict[str, int] = {}
    for key in metrics:
        support_field = conditional_support.get(key)
        eligible = (
            [sample for sample in samples if int(sample[support_field]) > 0]
            if support_field
            else samples
        )
        metric_sample_counts[key] = len(eligible)
        result[key] = mean(float(sample[key]) for sample in eligible) if eligible else 0.0
    result["failure_rate"] = (attempted - len(samples)) / max(attempted, 1)
    metric_sample_counts["failure_rate"] = attempted
    result["metric_sample_counts"] = metric_sample_counts
    return result


def _target_results(metrics: dict[str, Any]) -> dict[str, bool]:
    return {
        name: (
            float(metrics[name]) >= float(target["value"])
            if target["operator"] == ">="
            else float(metrics[name]) <= float(target["value"])
        )
        for name, target in TARGETS.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DDR OCR without exposing private inputs.")
    parser.add_argument("--mode", choices=["real", "surrogate"], default="surrogate")
    parser.add_argument("--backend", choices=["auto", "tesseract", "rapidocr"], default="auto")
    parser.add_argument("--sample-count", type=int, default=10)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--annotation-root", type=Path)
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "data/evaluation/ocr_manifest.csv"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/processed/evaluations/ocr_surrogate.json",
    )
    args = parser.parse_args()
    active_backend = _backend(args.backend)
    failures: list[dict[str, str]] = []
    samples: list[dict[str, Any]] = []
    if args.mode == "real":
        with args.manifest.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise SystemExit("Real OCR evaluation requires annotated manifest rows and genuine scans.")
        if args.input_root is None or args.annotation_root is None:
            raise SystemExit("Real OCR evaluation requires --input-root and --annotation-root.")
        for row in rows:
            try:
                samples.append(
                    _score_real(
                        row,
                        active_backend,
                        args.input_root,
                        args.annotation_root,
                        args.dpi,
                    )
                )
            except Exception as exc:
                failures.append(
                    {"source_id": row.get("source_id", "unknown"), "error_category": type(exc).__name__}
                )
        attempted = len(rows)
        fingerprint_items = [
            (row["source_id"], sha256_file(_resolve_under(args.input_root, row["file_name"])))
            for row in rows
        ]
        benchmark_type = "genuine_scanned_ddr_human_annotated"
        real_inputs = True
        selection = "annotated OCR manifest"
    else:
        sources = _representative_sources(args.sample_count)
        with tempfile.TemporaryDirectory(prefix="ddr-ocr-surrogate-") as temporary:
            workdir = Path(temporary)
            for source in sources:
                try:
                    samples.append(_score_surrogate(source, active_backend, workdir, args.dpi))
                except Exception as exc:
                    failures.append(
                        {"source_id": str(source.id), "error_category": type(exc).__name__}
                    )
        attempted = len(sources)
        fingerprint_items = [(item.id, item.sha256) for item in sources]
        benchmark_type = "surrogate_native_pages_rasterized_to_image_only_pdf"
        real_inputs = False
        selection = "deterministic mix of operation and equipment-failure reports"
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_items, separators=(",", ":")).encode()
    ).hexdigest()
    actual_metrics = _aggregate(samples, attempted)
    settings = get_settings()
    result = {
        "evaluation_name": (
            "ddr_ocr_real_scanned_benchmark"
            if args.mode == "real"
            else "ddr_ocr_surrogate_robustness"
        ),
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "parser_version": settings.parser_version,
        "model_version": active_backend.name,
        "data_fingerprint": fingerprint,
        "sample_count": len(samples),
        "parameters": {
            "benchmark_type": benchmark_type,
            "real_scanned_inputs": real_inputs,
            "backend": active_backend.name,
            "dpi": args.dpi,
            "predeclared_targets": TARGETS,
            "selection": selection,
        },
        "actual_metrics": actual_metrics,
        "target_results": _target_results(actual_metrics),
        "samples": samples,
        "failures": failures,
        "limitations": (
            [
                "Metrics apply only to the authorized annotated genuine-scan sample.",
                "Extraction measurements are not drilling-engineering validation.",
            ]
            if args.mode == "real"
            else [
                "This is a surrogate robustness benchmark, not a genuine scanned-DDR benchmark.",
                "Ground truth is derived from native extraction rather than human annotation.",
                "Real scanned-DDR validation remains blocked until genuine samples are authorized.",
            ]
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "backend": active_backend.name,
                "sample_count": len(samples),
                "failures": len(failures),
                "target_results": result["target_results"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
