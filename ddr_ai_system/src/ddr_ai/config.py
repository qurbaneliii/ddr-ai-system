from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STREAMLIT_SECRET_KEYS = {
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_CHAT_MODEL",
    "OLLAMA_EMBED_MODEL",
    "OLLAMA_TIMEOUT_SECONDS",
    "OLLAMA_MAX_RETRIES",
    "OLLAMA_NUM_CTX",
    "OLLAMA_TEMPERATURE",
    "OLLAMA_REMOTE_AUTH_TOKEN",
    "OLLAMA_ENABLE_SEMANTIC_RETRIEVAL",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DDR_",
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data/processed/ddr_ai.db').as_posix()}"
    raw_dir: Path = PROJECT_ROOT / "data/raw"
    processed_dir: Path = PROJECT_ROOT / "data/processed"
    cache_dir: Path = PROJECT_ROOT / "data/cache"
    log_level: str = "INFO"
    max_upload_mb: int = Field(default=250, ge=1, le=2000)
    query_timeout_seconds: int = Field(default=10, ge=1, le=120)
    default_query_limit: int = Field(default=200, ge=1, le=1000)
    max_query_limit: int = Field(default=1000, ge=1, le=10000)
    parser_version: str = "0.1.0"

    llm_provider: str = Field(
        default="ollama",
        validation_alias=AliasChoices("LLM_PROVIDER", "DDR_LLM_PROVIDER"),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "DDR_OLLAMA_BASE_URL"),
    )
    ollama_chat_model: str = Field(
        default="qwen2.5:3b-instruct-q4_K_M",
        validation_alias=AliasChoices("OLLAMA_CHAT_MODEL", "DDR_OLLAMA_CHAT_MODEL"),
    )
    ollama_embed_model: str = Field(
        default="bge-m3:567m",
        validation_alias=AliasChoices("OLLAMA_EMBED_MODEL", "DDR_OLLAMA_EMBED_MODEL"),
    )
    ollama_timeout_seconds: float = Field(
        default=120,
        ge=1,
        le=600,
        validation_alias=AliasChoices("OLLAMA_TIMEOUT_SECONDS", "DDR_OLLAMA_TIMEOUT_SECONDS"),
    )
    ollama_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias=AliasChoices("OLLAMA_MAX_RETRIES", "DDR_OLLAMA_MAX_RETRIES"),
    )
    ollama_num_ctx: int = Field(
        default=4096,
        ge=1024,
        le=131072,
        validation_alias=AliasChoices("OLLAMA_NUM_CTX", "DDR_OLLAMA_NUM_CTX"),
    )
    ollama_temperature: float = Field(
        default=0.1,
        ge=0,
        le=2,
        validation_alias=AliasChoices("OLLAMA_TEMPERATURE", "DDR_OLLAMA_TEMPERATURE"),
    )
    ollama_remote_auth_token: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        validation_alias=AliasChoices(
            "OLLAMA_REMOTE_AUTH_TOKEN", "DDR_OLLAMA_REMOTE_AUTH_TOKEN"
        ),
    )
    ollama_enable_semantic_retrieval: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OLLAMA_ENABLE_SEMANTIC_RETRIEVAL",
            "DDR_OLLAMA_ENABLE_SEMANTIC_RETRIEVAL",
        ),
    )
    ollama_embedding_batch_size: int = Field(default=16, ge=1, le=128)

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def normalized_ollama_base_url(self) -> str:
        return self.ollama_base_url.rstrip("/")

    @property
    def ollama_is_local(self) -> bool:
        parsed = urlparse(self.normalized_ollama_base_url)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1", "ollama"}

    @property
    def ollama_mode(self) -> str:
        return "local" if self.ollama_is_local else "remote"

    def remote_ollama_configuration_error(self) -> str | None:
        if self.ollama_is_local:
            return None
        parsed = urlparse(self.normalized_ollama_base_url)
        if parsed.scheme != "https":
            return "Remote Ollama endpoints must use HTTPS."
        if not self.ollama_remote_auth_token.get_secret_value():
            return "Remote Ollama endpoints require an authentication proxy token."
        return None


def streamlit_secret_overrides(secrets: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only supported non-OpenAI keys from Streamlit Secrets."""
    return {key: secrets[key] for key in STREAMLIT_SECRET_KEYS if key in secrets}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
