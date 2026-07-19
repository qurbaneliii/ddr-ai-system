from __future__ import annotations

import logging
import mimetypes
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ddr_ai.assets import PROJECT_ROOT, SUPPORTED_IMAGE_EXTENSIONS, portable_asset_path
from ddr_ai.common.hashing import sha256_file
from ddr_ai.config import Settings
from ddr_ai.db.models import (
    Anomaly,
    ExtractedValue,
    IdentityMapping,
    Operation,
    Page,
    Plot,
    PlotPoint,
    ProcessingJob,
    Report,
    ReportSection,
    SourceDocument,
)
from ddr_ai.db.session import session_scope
from ddr_ai.ingestion.router import AssetKind, route_asset
from ddr_ai.pdf.ocr import BaseOCRBackend, parse_scanned_pdf
from ddr_ai.pdf.parser import parse_ddr_pdf
from ddr_ai.plots import digitize_pressure_profile, digitize_pressure_time
from ddr_ai.retrieval.corpus import replace_document_chunks
from ddr_ai.services.asset_storage import persist_asset_record
from ddr_ai.services.failure_correlations import replace_report_correlations

LOGGER = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    del exc
    return "Processing failed. Review the server log for the error category."


def _source_for_path(
    session: Session,
    path: Path,
    sha256: str,
    asset_kind: str,
    settings: Settings,
) -> tuple[SourceDocument, bool]:
    stored_path = (
        portable_asset_path(path)
        if path.suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS
        else str(path.resolve())
    )
    existing = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha256))
    if existing:
        existing.source_path = stored_path
        unchanged = existing.processing_status == "complete"
        return existing, unchanged
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    source = SourceDocument(
        sha256=sha256,
        file_name=path.name,
        source_path=stored_path,
        media_type=media_type,
        asset_kind=asset_kind,
        byte_size=path.stat().st_size,
        parser_version=settings.parser_version,
        processing_status="pending",
    )
    session.add(source)
    session.flush()
    return source, False


def _persist_report(session: Session, source: SourceDocument, parsed: Any) -> None:
    source.page_count = len(parsed.pages)
    source.metadata_json = {
        **parsed.metadata,
        "pdf_version": parsed.pdf_version,
        "sentinel_count": parsed.sentinel_count,
    }
    for item in parsed.pages:
        session.add(
            Page(
                source_document_id=source.id,
                page_number=item.page_number,
                width=item.width,
                height=item.height,
                native_character_count=item.native_character_count,
                deduplicated_character_count=item.deduplicated_character_count,
                raw_text=item.text,
                extraction_method=item.extraction_method,
                confidence=item.confidence,
            )
        )
    report = Report(
        source_document_id=source.id,
        wellbore=parsed.wellbore,
        filename_wellbore=parsed.filename_wellbore,
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        filename_date=parsed.filename_date,
        spud_date=parsed.spud_date,
        report_number=parsed.report_number,
        status_raw=parsed.status_raw,
        summary_activities=parsed.summary_activities,
        summary_planned=parsed.summary_planned,
        filename_identity_match=parsed.filename_identity_match,
        filename_date_match=parsed.filename_date_match,
        excluded_from_default_trends=parsed.excluded_from_default_trends,
        data_quality_status="candidate_warning" if parsed.warnings else "passed_automated_checks",
        confidence=0.98,
    )
    session.add(report)
    session.flush()
    for item in parsed.sections:
        session.add(
            ReportSection(
                report_id=report.id,
                section_type=item.section_type,
                heading_raw=item.heading_raw,
                page_number=item.page_number,
                text=item.text,
                row_count=item.row_count,
                bbox_json=None
                if item.bbox is None
                else dict(zip(("x0", "top", "x1", "bottom"), item.bbox, strict=True)),
                confidence=item.confidence,
            )
        )
    for item in parsed.operations:
        session.add(
            Operation(
                report_id=report.id,
                row_index=item.row_index,
                page_number=item.page_number,
                start_time_raw=item.start_time_raw,
                end_time_raw=item.end_time_raw,
                duration_hours=item.duration_hours,
                end_depth_mmd_raw=item.end_depth_raw,
                end_depth_mmd=item.end_depth_mmd,
                end_depth_missing_reason=item.end_depth_missing_reason,
                main_activity_raw=item.main_activity_raw,
                sub_activity_raw=item.sub_activity_raw,
                main_activity_normalized=item.main_activity_normalized,
                sub_activity_normalized=item.sub_activity_normalized,
                state_raw=item.state_raw,
                state_normalized=item.state_normalized,
                remark=item.remark,
                start_datetime=item.start_datetime,
                end_datetime=item.end_datetime,
                temporal_status=item.temporal_status,
                temporal_ambiguity=item.temporal_ambiguity,
                raw_values_json=item.raw_values,
                normalized_values_json=item.normalized_values,
                bbox_json=None
                if item.bbox is None
                else dict(zip(("x0", "top", "x1", "bottom"), item.bbox, strict=True)),
                confidence=item.confidence,
            )
        )
    session.flush()
    replace_report_correlations(session, report, parsed.equipment_failures)
    for item in parsed.fields:
        bbox = item.provenance.bbox
        session.add(
            ExtractedValue(
                source_document_id=source.id,
                page_number=item.provenance.page_number,
                section_type=item.provenance.section,
                field_name=item.field_name,
                raw_value=item.raw_value,
                normalized_text=item.normalized_text,
                normalized_number=item.normalized_number,
                unit_raw=item.unit_raw,
                unit_normalized=item.unit_normalized,
                missing_reason=item.missing_reason,
                bbox_json=None
                if bbox is None
                else dict(zip(("x0", "top", "x1", "bottom"), bbox, strict=True)),
                confidence=item.confidence,
            )
        )
    for warning in parsed.warnings:
        session.add(
            Anomaly(
                source_document_id=source.id,
                source_record_type="report",
                source_record_id=report.id,
                category="source_data_quality",
                rule_or_model=str(warning["code"]),
                evidence_json=warning,
                score=1.0,
                severity_heuristic=str(warning.get("severity", "medium")),
                confidence=1.0,
                threshold_json={},
                domain_validated=False,
                explanation="Automated data-quality candidate; requires human/domain review.",
            )
        )


