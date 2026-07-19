from __future__ import annotations

from pathlib import Path

from ddr_ai.config import Settings, streamlit_secret_overrides
from ddr_ai.db.session import dispose_all_engines, get_engine


def test_streamlit_secrets_resolve_one_postgres_source_of_truth() -> None:
    values = streamlit_secret_overrides(
        {
            "DDR_DATABASE_URL": "postgresql+psycopg://user:password@host/database",
            "LLM_PROVIDER": "openai",
            "OPENAI_MODEL": "gpt-test",
            "UNSUPPORTED_VALUE": "ignored",
        }
    )
    settings = Settings(**values, _env_file=None)

    assert settings.is_postgres is True
    assert settings.persistence_mode == "persistent PostgreSQL"
    assert settings.openai_model == "gpt-test"
    assert "UNSUPPORTED_VALUE" not in values


def test_engine_cache_is_keyed_by_database_url(tmp_path: Path) -> None:
    first_url = f"sqlite:///{(tmp_path / 'first.db').as_posix()}"
    second_url = f"sqlite:///{(tmp_path / 'second.db').as_posix()}"

    first = get_engine(first_url)
    assert get_engine(first_url) is first
    assert get_engine(second_url) is not first

    dispose_all_engines()
    assert get_engine(first_url) is not first
    dispose_all_engines()
