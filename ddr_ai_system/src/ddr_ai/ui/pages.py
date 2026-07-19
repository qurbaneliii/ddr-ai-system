from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from ddr_ai.chat.service import answer_question
from ddr_ai.config import Settings
from ddr_ai.db.models import (
    Anomaly,
    IdentityMapping,
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
from ddr_ai.ingestion.safe_zip import UnsafeArchiveError, inspect_zip, safe_extract_zip
from ddr_ai.nlp.providers import ProviderSelection, provider_status
from ddr_ai.services.processor import process_file
from ddr_ai.ui.components import header, render_chat_message, render_plot_images, safe_metric

LOGGER = logging.getLogger(__name__)


def _count(database_url: str, model: type[Any]) -> int:
    with session_scope(database_url) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def overview(database_url: str, settings: Settings) -> None:
    header("DDR Intelligence", "Evidence-first Daily Drilling Report analytics")
    columns = st.columns(4)
    metrics = [
        ("Source documents", SourceDocument),
        ("Reports", Report),
        ("Operations", Operation),
        ("Plot points", PlotPoint),
    ]
    for column, (label, model) in zip(columns, metrics, strict=True):
        with column:
            safe_metric(label, partial(_count, database_url, model))
    st.info(
        f"Persistence mode: {settings.persistence_mode}. "
        + (
            "Extracted upload records persist across redeployments. Raw files require separate object storage."
            if settings.is_postgres
            else "Uploads are processed into a temporary runtime snapshot and do not survive restart."
        )
    )
    try:
        with session_scope(database_url) as session:
            rows = session.execute(
                select(Report.wellbore, func.count(Report.id))
                .group_by(Report.wellbore)
                .order_by(func.count(Report.id).desc())
                .limit(20)
            ).all()
        frame = pd.DataFrame(rows, columns=["Wellbore", "Reports"])
        if not frame.empty:
            st.plotly_chart(
                px.bar(frame, x="Reports", y="Wellbore", orientation="h"),
                use_container_width=True,
            )
    except Exception:
        LOGGER.exception("Overview chart failed")
        st.warning("Report coverage is temporarily unavailable.")


def reports(database_url: str) -> None:
    header("Report browser", "Stored text, sections, tables, operations, and provenance")
    with session_scope(database_url) as session:
        wellbores = list(
            session.scalars(select(Report.wellbore).distinct().order_by(Report.wellbore))
        )
    wellbores = [item for item in wellbores if item]
    if not wellbores:
        st.info("No reports are available.")
        return
    selected_well = st.selectbox("Wellbore", wellbores)
    with session_scope(database_url) as session:
        choices = session.execute(
            select(Report.id, Report.period_end, SourceDocument.file_name)
            .join(SourceDocument, SourceDocument.id == Report.source_document_id)
            .where(Report.wellbore == selected_well)
            .order_by(Report.period_end.desc())
        ).all()
    selected = st.selectbox(
        "Report",
        choices,
        format_func=lambda row: f"{row[1] or 'unknown date'} · {row[2]}",
    )
    with session_scope(database_url) as session:
        report = session.get(Report, selected[0])
        document = session.get(SourceDocument, report.source_document_id) if report else None
        sections = list(
            session.scalars(
                select(ReportSection)
                .where(ReportSection.report_id == selected[0])
                .order_by(ReportSection.page_number)
            )
        )
        operations = list(
            session.scalars(
                select(Operation)
                .where(Operation.report_id == selected[0])
                .order_by(Operation.row_index)
            )
        )
        table_rows = list(
            session.scalars(
                select(SectionTableRow).where(SectionTableRow.report_id == selected[0]).limit(500)
            )
        )
    if report is None or document is None:
        st.warning("The selected report is unavailable.")
        return
    st.caption(f"Source: {document.file_name} · SHA-256 {document.sha256[:16]}…")
    st.write(report.summary_activities or "No source activity summary was extracted.")
    for section in sections:
        with st.expander(f"Page {section.page_number} · {section.heading_raw}"):
            st.write(section.text or "No text extracted.")
    if operations:
        st.subheader("Operations")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "row": item.row_index,
                        "page": item.page_number,
                        "start": item.start_time_raw,
                        "end": item.end_time_raw,
                        "hours": item.duration_hours,
                        "activity": item.main_activity_normalized,
                        "state": item.state_normalized,
                        "remark": item.remark,
                    }
                    for item in operations
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    if table_rows:
        with st.expander(f"Normalized optional-section table rows · {len(table_rows):,}"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "page": item.page_number,
                            "section": item.section_type,
                            "table": item.table_index,
                            "row": item.row_index,
                            "cells": item.raw_cells_json,
                        }
                        for item in table_rows
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )


