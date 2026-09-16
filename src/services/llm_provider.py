"""Provider boundary and OpenAI Responses API implementation for LLM inference."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from time import sleep
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import openai
from openai import OpenAI
from openai.types.responses import Response
from pydantic import SecretStr

from src.core.settings import (
    AppSettings,
    LLMProviderName,
    OpenAISettings,
    QwenSettings,
)
from src.models.types import JsonObject
from src.services.provider_transport import resolve_provider_transport_config

_SAFE_PROVIDER_METADATA = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,128}$")
_API_KEY_DISCLOSURE = re.compile(
    r"(?i)(api[ _-]?key(?:\s+provided)?(?:\s+is)?\s*[:=]\s*)\S+"
)
_BEARER_DISCLOSURE = re.compile(r"(?i)(bearer\s+)\S+")
_MAX_PROVIDER_MESSAGE_LENGTH = 2_000
_MAX_RETRY_DELAY_SECONDS = 60.0
_NON_RETRYABLE_RATE_LIMIT_CODES = {
    "billing_hard_limit_reached",
    "credit_balance_exhausted",
    "insufficient_quota",
}


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
        configuration_stage: object = None,
        retry_count: int = 0,
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
            configuration_stage: Optional safe provider configuration stage.
            retry_count: Number of additional transport attempts already made.
            api_key: Optional credential to redact from diagnostics.
        """

        safe_message = _safe_provider_message(message, api_key=api_key)
        super().__init__(safe_message or "LLM provider request failed")
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
        self.configuration_stage = _safe_provider_metadata(configuration_stage)
        self.retry_count = retry_count if 0 <= retry_count <= 100 else 0


class LLMConfigurationError(LLMProviderError):
    """Raised when required provider configuration is missing."""

    code = "configuration_error"


class CredentialNotConfigured(LLMConfigurationError):
    """Raised when the selected live provider has no configured credential."""

    code = "credential_not_configured"


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


class LLMInvalidJSONError(LLMInvalidResponseError):
    """Raised when provider text cannot be decoded as one JSON object."""

    code = "invalid_json"


