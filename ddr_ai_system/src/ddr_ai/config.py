from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DDR_", env_file=".env", extra="ignore")

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

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.processed_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
