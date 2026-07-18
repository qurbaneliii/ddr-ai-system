from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from ddr_ai.assets import render_image_safely
from ddr_ai.chat import answer_question
from ddr_ai.config import Settings, get_settings, streamlit_secret_overrides
from ddr_ai.db.models import (
    Anomaly,
    EquipmentFailure,
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
from ddr_ai.db.session import session_scope, upgrade_schema
from ddr_ai.ingestion.router import AssetKind, route_asset
from ddr_ai.ingestion.safe_zip import UnsafeArchiveError, safe_extract_zip
from ddr_ai.nlp.providers import ProviderSelection, provider_status, select_provider
from ddr_ai.services.failure_correlations import ensure_failure_correlations
from ddr_ai.services.processor import process_file

st.set_page_config(page_title="DDR Intelligence", page_icon="⛽", layout="wide")


def load_css(path: Path) -> None:
    """Load the app stylesheet from a path anchored to this source file."""
    st.markdown(f"<style>{path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


load_css(PROJECT_ROOT / "assets" / "styles.css")

try:
    _secret_overrides = streamlit_secret_overrides(st.secrets)
except Exception:
    _secret_overrides = {}
settings = Settings(**_secret_overrides) if _secret_overrides else get_settings()
settings.ensure_directories()


def _provider_fingerprint(config: Settings) -> str:
    token_present = bool(config.ollama_remote_auth_token.get_secret_value())
    material = "|".join([
        config.llm_provider,
        config.normalized_ollama_base_url,
        config.ollama_chat_model,
        config.ollama_embed_model,
        str(config.ollama_timeout_seconds),
        str(config.ollama_max_retries),
        str(token_present),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@st.cache_resource(show_spinner=False)
def initialize_provider(_settings: Settings, fingerprint: str) -> ProviderSelection:
    del fingerprint
    return select_provider(_settings)


provider_selection = initialize_provider(settings, _provider_fingerprint(settings))


@st.cache_resource
def initialize_database(database_url: str) -> None:
    if not database_url:
        raise RuntimeError("A database URL is required")
    upgrade_schema()
    with session_scope() as session:
        ensure_failure_correlations(session)


initialize_database(settings.database_url)


@st.cache_data(ttl=10)
def counts() -> dict[str, int]:
    with session_scope() as session:
        return {
            "documents": session.scalar(select(func.count(SourceDocument.id))) or 0,
            "reports": session.scalar(select(func.count(Report.id))) or 0,
            "operations": session.scalar(select(func.count(Operation.id))) or 0,
            "plots": session.scalar(select(func.count(Plot.id))) or 0,
            "anomalies": session.scalar(select(func.count(Anomaly.id))) or 0,
            "section_rows": session.scalar(select(func.count(SectionTableRow.id))) or 0,
            "equipment_failures": session.scalar(select(func.count(EquipmentFailure.id))) or 0,
            "failed": session.scalar(select(func.count(SourceDocument.id)).where(SourceDocument.processing_status == "failed")) or 0,
        }


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def empty_state() -> None:
    st.info("The database is empty. Run `python scripts/process_all.py` after the safe input bootstrap, or use Upload & Processing.")


def chat_messages() -> list[dict[str, Any]]:
    """Return the single, validated message list used across Streamlit reruns."""
    messages = st.session_state.get("chat_messages")
    valid = isinstance(messages, list) and all(
        isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
        for message in messages
    )
    if not valid:
        st.session_state["chat_messages"] = []
    return st.session_state["chat_messages"]


def render_chat_message(message: dict[str, Any], message_index: int) -> None:
    """Render a persisted user or assistant message with its supporting details."""
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "user":
            return

        st.caption(
            f"Provider: {message.get('provider', 'Lexical fallback')} · "
            f"model: {message.get('model') or 'none'} · route: {message['route']} · "
            f"language: {message.get('selected_language', 'en')} · "
            f"confidence {message['confidence']:.0%} · scope: {message['data_scope']}"
        )
        if message.get("fallback_reason"):
            st.info(f"Fallback reason: {message['fallback_reason']}")
        if message.get("retrieval_query"):
            with st.expander("English DDR retrieval representation"):
                st.write(message["retrieval_query"])
        if message["limitations"]:
            st.warning(" · ".join(message["limitations"]))
        if message["evidence"]:
            st.markdown("#### Evidence")
            for item in message["evidence"][:20]:
                st.markdown(
                    f'<div class="citation">{json.dumps(item, ensure_ascii=False, default=str)}</div>',
                    unsafe_allow_html=True,
                )
        if message["rows"]:
            frame = pd.DataFrame(message["rows"])
            st.dataframe(frame.fillna("Not available"), hide_index=True, use_container_width=True)
            csv_bytes = frame.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download complete result CSV",
                data=csv_bytes,
                file_name=message.get("export_filename") or "ddr_chat_result.csv",
                mime="text/csv",
                key=f"chat_csv_{message_index}",
            )
        if message["sql"]:
            with st.expander("Generated read-only SQL"):
                st.code(message["sql"], language="sql")
        if message.get("model_metrics"):
            with st.expander("Local model metrics"):
                st.json(message["model_metrics"])


PAGES = [
    "Overview Dashboard", "Upload & Processing", "Report Browser", "Activities & Operations",
    "Trends & Anomalies", "Pressure Profile Explorer", "Pressure-Time Explorer",
    "Identity / Mapping Review", "Chatbot", "System / Data Quality",
]
with st.sidebar:
    st.markdown("## DDR Intelligence")
    st.caption("Evidence-first drilling report workspace")
    page = st.radio("Workspace", PAGES, label_visibility="collapsed")
    st.divider()
    st.caption(f"Parser {settings.parser_version}")
    st.caption(provider_selection.provider.mode_label)
    st.caption(f"Model: {provider_selection.provider.model or 'none'}")

metrics = counts()

if page == "Overview Dashboard":
    hero("Operations evidence, made queryable", "Native PDF extraction, plot digitization, candidate analytics, and traceable answers.")
    cols = st.columns(6)
    for column, (label, value) in zip(cols, [("Documents", metrics["documents"]), ("DDR reports", metrics["reports"]),
        ("Operations", metrics["operations"]), ("Plots", metrics["plots"]),
        ("Candidates", metrics["anomalies"]), ("Failed", metrics["failed"])], strict=True):
        column.metric(label, f"{value:,}")
    if not metrics["documents"]:
        empty_state()
    else:
        with session_scope() as session:
            well_rows = session.execute(select(Report.wellbore, func.count(Report.id)).group_by(Report.wellbore)).all()
            section_rows = session.execute(select(ReportSection.section_type, func.count(ReportSection.id)).group_by(ReportSection.section_type)).all()
            status_rows = session.execute(select(SourceDocument.processing_status, func.count(SourceDocument.id)).group_by(SourceDocument.processing_status)).all()
            dates = session.execute(select(func.min(Report.period_end), func.max(Report.period_end))).one()
        left, right = st.columns([1.1, 1])
        with left:
            st.subheader("Reports by wellbore")
            frame = pd.DataFrame(well_rows, columns=["Wellbore", "Reports"])
            st.plotly_chart(px.bar(frame, x="Reports", y="Wellbore", orientation="h", color="Reports",
                                   color_continuous_scale=["#95c8bd", "#0b7a75"]), use_container_width=True)
        with right:
            st.subheader("Coverage and processing")
            st.write(f"Operational period: **{dates[0]}** to **{dates[1]}**")
            st.dataframe(pd.DataFrame(section_rows, columns=["Section", "Count"]), hide_index=True, use_container_width=True)
            st.dataframe(pd.DataFrame(status_rows, columns=["Status", "Count"]), hide_index=True, use_container_width=True)
        st.markdown('<div class="notice"><b>Interpretation boundary:</b> automated anomalies are candidates; pressure-time units and cross-namespace mappings remain unresolved unless reviewed evidence says otherwise.</div>', unsafe_allow_html=True)

elif page == "Upload & Processing":
    hero("Controlled ingestion", "Uploads are hashed, classified, and processed locally. ZIPs pass the same traversal, collision, link, executable, and size controls as the source bootstrap.")
    uploads = st.file_uploader("Upload PDF, PNG/JPEG/TIFF, or ZIP", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "zip"], accept_multiple_files=True)
    if uploads and st.button("Validate and process", type="primary"):
        upload_root = settings.processed_dir / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        progress = st.progress(0)
        results = []
        for index, upload in enumerate(uploads):
            data = upload.getvalue()
            if len(data) > settings.max_upload_mb * 1024 * 1024:
                results.append({"file": upload.name, "status": "rejected", "reason": "upload_size_limit"})
                continue
            digest = hashlib.sha256(data).hexdigest()
            safe_name = Path(upload.name).name
            target = upload_root / f"{digest[:12]}_{safe_name}"
            if not target.exists():
                with target.open("xb") as output:
                    output.write(data)
            try:
                decision = route_asset(target)
                if decision.kind == AssetKind.ZIP:
                    extracted = upload_root / digest
                    if not extracted.exists():
                        safe_extract_zip(target, extracted)
                    for child in sorted(extracted.rglob("*")):
                        if child.is_file() and route_asset(child).kind not in {AssetKind.ZIP, AssetKind.UNSUPPORTED}:
                            results.append(process_file(child))
                else:
                    results.append(process_file(target))
            except (UnsafeArchiveError, ValueError) as exc:
                results.append({"file": upload.name, "status": "rejected", "reason": str(exc)})
            progress.progress((index + 1) / len(uploads))
        counts.clear()
        st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
    with session_scope() as session:
        jobs = session.execute(select(ProcessingJob.status, ProcessingJob.job_type, ProcessingJob.duration_seconds,
                                      ProcessingJob.error_code).order_by(ProcessingJob.id.desc()).limit(50)).all()
    st.subheader("Recent processing jobs")
    st.dataframe(pd.DataFrame(jobs, columns=["Status", "Job", "Seconds", "Error code"]), hide_index=True, use_container_width=True)

elif page == "Report Browser":
    hero("Report browser", "Filter extracted reports, inspect source summaries and section-level provenance, and distinguish automated confidence from review state.")
    if not metrics["reports"]:
        empty_state()
    else:
        with session_scope() as session:
            wellbores = session.scalars(select(Report.wellbore).distinct().order_by(Report.wellbore)).all()
            selected_well = st.selectbox("Wellbore", wellbores)
            reports = session.execute(select(Report.id, Report.period_end, SourceDocument.file_name)
                                      .join(SourceDocument, SourceDocument.id == Report.source_document_id)
                                      .where(Report.wellbore == selected_well).order_by(Report.period_end.desc())).all()
            selected = st.selectbox("Report", reports, format_func=lambda row: f"{row[1]} · {row[2]}")
            report = session.get(Report, selected[0])
            document = session.get(SourceDocument, report.source_document_id)
            sections = session.scalars(select(ReportSection).where(ReportSection.report_id == report.id)
                                       .order_by(ReportSection.page_number, ReportSection.id)).all()
            operations = session.scalars(select(Operation).where(Operation.report_id == report.id)
                                         .order_by(Operation.row_index)).all()
            table_rows = session.scalars(select(SectionTableRow).where(
                SectionTableRow.report_id == report.id).order_by(
                    SectionTableRow.page_number, SectionTableRow.table_index,
                    SectionTableRow.row_index)).all()
        a, b, c, d = st.columns(4)
        a.metric("Period end", str(report.period_end.date()) if report.period_end else "Unknown")
        b.metric("Operations", len(operations))
        c.metric("Confidence", f"{report.confidence:.0%}")
        d.metric("Default trend", "Excluded" if report.excluded_from_default_trends else "Included")
        st.caption(f"Source: {document.file_name} · SHA-256 {document.sha256[:16]}…")
        left, right = st.columns(2)
        left.markdown("### Completed activities")
        left.write(report.summary_activities or "Unavailable")
        right.markdown("### Planned activities")
        right.write(report.summary_planned or "Unavailable")
        for section in sections:
            with st.expander(f"Page {section.page_number} · {section.heading_raw} · confidence {section.confidence:.0%}"):
                st.text(section.text or "No section text extracted")
        if operations:
            st.dataframe(pd.DataFrame([{"row": item.row_index, "page": item.page_number, "start": item.start_time_raw,
                "end": item.end_time_raw, "hours": item.duration_hours, "end_depth_mMD": item.end_depth_mmd,
                "activity": item.main_activity_normalized, "subactivity": item.sub_activity_normalized,
                "state": item.state_normalized, "remark": item.remark} for item in operations]), hide_index=True, use_container_width=True)
        if table_rows:
            with st.expander(f"Structured optional-section rows · {len(table_rows):,}"):
                st.dataframe(pd.DataFrame([{
                    "page": item.page_number, "section": item.section_type,
                    "table": item.table_index, "row": item.row_index,
                    "headers": item.header_cells_json, "raw_cells": item.raw_cells_json,
                    "normalized_cells": item.normalized_cells_json,
                    "confidence": item.confidence,
                } for item in table_rows]), hide_index=True, use_container_width=True)

elif page == "Activities & Operations":
    hero("Activities and operations", "Campaign-aware filtering, duration distributions, and direct inspection of weak fail-state evidence.")
    if not metrics["operations"]:
        empty_state()
    else:
        with session_scope() as session:
            rows = session.execute(select(Operation, Report).join(Report, Report.id == Operation.report_id)).all()
        frame = pd.DataFrame([{"wellbore": report.wellbore, "period_end": report.period_end,
            "start": operation.start_time_raw, "end": operation.end_time_raw, "hours": operation.duration_hours,
            "end_depth_mMD": operation.end_depth_mmd, "activity": operation.main_activity_normalized,
            "subactivity": operation.sub_activity_normalized, "state": operation.state_normalized,
            "remark": operation.remark} for operation, report in rows])
        wells = st.multiselect("Wellbores", sorted(frame.wellbore.dropna().unique()), default=[])
        state = st.selectbox("State", ["all", "fail", "ok"])
        filtered = frame
        if wells:
            filtered = filtered[filtered.wellbore.isin(wells)]
        if state != "all":
            filtered = filtered[filtered.state == state]
        chart = filtered.groupby("activity", dropna=False)["hours"].sum().reset_index().sort_values("hours", ascending=False)
        st.plotly_chart(px.bar(chart, x="activity", y="hours", color="hours", color_continuous_scale=["#a7d2c9", "#0b7a75"]), use_container_width=True)
        st.dataframe(filtered, hide_index=True, use_container_width=True, height=480)

elif page == "Trends & Anomalies":
    hero("Trends and anomaly candidates", "Evidence grouped by data quality, operational weak signals, numerical rules, and statistical descriptions—never relabeled as confirmed anomalies.")
    if not metrics["anomalies"]:
        empty_state()
    else:
        with session_scope() as session:
            anomalies = session.scalars(select(Anomaly).order_by(Anomaly.category, Anomaly.id)).all()
        frame = pd.DataFrame([{"id": item.id, "category": item.category, "rule": item.rule_or_model,
            "severity": item.severity_heuristic, "confidence": item.confidence,
            "validated": item.domain_validated, "status": item.validation_status,
            "explanation": item.explanation, "evidence": json.dumps(item.evidence_json, ensure_ascii=False)} for item in anomalies])
        category = st.multiselect("Category", sorted(frame.category.unique()))
        if category:
            frame = frame[frame.category.isin(category)]
        st.plotly_chart(px.histogram(frame, x="category", color="severity", barmode="group"), use_container_width=True)
        st.dataframe(frame, hide_index=True, use_container_width=True, height=520)

elif page == "Pressure Profile Explorer":
    hero("Pressure profile explorer", "Measured points, source curves, per-image calibration, debug overlays, and candidate band classifications.")
    with session_scope() as session:
        plots = session.scalars(select(Plot).where(Plot.plot_type == "pressure_profile").order_by(Plot.plot_identifier)).all()
        if not plots:
            empty_state()
        else:
            plot = st.selectbox("Profile", plots, format_func=lambda item: item.plot_identifier)
            document = session.get(SourceDocument, plot.source_document_id)
            points = session.scalars(select(PlotPoint).where(PlotPoint.plot_id == plot.id).order_by(PlotPoint.point_index)).all()
            left, right = st.columns(2)
            render_image_safely(
                left,
                document.source_path,
                caption=f"Source · {document.file_name}",
                asset_label="Source image",
            )
            render_image_safely(
                right,
                plot.overlay_path,
                caption="Detected plot area, markers, and candidate highlights",
                asset_label="Debug overlay",
            )
            frame = pd.DataFrame([{"point": item.point_index, "pressure_psi": item.x_value, "depth_ft": item.y_value,
                "band": item.band_classification, "candidate": item.anomaly_candidate,
                "confidence": item.confidence, **item.reference_values_json} for item in points])
            st.dataframe(frame, hide_index=True, use_container_width=True)
            st.caption(f"Calibration: {plot.calibration_json} · SoR remains undefined · candidate status requires domain review")

elif page == "Pressure-Time Explorer":
    hero("Pressure-time explorer", "Reconstructed sparse series with dynamic legend exclusion, robust trend-ready point tables, and an explicit unknown-unit boundary.")
    with session_scope() as session:
        plots = session.scalars(select(Plot).where(Plot.plot_type == "pressure_time").order_by(Plot.plot_identifier)).all()
        if not plots:
            empty_state()
        else:
            plot = st.selectbox("Comparison image", plots, format_func=lambda item: item.plot_identifier)
            document = session.get(SourceDocument, plot.source_document_id)
            points = session.scalars(select(PlotPoint).where(PlotPoint.plot_id == plot.id).order_by(PlotPoint.point_index)).all()
            left, right = st.columns(2)
            render_image_safely(
                left,
                document.source_path,
                caption="Source image",
                asset_label="Source image",
            )
            render_image_safely(
                right,
                plot.overlay_path,
                caption="Overlay · magenta legend exclusion",
                asset_label="Debug overlay",
            )
            frame = pd.DataFrame([{"series": item.series_identifier, "date": item.observed_date,
                "pressure_unknown_unit": item.y_value, "confidence": item.confidence} for item in points])
            figure = px.scatter(frame, x="date", y="pressure_unknown_unit", color="series", symbol="series")
            st.plotly_chart(figure, use_container_width=True)
            st.warning("Pressure unit is not stated in the source. Values are calibrated axis numbers with unit_status=unknown.")
            st.dataframe(frame, hide_index=True, use_container_width=True)

elif page == "Identity / Mapping Review":
    hero("Identity and mapping review", "Three incompatible namespaces stay unresolved until an explicit reviewer records authoritative evidence.")
    with session_scope() as session:
        mappings = session.scalars(select(IdentityMapping).order_by(IdentityMapping.source_namespace,
                                                                    IdentityMapping.source_identifier)).all()
    st.dataframe(pd.DataFrame([{"id": item.id, "source_namespace": item.source_namespace,
        "source_identifier": item.source_identifier, "target_namespace": item.target_namespace,
        "target_identifier": item.target_identifier, "status": item.mapping_status,
        "evidence": item.evidence, "confidence": item.confidence, "validation": item.validation_status,
        "reviewer": item.validated_by} for item in mappings]), hide_index=True, use_container_width=True, height=420)
    with st.form("mapping_form"):
        st.subheader("Create a reviewed mapping")
        cols = st.columns(2)
        source_namespace = cols[0].selectbox("Source namespace", ["ddr_wellbore", "pressure_profile", "pressure_time_plot", "displayed_series"])
        source_identifier = cols[1].text_input("Source identifier")
        target_namespace = cols[0].selectbox("Target namespace", ["ddr_wellbore", "pressure_profile", "pressure_time_plot", "displayed_series"])
        target_identifier = cols[1].text_input("Target identifier")
        evidence = st.text_area("Authoritative evidence / manifest reference")
        reviewer = st.text_input("Reviewer")
        submitted = st.form_submit_button("Save verified mapping", type="primary")
        if submitted:
            if not all([source_identifier.strip(), target_identifier.strip(), evidence.strip(), reviewer.strip()]):
                st.error("Identifiers, evidence, and reviewer are required.")
            else:
                with session_scope() as session:
                    session.add(IdentityMapping(source_namespace=source_namespace, source_identifier=source_identifier.strip(),
                        target_namespace=target_namespace, target_identifier=target_identifier.strip(),
                        mapping_status="verified", mapping_source="human_review", evidence=evidence.strip(),
                        confidence=1.0, validation_status="validated", validated_by=reviewer.strip(),
                        validated_at=datetime.now(UTC).replace(tzinfo=None), notes="Created through Streamlit mapping review."))
                st.success("Verified mapping saved with reviewer evidence.")

elif page == "Chatbot":
    hero("Grounded chatbot", "Structured SQL, narrative retrieval, plot evidence, and hybrid mapping answers—with route, citations, and limitations exposed.")
    st.caption("Examples: “How many operation rows were marked fail by wellbore?” · “Which wellbores had equipment failures, and what operational activities were being performed?” · “Which profile measurements are below MIN?” · “Are profile Well_15 and pressure_time_plot_15 related?”")
    controls, status_column = st.columns([1, 2])
    with controls:
        language_selection = st.selectbox(
            "Answer language",
            ["Auto", "Azərbaycan dili", "English"],
            key="chat_language",
        )
    with status_column:
        status = provider_status(settings, selection=provider_selection)
        st.markdown(
            f"**Active provider:** {status['active_label']}  \n"
            f"**Model:** {status['model'] or 'none'}  \n"
            f"**Ollama connection:** {'ready' if status['ollama_reachable'] else 'unreachable'}"
        )
        if status["fallback_reason"]:
            st.warning(f"Fallback is active: {status['fallback_reason']}")
    with st.expander("Ollama configuration help"):
        st.code(
            "ollama serve\n"
            "ollama pull qwen2.5:3b-instruct-q4_K_M\n"
            "python -m streamlit run streamlit_app.py",
            language="powershell",
        )
        st.caption(
            "Localhost needs no secret. Streamlit Community Cloud cannot reach Ollama on your "
            "laptop; public LLM responses require a separately authorized HTTPS endpoint behind "
            "an authentication proxy."
        )
    messages = chat_messages()
    for message_index, message in enumerate(messages):
        render_chat_message(message, message_index)

    question = st.chat_input("Ask the processed DDR and plot evidence")
    if question:
        user_message = {"role": "user", "content": question}
        messages.append(user_message)
        render_chat_message(user_message, len(messages) - 1)

        with session_scope() as session:
            response = answer_question(
                session,
                question,
                provider=provider_selection.provider,
                language=language_selection,
            )

        response_data = response.to_dict()
        assistant_message = {
            "role": "assistant",
            "content": response_data.pop("answer"),
            **response_data,
        }
        messages.append(assistant_message)
        render_chat_message(assistant_message, len(messages) - 1)

else:
    hero("System and data quality", "Parser version, database status, processing failures, environment providers, and exact local run guidance.")
    st.json({"database_url": settings.database_url, "parser_version": settings.parser_version,
             "raw_dir": str(settings.raw_dir.resolve()), "processed_dir": str(settings.processed_dir.resolve()),
             "provider": provider_status(settings, selection=provider_selection), "counts": metrics})
    with session_scope() as session:
        failed = session.scalars(select(SourceDocument).where(SourceDocument.processing_status == "failed")).all()
        jobs = session.scalars(select(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(100)).all()
    st.subheader("Failed documents")
    st.dataframe(pd.DataFrame([{"file": item.file_name, "route": item.asset_kind,
        "error": item.error_message} for item in failed]), hide_index=True, use_container_width=True)
    st.subheader("Recent jobs")
    st.dataframe(pd.DataFrame([{"id": item.id, "type": item.job_type, "status": item.status,
        "seconds": item.duration_seconds, "warnings": len(item.warnings_json), "error": item.error_code} for item in jobs]),
        hide_index=True, use_container_width=True)
    st.code(".\\.venv\\Scripts\\python.exe scripts\\process_all.py\n.\\.venv\\Scripts\\python.exe scripts\\evaluate_pipeline.py\n.\\.venv\\Scripts\\python.exe -m streamlit run streamlit_app.py", language="powershell")