def _mapped_status_error(
    error_type: type[LLMProviderError],
    message: str,
    exc: openai.APIStatusError,
    *,
    api_key: str | None,
    retry_count: int,
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
        retry_count=retry_count,
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class LLMProviderCapabilities:
    """Static structured-inference capabilities exposed by one adapter."""

    structured_json: bool
    native_json_schema: bool
    remote_storage_enabled: bool


@dataclass(frozen=True, slots=True)
class LLMProviderResult:
    """Structured result and safe metadata returned by an LLM provider."""

    content: JsonObject
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    response_id: str | None = None
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class LLMProviderCall:
    """One invocation captured by the test-only fake provider."""

    model: str
    system_prompt: str
    input_payload: JsonObject
    response_schema: JsonObject | None = None


class LLMProvider(Protocol):
    """Unified interface implemented by all Phase One LLM providers."""

    provider_name: str

    @property
    def capabilities(self) -> LLMProviderCapabilities:
        """Return adapter capabilities without a remote discovery request."""
        ...

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
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
        text: object | None = None,
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


class _ResponsesProviderSettings(Protocol):
    """Shared settings surface for OpenAI-compatible Responses providers."""

    api_key: SecretStr | None
    timeout_seconds: int
    max_retries: int
    store_remote: bool


class OpenAIProvider:
    """OpenAI Responses API provider for Phase One structured inference."""

    provider_name = "openai"
    json_input_prefix = "JSON input:\n"

    def __init__(
        self,
        settings: _ResponsesProviderSettings,
        *,
        request_extra_body: JsonObject | None = None,
        base_url: str | None = None,
        provider_label: str = "OpenAI",
        client: OpenAI | _OpenAIClient | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        """Initialize the provider with validated settings and an optional client.

        Args:
            settings: OpenAI timeout, retry, storage, and credential settings.
            request_extra_body: Optional compatible-provider body extensions.
            base_url: Optional OpenAI-compatible API root.
            provider_label: Safe provider name used in public errors.
            client: Optional injected Responses API client for offline tests.
            sleeper: Injectable bounded-retry delay function.
        """

        self._settings = settings
        self._base_url = base_url
        self._provider_label = provider_label
        self._request_extra_body = (
            None if request_extra_body is None else deepcopy(request_extra_body)
        )
        self._client = cast(_OpenAIClient | None, client)
        self._sleeper = sleeper

    @property
    def capabilities(self) -> LLMProviderCapabilities:
        """Return OpenAI's locally known structured-output capabilities."""

        return LLMProviderCapabilities(
            structured_json=True,
            native_json_schema=True,
            remote_storage_enabled=self._settings.store_remote,
        )

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
    ) -> LLMProviderResult:
        """Invoke the OpenAI Responses API and parse a JSON object.

        Args:
            model: Configured OpenAI model identifier.
            system_prompt: System-level instructions sent to the model.
            input_payload: JSON-compatible user message payload.
            response_schema: Optional JSON Schema for native structured output.
            schema_name: Provider-safe stable name for the response schema.

        Returns:
            Parsed JSON content and non-sensitive provider metadata.

        Raises:
            LLMProviderError: If configuration, transport, API, or response
                validation fails.
        """

        encoded_input = self.encode_input_payload(input_payload)
        response, retry_count = self._request_with_retries(
            model=model,
            system_prompt=system_prompt,
            encoded_input=encoded_input,
            response_schema=response_schema,
            schema_name=schema_name,
        )

        content = self._parse_content(response.output_text)
        usage = response.usage
        return LLMProviderResult(
            content=content,
            model=response.model,
            prompt_tokens=None if usage is None else usage.input_tokens,
            completion_tokens=None if usage is None else usage.output_tokens,
            response_id=response.id,
            retry_count=retry_count,
        )

    def _request_with_retries(
        self,
        *,
        model: str,
        system_prompt: str,
        encoded_input: str,
        response_schema: JsonObject | None,
        schema_name: str,
    ) -> tuple[Response, int]:
        """Execute one bounded request sequence and expose actual retry count."""

        retry_count = 0
        while True:
            try:
                response = self._create_response(
                    model=model,
                    system_prompt=system_prompt,
                    encoded_input=encoded_input,
                    response_schema=response_schema,
                    schema_name=schema_name,
                )
                return response, retry_count
            except LLMProviderError:
                raise
            except openai.APIError as exc:
                if self._is_retryable(exc) and retry_count < self._settings.max_retries:
                    delay = self._retry_delay(exc, retry_count)
                    retry_count += 1
                    self._sleeper(delay)
                    continue
                raise self._map_sdk_error(exc, retry_count=retry_count) from None
            except Exception:
                raise LLMRemoteError(
                    f"{self._provider_label} request failed",
                    retry_count=retry_count,
                ) from None

    def _create_response(
        self,
        *,
        model: str,
        system_prompt: str,
        encoded_input: str,
        response_schema: JsonObject | None,
        schema_name: str,
    ) -> Response:
        """Create one SDK response using this adapter's structured mode."""

        text_format = self._text_format(response_schema, schema_name)
        return self._request_client().responses.create(
            model=model,
            instructions=system_prompt,
            input=encoded_input,
            text=text_format,
            store=self._settings.store_remote,
            timeout=float(self._settings.timeout_seconds),
            extra_body=self._request_extra_body,
        )

    def _request_client(self) -> _OpenAIClient:
        """Return a client view with SDK-internal retries disabled."""

        client = self._get_client()
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            return cast(_OpenAIClient, with_options(max_retries=0))
        return client

    def _text_format(
        self,
        response_schema: JsonObject | None,
        schema_name: str,
    ) -> object:
        """Return OpenAI native JSON object or strict JSON Schema mode."""

        if response_schema is None:
            return {"format": {"type": "json_object"}}
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema_name) is None:
            raise LLMInvalidRequestError("LLM response schema name is invalid")
        return {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": deepcopy(response_schema),
                "strict": True,
            }
        }

    def _map_sdk_error(
        self,
        exc: openai.APIError,
        *,
        retry_count: int,
    ) -> LLMProviderError:
        """Map one SDK exception to a provider-independent safe error."""

        if isinstance(exc, openai.APITimeoutError):
            secret = self._settings.api_key
            api_key = None if secret is None else secret.get_secret_value()
            return LLMTimeoutError(
                f"{self._provider_label} request timed out",
                provider_endpoint=str(exc.request.url),
                retry_count=retry_count,
                api_key=api_key,
            )
        if isinstance(exc, openai.RateLimitError):
            return self._map_status_error(
                LLMRateLimitError,
                f"{self._provider_label} request exceeded its rate limit",
                exc,
                retry_count=retry_count,
            )
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return self._map_status_error(
                LLMAuthenticationError,
                f"{self._provider_label} credentials or permissions were rejected",
                exc,
                retry_count=retry_count,
            )
        if isinstance(
            exc,
            (
                openai.BadRequestError,
                openai.NotFoundError,
                openai.UnprocessableEntityError,
            ),
        ):
            return self._map_status_error(
                LLMInvalidRequestError,
                f"{self._provider_label} rejected the request",
                exc,
                retry_count=retry_count,
            )
        if isinstance(exc, openai.APIConnectionError):
            return LLMConnectionError(
                f"{self._provider_label} could not be reached",
                retry_count=retry_count,
            )
        if isinstance(exc, openai.APIStatusError):
            return self._map_status_error(
                LLMRemoteError,
                f"{self._provider_label} request failed",
                exc,
                retry_count=retry_count,
            )
        return LLMRemoteError(
            f"{self._provider_label} request failed",
            retry_count=retry_count,
        )

    @staticmethod
    def _is_retryable(exc: openai.APIError) -> bool:
        """Return whether one transport/API failure permits another attempt."""

        if isinstance(exc, openai.RateLimitError):
            values = {exc.code, getattr(exc, "type", None)}
            return not bool(values.intersection(_NON_RETRYABLE_RATE_LIMIT_CODES))
        if isinstance(exc, openai.APIConnectionError):
            return True
        if isinstance(exc, openai.APIStatusError):
            return exc.status_code in {408, 409, 429} or exc.status_code >= 500
        return False

    @staticmethod
    def _retry_delay(exc: openai.APIError, retry_count: int) -> float:
        """Return a bounded Retry-After or deterministic exponential delay."""

        if isinstance(exc, openai.APIStatusError):
            headers = exc.response.headers
            retry_after = headers.get("retry-after")
            retry_after_ms = headers.get("retry-after-ms")
            for raw, scale in ((retry_after, 1.0), (retry_after_ms, 0.001)):
                try:
                    delay = float(raw) * scale if raw is not None else -1.0
                except ValueError:
                    continue
                if 0.0 <= delay <= _MAX_RETRY_DELAY_SECONDS:
                    return delay
        return float(min(0.5 * (2**retry_count), 8.0))

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
        *,
        retry_count: int,
    ) -> LLMProviderError:
        """Map an SDK status error using this provider's secret redaction."""

        secret = self._settings.api_key
        api_key = None if secret is None else secret.get_secret_value()
        return _mapped_status_error(
            error_type,
            message,
            exc,
            api_key=api_key,
            retry_count=retry_count,
        )

    def _get_client(self) -> _OpenAIClient:
        if self._client is not None:
            return self._client

        secret = self._settings.api_key
        if secret is None or not secret.get_secret_value().strip():
            raise CredentialNotConfigured(
                f"{self._provider_label} API key is not configured",
                configuration_stage="credential_resolution",
            )

        try:
            transport = resolve_provider_transport_config()
            http_client = transport.build_http_client()
            if self._base_url is None and http_client is None:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=0,
                )
            elif self._base_url is None:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=0,
                    http_client=http_client,
                )
            elif http_client is None:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    base_url=self._base_url,
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=0,
                )
            else:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    base_url=self._base_url,
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=0,
                    http_client=http_client,
                )
            self._client = cast(_OpenAIClient, sdk_client)
        except ValueError as exc:
            message = str(exc).casefold()
            if "socks" in message or "socksio" in message:
                raise LLMConfigurationError(
                    f"{self._provider_label} client initialization requires "
                    "HTTPX SOCKS support",
                    configuration_stage="client_initialization",
                ) from None
            raise LLMConfigurationError(
                f"{self._provider_label} client initialization failed",
                configuration_stage="client_initialization",
            ) from None
        except Exception:
            raise LLMConfigurationError(
                f"{self._provider_label} client initialization failed",
                configuration_stage="client_initialization",
            ) from None
        return self._client

    def _parse_content(self, output_text: str) -> JsonObject:
        try:
            decoded: object = json.loads(output_text)
        except (TypeError, ValueError):
            raise LLMInvalidJSONError(
                f"{self._provider_label} response was not valid JSON"
            ) from None
        if not isinstance(decoded, dict):
            raise LLMInvalidJSONError(
                f"{self._provider_label} response JSON must be an object"
            )
        return cast(JsonObject, decoded)


