"""Cached, observable, and dependency-injectable structured LLM gateway."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from time import monotonic
from typing import Protocol, cast

import structlog
from structlog.typing import FilteringBoundLogger

from src.core.settings import OpenAISettings
from src.models.types import JsonObject
from src.repositories.base import RepositoryError
from src.repositories.records import LLMCacheRecord
from src.services.llm_provider import (
    LLMProvider,
    LLMProviderError,
    OpenAIProvider,
)


class LLMCacheError(RuntimeError):
    """Raised when the LLM cache cannot be read or updated."""

    code = "cache_error"


class LLMCache(Protocol):
    """Persistence boundary required by the LLM gateway."""

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        """Return one cached response."""
        ...

    def put(self, record: LLMCacheRecord) -> None:
        """Persist one cached response."""
        ...


class LLMGateway:
    """Single Phase One entry point for cached structured LLM inference."""

    def __init__(
        self,
        cache_repo: LLMCache,
        settings: OpenAISettings,
        *,
        provider: LLMProvider | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        """Initialize the gateway with injected persistence and provider boundaries.

        Args:
            cache_repo: Provider-independent structured response cache.
            settings: Validated OpenAI request settings.
            provider: Optional provider replacement, primarily for tests.
            logger: Optional structured logger replacement.
        """

        self._cache_repo = cache_repo
        self._provider = provider if provider is not None else OpenAIProvider(settings)
        self._logger = (
            logger
            if logger is not None
            else cast(
                FilteringBoundLogger,
                structlog.get_logger(__name__),
            )
        )

    @staticmethod
    def build_cache_key(
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> str:
        """Build a deterministic key from all inference-affecting inputs.

        Args:
            model: Configured model identifier.
            system_prompt: Complete system instructions.
            input_payload: JSON-compatible user payload.

        Returns:
            Lowercase SHA-256 hexadecimal digest.

        Raises:
            ValueError: If any value cannot be encoded as strict JSON.
        """

        try:
            canonical = json.dumps(
                {
                    "input_payload": input_payload,
                    "model": model,
                    "system_prompt": system_prompt,
                },
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            raise ValueError("LLM request inputs must be valid JSON") from None
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _cache_key(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> str:
        """Return the canonical cache key used by this Gateway."""

        return self.build_cache_key(model, system_prompt, input_payload)

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        """Return cached or newly generated structured JSON content.

        Args:
            model: Configured model identifier.
            system_prompt: Complete system instructions.
            input_payload: JSON-compatible user payload.

        Returns:
            Provider-independent JSON object.

        Raises:
            LLMCacheError: If cache persistence fails.
            LLMProviderError: If the provider request or response fails.
        """

        started_at = monotonic()
        cache_key = self._cache_key(model, system_prompt, input_payload)
        request_fingerprint = cache_key[:12]

        try:
            cached = self._cache_repo.get(cache_key)
        except RepositoryError:
            cache_error = LLMCacheError("LLM cache read failed")
            self._log_failure(
                model=model,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                error_code=cache_error.code,
            )
            raise cache_error from None

        if cached is not None:
            self._logger.info(
                "llm_request_completed",
                provider=cached.provider,
                model=model,
                status="ok",
                cache_hit=True,
                latency_ms=self._latency_ms(started_at),
                prompt_tokens=None,
                completion_tokens=None,
                response_id=None,
                request_fingerprint=request_fingerprint,
            )
            return deepcopy(cached.response)

        try:
            result = self._provider.invoke_json(
                model=model,
                system_prompt=system_prompt,
                input_payload=input_payload,
            )
        except LLMProviderError as exc:
            self._log_failure(
                model=model,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                error_code=exc.code,
            )
            raise
        except Exception:
            provider_error = LLMProviderError("LLM provider request failed")
            self._log_failure(
                model=model,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                error_code=provider_error.code,
            )
            raise provider_error from None

        record = LLMCacheRecord(
            cache_key=cache_key,
            provider=self._provider.provider_name,
            model_name=model,
            prompt_hash=self._prompt_hash(system_prompt),
            response=result.content,
        )
        try:
            self._cache_repo.put(record)
        except RepositoryError:
            cache_error = LLMCacheError("LLM cache write failed")
            self._log_failure(
                model=model,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                error_code=cache_error.code,
            )
            raise cache_error from None

        self._logger.info(
            "llm_request_completed",
            provider=self._provider.provider_name,
            model=model,
            status="ok",
            cache_hit=False,
            latency_ms=self._latency_ms(started_at),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            response_id=result.response_id,
            request_fingerprint=request_fingerprint,
        )
        return deepcopy(result.content)

    def _log_failure(
        self,
        *,
        model: str,
        request_fingerprint: str,
        started_at: float,
        error_code: str,
    ) -> None:
        self._logger.error(
            "llm_request_failed",
            provider=self._provider.provider_name,
            model=model,
            status="error",
            cache_hit=False,
            latency_ms=self._latency_ms(started_at),
            error_code=error_code,
            request_fingerprint=request_fingerprint,
        )

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, round((monotonic() - started_at) * 1000))

    @staticmethod
    def _prompt_hash(system_prompt: str) -> str:
        return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
