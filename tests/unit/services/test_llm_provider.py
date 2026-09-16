"""Offline tests for the unified LLM provider boundary."""

from __future__ import annotations

import httpx
import openai
import pytest
from openai import OpenAI
from openai.types.responses import Response
from pydantic import SecretStr

from src.core.settings import OpenAISettings, QwenSettings
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
    QwenProvider,
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
        text: object | None = None,
        store: bool,
        timeout: float,
        extra_body: object | None,
    ) -> Response:
        self.calls.append(
            {
                "model": model,
                "instructions": instructions,
                "input": input,
                "text": text,
                "store": store,
                "timeout": timeout,
                "extra_body": extra_body,
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
            "input": 'JSON input:\n{"asset_id":"US:AAPL"}',
            "text": {"format": {"type": "json_object"}},
            "store": True,
            "timeout": 17.0,
            "extra_body": None,
        }
    ]


def test_openai_provider_passes_compatible_request_extensions() -> None:
    """An injected compatible provider may receive explicit body extensions."""

    responses = StubResponses(response=_response('{"summary":"ok"}'))
    provider = OpenAIProvider(
        OpenAISettings(),
        request_extra_body={"enable_thinking": True},
        client=StubClient(responses),
    )

    provider.invoke_json(
        model="qwen",
        system_prompt="Return JSON.",
        input_payload={"context": "test"},
    )

    assert responses.calls[0]["extra_body"] == {"enable_thinking": True}


