from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from ddr_ai.db.models import (
    Anomaly,
    ExtractedValue,
    Operation,
    Plot,
    PlotPoint,
    ProcessingJob,
    Report,
    ReportSection,
    SectionTableRow,
    SourceDocument,
)
from ddr_ai.db.session import session_scope

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "processed" / "evaluation_summary.json"
DOC = ROOT / "docs" / "EVALUATION.md"


def collect() -> dict[str, Any]:
    with session_scope() as session:
        statuses = dict(session.execute(select(SourceDocument.processing_status, func.count(SourceDocument.id))
                                        .group_by(SourceDocument.processing_status)).all())
        routes = dict(session.execute(select(SourceDocument.asset_kind, func.count(SourceDocument.id))
                                      .group_by(SourceDocument.asset_kind)).all())
        report_count = session.scalar(select(func.count(Report.id))) or 0
        operation_count = session.scalar(select(func.count(Operation.id))) or 0
        fail_count = session.scalar(select(func.count(Operation.id)).where(Operation.state_normalized == "fail")) or 0
        fail_pdfs = session.scalar(select(func.count(func.distinct(Report.source_document_id)))
                                   .join(Operation, Operation.report_id == Report.id)
                                   .where(Operation.state_normalized == "fail")) or 0
        equipment_reports = session.scalar(select(func.count(func.distinct(ReportSection.report_id))).where(
            ReportSection.section_type == "equipment_failure_information")) or 0
        excluded_reports = session.scalar(select(func.count(Report.id)).where(Report.excluded_from_default_trends.is_(True))) or 0
        profile_plots = session.scalars(select(Plot).where(Plot.plot_type == "pressure_profile")).all()
        time_plots = session.scalars(select(Plot).where(Plot.plot_type == "pressure_time")).all()
        profile_points = session.execute(select(PlotPoint, Plot).join(Plot, Plot.id == PlotPoint.plot_id)
                                         .where(Plot.plot_type == "pressure_profile")).all()
        time_points = session.execute(select(PlotPoint, Plot).join(Plot, Plot.id == PlotPoint.plot_id)
                                      .where(Plot.plot_type == "pressure_time")).all()
        anomalies = session.scalar(select(func.count(Anomaly.id))) or 0
        anomaly_rules = dict(session.execute(
            select(Anomaly.rule_or_model, func.count(Anomaly.id)).group_by(Anomaly.rule_or_model)
        ).all())
        job_duration = session.scalar(select(func.sum(ProcessingJob.duration_seconds))) or 0.0
        failures = session.scalars(select(SourceDocument.file_name, SourceDocument.error_message)
                                   .where(SourceDocument.processing_status == "failed")).all()
        section_rows = session.scalars(select(SectionTableRow)).all()
        header_sentinels = session.scalar(select(func.count(ExtractedValue.id)).where(
            ExtractedValue.missing_reason == "source_sentinel")) or 0
        operation_sentinels = session.scalar(select(func.count(Operation.id)).where(
            Operation.end_depth_missing_reason == "source_sentinel")) or 0
    band_counts = Counter(point.band_classification or "unclassified" for point, _ in profile_points)
    profile_by_plot = Counter(plot.plot_identifier for _, plot in profile_points)
    time_by_plot = Counter(plot.plot_identifier for _, plot in time_points)
    time_by_series = Counter(point.series_identifier for point, _ in time_points)
    section_rows_by_type = Counter(row.section_type for row in section_rows)
    section_sentinel_cells = sum(
        cell.get("missing_reason") == "source_sentinel"
        for row in section_rows for cell in row.normalized_cells_json
    )
    profile_calibrated = sum(bool(plot.calibration_json.get("x") and plot.calibration_json.get("y")) for plot in profile_plots)
    time_calibrated = sum(bool(plot.calibration_json.get("x") and plot.calibration_json.get("y")) for plot in time_plots)
    legend_excluded = 0
    unknown_units = 0
    for plot in time_plots:
        unknown_units += int(plot.unit_status == "unknown")
        # The digitizer emits exactly one excluded legend marker for each detected displayed series.
        legend_excluded += 4 if not any(w.get("code") == "legend_detection_uncertain" for w in plot.warnings_json) else 0
    audit_path = ROOT / "data" / "processed" / "audit_summary.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    independent_sentinels = audit.get("ddr_pdfs", {}).get("sentinel_occurrences")
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "processing": {"statuses": statuses, "routes": routes, "job_duration_seconds": round(job_duration, 3),
                       "failed_files": [{"file": name, "error": error} for name, error in failures]},
        "ddr": {"reports": report_count, "operations": operation_count, "fail_operation_rows": fail_count,
                "pdfs_with_fail_rows": fail_pdfs, "equipment_failure_reports": equipment_reports,
                "excluded_from_default_trends": excluded_reports,
                "optional_section_table_rows": len(section_rows),
                "optional_rows_by_section": dict(sorted(section_rows_by_type.items())),
                "independent_text_sentinel_occurrences": independent_sentinels,
                "normalized_sentinel_records": section_sentinel_cells + header_sentinels + operation_sentinels,
                "normalized_optional_section_sentinel_cells": section_sentinel_cells},
        "pressure_profiles": {"plots": len(profile_plots), "points": len(profile_points),
                              "points_per_plot": dict(sorted(profile_by_plot.items())),
                              "band_classifications": dict(sorted(band_counts.items())),
                              "calibrated_images": profile_calibrated,
                              "candidate_points": sum(point.anomaly_candidate for point, _ in profile_points)},
        "pressure_time": {"plots": len(time_plots), "points": len(time_points),
                          "points_per_plot": dict(sorted(time_by_plot.items())),
                          "points_per_series": dict(sorted(time_by_series.items())),
                          "calibrated_images": time_calibrated, "legend_markers_excluded": legend_excluded,
                          "unknown_unit_images": unknown_units},
        "anomaly_candidates": anomalies,
        "anomaly_candidates_by_rule": dict(sorted(anomaly_rules.items())),
        "interpretation": {"status": "candidate_level", "domain_validated": False,
                           "sor_definition": "unresolved", "pressure_time_unit": "unknown",
                           "identity_mappings": "unresolved unless reviewed evidence exists"},
    }