class QwenProvider(OpenAIProvider):
    """DashScope Qwen implementation through the unified Responses boundary."""

    provider_name = "qwen"

    def __init__(
        self,
        settings: QwenSettings,
        *,
        client: OpenAI | _OpenAIClient | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        """Initialize Qwen with its OpenAI-compatible endpoint.

        Args:
            settings: Validated DashScope model and request settings.
            client: Optional injected compatible client for offline tests.
            sleeper: Injectable bounded-retry delay function.
        """

        secret = settings.api_key
        if secret is None or not secret.get_secret_value().strip():
            raise CredentialNotConfigured(
                "Qwen API key is not configured",
                configuration_stage="credential_resolution",
            )
        super().__init__(
            settings,
            request_extra_body={"enable_thinking": settings.enable_thinking},
            base_url=settings.base_url,
            provider_label="Qwen",
            client=client,
            sleeper=sleeper,
        )

    @property
    def capabilities(self) -> LLMProviderCapabilities:
        """Return Qwen Responses capabilities without a remote probe."""

        return LLMProviderCapabilities(
            structured_json=True,
            native_json_schema=False,
            remote_storage_enabled=self._settings.store_remote,
        )

    def _create_response(
        self,
        *,
        model: str,
        system_prompt: str,
        encoded_input: str,
        response_schema: JsonObject | None,
        schema_name: str,
    ) -> Response:
        """Create Qwen output without leaking unsupported OpenAI text options."""

        del response_schema, schema_name
        return self._request_client().responses.create(
            model=model,
            instructions=system_prompt,
            input=encoded_input,
            store=self._settings.store_remote,
            timeout=float(self._settings.timeout_seconds),
            extra_body=self._request_extra_body,
        )


@dataclass(frozen=True, slots=True)
class ConfiguredLLMProvider:
    """Selected live provider and its provider-specific models."""

    provider: LLMProvider
    provider_name: LLMProviderName
    model_default: str
    model_fast: str
    endpoint: str
    settings: OpenAISettings | QwenSettings


def build_configured_llm_provider(
    settings: AppSettings,
    *,
    client: OpenAI | _OpenAIClient | None = None,
) -> ConfiguredLLMProvider:
    """Build the configured live LLM provider at the composition boundary.

    Args:
        settings: Unified application settings.
        client: Optional compatible SDK client for offline tests.

    Returns:
        Selected provider with model and diagnostic metadata.
    """

    if settings.llm.provider is LLMProviderName.QWEN:
        qwen = settings.qwen
        return ConfiguredLLMProvider(
            provider=QwenProvider(qwen, client=client),
            provider_name=LLMProviderName.QWEN,
            model_default=qwen.model_default,
            model_fast=qwen.model_fast,
            endpoint=f"{qwen.base_url.rstrip('/')}/responses",
            settings=qwen,
        )
    openai_settings = settings.openai
    return ConfiguredLLMProvider(
        provider=OpenAIProvider(openai_settings, client=client),
        provider_name=LLMProviderName.OPENAI,
        model_default=openai_settings.model_default,
        model_fast=openai_settings.model_fast,
        endpoint="https://api.openai.com/v1/responses",
        settings=openai_settings,
    )


class FakeLLMProvider:
    """Deterministic provider for unit tests with no network access."""

    provider_name = "fake"

    def __init__(
        self,
        response: JsonObject,
        *,
        model: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        retry_count: int = 0,
        remote_storage_enabled: bool = False,
        error: LLMProviderError | None = None,
    ) -> None:
        """Configure a fixed response or mapped error.

        Args:
            response: JSON object returned by each successful invocation.
            model: Optional resolved model version returned in metadata.
            prompt_tokens: Optional fake input-token count.
            completion_tokens: Optional fake output-token count.
            retry_count: Deterministic number of simulated retries.
            remote_storage_enabled: Simulated remote-storage configuration.
            error: Optional mapped error raised by each invocation.
        """

        self._response = deepcopy(response)
        self._model = model
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._retry_count = retry_count
        self._remote_storage_enabled = remote_storage_enabled
        self._error = error
        self.calls: list[LLMProviderCall] = []

    @property
    def capabilities(self) -> LLMProviderCapabilities:
        """Return deterministic Fake capabilities for offline parity tests."""

        return LLMProviderCapabilities(
            structured_json=True,
            native_json_schema=True,
            remote_storage_enabled=self._remote_storage_enabled,
        )

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
    ) -> LLMProviderResult:
        """Capture the request and return the configured deterministic result."""

        del schema_name

        self.calls.append(
            LLMProviderCall(
                model=model,
                system_prompt=system_prompt,
                input_payload=deepcopy(input_payload),
                response_schema=(
                    None if response_schema is None else deepcopy(response_schema)
                ),
            )
        )
        if self._error is not None:
            raise self._error
        return LLMProviderResult(
            content=deepcopy(self._response),
            model=self._model or model,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            response_id="fake-response",
            retry_count=self._retry_count,
        )
