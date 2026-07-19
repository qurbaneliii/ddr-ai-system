from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from ddr_ai.config import Settings


class LLMProviderError(RuntimeError):
    """Secret-safe provider error."""


class OpenAIProviderError(LLMProviderError):
    pass


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    model: str
    total_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    configured: bool
    mode: str
    model: str | None
    last_request_success: bool | None = None
    reason: str | None = None


class BaseLLMProvider(ABC):
    name: str
    mode_label: str
    model: str | None

    @abstractmethod
    def health_check(self, *, force: bool = False) -> ProviderHealth:
        """Return configuration and last-request status without a paid probe."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Generate one response."""


@dataclass(slots=True)
class LexicalFallbackProvider(BaseLLMProvider):
    reason: str = "OpenAI is not configured."
    name: str = "lexical_fallback"
    mode_label: str = "Lexical fallback"
    model: str | None = None

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        del force
        return ProviderHealth(False, "fallback", None, None, self.reason)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        del messages, json_schema
        raise LLMProviderError(self.reason)


@lru_cache(maxsize=4)
def _openai_client(api_key: str, timeout_seconds: float, max_retries: int) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=max_retries)


@dataclass(slots=True)
class OpenAIProvider(BaseLLMProvider):
    settings: Settings
    name: str = "openai"
    mode_label: str = "OpenAI-verbalized"
    model: str = field(init=False)
    _client: OpenAI = field(init=False, repr=False)
    _last_request_success: bool | None = field(default=None, init=False, repr=False)
    _last_reason: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.model = self.settings.openai_model.strip()
        key = self.settings.openai_api_key.get_secret_value().strip()
        if not key:
            raise OpenAIProviderError("OPENAI_API_KEY is not configured.")
        if not self.model:
            raise OpenAIProviderError("OPENAI_MODEL is not configured.")
        self._client = _openai_client(
            key, self.settings.openai_timeout_seconds, self.settings.openai_max_retries
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, AuthenticationError):
            return "OpenAI authentication failed."
        if isinstance(exc, RateLimitError):
            return "OpenAI rate or project usage limit was reached."
        if isinstance(exc, APITimeoutError):
            return "OpenAI request timed out."
        if isinstance(exc, APIConnectionError):
            return "OpenAI API is unreachable."
        if isinstance(exc, APIStatusError):
            return f"OpenAI returned HTTP {exc.status_code}."
        return "OpenAI request failed."

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        del force
        return ProviderHealth(
            configured=True,
            mode="remote",
            model=self.model,
            last_request_success=self._last_request_success,
            reason=self._last_reason,
        )

    def _create(self, request: dict[str, Any]) -> ChatResult:
        started = time.perf_counter_ns()
        try:
            response = self._client.responses.create(**request)
        except (
            AuthenticationError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as exc:
            self._last_request_success = False
            self._last_reason = self._safe_error(exc)
            raise OpenAIProviderError(self._last_reason) from None
        content = (response.output_text or "").strip()
        if not content:
            self._last_request_success = False
            self._last_reason = "OpenAI returned an empty response."
            raise OpenAIProviderError(self._last_reason)
        self._last_request_success = True
        self._last_reason = None
        usage = getattr(response, "usage", None)
        return ChatResult(
            content=content,
            model=getattr(response, "model", None) or self.model,
            total_duration_ns=time.perf_counter_ns() - started,
            prompt_eval_count=getattr(usage, "input_tokens", None) if usage else None,
            eval_count=getattr(usage, "output_tokens", None) if usage else None,
        )

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        instructions = "\n\n".join(
            message["content"]
            for message in messages
            if message.get("role") == "system" and message.get("content")
        )
        inputs = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message.get("role") != "system" and message.get("content")
        ]
        if not inputs:
            raise OpenAIProviderError("At least one non-system message is required.")
        request: dict[str, Any] = {
            "model": self.model,
            "input": inputs,
            "max_output_tokens": self.settings.openai_max_output_tokens,
        }
        if instructions:
            request["instructions"] = instructions
        if json_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "ddr_grounded_response",
                    "schema": json_schema,
                    "strict": False,
                }
            }
        return self._create(request)

    def describe_image(self, image_bytes: bytes, *, mime_type: str, prompt: str) -> ChatResult:
        if not self.settings.openai_vlm_enabled:
            raise OpenAIProviderError("Optional OpenAI image description is disabled.")
        if len(image_bytes) > 4 * 1024 * 1024:
            raise OpenAIProviderError("The selected image exceeds the 4 MB VLM limit.")
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        return self._create(
            {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
                "max_output_tokens": min(self.settings.openai_max_output_tokens, 800),
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: BaseLLMProvider
    health: ProviderHealth
    fallback_reason: str | None = None


def _fallback(reason: str) -> ProviderSelection:
    provider = LexicalFallbackProvider(reason)
    return ProviderSelection(provider, provider.health_check(), reason)


def select_provider(settings: Settings) -> ProviderSelection:
    requested = settings.llm_provider.casefold().strip()
    if requested in {"lexical", "lexical_fallback", "none", "disabled"}:
        return _fallback("LLM_PROVIDER selected deterministic lexical fallback.")
    if requested not in {"openai", "auto"}:
        return _fallback(f"Unsupported LLM_PROVIDER value: {settings.llm_provider}")
    if not settings.openai_api_key.get_secret_value().strip():
        return _fallback("OPENAI_API_KEY is not configured.")
    try:
        provider = OpenAIProvider(settings)
    except OpenAIProviderError as exc:
        return _fallback(str(exc))
    return ProviderSelection(provider, provider.health_check())


def provider_status(
    settings: Settings, *, selection: ProviderSelection | None = None
) -> dict[str, object]:
    selected = selection or select_provider(settings)
    health = selected.provider.health_check()
    active_openai = selected.provider.name == "openai"
    return {
        "active": selected.provider.name,
        "active_label": selected.provider.mode_label,
        "configured": health.configured,
        "model": selected.provider.model if active_openai else None,
        "last_request_success": health.last_request_success,
        "fallback_reason": selected.fallback_reason or health.reason,
        "external_proprietary_api_required": active_openai,
    }
