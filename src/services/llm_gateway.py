"""Cached, observable, and dependency-injectable structured LLM runtime."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic, sleep
from typing import Literal, Protocol, cast

import structlog
from pydantic import BaseModel, ValidationError
from structlog.typing import FilteringBoundLogger

from src.core.settings import OpenAISettings
from src.models.types import JsonObject, JsonValue
from src.repositories.base import RepositoryError, TransientRepositoryError
from src.repositories.records import LLMCacheRecord
from src.schemas.llm import LLMRunMetadata as LLMRunMetadata
from src.services.llm_provider import (
    LLMInvalidResponseError,
    LLMProvider,
    LLMProviderError,
    LLMProviderResult,
    OpenAIProvider,
)

_DEFAULT_PROMPT_VERSION = "unversioned"
_DEFAULT_SCHEMA_VERSION = "json_object_v1"

type CacheReadStatus = Literal["hit", "miss", "degraded"]
type CacheReadLogStatus = Literal["hit", "miss", "degraded", "failed"]
type CacheWriteStatus = Literal["not_attempted", "success", "degraded"]


class LLMCacheError(RuntimeError):
    """Raised when the LLM cache cannot be read or updated."""

    code = "cache_error"


class LLMMetadataError(RuntimeError):
    """Raised when an injected metadata audit sink rejects a run."""

    code = "metadata_error"


class LLMSchemaValidationError(LLMInvalidResponseError):
    """Raised when provider JSON does not satisfy the requested schema."""

    code = "schema_validation"

    def __init__(
        self,
        message: str,
        *,
        schema_name: str,
        schema_version: str,
        validation_errors: tuple[tuple[str, str], ...],
        contract_diff: JsonObject,
        retry_count: int = 0,
    ) -> None:
        """Retain only credential-safe schema identity and field error paths."""

        super().__init__(message, retry_count=retry_count)
        self.schema_name = schema_name
        self.schema_version = schema_version
        self.validation_errors = validation_errors
        self.contract_diff = contract_diff


@dataclass(frozen=True, slots=True)
class LLMCacheReliabilityPolicy:
    """Small bounded retry policy for optional LLM cache operations."""

    read_max_retries: int = 2
    write_max_retries: int = 1
    backoff_base_seconds: float = 0.01
    max_backoff_seconds: float = 0.05

    def __post_init__(self) -> None:
        """Reject unbounded or invalid cache retry configuration."""

        if not 0 <= self.read_max_retries <= 2:
            raise ValueError("cache read retries must be between 0 and 2")
        if not 0 <= self.write_max_retries <= 2:
            raise ValueError("cache write retries must be between 0 and 2")
        if self.backoff_base_seconds < 0:
            raise ValueError("cache retry backoff cannot be negative")
        if self.max_backoff_seconds < self.backoff_base_seconds:
            raise ValueError("cache maximum backoff cannot be below its base")

    def delay(self, retry_count: int) -> float:
        """Return deterministic exponential backoff bounded by policy."""

        return float(
            min(
                self.backoff_base_seconds * (2**retry_count),
                self.max_backoff_seconds,
            )
        )


@dataclass(frozen=True, slots=True)
class _CacheReadOutcome:
    record: LLMCacheRecord | None
    status: CacheReadStatus
    retry_count: int
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class _CacheWriteOutcome:
    status: CacheWriteStatus
    retry_count: int
    error_type: str | None = None


class LLMSingleFlight:
    """Coordinate identical in-process requests without global mutable state."""

    def __init__(self) -> None:
        """Initialize an empty per-fingerprint lock registry."""

        self._guard = Lock()
        self._locks: dict[str, tuple[Lock, int]] = {}

    @contextmanager
    def coordinate(self, request_fingerprint: str) -> Iterator[None]:
        """Serialize one fingerprint while allowing unrelated calls to proceed."""

        with self._guard:
            lock, users = self._locks.get(request_fingerprint, (Lock(), 0))
            self._locks[request_fingerprint] = (lock, users + 1)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                current_lock, current_users = self._locks[request_fingerprint]
                if current_users == 1:
                    del self._locks[request_fingerprint]
                else:
                    self._locks[request_fingerprint] = (
                        current_lock,
                        current_users - 1,
                    )


@dataclass(frozen=True, slots=True)
class LLMRunResult:
    """Structured business content paired with non-sensitive run metadata."""

    content: JsonObject
    metadata: LLMRunMetadata


class LLMRunMetadataSink(Protocol):
    """Optional audit boundary for LLM run metadata persistence."""

    def record(self, metadata: LLMRunMetadata) -> None:
        """Persist one credential-free run metadata record."""
        ...


@dataclass(frozen=True, slots=True)
class LLMFailureMetadata:
    """Credential-free failure metadata for runtime acceptance artifacts."""

    provider: str
    model: str
    error_code: str
    error_message_safe: str
    configuration_stage: str | None
    timestamp: datetime


class LLMFailureMetadataSink(Protocol):
    """Optional observer for safe Provider failure diagnostics."""

    def record_failure(self, metadata: LLMFailureMetadata) -> None:
        """Record one immutable, credential-free failure summary."""
        ...


class LLMCache(Protocol):
    """Persistence boundary required by the LLM gateway."""

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        """Return one cached response."""
        ...

    def put(self, record: LLMCacheRecord) -> None:
        """Persist one cached response."""
        ...


class _LegacyLLMProvider(Protocol):
    """Compatibility surface for wrappers that do not request a schema."""

    provider_name: str

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> LLMProviderResult:
        """Return one structured JSON object without native schema hints."""
        ...


class LLMGateway:
    """Model-agnostic runtime for cached, schema-validated LLM inference."""

    def __init__(
        self,
        cache_repo: LLMCache,
        settings: OpenAISettings | None = None,
        *,
        provider: LLMProvider | _LegacyLLMProvider | None = None,
        metadata_sink: LLMRunMetadataSink | None = None,
        failure_sink: LLMFailureMetadataSink | None = None,
        cache_policy: LLMCacheReliabilityPolicy | None = None,
        singleflight: LLMSingleFlight | None = None,
        logger: FilteringBoundLogger | None = None,
        clock: Callable[[], datetime] | None = None,
        timer: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        """Bind cache, provider, audit, logging, and time dependencies.

        Args:
            cache_repo: Provider-independent structured response cache.
            settings: Legacy OpenAI settings used only when provider is absent.
            provider: Injected OpenAI, Qwen, or offline Fake provider.
            metadata_sink: Optional run metadata audit store.
            failure_sink: Optional credential-free Provider failure observer.
            cache_policy: Optional bounded cache retry policy.
            singleflight: Optional identical-request concurrency coordinator.
            logger: Optional credential-safe structured logger.
            clock: Optional deterministic timezone-aware wall clock.
            timer: Optional monotonic latency clock.
            sleeper: Optional cache retry delay function.
        """

        if provider is None and settings is None:
            raise ValueError("settings or provider must be supplied")
        self._cache_repo = cache_repo
        self._provider = (
            provider
            if provider is not None
            else OpenAIProvider(cast(OpenAISettings, settings))
        )
        self._metadata_sink = metadata_sink
        self._failure_sink = failure_sink
        self._cache_policy = cache_policy or LLMCacheReliabilityPolicy()
        self._singleflight = singleflight or LLMSingleFlight()
        self._logger = (
            logger
            if logger is not None
            else cast(FilteringBoundLogger, structlog.get_logger(__name__))
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timer = timer
        self._sleeper = sleeper

    @property
    def supports_structured_repair(self) -> bool:
        """Allow one repair only for a real configured Provider."""

        return self._provider.provider_name != "fake"

    @staticmethod
    def build_cache_key(
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        provider: str = "openai",
        prompt_version: str = _DEFAULT_PROMPT_VERSION,
        schema_version: str = _DEFAULT_SCHEMA_VERSION,
        response_schema: JsonObject | None = None,
    ) -> str:
        """Build a stable key from every response-affecting request input.

        Args:
            model: Requested model identifier/version.
            system_prompt: Complete system instructions.
            input_payload: JSON-compatible user payload.
            provider: Provider adapter identity.
            prompt_version: Version of the system prompt contract.
            schema_version: Version of the requested response contract.
            response_schema: Optional concrete JSON Schema.

        Returns:
            Lowercase SHA-256 hexadecimal digest.

        Raises:
            ValueError: If an identity is empty or input is not strict JSON.
        """

        identities = (model, provider, prompt_version, schema_version)
        if any(not value.strip() for value in identities):
            raise ValueError("LLM request identities cannot be empty")
        try:
            canonical = json.dumps(
                {
                    "input_payload": input_payload,
                    "model": model,
                    "prompt_version": prompt_version,
                    "provider": provider,
                    "response_schema": response_schema,
                    "schema_version": schema_version,
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

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str = _DEFAULT_PROMPT_VERSION,
        schema_version: str = _DEFAULT_SCHEMA_VERSION,
        response_model: type[BaseModel] | None = None,
    ) -> JsonObject:
        """Return provider-independent JSON while retaining the legacy shape."""

        return self.invoke_json_with_metadata(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version=schema_version,
            response_model=response_model,
        ).content

    def invoke_json_with_metadata(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str = _DEFAULT_PROMPT_VERSION,
        schema_version: str = _DEFAULT_SCHEMA_VERSION,
        response_model: type[BaseModel] | None = None,
    ) -> LLMRunResult:
        """Return schema-validated JSON and unified run metadata.

        Provider-native schema differences remain inside adapters. Pydantic
        validation is always performed locally when ``response_model`` is set,
        including for cache hits and the offline Fake provider.
        """

        started_at = self._timer()
        response_schema = self._response_schema(response_model)
        provider = self._provider.provider_name
        cache_key = self.build_cache_key(
            model,
            system_prompt,
            input_payload,
            provider=provider,
            prompt_version=prompt_version,
            schema_version=schema_version,
            response_schema=response_schema,
        )
        request_fingerprint = cache_key
        with self._singleflight.coordinate(request_fingerprint):
            return self._invoke_json_coordinated(
                model=model,
                system_prompt=system_prompt,
                input_payload=input_payload,
                prompt_version=prompt_version,
                schema_version=schema_version,
                response_model=response_model,
                response_schema=response_schema,
                provider=provider,
                cache_key=cache_key,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
            )

    def _invoke_json_coordinated(
        self,
        *,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        prompt_version: str,
        schema_version: str,
        response_model: type[BaseModel] | None,
        response_schema: JsonObject | None,
        provider: str,
        cache_key: str,
        request_fingerprint: str,
        started_at: float,
    ) -> LLMRunResult:
        """Execute one fingerprint while identical local callers wait."""

        try:
            cache_read = self._read_cache(cache_key)
        except RepositoryError as exc:
            error = LLMCacheError("LLM cache read failed")
            self._log_failure(
                model=model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                retry_count=0,
                error_code=error.code,
                cache_read_status="failed",
                cache_read_error_type=exc.database_error_type,
                provider_invoked=False,
            )
            raise error from None

        if cache_read.status == "degraded":
            self._logger.warning(
                "llm_cache_read_degraded",
                provider=provider,
                model=model,
                cache_read_status="degraded",
                cache_retry_count=cache_read.retry_count,
                cache_error_type=cache_read.error_type,
                provider_invoked=True,
                request_fingerprint=request_fingerprint,
            )

        cached = cache_read.record
        if cached is not None:
            try:
                content = self._validate_content(
                    cached.response,
                    response_model,
                    schema_version=schema_version,
                    retry_count=0,
                )
            except LLMSchemaValidationError as exc:
                self._log_failure(
                    model=cached.model_name,
                    prompt_version=prompt_version,
                    schema_version=schema_version,
                    request_fingerprint=request_fingerprint,
                    started_at=started_at,
                    retry_count=0,
                    error_code=exc.code,
                    cache_hit=True,
                    cache_read_status="hit",
                    cache_retry_count=cache_read.retry_count,
                    provider_invoked=False,
                )
                raise
            metadata = self._metadata(
                provider=provider,
                model=cached.model_name,
                prompt_version=prompt_version,
                schema_version=schema_version,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                input_tokens=None,
                output_tokens=None,
                retry_count=0,
                cache_hit=True,
                cache_read_status="hit",
                cache_write_status="not_attempted",
                cache_retry_count=cache_read.retry_count,
                cache_read_error_type=cache_read.error_type,
                cache_write_error_type=None,
            )
            self._record_and_log(metadata)
            return LLMRunResult(content=content, metadata=metadata)

        try:
            result = self._invoke_provider(
                model=model,
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_schema=response_schema,
                response_model=response_model,
            )
            content = self._validate_content(
                result.content,
                response_model,
                schema_version=schema_version,
                retry_count=result.retry_count,
            )
        except LLMProviderError as exc:
            self._record_failure(model=model, error=exc)
            schema_validation = (
                exc if isinstance(exc, LLMSchemaValidationError) else None
            )
            self._log_failure(
                model=model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                retry_count=exc.retry_count,
                error_code=exc.code,
                error_message_safe=str(exc),
                configuration_stage=exc.configuration_stage,
                cache_read_status=cache_read.status,
                cache_retry_count=cache_read.retry_count,
                cache_read_error_type=cache_read.error_type,
                provider_invoked=True,
                validation_errors=(
                    schema_validation.validation_errors
                    if schema_validation is not None
                    else None
                ),
                contract_diff=(
                    schema_validation.contract_diff
                    if schema_validation is not None
                    else None
                ),
            )
            raise
        except Exception:
            provider_error = LLMProviderError("LLM provider request failed")
            self._record_failure(model=model, error=provider_error)
            self._log_failure(
                model=model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                retry_count=0,
                error_code=provider_error.code,
                error_message_safe=str(provider_error),
                configuration_stage=provider_error.configuration_stage,
                cache_read_status=cache_read.status,
                cache_retry_count=cache_read.retry_count,
                cache_read_error_type=cache_read.error_type,
                provider_invoked=True,
            )
            raise provider_error from None

        record = LLMCacheRecord(
            cache_key=cache_key,
            provider=provider,
            model_name=result.model,
            prompt_hash=self._prompt_hash(system_prompt),
            response=content,
        )
        cache_write = self._write_cache(record)
        if cache_write.status == "degraded":
            self._logger.warning(
                "llm_cache_write_degraded",
                provider=provider,
                model=result.model,
                cache_write_status="degraded",
                cache_retry_count=cache_write.retry_count,
                cache_error_type=cache_write.error_type,
                provider_invoked=True,
                request_fingerprint=request_fingerprint,
            )

        metadata = self._metadata(
            provider=provider,
            model=result.model,
            prompt_version=prompt_version,
            schema_version=schema_version,
            request_fingerprint=request_fingerprint,
            started_at=started_at,
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            retry_count=result.retry_count,
            cache_hit=False,
            cache_read_status=cache_read.status,
            cache_write_status=cache_write.status,
            cache_retry_count=cache_read.retry_count + cache_write.retry_count,
            cache_read_error_type=cache_read.error_type,
            cache_write_error_type=cache_write.error_type,
        )
        self._record_and_log(metadata)
        return LLMRunResult(content=content, metadata=metadata)

    def _read_cache(self, cache_key: str) -> _CacheReadOutcome:
        """Read cache with finite retries and degrade only transient failures."""

        retry_count = 0
        while True:
            try:
                record = self._cache_repo.get(cache_key)
                return _CacheReadOutcome(
                    record=record,
                    status="hit" if record is not None else "miss",
                    retry_count=retry_count,
                )
            except TransientRepositoryError as exc:
                if retry_count >= self._cache_policy.read_max_retries:
                    return _CacheReadOutcome(
                        record=None,
                        status="degraded",
                        retry_count=retry_count,
                        error_type=exc.database_error_type,
                    )
                self._sleeper(self._cache_policy.delay(retry_count))
                retry_count += 1

    def _write_cache(self, record: LLMCacheRecord) -> _CacheWriteOutcome:
        """Best-effort cache write without discarding a valid LLM response."""

        retry_count = 0
        while True:
            try:
                self._cache_repo.put(record)
                return _CacheWriteOutcome(
                    status="success",
                    retry_count=retry_count,
                )
            except TransientRepositoryError as exc:
                if retry_count >= self._cache_policy.write_max_retries:
                    return _CacheWriteOutcome(
                        status="degraded",
                        retry_count=retry_count,
                        error_type=exc.database_error_type,
                    )
                self._sleeper(self._cache_policy.delay(retry_count))
                retry_count += 1
            except RepositoryError as exc:
                return _CacheWriteOutcome(
                    status="degraded",
                    retry_count=retry_count,
                    error_type=exc.database_error_type,
                )

    def _invoke_provider(
        self,
        *,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        response_schema: JsonObject | None,
        response_model: type[BaseModel] | None,
    ) -> LLMProviderResult:
        """Invoke old or schema-aware provider surfaces compatibly."""

        if response_schema is None or response_model is None:
            return self._provider.invoke_json(model, system_prompt, input_payload)
        schema_provider = cast(LLMProvider, self._provider)
        return schema_provider.invoke_json(
            model,
            system_prompt,
            input_payload,
            response_schema=response_schema,
            schema_name=self._schema_name(response_model),
        )

    @staticmethod
    def _response_schema(response_model: type[BaseModel] | None) -> JsonObject | None:
        if response_model is None:
            return None
        return cast(JsonObject, response_model.model_json_schema(mode="validation"))

    @staticmethod
    def _schema_name(response_model: type[BaseModel]) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]", "_", response_model.__name__)
        return normalized[:64] or "deepinsight_response"

    @staticmethod
    def _validate_content(
        content: JsonObject,
        response_model: type[BaseModel] | None,
        *,
        schema_version: str,
        retry_count: int,
    ) -> JsonObject:
        if response_model is None:
            return deepcopy(content)
        try:
            validated = response_model.model_validate(content)
        except ValidationError as exc:
            raw_errors = exc.errors(include_input=True, include_url=False)
            errors = tuple(
                (
                    ".".join(str(part) for part in item["loc"]) or "model",
                    str(item["type"]),
                )
                for item in raw_errors[:20]
            )
            missing = [path for path, error_type in errors if error_type == "missing"]
            extra = [
                path for path, error_type in errors if error_type == "extra_forbidden"
            ]
            type_mismatch: list[JsonObject] = []
            for item, (path, error_type) in zip(raw_errors, errors, strict=True):
                if error_type in {"missing", "extra_forbidden"}:
                    continue
                mismatch: JsonObject = {
                    "path": path,
                    "error_type": error_type,
                }
                observed = item.get("input")
                if (
                    error_type == "enum"
                    and isinstance(observed, str)
                    and re.fullmatch(r"[A-Za-z_]{1,64}", observed) is not None
                ):
                    mismatch["observed_identifier"] = observed
                type_mismatch.append(mismatch)
            analysis = content.get("analysis")
            actual: JsonObject = {
                "top_level_fields": cast(JsonValue, sorted(content)),
                "analysis_fields": cast(
                    JsonValue,
                    sorted(analysis) if isinstance(analysis, dict) else [],
                ),
            }
            agent_name = content.get("agent_name")
            if isinstance(agent_name, str):
                actual["agent_name"] = agent_name
            raise LLMSchemaValidationError(
                "LLM response failed schema validation",
                schema_name=LLMGateway._schema_name(response_model),
                schema_version=schema_version,
                validation_errors=errors,
                contract_diff={
                    "expected": {
                        "schema_name": LLMGateway._schema_name(response_model),
                        "top_level_fields": cast(
                            JsonValue, sorted(response_model.model_fields)
                        ),
                    },
                    "actual": actual,
                    "missing": cast(JsonValue, missing),
                    "extra": cast(JsonValue, extra),
                    "type_mismatch": cast(JsonValue, type_mismatch),
                },
                retry_count=retry_count,
            ) from None
        return cast(JsonObject, validated.model_dump(mode="json"))

    def _metadata(
        self,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        schema_version: str,
        request_fingerprint: str,
        started_at: float,
        input_tokens: int | None,
        output_tokens: int | None,
        retry_count: int,
        cache_hit: bool,
        cache_read_status: CacheReadStatus,
        cache_write_status: CacheWriteStatus,
        cache_retry_count: int,
        cache_read_error_type: str | None,
        cache_write_error_type: str | None,
    ) -> LLMRunMetadata:
        return LLMRunMetadata(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            request_fingerprint=request_fingerprint,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=self._latency_ms(started_at),
            cache_hit=cache_hit,
            retry_count=retry_count,
            timestamp=self._clock(),
            schema_version=schema_version,
            remote_storage_enabled=self._remote_storage_enabled(),
            cache_read_status=cache_read_status,
            cache_write_status=cache_write_status,
            cache_retry_count=cache_retry_count,
            cache_read_error_type=cache_read_error_type,
            cache_write_error_type=cache_write_error_type,
        )

    def _record_and_log(self, metadata: LLMRunMetadata) -> None:
        if self._metadata_sink is not None:
            try:
                self._metadata_sink.record(metadata.model_copy(deep=True))
            except Exception:
                raise LLMMetadataError("LLM run metadata audit failed") from None
        self._logger.info(
            "llm_request_completed",
            provider=metadata.provider,
            model=metadata.model,
            prompt_version=metadata.prompt_version,
            schema_version=metadata.schema_version,
            status="ok",
            cache_hit=metadata.cache_hit,
            latency_ms=metadata.latency_ms,
            input_tokens=metadata.input_tokens,
            output_tokens=metadata.output_tokens,
            prompt_tokens=metadata.input_tokens,
            completion_tokens=metadata.output_tokens,
            retry_count=metadata.retry_count,
            timestamp=metadata.timestamp.isoformat(),
            remote_storage_enabled=metadata.remote_storage_enabled,
            cache_read_status=metadata.cache_read_status,
            cache_write_status=metadata.cache_write_status,
            cache_retry_count=metadata.cache_retry_count,
            cache_read_error_type=metadata.cache_read_error_type,
            cache_write_error_type=metadata.cache_write_error_type,
            provider_invoked=not metadata.cache_hit,
            request_fingerprint=metadata.request_fingerprint,
        )

    def _log_failure(
        self,
        *,
        model: str,
        prompt_version: str,
        schema_version: str,
        request_fingerprint: str,
        started_at: float,
        retry_count: int,
        error_code: str,
        error_message_safe: str | None = None,
        configuration_stage: str | None = None,
        cache_hit: bool = False,
        cache_read_status: CacheReadLogStatus = "miss",
        cache_retry_count: int = 0,
        cache_read_error_type: str | None = None,
        provider_invoked: bool = False,
        validation_errors: tuple[tuple[str, str], ...] | None = None,
        contract_diff: JsonObject | None = None,
    ) -> None:
        self._logger.error(
            "llm_request_failed",
            provider=self._provider.provider_name,
            model=model,
            prompt_version=prompt_version,
            schema_version=schema_version,
            status="error",
            cache_hit=cache_hit,
            latency_ms=self._latency_ms(started_at),
            retry_count=retry_count,
            error_code=error_code,
            error_message_safe=error_message_safe,
            configuration_stage=configuration_stage,
            remote_storage_enabled=self._remote_storage_enabled(),
            cache_read_status=cache_read_status,
            cache_retry_count=cache_retry_count,
            cache_read_error_type=cache_read_error_type,
            provider_invoked=provider_invoked,
            request_fingerprint=request_fingerprint,
            validation_errors=validation_errors,
            contract_diff=contract_diff,
        )

    def _record_failure(self, *, model: str, error: LLMProviderError) -> None:
        """Emit one safe Provider failure without masking the original error."""

        if self._failure_sink is None:
            return
        metadata = LLMFailureMetadata(
            provider=self._provider.provider_name,
            model=model,
            error_code=error.code,
            error_message_safe=str(error),
            configuration_stage=error.configuration_stage,
            timestamp=self._clock(),
        )
        try:
            self._failure_sink.record_failure(metadata)
        except Exception:
            self._logger.error(
                "llm_failure_metadata_sink_failed",
                provider=metadata.provider,
                model=metadata.model,
                error_code=metadata.error_code,
            )

    def _remote_storage_enabled(self) -> bool:
        capabilities = getattr(self._provider, "capabilities", None)
        value = getattr(capabilities, "remote_storage_enabled", False)
        return value if isinstance(value, bool) else False

    def _latency_ms(self, started_at: float) -> int:
        return max(0, round((self._timer() - started_at) * 1000))

    @staticmethod
    def _prompt_hash(system_prompt: str) -> str:
        return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