def activities(database_url: str) -> None:
    header("Activities", "Normalized operational events and durations")
    with session_scope(database_url) as session:
        rows = session.execute(
            select(
                Report.wellbore,
                Report.period_end,
                Operation.main_activity_normalized,
                Operation.sub_activity_normalized,
                Operation.duration_hours,
                Operation.state_normalized,
                Operation.remark,
            )
            .join(Report, Report.id == Operation.report_id)
            .limit(5000)
        ).all()
    frame = pd.DataFrame(
        rows,
        columns=["wellbore", "date", "activity", "sub_activity", "hours", "state", "remark"],
    )
    if frame.empty:
        st.info("No operation rows are available.")
        return
    state = st.selectbox("State", ["all", "fail", "ok"])
    filtered = frame if state == "all" else frame[frame["state"] == state]
    chart = filtered.groupby("activity", dropna=False)["hours"].sum().reset_index()
    st.plotly_chart(px.bar(chart, x="activity", y="hours"), use_container_width=True)
    st.dataframe(filtered, hide_index=True, use_container_width=True, height=480)


def trends(database_url: str) -> None:
    header("Trends and anomaly candidates", "Candidate-level signals requiring domain review")
    with session_scope(database_url) as session:
        rows = session.execute(
            select(
                Anomaly.category,
                Anomaly.rule_or_model,
                Anomaly.severity_heuristic,
                Anomaly.confidence,
                Anomaly.domain_validated,
                Anomaly.explanation,
            ).limit(5000)
        ).all()
    frame = pd.DataFrame(
        rows,
        columns=["category", "rule", "severity", "confidence", "domain_validated", "explanation"],
    )
    if frame.empty:
        st.info("No anomaly candidates are available.")
        return
    st.warning("Automated anomalies are candidates, not confirmed incidents.")
    chart = frame.groupby(["category", "severity"]).size().reset_index(name="count")
    st.plotly_chart(
        px.bar(chart, x="category", y="count", color="severity"), use_container_width=True
    )
    st.dataframe(frame, hide_index=True, use_container_width=True, height=520)


def plots(database_url: str) -> None:
    header("Pressure plots", "Deterministic CV measurements, overlays, and unit boundaries")
    tab_profile, tab_time = st.tabs(["Pressure profiles", "Pressure-time"])
    for container, plot_type in ((tab_profile, "pressure_profile"), (tab_time, "pressure_time")):
        with container:
            with session_scope(database_url) as session:
                choices = list(
                    session.scalars(
                        select(Plot)
                        .where(Plot.plot_type == plot_type)
                        .order_by(Plot.plot_identifier)
                    )
                )
            if not choices:
                st.info("No plots of this type are available.")
                continue
            identifier = st.selectbox(
                "Plot",
                [item.plot_identifier for item in choices],
                key=f"plot-select-{plot_type}",
            )
            with session_scope(database_url) as session:
                row = session.execute(
                    select(Plot, SourceDocument)
                    .join(SourceDocument, SourceDocument.id == Plot.source_document_id)
                    .where(Plot.plot_identifier == identifier)
                ).one()
                plot, document = row
                points = list(
                    session.scalars(
                        select(PlotPoint)
                        .where(PlotPoint.plot_id == plot.id)
                        .order_by(PlotPoint.point_index)
                    )
                )
            render_plot_images(document.source_path, plot.overlay_path)
            st.caption(
                f"{plot.plot_identifier} · {len(points)} points · unit status: {plot.unit_status} · "
                f"confidence {plot.confidence:.0%}"
            )
            frame = pd.DataFrame(
                [
                    {
                        "series": point.series_identifier,
                        "date": point.observed_date,
                        "x": point.x_value,
                        "y": point.y_value,
                        "band": point.band_classification,
                        "candidate": point.anomaly_candidate,
                        "confidence": point.confidence,
                    }
                    for point in points
                ]
            )
            if plot_type == "pressure_time" and not frame.empty:
                st.plotly_chart(
                    px.line(frame, x="date", y="y", color="series", markers=True),
                    use_container_width=True,
                )
                st.warning(
                    "The pressure-time unit is unknown. Numeric axis values are not labeled PSI or another unit."
                )
            st.dataframe(frame, hide_index=True, use_container_width=True)
            with st.expander("Calibration, provenance, and warnings"):
                st.json(
                    {
                        "source_file": document.file_name,
                        "plot_bbox": plot.plot_bbox_json,
                        "calibration": plot.calibration_json,
                        "x_unit": plot.x_unit,
                        "y_unit": plot.y_unit,
                        "unit_status": plot.unit_status,
                        "warnings": plot.warnings_json,
                    }
                )


