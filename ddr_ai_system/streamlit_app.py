from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

# Streamlit Community Cloud executes this nested entrypoint directly instead of
# installing the local package. Keep imports deterministic in both deployment
# and editable-install environments.
SOURCE_ROOT = Path(__file__).resolve().parent / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ddr_ai.build_info import collect_build_info
from ddr_ai.config import resolve_settings, streamlit_secret_overrides
from ddr_ai.db.bootstrap import DatabaseBootstrapError, prepare_runtime_database
from ddr_ai.db.session import upgrade_schema
from ddr_ai.nlp.providers import select_provider
from ddr_ai.ui.pages import PAGES

LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="DDR Intelligence", page_icon="⛏️", layout="wide")


@st.cache_resource
def initialize_database(configured_url: str, sqlite_demo: bool) -> str:
    resolved_url = (
        prepare_runtime_database(configured_url, cloud_runtime=True)
        if sqlite_demo
        else configured_url
    )
    upgrade_schema(resolved_url)
    return resolved_url


def _secret_values() -> dict[str, object]:
    try:
        return streamlit_secret_overrides(st.secrets)
    except Exception:
        return {}


def main() -> None:
    settings = resolve_settings(_secret_values())
    try:
        database_url = initialize_database(settings.database_url, not settings.is_postgres)
    except DatabaseBootstrapError:
        LOGGER.exception("Database bootstrap validation failed")
        st.error("The demo database failed validation. The application cannot query unsafe data.")
        st.stop()
    except Exception:
        LOGGER.exception("Database initialization failed")
        st.error("Database initialization failed. Review the server log and deployment settings.")
        st.stop()

    selection = select_provider(settings)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("processed_upload_hashes", set())
    st.session_state.setdefault("last_question_time", 0.0)
    st.session_state.setdefault("question_count", 0)

    st.sidebar.title("DDR Intelligence")
    page_name = st.sidebar.radio("Workspace", list(PAGES))
    build = collect_build_info(database_url, settings, selection)
    with st.sidebar.expander("Build & runtime", expanded=False):
        for label, value in (
            ("Build", build.build_sha),
            ("App", build.app_version),
            ("Parser", build.parser_version),
            ("Database", f"{build.database_mode} / schema {build.database_revision}"),
            ("Seed", build.seed_version),
            ("Activity model", build.activity_model_version),
            ("Anomaly model", build.anomaly_model_version),
            ("Language model", f"{build.llm_mode} / {build.llm_model}"),
            ("Visual model", build.vlm_state),
        ):
            st.caption(f"{label}: {value}")
    page = PAGES[page_name]
    if page_name in {"Overview", "Upload & processing"}:
        page(database_url, settings)
    elif page_name == "Chat":
        page(database_url, settings, selection)
    else:
        page(database_url)


if __name__ == "__main__":
    main()