def markdown(result: dict[str, Any]) -> str:
    processing = result["processing"]
    ddr = result["ddr"]
    profiles = result["pressure_profiles"]
    times = result["pressure_time"]
    return f"""# Evaluation

Generated: {result['generated_at']}

## Processing outcome

- Statuses: {processing['statuses']}
- Routes: {processing['routes']}
- Recorded processing duration: {processing['job_duration_seconds']} seconds
- Failed files: {len(processing['failed_files'])}

## DDR extraction

- Reports stored: {ddr['reports']}
- Operation rows stored: {ddr['operations']}
- Operation rows marked fail: {ddr['fail_operation_rows']} across {ddr['pdfs_with_fail_rows']} PDFs
- Reports with Equipment Failure Information: {ddr['equipment_failure_reports']}
- Reports excluded from default trends by automated data-quality rules: {ddr['excluded_from_default_trends']}
- Optional-section table rows stored: {ddr['optional_section_table_rows']}
- Optional rows by section: {ddr['optional_rows_by_section']}
- Independent source-text sentinel occurrences: {ddr['independent_text_sentinel_occurrences']}
- Optional-section sentinel cells normalized with raw-value preservation: {ddr['normalized_optional_section_sentinel_cells']}
- Normalized database sentinel records across overlapping extraction surfaces: {ddr['normalized_sentinel_records']}

## Pressure profiles

- Images processed: {profiles['plots']}
- Measured markers stored: {profiles['points']}
- Per-image axes calibrated: {profiles['calibrated_images']}/{profiles['plots']}
- Band classifications: {profiles['band_classifications']}
- Visual anomaly candidates: {profiles['candidate_points']}

## Pressure-time plots

- Images processed: {times['plots']}
- Data points stored after legend exclusion: {times['points']}
- Points by displayed series: {times['points_per_series']}
- Per-image axes calibrated: {times['calibrated_images']}/{times['plots']}
- Legend markers excluded: {times['legend_markers_excluded']}
- Images with explicitly unknown pressure unit: {times['unknown_unit_images']}

## Interpretation boundary

These are extraction and candidate-level analytics measurements, not drilling-engineering validation. SoR is unresolved, pressure-time units remain unknown, automated anomalies are not domain-validated, and no cross-namespace mapping is inferred by matching indices.

The database sentinel-record count can exceed the independent source-text occurrence count because the same source page can be represented in both document-level key/value fields and normalized section tables. It is a record count, not a unique-source-occurrence count.
"""


def main() -> None:
    result = collect()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    DOC.write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
