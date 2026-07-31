"""Provider boundary and OpenAI Responses API implementation for LLM inference."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, cast

import openai
from openai import OpenAI
from openai.types.responses import Response

from src.core.settings import OpenAISettings
from src.models.types import JsonObject


class LLMProviderError(RuntimeError):
    """Base error for safe, provider-independent LLM failures."""

    code = "provider_error"


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

    def __init__(
        self,
        settings: OpenAISettings,
        *,
        client: OpenAI | _OpenAIClient | None = None,
    ) -> None:
        """Initialize the provider with validated settings and an optional client.

        Args:
            settings: OpenAI timeout, retry, storage, and credential settings.
            client: Optional injected Responses API client for offline tests.
        """

        self._settings = settings
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

        try:
            encoded_input = json.dumps(
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

        try:
            response = self._get_client().responses.create(
                model=model,
                instructions=system_prompt,
                input=encoded_input,
                text={"format": {"type": "json_object"}},
                store=self._settings.store_remote,
                timeout=float(self._settings.timeout_seconds),
            )
        except openai.APITimeoutError:
            raise LLMTimeoutError("OpenAI request timed out") from None
        except openai.RateLimitError:
            raise LLMRateLimitError("OpenAI request exceeded its rate limit") from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise LLMAuthenticationError(
                "OpenAI credentials or permissions were rejected"
            ) from None
        except (
            openai.BadRequestError,
            openai.NotFoundError,
            openai.UnprocessableEntityError,
        ):
            raise LLMInvalidRequestError("OpenAI rejected the request") from None
        except openai.APIConnectionError:
            raise LLMConnectionError("OpenAI could not be reached") from None
        except (openai.APIStatusError, openai.APIError):
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
