from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from ddr_ai.config import Settings, get_settings


# ============================================================
# Provider errors
# ============================================================


class LLMProviderError(RuntimeError):
    """Safe provider error that never includes request headers or secrets."""


class OpenAIProviderError(LLMProviderError):
    """Secret-safe OpenAI provider error."""


class OllamaUnavailableError(LLMProviderError):
    """Ollama server is unavailable."""


class OllamaModelNotFoundError(LLMProviderError):
    """Configured Ollama model was not found."""


class OllamaMalformedResponseError(LLMProviderError):
    """Ollama returned an invalid response."""


# ============================================================
# Provider result models
# ============================================================


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


# ============================================================
# Base provider
# ============================================================


class BaseLLMProvider(ABC):
    name: str
    mode_label: str
    model: str | None

    @abstractmethod
    def health_check(
        self,
        *,
        force: bool = False,
    ) -> ProviderHealth:
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
    def embed(
        self,
        texts: Sequence[str],
    ) -> EmbeddingResult:
        """Embed a batch of texts."""


# ============================================================
# Lexical fallback
# ============================================================


@dataclass(slots=True)
class LexicalFallbackProvider(BaseLLMProvider):
    reason: str = "No LLM provider was configured or reachable."
    name: str = "lexical_fallback"
    mode_label: str = "Lexical fallback"
    model: str | None = None

    def health_check(
        self,
        *,
        force: bool = False,
    ) -> ProviderHealth:
        del force

        return ProviderHealth(
            reachable=False,
            model_available=False,
            mode="fallback",
            model=None,
            reason=self.reason,
        )

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        del messages, json_schema
        raise LLMProviderError(self.reason)

    def embed(
        self,
        texts: Sequence[str],
    ) -> EmbeddingResult:
        del texts
        raise LLMProviderError(self.reason)


# ============================================================
# Ollama provider
#
# Lokal istifadə və əvvəlki kodla uyğunluq üçün saxlanılır.
# LLM_PROVIDER=openai olduqda istifadə edilməyəcək.
# ============================================================