def mappings(database_url: str) -> None:
    header("Identity mappings", "Reviewer-controlled links; numeric indices are never assumed")
    with session_scope(database_url) as session:
        rows = list(
            session.scalars(select(IdentityMapping).order_by(IdentityMapping.id.desc()).limit(500))
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "source": f"{item.source_namespace}:{item.source_identifier}",
                    "target": f"{item.target_namespace}:{item.target_identifier}",
                    "status": item.mapping_status,
                    "evidence": item.evidence,
                    "reviewer": item.validated_by,
                }
                for item in rows
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    with st.form("verified-mapping"):
        source_namespace = st.text_input("Source namespace")
        source_identifier = st.text_input("Source identifier")
        target_namespace = st.text_input("Target namespace")
        target_identifier = st.text_input("Target identifier")
        evidence = st.text_area("Authoritative evidence")
        reviewer = st.text_input("Reviewer")
        submitted = st.form_submit_button("Save verified mapping", type="primary")
    if submitted:
        values = [
            source_namespace,
            source_identifier,
            target_namespace,
            target_identifier,
            evidence,
            reviewer,
        ]
        if not all(value.strip() for value in values):
            st.error("Every mapping field is required.")
        else:
            with session_scope(database_url) as session:
                session.add(
                    IdentityMapping(
                        source_namespace=source_namespace.strip(),
                        source_identifier=source_identifier.strip(),
                        target_namespace=target_namespace.strip(),
                        target_identifier=target_identifier.strip(),
                        mapping_status="verified",
                        mapping_source="human_review",
                        evidence=evidence.strip(),
                        confidence=1.0,
                        validation_status="validated",
                        validated_by=reviewer.strip(),
                    )
                )
            st.success("Verified mapping saved with reviewer evidence.")


def _safe_name(name: str) -> str:
    base = Path(name).name
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return normalized[:180] or "upload.bin"


