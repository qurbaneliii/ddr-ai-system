from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy import select, text

from ddr_ai import __version__
from ddr_ai.config import PROJECT_ROOT, Settings
from ddr_ai.db.models import ModelRun, SeedVersion
from ddr_ai.db.session import session_scope
from ddr_ai.nlp.providers import ProviderSelection

_SAFE_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


@dataclass(frozen=True, slots=True)
class BuildInfo:
    app_version: str
    parser_version: str
    database_revision: str
    database_mode: str
    seed_version: str
    activity_model_version: str
    anomaly_model_version: str
    build_sha: str
    llm_mode: str
    llm_model: str
    vlm_state: str

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


def _package_version() -> str:
    try:
        return version("ddr-ai-system")
    except PackageNotFoundError:
        return __version__


def _short_sha(configured_sha: str) -> str:
    candidate = configured_sha.strip()
    if not candidate:
        try:
            candidate = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unknown"
    return candidate[:12].lower() if _SAFE_SHA.fullmatch(candidate) else "unknown"


def collect_build_info(
    database_url: str,
    settings: Settings,
    selection: ProviderSelection,
) -> BuildInfo:
    revision = "unavailable"
    seed_version = "none"
    model_versions: dict[str, str] = {}
    try:
        with session_scope(database_url) as session:
            revision = str(session.execute(text("SELECT version_num FROM alembic_version")).scalar())
            seed_version = (
                session.scalar(
                    select(SeedVersion.version).order_by(SeedVersion.applied_at.desc()).limit(1)
                )
                or "none"
            )
            active_runs = session.scalars(select(ModelRun).where(ModelRun.is_active.is_(True))).all()
            model_versions = {run.model_type: run.model_version for run in active_runs}
    except Exception:
        revision = "unavailable"
        seed_version = "unavailable"

    provider = selection.provider
    active_openai = provider.name == "openai"
    return BuildInfo(
        app_version=_package_version(),
        parser_version=settings.parser_version,
        database_revision=revision,
        database_mode=settings.persistence_mode,
        seed_version=seed_version,
        activity_model_version=model_versions.get("activity_classifier", "artifact-backed"),
        anomaly_model_version=model_versions.get("duration_anomaly", "none"),
        build_sha=_short_sha(settings.build_sha),
        llm_mode=provider.mode_label,
        llm_model=provider.model if active_openai and provider.model else "none",
        vlm_state=(
            f"enabled ({settings.openai_vlm_model})"
            if active_openai and provider.supports_images
            else "disabled"
        ),
    )
