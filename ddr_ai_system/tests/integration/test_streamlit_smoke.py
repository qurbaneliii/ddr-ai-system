from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert app.title or app.markdown


def test_chat_history_survives_page_reruns(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio[0].set_value("Chatbot").run()
    app.session_state["chat_messages"] = [
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

    app.radio[0].set_value("Overview Dashboard").run()
    app.radio[0].set_value("Chatbot").run()

    assert len(app.chat_message) == 2
    assert app.chat_message[0].name == "user"
    assert app.chat_message[0].markdown[0].value == "Persist this question"
    assert app.chat_message[1].name == "assistant"
    assert app.chat_message[1].markdown[0].value == "Persist this answer"
