from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STREAMLIT_SECRET_KEYS = {
    "DDR_DATABASE_URL",
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_MAX_RETRIES",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_VLM_ENABLED",
}


class Settings(BaseSettings):
    """One resolved application configuration.

    Local secrets are read from the ignored ``.env.local`` file. Streamlit
    secrets are supplied explicitly by the entrypoint through
    :func:`streamlit_secret_overrides`.
    """

    model_config = SettingsConfigDict(
        env_prefix="DDR_",
        env_file=(PROJECT_ROOT / ".env.local",),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default=f"sqlite:///{(PROJECT_ROOT / 'data/processed/ddr_ai.db').as_posix()}",
        validation_alias=AliasChoices("DDR_DATABASE_URL", "DATABASE_URL"),
    )
    raw_dir: Path = PROJECT_ROOT / "data/raw"
    processed_dir: Path = PROJECT_ROOT / "data/processed"
    cache_dir: Path = PROJECT_ROOT / "data/cache"
    log_level: str = "INFO"
    parser_version: str = "0.2.0"

    max_upload_mb: int = Field(default=50, ge=1, le=250)
    max_question_chars: int = Field(default=2000, ge=100, le=10000)
    max_chat_history: int = Field(default=20, ge=2, le=100)
    question_cooldown_seconds: float = Field(default=1.0, ge=0, le=60)
    session_question_limit: int = Field(default=50, ge=1, le=500)
    query_timeout_seconds: int = Field(default=10, ge=1, le=120)
    default_query_limit: int = Field(default=200, ge=1, le=1000)
    max_query_limit: int = Field(default=1000, ge=1, le=10000)

    llm_provider: str = Field(
        default="openai",
        validation_alias=AliasChoices("LLM_PROVIDER", "DDR_LLM_PROVIDER"),
    )
    openai_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias=AliasChoices("OPENAI_API_KEY", "DDR_OPENAI_API_KEY"),
    )
    openai_model: str = Field(
        default="gpt-5.6-luna",
        validation_alias=AliasChoices("OPENAI_MODEL", "DDR_OPENAI_MODEL"),
    )
    openai_timeout_seconds: float = Field(
        default=60,
        ge=1,
        le=300,
        validation_alias=AliasChoices("OPENAI_TIMEOUT_SECONDS", "DDR_OPENAI_TIMEOUT_SECONDS"),
    )
    openai_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias=AliasChoices("OPENAI_MAX_RETRIES", "DDR_OPENAI_MAX_RETRIES"),
    )
    openai_max_output_tokens: int = Field(
        default=1200,
        ge=100,
        le=4000,
        validation_alias=AliasChoices("OPENAI_MAX_OUTPUT_TOKENS", "DDR_OPENAI_MAX_OUTPUT_TOKENS"),
    )
    openai_vlm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("OPENAI_VLM_ENABLED", "DDR_OPENAI_VLM_ENABLED"),
    )

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgresql+psycopg://"))

    @property
    def persistence_mode(self) -> str:
        return "persistent PostgreSQL" if self.is_postgres else "temporary SQLite demo"


def streamlit_secret_overrides(secrets: Mapping[str, Any]) -> dict[str, Any]:
    """Return only supported, non-displayable configuration values."""

    return {key: secrets[key] for key in STREAMLIT_SECRET_KEYS if key in secrets}


def resolve_settings(overrides: Mapping[str, Any] | None = None) -> Settings:
    settings = Settings(**dict(overrides or {}))
    settings.ensure_directories()
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Compatibility entrypoint for CLI commands; app layers pass settings explicitly."""

    return resolve_settings()
