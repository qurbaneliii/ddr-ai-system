from __future__ import annotations

import shutil
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ddr_ai.config import get_settings
from ddr_ai.db.session import dispose_all_engines


def configure_test_database(monkeypatch, tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "data" / "processed" / "ddr_ai.db"
    target = tmp_path / "streamlit.db"
    shutil.copy2(source, target)
    monkeypatch.setenv("DDR_DATABASE_URL", f"sqlite:///{target.as_posix()}")
    get_settings.cache_clear()
    dispose_all_engines()


def test_streamlit_app_starts_with_lexical_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "lexical")
    configure_test_database(monkeypatch, tmp_path)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert app.title or app.markdown


def test_chat_history_survives_page_reruns(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "lexical")
    configure_test_database(monkeypatch, tmp_path)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio[0].set_value("Chat").run()
    app.session_state["chat_history"] = [
        {"role": "user", "content": "Persist this question"},
        {
            "role": "assistant",
            "content": "Persist this answer",
            "route": "test",
            "confidence": 1.0,
            "data_scope": "test fixture",
            "limitations": [],
            "evidence": [],
            "rows": [],
            "sql": None,
        },
    ]
    app.run()

    app.radio[0].set_value("Overview").run()
    app.radio[0].set_value("Chat").run()

    assert len(app.chat_message) == 2
    assert app.chat_message[0].name == "user"
    assert app.chat_message[0].markdown[0].value == "Persist this question"
    assert app.chat_message[1].name == "assistant"
    assert app.chat_message[1].markdown[0].value == "Persist this answer"


def test_failure_chat_renders_complete_table_and_csv_download(monkeypatch, tmp_path: Path) -> None:
    configure_test_database(monkeypatch, tmp_path)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=60).run()
    app.radio[0].set_value("Chat").run(timeout=60)
    app.chat_input[0].set_value(
        "Which wellbores had equipment failures, and what operational activities were being "
        "performed when those failures occurred? Include failure details, report dates, match "
        "confidence, and source references."
    ).run(timeout=60)

    assert not app.exception
    assert len(app.chat_message) == 2
    assert "244 populated equipment-failure records" in app.chat_message[-1].markdown[0].value
    assert app.dataframe[-1].value.shape == (244, 17)
    assert list(app.dataframe[-1].value.columns)[-3:] == [
        "source_file", "failure_page", "operation_page",
    ]
    assert [button.label for button in app.get("download_button")] == [
        "Download result CSV"
    ]
