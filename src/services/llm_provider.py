"""Provider boundary and OpenAI Responses API implementation for LLM inference."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import openai
from openai import OpenAI
from openai.types.responses import Response

from src.core.settings import OpenAISettings
from src.models.types import JsonObject

_SAFE_PROVIDER_METADATA = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,128}$")
_API_KEY_DISCLOSURE = re.compile(
    r"(?i)(api[ _-]?key(?:\s+provided)?(?:\s+is)?\s*[:=]\s*)\S+"
)
_BEARER_DISCLOSURE = re.compile(r"(?i)(bearer\s+)\S+")
_MAX_PROVIDER_MESSAGE_LENGTH = 2_000


def _safe_provider_metadata(value: object) -> str | None:
    """Return one bounded provider diagnostic value, or suppress it."""

    if not isinstance(value, str) or _SAFE_PROVIDER_METADATA.fullmatch(value) is None:
        return None
    return value


def _safe_provider_message(value: object, *, api_key: str | None) -> str | None:
    """Redact credentials from one bounded provider diagnostic message."""

    if not isinstance(value, str) or not value:
        return None
    sanitized = value
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = _API_KEY_DISCLOSURE.sub(r"\1[REDACTED]", sanitized)
    sanitized = _BEARER_DISCLOSURE.sub(r"\1[REDACTED]", sanitized)
    return sanitized[:_MAX_PROVIDER_MESSAGE_LENGTH]


def _safe_provider_endpoint(
    value: object,
    *,
    api_key: str | None,
) -> str | None:
    """Return an HTTP endpoint without query, fragment, or user information."""

    if not isinstance(value, str):
        return None
    sanitized = value.replace(api_key, "[REDACTED]") if api_key else value
    parsed = urlsplit(sanitized)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _provider_error_message(exc: openai.APIStatusError) -> object:
    """Extract the provider message from an SDK status error body."""

    body = exc.body
    if not isinstance(body, dict):
        return None
    nested_error = body.get("error")
    error = nested_error if isinstance(nested_error, dict) else body
    return error.get("message")


class LLMProviderError(RuntimeError):
    """Base error for safe, provider-independent LLM failures."""

    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider_code: object = None,
        provider_param: object = None,
        provider_type: object = None,
        provider_status_code: int | None = None,
        provider_endpoint: object = None,
        provider_message: object = None,
        provider_request_id: object = None,
        provider_retry_after: object = None,
        provider_rate_limit_reset_requests: object = None,
        provider_rate_limit_reset_tokens: object = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize a safe error with optional allowlisted diagnostics.

        Args:
            message: Provider-independent public error message.
            provider_code: Optional provider error code.
            provider_param: Optional rejected request parameter name.
            provider_type: Optional provider error category.
            provider_status_code: Optional provider HTTP status.
            provider_endpoint: Optional request endpoint.
            provider_message: Optional provider diagnostic message.
            provider_request_id: Optional provider request identifier.
            provider_retry_after: Optional Retry-After header.
            provider_rate_limit_reset_requests: Optional request-limit reset.
            provider_rate_limit_reset_tokens: Optional token-limit reset.
            api_key: Optional credential to redact from diagnostics.
        """

        super().__init__(message)
        self.provider_code = _safe_provider_metadata(provider_code)
        self.provider_param = _safe_provider_metadata(provider_param)
        self.provider_type = _safe_provider_metadata(provider_type)
        self.provider_status_code = (
            provider_status_code
            if provider_status_code is not None and 100 <= provider_status_code <= 599
            else None
        )
        self.provider_endpoint = _safe_provider_endpoint(
            provider_endpoint,
            api_key=api_key,
        )
        self.provider_message = _safe_provider_message(
            provider_message,
            api_key=api_key,
        )
        self.provider_request_id = _safe_provider_metadata(provider_request_id)
        self.provider_retry_after = _safe_provider_metadata(provider_retry_after)
        self.provider_rate_limit_reset_requests = _safe_provider_metadata(
            provider_rate_limit_reset_requests
        )
        self.provider_rate_limit_reset_tokens = _safe_provider_metadata(
            provider_rate_limit_reset_tokens
        )


class LLMConfigurationError(LLMProviderError):
    """Raised when required provider configuration is missing."""

    code = "configuration_error"


