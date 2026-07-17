from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STREAMLIT_SECRET_FIELDS = {
    "LLM_PROVIDER": "llm_provider",
    "OLLAMA_BASE_URL": "ollama_base_url",
    "OLLAMA_CHAT_MODEL": "ollama_chat_model",
    "OLLAMA_EMBED_MODEL": "ollama_embed_model",
    "OLLAMA_TIMEOUT_SECONDS": "ollama_timeout_seconds",
    "OLLAMA_MAX_RETRIES": "ollama_max_retries",
    "OLLAMA_NUM_CTX": "ollama_num_ctx",
    "OLLAMA_TEMPERATURE": "ollama_temperature",
    "OLLAMA_REMOTE_AUTH_TOKEN": "ollama_remote_auth_token",
    "OLLAMA_ENABLE_SEMANTIC_RETRIEVAL": "ollama_enable_semantic_retrieval",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default=f"sqlite:///{(PROJECT_ROOT / 'data/processed/ddr_ai.db').as_posix()}",
        validation_alias="DDR_DATABASE_URL",
    )
    raw_dir: Path = Field(default=PROJECT_ROOT / "data/raw", validation_alias="DDR_RAW_DIR")
    processed_dir: Path = Field(
        default=PROJECT_ROOT / "data/processed", validation_alias="DDR_PROCESSED_DIR"
    )
    cache_dir: Path = Field(
        default=PROJECT_ROOT / "data/cache", validation_alias="DDR_CACHE_DIR"
    )
    log_level: str = Field(default="INFO", validation_alias="DDR_LOG_LEVEL")
    max_upload_mb: int = Field(
        default=250, ge=1, le=2000, validation_alias="DDR_MAX_UPLOAD_MB"
    )
    query_timeout_seconds: int = Field(
        default=10, ge=1, le=120, validation_alias="DDR_QUERY_TIMEOUT_SECONDS"
    )
    default_query_limit: int = Field(
        default=200, ge=1, le=1000, validation_alias="DDR_DEFAULT_QUERY_LIMIT"
    )
    max_query_limit: int = Field(
        default=1000, ge=1, le=10000, validation_alias="DDR_MAX_QUERY_LIMIT"
    )
    parser_version: str = Field(default="0.1.0", validation_alias="DDR_PARSER_VERSION")

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "qwen2.5:3b-instruct-q4_K_M"
    ollama_embed_model: str = "bge-m3:567m"
    ollama_timeout_seconds: float = Field(default=120, ge=1, le=600)
    ollama_max_retries: int = Field(default=2, ge=0, le=5)
    ollama_num_ctx: int = Field(default=4096, ge=1024, le=131072)
    ollama_temperature: float = Field(default=0.1, ge=0, le=2)
    ollama_remote_auth_token: SecretStr = Field(default_factory=lambda: SecretStr(""))
    ollama_enable_semantic_retrieval: bool = False
    ollama_embedding_batch_size: int = Field(default=16, ge=1, le=128)

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._prepare_streamlit_cloud_database()

    def _prepare_streamlit_cloud_database(self) -> None:
        """Use an ephemeral writable copy when Community Cloud mounts the repository read-only."""
        if not self.database_url.startswith("sqlite:///"):
            return
        source = Path(self.database_url.removeprefix("sqlite:///"))
        source_posix = source.as_posix()
        cloud_runtime = bool(os.getenv("STREAMLIT_SHARING_MODE")) or source_posix.startswith(
            "/mount/src/"
        )
        if not cloud_runtime or not source.is_file():
            return
        runtime_dir = Path(tempfile.gettempdir()) / "ddr_ai_system_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        target = runtime_dir / source.name
        if (
            not target.exists()
            or target.stat().st_size != source.stat().st_size
            or target.stat().st_mtime_ns != source.stat().st_mtime_ns
        ):
            shutil.copy2(source, target)
        self.database_url = f"sqlite:///{target.as_posix()}"

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
    """Copy only supported Ollama settings from Streamlit Secrets."""
    return {
        field_name: secrets[secret_name]
        for secret_name, field_name in STREAMLIT_SECRET_FIELDS.items()
        if secret_name in secrets
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
