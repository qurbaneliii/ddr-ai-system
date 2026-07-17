from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ddr_ai.config import Settings, get_settings


class LLMProviderError(RuntimeError):
    """Safe provider error that never includes request headers or secrets."""


class OllamaUnavailableError(LLMProviderError):
    pass


class OllamaModelNotFoundError(LLMProviderError):
    pass


class OllamaMalformedResponseError(LLMProviderError):
    pass


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    model: str
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    embeddings: list[list[float]]
    model: str
    dimension: int
    prompt_eval_count: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    reachable: bool
    model_available: bool
    mode: str
    model: str | None
    available_models: tuple[str, ...] = ()
    reason: str | None = None


class BaseLLMProvider(ABC):
    name: str
    mode_label: str
    model: str | None

    @abstractmethod
    def health_check(self, *, force: bool = False) -> ProviderHealth:
        """Return a secret-safe provider status."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Generate one response from supplied messages."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed a batch of texts without mixing model identities."""


@dataclass(slots=True)
class LexicalFallbackProvider(BaseLLMProvider):
    reason: str = "Ollama was not configured or reachable."
    name: str = "lexical_fallback"
    mode_label: str = "Lexical fallback"
    model: str | None = None

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        del force
        return ProviderHealth(False, False, "fallback", None, reason=self.reason)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        del messages, json_schema
        raise OllamaUnavailableError(self.reason)

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        del texts
        raise OllamaUnavailableError(self.reason)


