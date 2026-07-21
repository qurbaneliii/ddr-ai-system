from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import pandas as pd
import streamlit as st

from ddr_ai.assets import ImageTarget, render_image_safely

LOGGER = logging.getLogger(__name__)


def header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)


def safe_metric(label: str, loader: Callable[[], int], *, suffix: str = "") -> None:
    try:
        value = loader()
        st.metric(label, f"{value:,}{suffix}")
    except Exception:
        LOGGER.exception("Metric failed: %s", label)
        st.metric(label, "Unavailable")


def render_plot_images(source_path: str | None, overlay_path: str | None) -> None:
    source_column, overlay_column = st.columns(2)
    with source_column:
        render_image_safely(
            cast(ImageTarget, st),
            source_path,
            caption="Source image",
            asset_label="Source image",
        )
    with overlay_column:
        render_image_safely(
            cast(ImageTarget, st),
            overlay_path,
            caption="Deterministic CV overlay",
            asset_label="CV overlay",
        )


def render_chat_message(message: dict[str, Any], index: int) -> None:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] != "assistant":
            return
        st.caption(
            f"Answer type: {message.get('answer_type', 'deterministic')} · "
            f"Route: {message.get('route', 'unknown')}"
        )
        if message.get("retrieval_source_types") or message.get("evidence_hit_count"):
            sources = ", ".join(message.get("retrieval_source_types") or []) or "structured facts"
            st.caption(
                f"Evidence hits: {message.get('evidence_hit_count', 0)} · Sources: {sources} · "
                f"Corpus: {message.get('corpus_status', 'ready')}"
            )
        if message.get("fallback_reason"):
            st.info(f"Fallback: {message['fallback_reason']}")
        if message.get("selected_plot_identifier"):
            st.caption(
                f"Selected plot: {message['selected_plot_identifier']} · "
                f"Visual validation: {message.get('visual_validation_status', 'not_requested')}"
            )
            if message.get("visual_provider"):
                st.caption(
                    f"Visual provider: {message['visual_provider']}"
                    + (
                        f" · model {message['visual_model']}"
                        if message.get("visual_model")
                        else ""
                    )
                )
        if message.get("limitations"):
            with st.expander("Limitations"):
                for limitation in message["limitations"]:
                    st.write(f"- {limitation}")
        if message.get("evidence"):
            with st.expander("Citations and evidence"):
                st.json(message["evidence"])
        if message.get("rows"):
            frame = pd.DataFrame(message["rows"])
            with st.expander("Deterministic result rows"):
                st.dataframe(
                    frame.fillna("Not available"), hide_index=True, use_container_width=True
                )
                st.download_button(
                    "Download result CSV",
                    frame.to_csv(index=False).encode("utf-8-sig"),
                    file_name=message.get("export_filename") or f"chat-result-{index}.csv",
                    mime="text/csv",
                    key=f"chat-download-{index}",
                )
        if message.get("sql"):
            with st.expander("Generated read-only SQL"):
                st.code(message["sql"], language="sql")
        if message.get("rewritten_query") or message.get("query_plan"):
            with st.expander("Query interpretation (debug)"):
                if message.get("rewritten_query"):
                    st.write(f"Standalone query: {message['rewritten_query']}")
                if message.get("query_plan"):
                    st.json(message["query_plan"])
                if message.get("retrieval_diagnostics"):
                    st.json(message["retrieval_diagnostics"])
