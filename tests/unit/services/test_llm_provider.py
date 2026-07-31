"""Offline tests for the unified LLM provider boundary."""

from __future__ import annotations

import httpx
import openai
import pytest
from openai import OpenAI
from openai.types.responses import Response
from pydantic import SecretStr

from src.core.settings import OpenAISettings
from src.models.types import JsonObject
from src.services.llm_provider import (
    FakeLLMProvider,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRemoteError,
    LLMTimeoutError,
    OpenAIProvider,
)


def _response(output_text: str) -> Response:
    return Response.model_validate(
        {
            "id": "resp-test",
            "created_at": 0.0,
            "model": "configured-model",
            "object": "response",
            "output": [
                {
                    "id": "msg-test",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                            "annotations": [],
                        }
                    ],
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 10,
                "input_tokens_details": {
                    "cache_write_tokens": 0,
                    "cached_tokens": 0,
                },
                "output_tokens": 5,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 15,
            },
        }
    )


class StubResponses:
    """Capture one Responses API call and return or raise a configured value."""

    def __init__(
        self,
        *,
        response: Response | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, object]] = []

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text: object,
        store: bool,
        timeout: float,
    ) -> Response:
        self.calls.append(
            {
                "model": model,
                "instructions": instructions,
                "input": input,
                "text": text,
                "store": store,
                "timeout": timeout,
            }
        )
        if self._error is not None:
            raise self._error
        if self._response is None:
            raise AssertionError("stub response was not configured")
        return self._response


class StubClient:
    """Minimal injected OpenAI client."""

    def __init__(self, responses: StubResponses) -> None:
        self.responses = responses


def test_openai_provider_sends_structured_responses_request() -> None:
    """System instructions, user JSON, storage, and timeout reach the SDK."""

    responses = StubResponses(response=_response('{"summary":"ok"}'))
    provider = OpenAIProvider(
        OpenAISettings(timeout_seconds=17, store_remote=True),
        client=StubClient(responses),
    )

    result = provider.invoke_json(
        model="configured-model",
        system_prompt="Return a JSON object.",
        input_payload={"asset_id": "US:AAPL"},
    )

    assert result.content == {"summary": "ok"}
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.response_id == "resp-test"
    assert responses.calls == [
        {
            "model": "configured-model",
            "instructions": "Return a JSON object.",
            "input": '{"asset_id":"US:AAPL"}',
            "text": {"format": {"type": "json_object"}},
            "store": True,
            "timeout": 17.0,
        }
    ]


@pytest.mark.parametrize("output_text", ["not-json", "[]"])
def test_openai_provider_rejects_invalid_json_objects(output_text: str) -> None:
    """Malformed JSON and non-object JSON are mapped to one safe error."""

    provider = OpenAIProvider(
        OpenAISettings(),
        client=StubClient(StubResponses(response=_response(output_text))),
    )

    with pytest.raises(LLMInvalidResponseError):
        provider.invoke_json("model", "system", {"input": "value"})


def test_openai_provider_maps_timeout_without_leaking_cause() -> None:
    """SDK timeout details are not copied into the public error message."""

    secret = "unit-test-secret"
    sdk_error = openai.APITimeoutError(
        request=httpx.Request("POST", f"https://unit.test/{secret}")
    )
    provider = OpenAIProvider(
        OpenAISettings(api_key=SecretStr(secret)),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(LLMTimeoutError) as raised:
        provider.invoke_json("model", "system", {"input": secret})

    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("sdk_error", "mapped_type"),
    [
        (
            openai.AuthenticationError(
                "secret remote detail",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://unit.test/v1/responses"),
                ),
                body=None,
            ),
            LLMAuthenticationError,
        ),
        (
            openai.BadRequestError(
                "secret remote detail",
                response=httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://unit.test/v1/responses"),
                ),
                body=None,
            ),
            LLMInvalidRequestError,
        ),
        (
            openai.APIConnectionError(
                message="secret remote detail",
                request=httpx.Request("POST", "https://unit.test/v1/responses"),
            ),
            LLMConnectionError,
        ),
        (
            openai.InternalServerError(
                "secret remote detail",
                response=httpx.Response(
                    500,
                    request=httpx.Request("POST", "https://unit.test/v1/responses"),
                ),
                body=None,
            ),
            LLMRemoteError,
        ),
    ],
)
def test_openai_provider_maps_sdk_errors_to_safe_types(
    sdk_error: Exception,
    mapped_type: type[LLMProviderError],
) -> None:
    """Provider-specific failures expose stable types and safe messages."""

    provider = OpenAIProvider(
        OpenAISettings(),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(mapped_type) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert "secret remote detail" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_openai_provider_requires_configured_api_key() -> None:
    """The default client cannot be created without a non-empty API key."""

    provider = OpenAIProvider(OpenAISettings(api_key=None))

    with pytest.raises(LLMConfigurationError, match="not configured"):
        provider.invoke_json("model", "system", {"input": "value"})


def test_openai_provider_configures_sdk_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured timeout and retry values are supplied to the official SDK."""

    captured: dict[str, object] = {}
    responses = StubResponses(response=_response('{"ok":true}'))

    def fake_client_factory(**kwargs: object) -> StubClient:
        captured.update(kwargs)
        return StubClient(responses)

    monkeypatch.setattr("src.services.llm_provider.OpenAI", fake_client_factory)
    settings = OpenAISettings(
        api_key=SecretStr("unit-test-secret"),
        timeout_seconds=23,
        max_retries=4,
    )

    OpenAIProvider(settings).invoke_json("model", "system", {"input": "value"})

    assert captured["api_key"] == "unit-test-secret"
    assert captured["timeout"] == 23.0
    assert captured["max_retries"] == 4


def test_openai_sdk_stops_after_configured_rate_limit_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The official SDK performs no more than max_retries additional attempts."""

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"retry-after-ms": "0"},
            json={
                "error": {
                    "message": "rate limited",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
            request=request,
        )

    monkeypatch.setattr("openai._base_client.time.sleep", lambda _: None)
    settings = OpenAISettings(timeout_seconds=1, max_retries=2)
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAI(
        api_key="unit-test-secret",
        base_url="https://unit.test/v1",
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        http_client=http_client,
    )
    provider = OpenAIProvider(settings, client=client)

    with pytest.raises(LLMRateLimitError):
        provider.invoke_json("model", "system", {"input": "value"})

    assert attempts == settings.max_retries + 1
    http_client.close()


def test_fake_provider_is_deterministic_and_captures_calls() -> None:
    """The fake provider supports complete offline dependency injection."""

    provider = FakeLLMProvider(
        {"result": "ok"},
        prompt_tokens=3,
        completion_tokens=2,
    )
    payload: JsonObject = {"nested": {"value": 1}}

    first = provider.invoke_json("model", "system", payload)
    payload["nested"] = {"value": 2}
    second = provider.invoke_json("model", "system", {"nested": {"value": 1}})

    assert first == second
    assert len(provider.calls) == 2
    assert provider.calls[0].input_payload == {"nested": {"value": 1}}