@dataclass(slots=True)
class OllamaProvider(BaseLLMProvider):
    settings: Settings
    name: str = "ollama"
    model: str = field(init=False)
    mode_label: str = field(init=False)
    _cached_health: ProviderHealth | None = field(default=None, init=False, repr=False)
    _health_checked_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.model = self.settings.ollama_chat_model
        self.mode_label = (
            "Ollama Local LLM" if self.settings.ollama_is_local else "Ollama Remote"
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = self.settings.ollama_remote_auth_token.get_secret_value()
        if token and not self.settings.ollama_is_local:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        configuration_error = self.settings.remote_ollama_configuration_error()
        if configuration_error:
            raise OllamaUnavailableError(configuration_error)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.settings.normalized_ollama_base_url}{path}",
            data=data,
            headers=self._headers(),
            method=method,
        )
        attempts = self.settings.ollama_max_retries + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.settings.ollama_timeout_seconds) as response:
                    raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise OllamaMalformedResponseError("Ollama returned a non-object response.")
                return parsed
            except HTTPError as exc:
                if exc.code == 404:
                    raise OllamaModelNotFoundError(
                        "The configured Ollama model or API endpoint was not found."
                    ) from None
                if attempt == attempts - 1:
                    raise OllamaUnavailableError(
                        f"Ollama returned HTTP {exc.code}."
                    ) from None
            except (TimeoutError, URLError, OSError) as exc:
                if attempt == attempts - 1:
                    error_name = type(getattr(exc, "reason", exc)).__name__
                    raise OllamaUnavailableError(
                        f"Ollama is unreachable ({error_name})."
                    ) from None
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise OllamaMalformedResponseError(
                    "Ollama returned malformed JSON."
                ) from exc
            if attempt < attempts - 1:
                time.sleep(min(0.25 * (2**attempt), 1.0))
        raise OllamaUnavailableError("Ollama request failed.")

    def available_models(self) -> tuple[str, ...]:
        response = self._request("GET", "/api/tags")
        models = response.get("models")
        if not isinstance(models, list):
            raise OllamaMalformedResponseError("Ollama tags response has no model list.")
        names = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
        return tuple(sorted(set(names)))

    def health_check(self, *, force: bool = False) -> ProviderHealth:
        now = time.monotonic()
        if not force and self._cached_health and now - self._health_checked_at < 30:
            return self._cached_health
        try:
            models = self.available_models()
            available = self.settings.ollama_chat_model in models
            reason = None if available else (
                f"Configured model {self.settings.ollama_chat_model} is not installed."
            )
            health = ProviderHealth(
                True,
                available,
                self.settings.ollama_mode,
                self.settings.ollama_chat_model,
                models,
                reason,
            )
        except LLMProviderError as exc:
            health = ProviderHealth(
                False,
                False,
                self.settings.ollama_mode,
                self.settings.ollama_chat_model,
                reason=str(exc),
            )
        self._cached_health = health
        self._health_checked_at = now
        return health

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.settings.ollama_chat_model,
            "messages": list(messages),
            "stream": False,
            "options": {
                "temperature": self.settings.ollama_temperature,
                "num_ctx": self.settings.ollama_num_ctx,
            },
        }
        if json_schema is not None:
            payload["format"] = json_schema
        response = self._request("POST", "/api/chat", payload)
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaMalformedResponseError("Ollama chat response has no content.")
        return ChatResult(
            content=content.strip(),
            model=str(response.get("model") or self.settings.ollama_chat_model),
            total_duration_ns=_optional_int(response.get("total_duration")),
            load_duration_ns=_optional_int(response.get("load_duration")),
            prompt_eval_count=_optional_int(response.get("prompt_eval_count")),
            eval_count=_optional_int(response.get("eval_count")),
        )

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        payload = {
            "model": self.settings.ollama_chat_model,
            "messages": list(messages),
            "stream": True,
            "options": {
                "temperature": self.settings.ollama_temperature,
                "num_ctx": self.settings.ollama_num_ctx,
            },
        }
        request = Request(
            f"{self.settings.normalized_ollama_base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.ollama_timeout_seconds) as response:
                for raw_line in response:
                    if not raw_line.strip():
                        continue
                    item = json.loads(raw_line.decode("utf-8"))
                    message = item.get("message") if isinstance(item, dict) else None
                    content = message.get("content") if isinstance(message, dict) else None
                    if isinstance(content, str) and content:
                        yield content
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise OllamaUnavailableError("Ollama streaming request failed.") from exc

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            raise ValueError("At least one text is required for embedding.")
        response = self._request(
            "POST",
            "/api/embed",
            {
                "model": self.settings.ollama_embed_model,
                "input": list(texts),
                "truncate": True,
            },
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise OllamaMalformedResponseError("Ollama embedding count does not match input.")
        if not embeddings or not all(
            isinstance(vector, list) and vector and all(isinstance(value, (int, float)) for value in vector)
            for vector in embeddings
        ):
            raise OllamaMalformedResponseError("Ollama returned malformed embeddings.")
        dimensions = {len(vector) for vector in embeddings}
        if len(dimensions) != 1:
            raise OllamaMalformedResponseError("Ollama returned inconsistent embedding dimensions.")
        return EmbeddingResult(
            embeddings=[[float(value) for value in vector] for vector in embeddings],
            model=str(response.get("model") or self.settings.ollama_embed_model),
            dimension=dimensions.pop(),
            prompt_eval_count=_optional_int(response.get("prompt_eval_count")),
        )


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: BaseLLMProvider
    health: ProviderHealth
    fallback_reason: str | None = None


def select_provider(settings: Settings | None = None) -> ProviderSelection:
    settings = settings or get_settings()
    if settings.llm_provider.casefold() not in {"ollama", "auto"}:
        reason = "LLM_PROVIDER explicitly selected lexical fallback."
        fallback = LexicalFallbackProvider(reason)
        return ProviderSelection(fallback, fallback.health_check(), reason)
    provider = OllamaProvider(settings)
    health = provider.health_check()
    if health.reachable and health.model_available:
        return ProviderSelection(provider, health)
    reason = health.reason or "Ollama is unavailable."
    fallback = LexicalFallbackProvider(reason)
    return ProviderSelection(fallback, health, reason)


def provider_status(
    settings: Settings | None = None,
    *,
    selection: ProviderSelection | None = None,
) -> dict[str, object]:
    selected = selection or select_provider(settings)
    return {
        "active": selected.provider.name,
        "active_label": selected.provider.mode_label,
        "model": selected.provider.model,
        "ollama_reachable": selected.health.reachable,
        "ollama_model_available": selected.health.model_available,
        "ollama_mode": selected.health.mode,
        "fallback_reason": selected.fallback_reason,
        "external_proprietary_api_required": False,
    }