def _unresolved_mapping(
    session: Session,
    source_namespace: str,
    source_identifier: str,
    target_namespace: str,
    note: str,
) -> None:
    existing = session.scalar(
        select(IdentityMapping).where(
            IdentityMapping.source_namespace == source_namespace,
            IdentityMapping.source_identifier == source_identifier,
            IdentityMapping.target_namespace == target_namespace,
            IdentityMapping.target_identifier == "unresolved",
        )
    )
    if not existing:
        session.add(
            IdentityMapping(
                source_namespace=source_namespace,
                source_identifier=source_identifier,
                target_namespace=target_namespace,
                target_identifier="unresolved",
                mapping_status="unresolved",
                mapping_source="no_manifest_or_metadata",
                evidence="No authoritative mapping metadata was supplied.",
                confidence=0.0,
                validation_status="unreviewed",
                notes=note,
            )
        )


def _persist_plot(session: Session, source: SourceDocument, result: dict[str, Any]) -> None:
    overlay_path = result.get("overlay_path")
    plot = Plot(
        source_document_id=source.id,
        plot_type=result["plot_type"],
        plot_identifier=result["plot_identifier"],
        width=result["width"],
        height=result["height"],
        plot_bbox_json=result["plot_bbox"],
        x_axis_label=result["x_axis_label"],
        y_axis_label=result["y_axis_label"],
        x_unit=result["x_unit"],
        y_unit=result["y_unit"],
        unit_status=result["unit_status"],
        calibration_json=result["calibration"],
        confidence=result["confidence"],
        overlay_path=portable_asset_path(overlay_path) if overlay_path else None,
        warnings_json=result["warnings"],
    )
    session.add(plot)
    session.flush()
    for item in result["points"]:
        observed = item.get("observed_date")
        session.add(
            PlotPoint(
                plot_id=plot.id,
                point_index=item["point_index"],
                series_identifier=item["series_identifier"],
                pixel_x=item["pixel_x"],
                pixel_y=item["pixel_y"],
                x_value=item.get("pressure") if result["plot_type"] == "pressure_profile" else None,
                y_value=item.get("depth")
                if result["plot_type"] == "pressure_profile"
                else item.get("pressure"),
                observed_date=date.fromisoformat(observed) if observed else None,
                reference_values_json=item.get("reference_values", {}),
                band_classification=item.get("band_classification"),
                anomaly_candidate=item.get("anomaly_candidate", False),
                confidence=item["confidence"],
                source_bbox_json=item["source_bbox"],
            )
        )
        if item.get("anomaly_candidate"):
            session.add(
                Anomaly(
                    source_document_id=source.id,
                    source_record_type="plot_point",
                    source_record_id=None,
                    category="profile_reference_band_candidate",
                    rule_or_model="pixel_curve_relative_position",
                    evidence_json={"plot": result["plot_identifier"], "point": item},
                    score=1.0,
                    severity_heuristic="medium",
                    confidence=item["confidence"],
                    threshold_json={},
                    domain_validated=False,
                    explanation=f"Measured marker classified as {item['band_classification']}; candidate only.",
                )
            )
    if result["plot_type"] == "pressure_profile":
        _unresolved_mapping(
            session,
            "pressure_profile",
            result["plot_identifier"],
            "ddr_wellbore",
            "Generic profile identifiers must not be mapped to DDR wellbores by index.",
        )
        _unresolved_mapping(
            session,
            "pressure_profile",
            result["plot_identifier"],
            "pressure_time_plot",
            "Profile and pressure-time filename indices are not established as identities.",
        )
    else:
        _unresolved_mapping(
            session,
            "pressure_time_plot",
            result["plot_identifier"],
            "pressure_profile",
            "Pressure-time filename index must not be mapped to a profile index.",
        )
        _unresolved_mapping(
            session,
            "pressure_time_plot",
            result["plot_identifier"],
            "ddr_wellbore",
            "Repeated displayed series are generic and not linked to DDR wellbores.",
        )