class LLMTimeoutError(LLMProviderError):
    """Raised when the provider request exceeds its configured timeout."""

    code = "timeout"


class LLMRateLimitError(LLMProviderError):
    """Raised when the provider rejects a request due to rate limiting."""

    code = "rate_limit"


class LLMAuthenticationError(LLMProviderError):
    """Raised when provider credentials or permissions are rejected."""

    code = "authentication"


class LLMInvalidRequestError(LLMProviderError):
    """Raised when a request is not accepted by the provider."""

    code = "invalid_request"


class LLMConnectionError(LLMProviderError):
    """Raised when the provider cannot be reached."""

    code = "connection"


class LLMRemoteError(LLMProviderError):
    """Raised for other errors returned by the remote provider."""

    code = "remote_error"


class LLMInvalidResponseError(LLMProviderError):
    """Raised when the provider response is not a valid JSON object."""

    code = "invalid_response"


def _mapped_status_error(
    error_type: type[LLMProviderError],
    message: str,
    exc: openai.APIStatusError,
    *,
    api_key: str | None,
) -> LLMProviderError:
    """Map one SDK status error with bounded, credential-safe diagnostics."""

    headers = exc.response.headers
    return error_type(
        message,
        provider_code=exc.code,
        provider_param=exc.param,
        provider_type=getattr(exc, "type", None),
        provider_status_code=exc.status_code,
        provider_endpoint=str(exc.request.url),
        provider_message=_provider_error_message(exc),
        provider_request_id=headers.get("x-request-id"),
        provider_retry_after=headers.get("retry-after"),
        provider_rate_limit_reset_requests=headers.get("x-ratelimit-reset-requests"),
        provider_rate_limit_reset_tokens=headers.get("x-ratelimit-reset-tokens"),
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class LLMProviderResult:
    """Structured result and safe metadata returned by an LLM provider."""

    content: JsonObject
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    response_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMProviderCall:
    """One invocation captured by the test-only fake provider."""

    model: str
    system_prompt: str
    input_payload: JsonObject


class LLMProvider(Protocol):
    """Unified interface implemented by all Phase One LLM providers."""

    provider_name: str

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> LLMProviderResult:
        """Return one structured JSON response."""
        ...


class _ResponsesClient(Protocol):
    """Narrow Responses API surface used for dependency injection."""

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text: object,
        store: bool,
        timeout: float,
        extra_body: object | None,
    ) -> Response:
        """Create one synchronous model response."""
        ...


class _OpenAIClient(Protocol):
    """Narrow OpenAI client surface used by the provider."""

    @property
    def responses(self) -> _ResponsesClient:
        """Return the synchronous Responses API resource."""
        ...