@dataclass(slots=True)
class OllamaProvider(BaseLLMProvider):
    settings: Settings
    name: str = "ollama"
    model: str = field(init=False)
    mode_label: str = field(init=False)

    _cached_health: ProviderHealth | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _health_checked_at: float = field(
        default=0.0,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.model = self.settings.ollama_chat_model

        self.mode_label = (
            "Ollama Local LLM"
            if self.settings.ollama_is_local
            else "Ollama Remote"
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        token = (
            self.settings.ollama_remote_auth_token
            .get_secret_value()
            .strip()
        )

        if token and not self.settings.ollama_is_local:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        configuration_error = (
            self.settings.remote_ollama_configuration_error()
        )

        if configuration_error:
            raise OllamaUnavailableError(configuration_error)

        data = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )

        request = Request(
            (
                f"{self.settings.normalized_ollama_base_url}"
                f"{path}"
            ),
            data=data,
            headers=self._headers(),
            method=method,
        )

        attempts = self.settings.ollama_max_retries + 1

        for attempt in range(attempts):
            try:
                with urlopen(
                    request,
                    timeout=self.settings.ollama_timeout_seconds,
                ) as response:
                    raw = response.read()

                parsed = json.loads(raw.decode("utf-8"))

                if not isinstance(parsed, dict):
                    raise OllamaMalformedResponseError(
                        "Ollama returned a non-object response."
                    )

                return parsed

            except HTTPError as exc:
                if exc.code == 404:
                    raise OllamaModelNotFoundError(
                        "The configured Ollama model or "
                        "API endpoint was not found."
                    ) from None

                if attempt == attempts - 1:
                    raise OllamaUnavailableError(
                        f"Ollama returned HTTP {exc.code}."
                    ) from None

            except (TimeoutError, URLError, OSError) as exc:
                if attempt == attempts - 1:
                    error_name = type(
                        getattr(exc, "reason", exc)
                    ).__name__

                    raise OllamaUnavailableError(
                        f"Ollama is unreachable ({error_name})."
                    ) from None

            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                raise OllamaMalformedResponseError(
                    "Ollama returned malformed JSON."
                ) from exc

            if attempt < attempts - 1:
                time.sleep(
                    min(
                        0.25 * (2**attempt),
                        1.0,
                    )
                )

        raise OllamaUnavailableError(
            "Ollama request failed."
        )

    def available_models(self) -> tuple[str, ...]:
        response = self._request(
            "GET",
            "/api/tags",
        )

        models = response.get("models")

        if not isinstance(models, list):
            raise OllamaMalformedResponseError(
                "Ollama tags response has no model list."
            )

        names: list[str] = []

        for item in models:
            if (
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
            ):
                names.append(item["name"])

        return tuple(sorted(set(names)))

    def health_check(
        self,
        *,
        force: bool = False,
    ) -> ProviderHealth:
        now = time.monotonic()

        if (
            not force
            and self._cached_health is not None
            and now - self._health_checked_at < 30
        ):
            return self._cached_health

        try:
            models = self.available_models()

            available = (
                self.settings.ollama_chat_model
                in models
            )

            reason = (
                None
                if available
                else (
                    "Configured model "
                    f"{self.settings.ollama_chat_model} "
                    "is not installed."
                )
            )

            health = ProviderHealth(
                reachable=True,
                model_available=available,
                mode=self.settings.ollama_mode,
                model=self.settings.ollama_chat_model,
                available_models=models,
                reason=reason,
            )

        except LLMProviderError as exc:
            health = ProviderHealth(
                reachable=False,
                model_available=False,
                mode=self.settings.ollama_mode,
                model=self.settings.ollama_chat_model,
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
                "temperature": (
                    self.settings.ollama_temperature
                ),
                "num_ctx": (
                    self.settings.ollama_num_ctx
                ),
            },
        }

        if json_schema is not None:
            payload["format"] = json_schema

        response = self._request(
            "POST",
            "/api/chat",
            payload,
        )

        message = response.get("message")

        content = (
            message.get("content")
            if isinstance(message, dict)
            else None
        )

        if (
            not isinstance(content, str)
            or not content.strip()
        ):
            raise OllamaMalformedResponseError(
                "Ollama chat response has no content."
            )

        return ChatResult(
            content=content.strip(),
            model=str(
                response.get("model")
                or self.settings.ollama_chat_model
            ),
            total_duration_ns=_optional_int(
                response.get("total_duration")
            ),
            load_duration_ns=_optional_int(
                response.get("load_duration")
            ),
            prompt_eval_count=_optional_int(
                response.get("prompt_eval_count")
            ),
            eval_count=_optional_int(
                response.get("eval_count")
            ),
        )

    def stream_chat(
        self,
        messages: Sequence[dict[str, str]],
    ) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self.settings.ollama_chat_model,
            "messages": list(messages),
            "stream": True,
            "options": {
                "temperature": (
                    self.settings.ollama_temperature
                ),
                "num_ctx": (
                    self.settings.ollama_num_ctx
                ),
            },
        }

        request = Request(
            (
                f"{self.settings.normalized_ollama_base_url}"
                "/api/chat"
            ),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.settings.ollama_timeout_seconds,
            ) as response:
                for raw_line in response:
                    if not raw_line.strip():
                        continue

                    item = json.loads(
                        raw_line.decode("utf-8")
                    )

                    message = (
                        item.get("message")
                        if isinstance(item, dict)
                        else None
                    )

                    content = (
                        message.get("content")
                        if isinstance(message, dict)
                        else None
                    )

                    if (
                        isinstance(content, str)
                        and content
                    ):
                        yield content

        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise OllamaUnavailableError(
                "Ollama streaming request failed."
            ) from exc

    def embed(
        self,
        texts: Sequence[str],
    ) -> EmbeddingResult:
        if not texts:
            raise ValueError(
                "At least one text is required for embedding."
            )

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

        if (
            not isinstance(embeddings, list)
            or len(embeddings) != len(texts)
        ):
            raise OllamaMalformedResponseError(
                "Ollama embedding count does not "
                "match input."
            )

        valid_embeddings = (
            bool(embeddings)
            and all(
                isinstance(vector, list)
                and bool(vector)
                and all(
                    isinstance(value, (int, float))
                    for value in vector
                )
                for vector in embeddings
            )
        )

        if not valid_embeddings:
            raise OllamaMalformedResponseError(
                "Ollama returned malformed embeddings."
            )

        dimensions = {
            len(vector)
            for vector in embeddings
        }

        if len(dimensions) != 1:
            raise OllamaMalformedResponseError(
                "Ollama returned inconsistent "
                "embedding dimensions."
            )

        return EmbeddingResult(
            embeddings=[
                [
                    float(value)
                    for value in vector
                ]
                for vector in embeddings
            ],
            model=str(
                response.get("model")
                or self.settings.ollama_embed_model
            ),
            dimension=dimensions.pop(),
            prompt_eval_count=_optional_int(
                response.get("prompt_eval_count")
            ),
        )


# ============================================================
# OpenAI provider
# ============================================================