def process_file(
    path: str | Path,
    *,
    database_url: str,
    settings: Settings,
    ocr_backend: BaseOCRBackend | None = None,
) -> dict[str, Any]:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path
    source_path = source_path.resolve()
    decision = route_asset(source_path)
    digest = sha256_file(source_path)
    started = time.perf_counter()
    with session_scope(database_url) as session:
        source, unchanged = _source_for_path(
            session, source_path, digest, decision.kind.value, settings
        )
        if unchanged:
            return {"path": str(source_path), "status": "skipped_unchanged", "sha256": digest}
        job = ProcessingJob(
            source_document_id=source.id,
            job_type=f"process_{decision.kind.value}",
            status="running",
            parser_version=settings.parser_version,
        )
        session.add(job)
        session.flush()
        try:
            with session.begin_nested():
                if decision.kind == AssetKind.DIGITAL_PDF:
                    _persist_report(session, source, parse_ddr_pdf(source_path))
                elif decision.kind == AssetKind.SCANNED_PDF:
                    _persist_report(
                        session,
                        source,
                        parse_scanned_pdf(source_path, backend=ocr_backend),
                    )
                elif decision.kind == AssetKind.PRESSURE_PROFILE:
                    overlay = (
                        settings.processed_dir / "overlays" / f"{source_path.stem}_overlay.png"
                    )
                    _persist_plot(session, source, digitize_pressure_profile(source_path, overlay))
                elif decision.kind == AssetKind.PRESSURE_TIME:
                    overlay = (
                        settings.processed_dir / "overlays" / f"{source_path.stem}_overlay.png"
                    )
                    _persist_plot(session, source, digitize_pressure_time(source_path, overlay))
                else:
                    raise ValueError(f"Unsupported processing route: {decision.kind.value}")
            source.processing_status = "complete"
            source.processed_at = datetime.now(UTC).replace(tzinfo=None)
            source.warning_count = 0
            session.flush()
            replace_document_chunks(session, source.id)
            persist_asset_record(session, source, source_path, settings)
            job.status = "complete"
        except Exception as exc:
            LOGGER.exception("Asset processing failed (%s)", decision.kind.value)
            message = _safe_error(exc)
            source.processing_status = "failed"
            source.error_message = message
            job.status = "failed"
            job.error_code = type(exc).__name__[:128]
            job.error_message = message
        job.finished_at = datetime.now(UTC).replace(tzinfo=None)
        job.duration_seconds = round(time.perf_counter() - started, 4)
        return {
            "path": str(source_path),
            "status": job.status,
            "sha256": digest,
            "duration_seconds": job.duration_seconds,
            "error": job.error_message,
        }


def process_paths(
    paths: list[Path], *, database_url: str, settings: Settings
) -> list[dict[str, Any]]:
    return [process_file(path, database_url=database_url, settings=settings) for path in paths]
