from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from ddr_ai.config import Settings, streamlit_secret_overrides
from ddr_ai.nlp.providers import (
    OllamaMalformedResponseError,
    OllamaProvider,
    OllamaUnavailableError,
    select_provider,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.body


def settings(**overrides) -> Settings:
    defaults = {
        "ollama_max_retries": 0,
        "ollama_timeout_seconds": 1,
        "ollama_chat_model": "qwen2.5:3b-instruct-q4_K_M",
        "ollama_embed_model": "bge-m3:567m",
    }
    return Settings(**(defaults | overrides), _env_file=None)


def test_ollama_configuration_and_streamlit_secret_allowlist() -> None:
    configured = settings()
    assert configured.ollama_is_local is True
    assert configured.ollama_num_ctx == 4096
    assert configured.ollama_temperature == 0.1
    overrides = streamlit_secret_overrides(
        {"OLLAMA_BASE_URL": "https://example.test", "UNRELATED_SECRET": "do-not-copy"}
    )
    assert overrides == {"OLLAMA_BASE_URL": "https://example.test"}


def test_health_and_available_model_detection(monkeypatch) -> None:
    monkeypatch.setattr(
        "ddr_ai.nlp.providers.urlopen",
        lambda request, timeout: FakeResponse(
            {"models": [{"name": "qwen2.5:3b-instruct-q4_K_M"}, {"name": "bge-m3:567m"}]}
        ),
    )
    provider = OllamaProvider(settings())
    health = provider.health_check(force=True)
    assert health.reachable is True
    assert health.model_available is True
    assert "bge-m3:567m" in health.available_models


def test_model_not_installed_activates_lexical_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "ddr_ai.nlp.providers.urlopen",
        lambda request, timeout: FakeResponse({"models": [{"name": "another-model:1b"}]}),
    )
    selected = select_provider(settings())
    assert selected.provider.name == "lexical_fallback"
    assert "not installed" in (selected.fallback_reason or "")


def test_chat_request_response_and_metrics(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/api/chat")
        body = json.loads(request.data)
        assert body["stream"] is False
        assert body["options"]["num_ctx"] == 4096
        return FakeResponse(
            {
                "model": "qwen2.5:3b-instruct-q4_K_M",
                "message": {"role": "assistant", "content": "Grounded answer"},
                "total_duration": 10,
                "prompt_eval_count": 20,
                "eval_count": 5,
            }
        )

    monkeypatch.setattr("ddr_ai.nlp.providers.urlopen", fake_urlopen)
    result = OllamaProvider(settings()).chat([{"role": "user", "content": "Question"}])
    assert result.content == "Grounded answer"
    assert result.prompt_eval_count == 20
    assert result.eval_count == 5


def test_embedding_request_response_and_dimension(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/api/embed")
        body = json.loads(request.data)
        assert body["input"] == ["azərbaycan", "english"]
        return FakeResponse({"model": "bge-m3:567m", "embeddings": [[1, 0, 0], [0, 1, 0]]})

    monkeypatch.setattr("ddr_ai.nlp.providers.urlopen", fake_urlopen)
    result = OllamaProvider(settings()).embed(["azərbaycan", "english"])
    assert result.dimension == 3
    assert result.model == "bge-m3:567m"


@pytest.mark.parametrize("error", [TimeoutError(), URLError("refused")])
def test_timeout_and_unreachable_ollama(monkeypatch, error) -> None:
    def fail(request, timeout):
        raise error

    monkeypatch.setattr("ddr_ai.nlp.providers.urlopen", fail)
    with pytest.raises(OllamaUnavailableError, match="unreachable"):
        OllamaProvider(settings()).available_models()


def test_malformed_chat_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "ddr_ai.nlp.providers.urlopen", lambda request, timeout: FakeResponse({"message": {}})
    )
    with pytest.raises(OllamaMalformedResponseError, match="no content"):
        OllamaProvider(settings()).chat([{"role": "user", "content": "Question"}])


def test_remote_endpoint_requires_https_and_token() -> None:
    provider = OllamaProvider(settings(ollama_base_url="http://remote.example.test"))
    with pytest.raises(OllamaUnavailableError, match="HTTPS"):
        provider.available_models()
    provider = OllamaProvider(settings(ollama_base_url="https://remote.example.test"))
    with pytest.raises(OllamaUnavailableError, match="authentication"):
        provider.available_models()