def test_openai_provider_places_json_mode_marker_in_input_message() -> None:
    """The input message itself must identify JSON mode for API validation."""

    encoded = OpenAIProvider.encode_input_payload(
        {"nested": {"b": 2, "a": 1}},
    )

    assert encoded == 'JSON input:\n{"nested":{"a":1,"b":2}}'


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
        OpenAISettings(api_key=SecretStr(secret), max_retries=0),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(LLMTimeoutError) as raised:
        provider.invoke_json("model", "system", {"input": secret})

    assert secret not in str(raised.value)
    assert secret not in repr(raised.value.provider_endpoint)
    assert raised.value.provider_endpoint == "https://unit.test/[REDACTED]"
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
        OpenAISettings(max_retries=0),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(mapped_type) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert "secret remote detail" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_invalid_request_exposes_only_allowlisted_provider_metadata() -> None:
    """Safe diagnostic fields identify a rejected parameter without raw details."""

    secret = "unit-test-secret"
    sdk_error = openai.BadRequestError(
        "secret remote detail",
        response=httpx.Response(
            400,
            request=httpx.Request("POST", "https://unit.test/v1/responses"),
        ),
        body={
            "code": "unsupported_value",
            "param": "text.format.type",
            "type": "invalid_request_error",
            "message": f"Rejected request with API key provided: {secret}",
        },
    )
    provider = OpenAIProvider(
        OpenAISettings(api_key=SecretStr(secret)),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(LLMInvalidRequestError) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert raised.value.provider_code == "unsupported_value"
    assert raised.value.provider_param == "text.format.type"
    assert raised.value.provider_type == "invalid_request_error"
    assert raised.value.provider_status_code == 400
    assert raised.value.provider_endpoint == "https://unit.test/v1/responses"
    assert raised.value.provider_message is not None
    assert secret not in raised.value.provider_message
    assert "[REDACTED]" in raised.value.provider_message
    assert "secret remote detail" not in str(raised.value)


def test_rate_limit_exposes_billing_code_and_retry_metadata() -> None:
    """A 429 should distinguish quota failures from transient request limits."""

    sdk_error = openai.RateLimitError(
        "secret remote detail",
        response=httpx.Response(
            429,
            request=httpx.Request("POST", "https://unit.test/v1/responses"),
            headers={
                "x-request-id": "req-safe-123",
                "retry-after": "20",
                "x-ratelimit-reset-requests": "1s",
                "x-ratelimit-reset-tokens": "2m0s",
            },
        ),
        body={
            "code": "credit_balance_exhausted",
            "param": None,
            "type": "insufficient_quota",
            "message": "Your credit balance is exhausted.",
        },
    )
    provider = OpenAIProvider(
        OpenAISettings(),
        client=StubClient(StubResponses(error=sdk_error)),
    )

    with pytest.raises(LLMRateLimitError) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert raised.value.provider_code == "credit_balance_exhausted"
    assert raised.value.provider_type == "insufficient_quota"
    assert raised.value.provider_status_code == 429
    assert raised.value.provider_message == "Your credit balance is exhausted."
    assert raised.value.provider_request_id == "req-safe-123"
    assert raised.value.provider_retry_after == "20"
    assert raised.value.provider_rate_limit_reset_requests == "1s"
    assert raised.value.provider_rate_limit_reset_tokens == "2m0s"


def test_provider_diagnostics_reject_unbounded_remote_values() -> None:
    """Provider-controlled prose must not cross the safe exception boundary."""

    error = LLMProviderError(
        "safe message",
        provider_code="unsafe remote prose",
        provider_param="input secret-value",
        provider_type="<invalid>",
        provider_status_code=999,
        provider_endpoint="file:///unsafe",
        provider_message="Bearer secret-token",
        provider_request_id="unsafe request id",
        provider_retry_after="20 seconds",
        provider_rate_limit_reset_requests="<one>",
        provider_rate_limit_reset_tokens="two tokens",
    )

    assert error.provider_code is None
    assert error.provider_param is None
    assert error.provider_type is None
    assert error.provider_status_code is None
    assert error.provider_endpoint is None
    assert error.provider_message == "Bearer [REDACTED]"
    assert error.provider_request_id is None
    assert error.provider_retry_after is None
    assert error.provider_rate_limit_reset_requests is None
    assert error.provider_rate_limit_reset_tokens is None


def test_openai_provider_requires_configured_api_key() -> None:
    """The default client cannot be created without a non-empty API key."""

    provider = OpenAIProvider(OpenAISettings(api_key=None))

    with pytest.raises(LLMConfigurationError, match="not configured"):
        provider.invoke_json("model", "system", {"input": "value"})


def test_openai_provider_configures_sdk_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK retry loop is disabled so the adapter can count retries."""

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
    assert captured["max_retries"] == 0


def test_openai_provider_maps_missing_socks_transport_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy transport dependency error must be actionable and redacted."""

    def missing_socks_factory(**kwargs: object) -> StubClient:
        del kwargs
        raise ValueError(
            "Using SOCKS proxy secret-proxy-value, install the socksio package"
        )

    monkeypatch.setattr("src.services.llm_provider.OpenAI", missing_socks_factory)
    provider = OpenAIProvider(OpenAISettings(api_key=SecretStr("unit-test-secret")))

    with pytest.raises(
        LLMConfigurationError,
        match="client initialization requires HTTPX SOCKS support",
    ) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert "secret-proxy-value" not in str(raised.value)
    assert "unit-test-secret" not in str(raised.value)
    assert raised.value.configuration_stage == "client_initialization"


def test_qwen_prefers_protocol_http_proxy_over_conflicting_all_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qwen initialization must not select an ambiguous generic SOCKS proxy."""

    proxy_secret = "proxy-secret-must-not-leak"
    captured_http: dict[str, object] = {}
    captured_sdk: dict[str, object] = {}
    responses = StubResponses(response=_response('{"ok":true}'))

    def fake_http_client(**kwargs: object) -> object:
        captured_http.update(kwargs)
        return object()

    def fake_client_factory(**kwargs: object) -> StubClient:
        captured_sdk.update(kwargs)
        return StubClient(responses)

    for name in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.unit.test:8080")
    monkeypatch.setenv(
        "ALL_PROXY",
        f"socks5://user:{proxy_secret}@proxy.unit.test:1080",
    )
    monkeypatch.setattr(
        "src.services.llm_provider.openai.DefaultHttpxClient",
        fake_http_client,
    )
    monkeypatch.setattr("src.services.llm_provider.OpenAI", fake_client_factory)

    provider = QwenProvider(
        QwenSettings(api_key=SecretStr("offline-qwen-key")),
    )
    result = provider.invoke_json("qwen-offline", "system", {"input": "value"})

    assert result.content == {"ok": True}
    assert captured_http == {
        "proxy": "http://proxy.unit.test:8080",
        "trust_env": False,
    }
    assert captured_sdk["http_client"] is not None
    assert proxy_secret not in repr(captured_http)
    assert proxy_secret not in repr(captured_sdk)


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


def test_provider_reports_actual_retry_count_after_transient_rate_limit() -> None:
    """A transient 429 is retried once and reported in the provider result."""

    rate_limit = openai.RateLimitError(
        "remote detail",
        response=httpx.Response(
            429,
            request=httpx.Request("POST", "https://unit.test/v1/responses"),
            headers={"retry-after-ms": "0"},
        ),
        body={"code": "rate_limit_exceeded", "type": "rate_limit_error"},
    )

    class SequenceResponses(StubResponses):
        def __init__(self) -> None:
            super().__init__(response=_response('{"ok":true}'))
            self._attempt = 0

        def create(
            self,
            *,
            model: str,
            instructions: str,
            input: str,
            text: object | None = None,
            store: bool,
            timeout: float,
            extra_body: object | None,
        ) -> Response:
            self._attempt += 1
            if self._attempt == 1:
                raise rate_limit
            return super().create(
                model=model,
                instructions=instructions,
                input=input,
                text=text,
                store=store,
                timeout=timeout,
                extra_body=extra_body,
            )

    responses = SequenceResponses()
    delays: list[float] = []
    provider = OpenAIProvider(
        OpenAISettings(max_retries=2),
        client=StubClient(responses),
        sleeper=delays.append,
    )

    result = provider.invoke_json("model", "system", {"input": "value"})

    assert result.retry_count == 1
    assert responses._attempt == 2
    assert delays == [0.0]


def test_provider_stops_after_timeout_retry_limit() -> None:
    """Timeout retries are finite and the mapped error carries their count."""

    error = openai.APITimeoutError(
        request=httpx.Request("POST", "https://unit.test/v1/responses")
    )
    responses = StubResponses(error=error)
    provider = OpenAIProvider(
        OpenAISettings(max_retries=2),
        client=StubClient(responses),
        sleeper=lambda _: None,
    )

    with pytest.raises(LLMTimeoutError) as raised:
        provider.invoke_json("model", "system", {"input": "value"})

    assert raised.value.retry_count == 2
    assert len(responses.calls) == 3


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
