from __future__ import annotations

from pathlib import Path

from ddr_ai.build_info import collect_build_info
from ddr_ai.config import Settings
from ddr_ai.db.session import upgrade_schema
from ddr_ai.nlp.providers import select_provider


def test_build_info_uses_configured_sha_and_exposes_no_secrets(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    upgrade_schema(database_url)
    settings = Settings(
        database_url=database_url,
        build_sha="A1B2C3D4E5F60718293A",
        llm_provider="lexical",
        openai_api_key="must-not-appear",
        _env_file=None,
    )

    info = collect_build_info(database_url, settings, select_provider(settings))
    public = info.public_dict()
    rendered = repr(public)

    assert info.build_sha == "a1b2c3d4e5f6"
    assert info.database_revision == "0006"
    assert info.database_mode == "temporary SQLite demo"
    assert "must-not-appear" not in rendered
    assert database_path.as_posix() not in rendered
    assert "sqlite:" not in rendered


def test_build_info_rejects_unsafe_sha(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}"
    upgrade_schema(database_url)
    settings = Settings(
        database_url=database_url,
        build_sha="not a commit; rm -rf",
        llm_provider="lexical",
        _env_file=None,
    )

    info = collect_build_info(database_url, settings, select_provider(settings))

    assert info.build_sha == "unknown"
