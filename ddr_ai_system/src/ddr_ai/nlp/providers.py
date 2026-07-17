from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def verbalize(self, facts_json: str, instruction: str) -> str:
        """Verbalize only the supplied facts."""


@dataclass(slots=True)
class NoKeyProvider:
    name: str = "deterministic_no_key"

    def verbalize(self, facts_json: str, instruction: str) -> str:
        raise RuntimeError("No external LLM provider is configured; deterministic templates remain active.")


def provider_status() -> dict[str, object]:
    return {
        "active": "deterministic_no_key",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "ollama_configured": bool(os.getenv("OLLAMA_BASE_URL")),
        "external_calls_enabled": False,
        "note": "External providers are opt-in and are not required for extraction, SQL, search, or summaries.",
    }