@dataclass(slots=True)
class OpenAIProvider(BaseLLMProvider):
    settings: Settings
    name: str = "openai"
    mode_label: str = "OpenAI API"
    model: str = field(init=False)

    _client: OpenAI = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.model = self.settings.openai_model

        api_key = (
            self.settings.openai_api_key
            .get_secret_value()
            .strip()
        )

        if not api_key:
            raise OpenAIProviderError(
                "OPENAI_API_KEY is not configured."
            )

        self._client = OpenAI(
            api_key=api_key,
            timeout=(
                self.settings.openai_timeout_seconds
            ),
            max_retries=(
                self.settings.openai_max_retries
            ),
        )

    @staticmethod
    def _safe_error(
        exc: Exception,
    ) -> str:
        if isinstance(exc, AuthenticationError):
            return (
                "OpenAI authentication failed. "
                "Check the configured project API key."
            )

        if isinstance(exc, RateLimitError):
            return (
                "OpenAI rate limit or project "
                "usage limit was reached."
            )

        if isinstance(exc, APITimeoutError):
            return "OpenAI request timed out."

        if isinstance(exc, APIConnectionError):
            return "OpenAI API is unreachable."

        if isinstance(exc, APIStatusError):
            return (
                f"OpenAI returned HTTP {exc.status_code}."
            )

        return "OpenAI request failed."

    def health_check(
        self,
        *,
        force: bool = False,
    ) -> ProviderHealth:
        del force

        try:
            self._client.models.retrieve(
                self.model
            )

            return ProviderHealth(
                reachable=True,
                model_available=True,
                mode="remote",
                model=self.model,
                available_models=(self.model,),
                reason=None,
            )

        except (
            AuthenticationError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as exc:
            return ProviderHealth(
                reachable=False,
                model_available=False,
                mode="remote",
                model=self.model,
                reason=self._safe_error(exc),
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
            if (
                message.get("role") == "system"
                and message.get("content")
            )
        )

        input_messages = [
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in messages
            if (
                message.get("role") != "system"
                and message.get("content")
            )
        ]

        if not input_messages:
            raise OpenAIProviderError(
                "At least one non-system message is required."
            )

        request: dict[str, Any] = {
            "model": self.model,
            "input": input_messages,
            "max_output_tokens": (
                self.settings.openai_max_output_tokens
            ),
        }

        if instructions:
            request["instructions"] = instructions

        if json_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "ddr_query_analysis",
                    "schema": json_schema,
                    "strict": False,
                }
            }

        started = time.perf_counter_ns()

        try:
            response = (
                self._client.responses.create(
                    **request
                )
            )

        except (
            AuthenticationError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as exc:
            raise OpenAIProviderError(
                self._safe_error(exc)
            ) from None

        content = (
            response.output_text or ""
        ).strip()

        if not content:
            raise OpenAIProviderError(
                "OpenAI returned an empty response."
            )

        usage = getattr(
            response,
            "usage",
            None,
        )

        input_tokens = (
            getattr(
                usage,
                "input_tokens",
                None,
            )
            if usage is not None
            else None
        )

        output_tokens = (
            getattr(
                usage,
                "output_tokens",
                None,
            )
            if usage is not None
            else None
        )

        response_model = (
            getattr(
                response,
                "model",
                None,
            )
            or self.model
        )

        return ChatResult(
            content=content,
            model=response_model,
            total_duration_ns=(
                time.perf_counter_ns()
                - started
            ),
            load_duration_ns=None,
            prompt_eval_count=input_tokens,
            eval_count=output_tokens,
        )

    def embed(
        self,
        texts: Sequence[str],
    ) -> EmbeddingResult:
        if not texts:
            raise ValueError(
                "At least one text is required for embedding."
            )

        try:
            response = (
                self._client.embeddings.create(
                    model=(
                        self.settings
                        .openai_embedding_model
                    ),
                    input=list(texts),
                    encoding_format="float",
                )
            )

        except (
            AuthenticationError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as exc:
            raise OpenAIProviderError(
                self._safe_error(exc)
            ) from None

        ordered = sorted(
            response.data,
            key=lambda item: item.index,
        )

        embeddings = [
            [
                float(value)
                for value in item.embedding
            ]
            for item in ordered
        ]

        if not embeddings:
            raise OpenAIProviderError(
                "OpenAI returned no embeddings."
            )

        dimensions = {
            len(vector)
            for vector in embeddings
        }

        if len(dimensions) != 1:
            raise OpenAIProviderError(
                "OpenAI returned inconsistent "
                "embedding dimensions."
            )

        usage = getattr(
            response,
            "usage",
            None,
        )

        prompt_tokens = (
            getattr(
                usage,
                "prompt_tokens",
                None,
            )
            if usage is not None
            else None
        )

        response_model = (
            getattr(
                response,
                "model",
                None,
            )
            or self.settings.openai_embedding_model
        )

        return EmbeddingResult(
            embeddings=embeddings,
            model=response_model,
            dimension=dimensions.pop(),
            prompt_eval_count=prompt_tokens,
        )


# ============================================================
# Helpers
# ============================================================


def _optional_int(
    value: Any,
) -> int | None:
    return (
        int(value)
        if isinstance(value, int)
        else None
    )


# ============================================================
# Provider selection
# ============================================================


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: BaseLLMProvider
    health: ProviderHealth
    fallback_reason: str | None = None


def _fallback_selection(
    reason: str,
    health: ProviderHealth | None = None,
) -> ProviderSelection:
    fallback = LexicalFallbackProvider(reason)

    return ProviderSelection(
        provider=fallback,
        health=(
            health
            or fallback.health_check()
        ),
        fallback_reason=reason,
    )


def select_provider(
    settings: Settings | None = None,
) -> ProviderSelection:
    settings = settings or get_settings()

    requested = (
        settings.llm_provider
        .casefold()
        .strip()
    )

    # --------------------------------------------------------
    # OpenAI
    # --------------------------------------------------------

    if requested in {"openai", "auto"}:
        api_key = (
            settings.openai_api_key
            .get_secret_value()
            .strip()
        )

        if api_key:
            try:
                openai_provider = OpenAIProvider(
                    settings
                )

                openai_health = (
                    openai_provider.health_check()
                )

                if (
                    openai_health.reachable
                    and openai_health.model_available
                ):
                    return ProviderSelection(
                        provider=openai_provider,
                        health=openai_health,
                    )

                if requested == "openai":
                    return _fallback_selection(
                        openai_health.reason
                        or "OpenAI API is unavailable.",
                        openai_health,
                    )

            except OpenAIProviderError as exc:
                if requested == "openai":
                    return _fallback_selection(
                        str(exc)
                    )

        elif requested == "openai":
            return _fallback_selection(
                "OPENAI_API_KEY is missing. "
                "Configure it in .env.local for "
                "local development or in Streamlit "
                "Secrets for the live deployment."
            )

    # --------------------------------------------------------
    # Ollama
    # --------------------------------------------------------

    if requested in {"ollama", "auto"}:
        ollama_provider = OllamaProvider(
            settings
        )

        ollama_health = (
            ollama_provider.health_check()
        )

        if (
            ollama_health.reachable
            and ollama_health.model_available
        ):
            return ProviderSelection(
                provider=ollama_provider,
                health=ollama_health,
            )

        return _fallback_selection(
            ollama_health.reason
            or "Ollama is unavailable.",
            ollama_health,
        )

    # --------------------------------------------------------
    # Explicit fallback
    # --------------------------------------------------------

    if requested in {
        "lexical",
        "lexical_fallback",
        "none",
        "disabled",
    }:
        return _fallback_selection(
            "LLM_PROVIDER explicitly selected "
            "lexical fallback."
        )

    return _fallback_selection(
        "Unsupported LLM_PROVIDER value: "
        f"{settings.llm_provider}"
    )


# ============================================================
# Public provider status
# ============================================================


def provider_status(
    settings: Settings | None = None,
    *,
    selection: ProviderSelection | None = None,
) -> dict[str, object]:
    selected = (
        selection
        or select_provider(settings)
    )

    active_provider = selected.provider.name

    provider_ready = (
        selected.health.reachable
        and selected.health.model_available
        and active_provider != "lexical_fallback"
    )

    return {
        # Generic provider status
        "active": active_provider,
        "active_label": (
            selected.provider.mode_label
        ),
        "model": selected.provider.model,
        "provider_reachable": (
            selected.health.reachable
        ),
        "model_available": (
            selected.health.model_available
        ),
        "provider_ready": provider_ready,
        "provider_mode": (
            selected.health.mode
        ),
        "fallback_reason": (
            selected.fallback_reason
        ),
        "external_api_required": (
            active_provider == "openai"
        ),

        # Köhnə streamlit_app.py ilə
        # müvəqqəti uyğunluq
        "ollama_reachable": (
            selected.health.reachable
            if active_provider == "ollama"
            else False
        ),
        "ollama_model_available": (
            selected.health.model_available
            if active_provider == "ollama"
            else False
        ),
        "ollama_mode": (
            selected.health.mode
            if active_provider == "ollama"
            else "not-active"
        ),
        "external_proprietary_api_required": (
            active_provider == "openai"
        ),
    }