class OpenAIProvider:
    """OpenAI Responses API provider for Phase One structured inference."""

    provider_name = "openai"
    json_input_prefix = "JSON input:\n"

    def __init__(
        self,
        settings: OpenAISettings,
        *,
        request_extra_body: JsonObject | None = None,
        client: OpenAI | _OpenAIClient | None = None,
    ) -> None:
        """Initialize the provider with validated settings and an optional client.

        Args:
            settings: OpenAI timeout, retry, storage, and credential settings.
            request_extra_body: Optional compatible-provider body extensions.
            client: Optional injected Responses API client for offline tests.
        """

        self._settings = settings
        self._request_extra_body = (
            None if request_extra_body is None else deepcopy(request_extra_body)
        )
        self._client = cast(_OpenAIClient | None, client)

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> LLMProviderResult:
        """Invoke the OpenAI Responses API and parse a JSON object.

        Args:
            model: Configured OpenAI model identifier.
            system_prompt: System-level instructions sent to the model.
            input_payload: JSON-compatible user message payload.

        Returns:
            Parsed JSON content and non-sensitive provider metadata.

        Raises:
            LLMProviderError: If configuration, transport, API, or response
                validation fails.
        """

        encoded_input = self.encode_input_payload(input_payload)

        try:
            response = self._get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=encoded_input,
                text={"format": {"type": "json_object"}},
                store=self._settings.store_remote,
                timeout=float(self._settings.timeout_seconds),
                extra_body=self._request_extra_body,
            )
        except openai.APITimeoutError as exc:
            secret = self._settings.api_key
            api_key = None if secret is None else secret.get_secret_value()
            raise LLMTimeoutError(
                "OpenAI request timed out",
                provider_endpoint=str(exc.request.url),
                api_key=api_key,
            ) from None
        except openai.RateLimitError as exc:
            raise self._map_status_error(
                LLMRateLimitError,
                "OpenAI request exceeded its rate limit",
                exc,
            ) from None
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise self._map_status_error(
                LLMAuthenticationError,
                "OpenAI credentials or permissions were rejected",
                exc,
            ) from None
        except (
            openai.BadRequestError,
            openai.NotFoundError,
            openai.UnprocessableEntityError,
        ) as exc:
            raise self._map_status_error(
                LLMInvalidRequestError,
                "OpenAI rejected the request",
                exc,
            ) from None
        except openai.APIConnectionError:
            raise LLMConnectionError("OpenAI could not be reached") from None
        except openai.APIStatusError as exc:
            raise self._map_status_error(
                LLMRemoteError,
                "OpenAI request failed",
                exc,
            ) from None
        except openai.APIError:
            raise LLMRemoteError("OpenAI request failed") from None
        except LLMProviderError:
            raise
        except Exception:
            raise LLMRemoteError("OpenAI request failed") from None

        content = self._parse_content(response.output_text)
        usage = response.usage
        return LLMProviderResult(
            content=content,
            model=response.model,
            prompt_tokens=None if usage is None else usage.input_tokens,
            completion_tokens=None if usage is None else usage.output_tokens,
            response_id=response.id,
        )

    @classmethod
    def encode_input_payload(cls, input_payload: JsonObject) -> str:
        """Serialize a payload with the JSON-mode input marker required by OpenAI.

        Args:
            input_payload: JSON-compatible user payload.

        Returns:
            Deterministic compact JSON preceded by a stable JSON-mode marker.

        Raises:
            LLMInvalidRequestError: If the payload is not strict JSON.
        """

        try:
            payload_json = json.dumps(
                input_payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            raise LLMInvalidRequestError(
                "LLM input payload is not valid JSON"
            ) from None
        return f"{cls.json_input_prefix}{payload_json}"

    def _map_status_error(
        self,
        error_type: type[LLMProviderError],
        message: str,
        exc: openai.APIStatusError,
    ) -> LLMProviderError:
        """Map an SDK status error using this provider's secret redaction."""

        secret = self._settings.api_key
        api_key = None if secret is None else secret.get_secret_value()
        return _mapped_status_error(
            error_type,
            message,
            exc,
            api_key=api_key,
        )

    def _get_client(self) -> _OpenAIClient:
        if self._client is not None:
            return self._client

        secret = self._settings.api_key
        if secret is None or not secret.get_secret_value().strip():
            raise LLMConfigurationError("OpenAI API key is not configured")

        try:
            self._client = cast(
                _OpenAIClient,
                OpenAI(
                    api_key=secret.get_secret_value(),
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=self._settings.max_retries,
                ),
            )
        except Exception:
            raise LLMConfigurationError("OpenAI client initialization failed") from None
        return self._client

    @staticmethod
    def _parse_content(output_text: str) -> JsonObject:
        try:
            decoded: object = json.loads(output_text)
        except (TypeError, ValueError):
            raise LLMInvalidResponseError(
                "OpenAI response was not valid JSON"
            ) from None
        if not isinstance(decoded, dict):
            raise LLMInvalidResponseError("OpenAI response JSON must be an object")
        return cast(JsonObject, decoded)


class FakeLLMProvider:
    """Deterministic provider for unit tests with no network access."""

    provider_name = "fake"

    def __init__(
        self,
        response: JsonObject,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error: LLMProviderError | None = None,
    ) -> None:
        """Configure a fixed response or mapped error.

        Args:
            response: JSON object returned by each successful invocation.
            prompt_tokens: Optional fake input-token count.
            completion_tokens: Optional fake output-token count.
            error: Optional mapped error raised by each invocation.
        """

        self._response = deepcopy(response)
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._error = error
        self.calls: list[LLMProviderCall] = []

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> LLMProviderResult:
        """Capture the request and return the configured deterministic result."""

        self.calls.append(
            LLMProviderCall(
                model=model,
                system_prompt=system_prompt,
                input_payload=deepcopy(input_payload),
            )
        )
        if self._error is not None:
            raise self._error
        return LLMProviderResult(
            content=deepcopy(self._response),
            model=model,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            response_id="fake-response",
        )
