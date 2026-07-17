from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    assert app.title or app.markdown