def uploads(database_url: str, settings: Settings) -> None:
    header("Upload and process", "One submission validates, deduplicates, and processes each file")
    if not settings.is_postgres:
        st.warning("SQLite demo mode: extracted upload data is temporary and is lost on restart.")
    with st.form("upload-and-process", clear_on_submit=True):
        uploaded = st.file_uploader(
            "PDF, pressure image, or safe ZIP",
            type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "zip"],
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("Upload and process", type="primary")
    if submitted:
        if not uploaded:
            st.warning("Select at least one supported file.")
        else:
            results: list[dict[str, Any]] = []
            progress = st.progress(0)
            with tempfile.TemporaryDirectory(prefix="ddr-upload-") as temporary:
                root = Path(temporary)
                candidates: list[Path] = []
                for item in uploaded:
                    content = item.getvalue()
                    if len(content) > settings.max_upload_mb * 1024 * 1024:
                        results.append({"file": item.name, "status": "rejected_size_limit"})
                        continue
                    digest = hashlib.sha256(content).hexdigest()
                    if digest in st.session_state.processed_upload_hashes:
                        results.append({"file": item.name, "status": "skipped_session_duplicate"})
                        continue
                    path = root / _safe_name(item.name)
                    path.write_bytes(content)
                    st.session_state.processed_upload_hashes.add(digest)
                    if path.suffix.casefold() == ".zip":
                        extract_root = root / f"extract-{digest[:12]}"
                        try:
                            inspect_zip(
                                path,
                                max_files=500,
                                max_uncompressed_bytes=settings.max_upload_mb * 10 * 1024 * 1024,
                                max_entry_bytes=settings.max_upload_mb * 1024 * 1024,
                            )
                            safe_extract_zip(path, extract_root)
                            candidates.extend(
                                file
                                for file in extract_root.rglob("*")
                                if file.is_file() and file.suffix.casefold() != ".zip"
                            )
                        except (UnsafeArchiveError, OSError):
                            LOGGER.exception("Unsafe or unreadable upload archive")
                            results.append({"file": item.name, "status": "rejected_unsafe_archive"})
                    else:
                        candidates.append(path)
                for index, candidate in enumerate(candidates, start=1):
                    results.append(
                        process_file(
                            candidate,
                            database_url=database_url,
                            settings=settings,
                        )
                    )
                    progress.progress(index / max(len(candidates), 1))
            if any(item.get("status") in {"complete", "skipped_unchanged"} for item in results):
                st.cache_data.clear()
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
    with session_scope(database_url) as session:
        jobs = session.execute(
            select(ProcessingJob.status, ProcessingJob.job_type, ProcessingJob.duration_seconds)
            .order_by(ProcessingJob.id.desc())
            .limit(20)
        ).all()
    st.subheader("Recent processing jobs")
    st.dataframe(pd.DataFrame(jobs, columns=["status", "job", "seconds"]), hide_index=True)


def chat(database_url: str, settings: Settings, selection: ProviderSelection) -> None:
    header(
        "Grounded chatbot", "Deterministic SQL/text/plot facts with optional OpenAI verbalization"
    )
    status = provider_status(settings, selection=selection)
    st.caption(
        f"Provider: {status['active_label']}"
        + (f" · model {status['model']}" if status.get("model") else "")
    )
    if status.get("fallback_reason"):
        st.info(f"Deterministic fallback is active: {status['fallback_reason']}")
    col_language, col_clear = st.columns([3, 1])
    with col_language:
        language = st.selectbox("Answer language", ["Auto", "Azərbaycan dili", "English"])
    with col_clear:
        if st.button("Clear chat"):
            st.session_state.chat_history = []
            st.rerun()
    for index, message in enumerate(st.session_state.chat_history):
        render_chat_message(message, index)
    question = st.chat_input(
        "Ask about reports, activities, failures, summaries, or pressure plots"
    )
    if not question:
        return
    if len(question) > settings.max_question_chars:
        st.error(f"Question limit is {settings.max_question_chars:,} characters.")
        return
    if st.session_state.question_count >= settings.session_question_limit:
        st.error("This session reached its question limit. Clear chat or start a new session.")
        return
    elapsed = time.monotonic() - st.session_state.last_question_time
    if elapsed < settings.question_cooldown_seconds:
        st.warning("Please wait briefly before submitting another question.")
        return
    st.session_state.last_question_time = time.monotonic()
    st.session_state.question_count += 1
    st.session_state.chat_history.append({"role": "user", "content": question})
    try:
        with session_scope(database_url) as session:
            answer = answer_question(
                session,
                question,
                provider=selection.provider,
                language=language,
            )
        st.session_state.chat_history.append(
            {"role": "assistant", "content": answer.answer, **answer.to_dict()}
        )
    except Exception:
        LOGGER.exception("Chat request failed")
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": "The question could not be completed safely. Please try again.",
                "answer_type": "deterministic",
                "route": "error",
                "limitations": ["Detailed errors are available only in the server log."],
            }
        )
    st.session_state.chat_history = st.session_state.chat_history[-settings.max_chat_history :]
    st.rerun()


PAGES = {
    "Overview": overview,
    "Report browser": reports,
    "Activities": activities,
    "Trends & anomalies": trends,
    "Pressure plots": plots,
    "Identity mappings": mappings,
    "Upload & processing": uploads,
    "Chat": chat,
}
