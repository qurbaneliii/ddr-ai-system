from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError

import ddr_ai.nlp.providers as providers
from ddr_ai.config import Settings
from ddr_ai.nlp.providers import OpenAIProvider, OpenAIProviderError


class FakeResponses:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.requests: list[dict[str, object]] = []

    def create(self, **request: object) -> object:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.result


def _settings(**values: object) -> Settings:
    return Settings(
        openai_api_key="test-secret-that-must-not-leak",
        openai_model="gpt-test",
        openai_vlm_enabled=True,
        openai_vlm_model="gpt-vlm-test",
        _env_file=None,
        **values,
    )


def _provider(monkeypatch: pytest.MonkeyPatch, responses: FakeResponses) -> OpenAIProvider:
    monkeypatch.setattr(
        providers,
        "_openai_client",
        lambda *_args: SimpleNamespace(responses=responses),
    )
    return OpenAIProvider(_settings())


def test_openai_responses_request_and_optional_image(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SimpleNamespace(
        output_text="Grounded answer",
        model="gpt-test",
        usage=SimpleNamespace(input_tokens=10, output_tokens=4),
    )
    responses = FakeResponses(result=result)
    provider = _provider(monkeypatch, responses)

    chat = provider.chat(
        [
            {"role": "system", "content": "Use supplied facts."},
            {"role": "user", "content": "Summarize."},
        ]
    )
    image = provider.describe_image(b"small-image", mime_type="image/png", prompt="Read it.")

    assert chat.content == image.content == "Grounded answer"
    assert responses.requests[0]["instructions"] == "Use supplied facts."
    image_content = responses.requests[1]["input"][0]["content"]
    assert responses.requests[1]["model"] == "gpt-vlm-test"
    assert image_content[1]["type"] == "input_image"
    assert image_content[1]["image_url"].startswith("data:image/png;base64,")
    assert provider.health_check().last_request_success is True
    assert provider.supports_images is True


def test_openai_structured_output_uses_strict_schema_and_bounded_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(output_text='{"intent":"narrative_corpus_search"}', model="gpt-test", usage=None)
    responses = FakeResponses(result=result)
    provider = _provider(monkeypatch, responses)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"intent": {"type": "string"}},
        "required": ["intent"],
    }
    provider.chat(
        [{"role": "user", "content": "Plan an unclear DDR question."}],
        json_schema=schema,
        max_output_tokens=400,
    )
    request = responses.requests[0]
    assert request["max_output_tokens"] == 400
    assert request["text"] == {
        "format": {
            "type": "json_schema",
            "name": "ddr_grounded_response",
            "schema": schema,
            "strict": True,
        }
    }


@pytest.mark.parametrize("status_code", [401, 429])
def test_openai_errors_are_classified_without_secret_leakage(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    error = (
        AuthenticationError("bad test-secret-that-must-not-leak", response=response, body=None)
        if status_code == 401
        else RateLimitError("bad test-secret-that-must-not-leak", response=response, body=None)
    )
    provider = _provider(monkeypatch, FakeResponses(error=error))

    with pytest.raises(OpenAIProviderError) as captured:
        provider.chat([{"role": "user", "content": "hello"}])

    assert "test-secret" not in str(captured.value)
    assert provider.health_check().last_request_success is False


def test_openai_timeout_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    provider = _provider(monkeypatch, FakeResponses(error=APITimeoutError(request)))

    with pytest.raises(OpenAIProviderError, match="timed out"):
        provider.chat([{"role": "user", "content": "hello"}])
