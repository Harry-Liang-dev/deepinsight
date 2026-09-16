"""Unit tests for cached LLM gateway behavior and safe metadata logging."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from structlog.testing import CapturingLogger

from src.core.settings import OpenAISettings
from src.models.types import JsonObject
from src.repositories.base import RepositoryError, TransientRepositoryError
from src.repositories.records import LLMCacheRecord
from src.services.llm_gateway import (
    LLMCacheError,
    LLMCacheReliabilityPolicy,
    LLMFailureMetadata,
    LLMGateway,
    LLMRunMetadata,
    LLMSchemaValidationError,
)
from src.services.llm_provider import (
    FakeLLMProvider,
    LLMConfigurationError,
    LLMProviderError,
    LLMProviderResult,
    LLMTimeoutError,
)


class InMemoryCache:
    """Small Repository-compatible cache used by gateway unit tests."""

    def __init__(self) -> None:
        self.records: dict[str, LLMCacheRecord] = {}
        self.get_calls = 0
        self.put_calls = 0
        self.read_error = False
        self.write_error = False
        self.transient_read_failures = 0
        self.transient_write_failures = 0

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        self.get_calls += 1
        if self.transient_read_failures:
            self.transient_read_failures -= 1
            raise TransientRepositoryError(
                "safe transient read",
                database_error_type="ConnectionException",
            )
        if self.read_error:
            raise RepositoryError(
                "unsafe database detail",
                database_error_type="CatalogException",
            )
        return self.records.get(cache_key)

    def put(self, record: LLMCacheRecord) -> None:
        self.put_calls += 1
        if self.transient_write_failures:
            self.transient_write_failures -= 1
            raise TransientRepositoryError(
                "safe transient write",
                database_error_type="SerializationException",
            )
        if self.write_error:
            raise RepositoryError(
                "unsafe database detail",
                database_error_type="ConstraintException",
            )
        self.records[record.cache_key] = record.model_copy(deep=True)


class StructuredResponse(BaseModel):
    """Strict response contract used by Gateway schema tests."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    score: float = Field(ge=0.0, le=1.0)


class MetadataSink:
    """Capture unified run metadata without persistence."""

    def __init__(self) -> None:
        self.records: list[LLMRunMetadata] = []

    def record(self, metadata: LLMRunMetadata) -> None:
        self.records.append(metadata)


class FailureSink:
    """Capture safe failure metadata without external persistence."""

    def __init__(self) -> None:
        self.records: list[LLMFailureMetadata] = []

    def record_failure(self, metadata: LLMFailureMetadata) -> None:
        self.records.append(metadata)


def _capturing_logger() -> tuple[Any, CapturingLogger]:
    logger = CapturingLogger()
    bound_logger = structlog.BoundLogger(logger, [], {})
    return cast(Any, bound_logger), logger


def test_cache_key_is_stable_for_equivalent_payload_order() -> None:
    """Canonical JSON ordering should produce a reproducible cache key."""

    first = LLMGateway.build_cache_key(
        "model",
        "system",
        {"asset_id": "US:AAPL", "features": {"b": 2, "a": 1}},
    )
    second = LLMGateway.build_cache_key(
        "model",
        "system",
        {"features": {"a": 1, "b": 2}, "asset_id": "US:AAPL"},
    )

    assert first == second


@pytest.mark.parametrize(
    ("model", "system_prompt", "payload"),
    [
        ("other-model", "system", {"value": 1}),
        ("model", "other-system", {"value": 1}),
        ("model", "system", {"value": 2}),
    ],
)
def test_cache_key_changes_with_every_inference_input(
    model: str,
    system_prompt: str,
    payload: JsonObject,
) -> None:
    """Model, prompt, and user payload must all affect the cache key."""

    baseline = LLMGateway.build_cache_key("model", "system", {"value": 1})

    assert LLMGateway.build_cache_key(model, system_prompt, payload) != baseline


@pytest.mark.parametrize(
    "identity",
    [
        {"provider": "qwen"},
        {"prompt_version": "prompt-v2"},
        {"schema_version": "schema-v2"},
        {
            "response_schema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            }
        },
    ],
)
def test_cache_key_isolated_by_runtime_identity(identity: dict[str, object]) -> None:
    """Provider, Prompt, and schema identities must prevent cache collisions."""

    baseline = LLMGateway.build_cache_key("model", "system", {"value": 1})
    changed = LLMGateway.build_cache_key(
        "model",
        "system",
        {"value": 1},
        **cast(Any, identity),
    )

    assert changed != baseline


def test_cache_miss_calls_provider_and_persists_content() -> None:
    """A miss invokes the provider once and writes a provider-neutral record."""

    cache = InMemoryCache()
    provider = FakeLLMProvider(
        {"analysis": "complete"},
        prompt_tokens=12,
        completion_tokens=7,
    )
    bound_logger, logger = _capturing_logger()
    gateway = LLMGateway(
        cache,
        OpenAISettings(),
        provider=provider,
        logger=bound_logger,
    )

    result = gateway.invoke_json("configured-model", "system", {"value": 1})

    assert result == {"analysis": "complete"}
    assert len(provider.calls) == 1
    assert cache.put_calls == 1
    record = next(iter(cache.records.values()))
    assert record.provider == "fake"
    assert record.model_name == "configured-model"
    assert record.response == result
    log = logger.calls[-1].kwargs
    assert log["cache_hit"] is False
    assert log["prompt_tokens"] == 12
    assert log["completion_tokens"] == 7


def test_gateway_returns_complete_run_metadata_and_audits_copy() -> None:
    """Fresh runs expose model version, tokens, latency, retries, and versions."""

    sink = MetadataSink()
    ticks = iter([10.0, 10.125])
    provider = FakeLLMProvider(
        {"summary": "complete", "score": 0.8},
        model="fake-model-2026-08-01",
        prompt_tokens=12,
        completion_tokens=7,
        retry_count=1,
        remote_storage_enabled=True,
    )
    gateway = LLMGateway(
        InMemoryCache(),
        provider=provider,
        metadata_sink=sink,
        clock=lambda: datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        timer=lambda: next(ticks),
    )

    result = gateway.invoke_json_with_metadata(
        "fake-model-alias",
        "system",
        {"value": 1},
        prompt_version="prompt-v3",
        schema_version="structured-response-v2",
        response_model=StructuredResponse,
    )

    assert result.content == {"summary": "complete", "score": 0.8}
    assert result.metadata.model_dump(mode="json") == {
        "provider": "fake",
        "model": "fake-model-2026-08-01",
        "prompt_version": "prompt-v3",
        "request_fingerprint": result.metadata.request_fingerprint,
        "input_tokens": 12,
        "output_tokens": 7,
        "latency_ms": 125,
        "cache_hit": False,
        "retry_count": 1,
        "timestamp": "2026-08-09T10:00:00Z",
        "schema_version": "structured-response-v2",
        "remote_storage_enabled": True,
        "cache_read_status": "miss",
        "cache_write_status": "success",
        "cache_retry_count": 0,
        "cache_read_error_type": None,
        "cache_write_error_type": None,
        "structured_output_attempts": 1,
        "repair_attempted": False,
    }
    assert len(result.metadata.request_fingerprint) == 64
    assert sink.records == [result.metadata]
    assert sink.records[0] is not result.metadata
    assert provider.calls[0].response_schema is not None


def test_gateway_rejects_invalid_schema_output_without_caching() -> None:
    """Provider JSON that fails the requested contract must never enter cache."""

    cache = InMemoryCache()
    gateway = LLMGateway(
        cache,
        provider=FakeLLMProvider({"summary": "missing score"}),
    )

    with pytest.raises(LLMSchemaValidationError, match="schema validation") as captured:
        gateway.invoke_json(
            "model",
            "system",
            {"value": 1},
            response_model=StructuredResponse,
            schema_version="structured-response-v1",
        )

    assert cache.put_calls == 0
    assert cache.records == {}
    error = captured.value
    assert error.schema_name == "StructuredResponse"
    assert error.schema_version == "structured-response-v1"
    assert ("score", "missing") in error.validation_errors
    assert error.contract_diff["missing"] == ["score"]
    assert error.contract_diff["actual"] == {
        "top_level_fields": ["summary"],
        "analysis_fields": [],
    }


def test_cache_hit_skips_provider_and_returns_defensive_copy() -> None:
    """A matching cache entry bypasses all remote provider work."""

    cache = InMemoryCache()
    provider = FakeLLMProvider({"must": "not run"})
    key = LLMGateway.build_cache_key("model", "system", {"value": 1}, provider="fake")
    cache.records[key] = LLMCacheRecord(
        cache_key=key,
        provider="fake",
        model_name="model",
        prompt_hash="prompt-hash",
        response={"cached": {"value": 1}},
    )
    gateway = LLMGateway(cache, OpenAISettings(), provider=provider)

    first = gateway.invoke_json("model", "system", {"value": 1})
    first["cached"] = {"value": 2}
    second = gateway.invoke_json("model", "system", {"value": 1})

    assert second == {"cached": {"value": 1}}
    assert provider.calls == []
    assert cache.put_calls == 0


def test_gateway_logs_only_safe_request_metadata() -> None:
    """Logs must exclude API keys, prompts, and user payload content."""

    secret = "api-key-must-not-leak"
    system_prompt = "sensitive-system-prompt"
    payload_content = "sensitive-user-content"
    provider = FakeLLMProvider(
        {},
        error=LLMTimeoutError("OpenAI request timed out"),
    )
    bound_logger, logger = _capturing_logger()
    gateway = LLMGateway(
        InMemoryCache(),
        OpenAISettings(api_key=SecretStr(secret)),
        provider=provider,
        logger=bound_logger,
    )

    with pytest.raises(LLMTimeoutError):
        gateway.invoke_json(
            "configured-model",
            system_prompt,
            {"content": payload_content},
        )

    serialized_logs = repr(logger.calls)
    assert secret not in serialized_logs
    assert system_prompt not in serialized_logs
    assert payload_content not in serialized_logs
    log = logger.calls[-1].kwargs
    assert log["error_code"] == "timeout"
    assert log["status"] == "error"


def test_gateway_persists_safe_configuration_failure_metadata() -> None:
    """Configuration stage and safe message survive without secret content."""

    secret = "gateway-secret-must-not-leak"
    failure_sink = FailureSink()
    bound_logger, logger = _capturing_logger()
    error = LLMConfigurationError(
        f"Qwen client initialization failed; API key: {secret}",
        configuration_stage="client_initialization",
        api_key=secret,
    )
    gateway = LLMGateway(
        InMemoryCache(),
        provider=FakeLLMProvider({}, error=error),
        failure_sink=failure_sink,
        logger=bound_logger,
    )

    with pytest.raises(LLMConfigurationError):
        gateway.invoke_json("qwen-offline", "sensitive prompt", {"secret": secret})

    assert len(failure_sink.records) == 1
    metadata = failure_sink.records[0]
    assert metadata.provider == "fake"
    assert metadata.model == "qwen-offline"
    assert metadata.error_code == "configuration_error"
    assert metadata.configuration_stage == "client_initialization"
    assert secret not in metadata.error_message_safe
    serialized_logs = repr(logger.calls)
    assert secret not in serialized_logs
    assert "sensitive prompt" not in serialized_logs
    assert logger.calls[-1].kwargs["configuration_stage"] == "client_initialization"


def test_permanent_cache_read_error_fails_before_provider() -> None:
    """Schema/catalog-style read errors remain explicit hard failures."""

    cache = InMemoryCache()
    cache.read_error = True
    provider = FakeLLMProvider({"result": "must not run"})
    gateway = LLMGateway(
        cache,
        OpenAISettings(),
        provider=provider,
    )

    with pytest.raises(LLMCacheError, match="cache read failed"):
        gateway.invoke_json("model", "system", {"value": 1})

    assert cache.get_calls == 1
    assert provider.calls == []


def test_transient_cache_read_retries_then_returns_hit() -> None:
    """A transient first read can recover without invoking the provider."""

    cache = InMemoryCache()
    cache.transient_read_failures = 1
    key = LLMGateway.build_cache_key("model", "system", {"value": 1}, provider="fake")
    cache.records[key] = LLMCacheRecord(
        cache_key=key,
        provider="fake",
        model_name="model",
        prompt_hash="hash",
        response={"cached": True},
    )
    provider = FakeLLMProvider({"must": "not run"})
    delays: list[float] = []
    result = LLMGateway(
        cache,
        provider=provider,
        sleeper=delays.append,
    ).invoke_json_with_metadata("model", "system", {"value": 1})

    assert result.content == {"cached": True}
    assert result.metadata.cache_read_status == "hit"
    assert result.metadata.cache_retry_count == 1
    assert cache.get_calls == 2
    assert provider.calls == []
    assert delays == [0.01]


def test_exhausted_transient_cache_read_degrades_to_one_provider_call() -> None:
    """Read retry exhaustion becomes an observable miss, not Agent failure."""

    cache = InMemoryCache()
    cache.transient_read_failures = 3
    provider = FakeLLMProvider({"result": "ok"})
    bound_logger, logger = _capturing_logger()
    result = LLMGateway(
        cache,
        provider=provider,
        logger=bound_logger,
        sleeper=lambda _: None,
    ).invoke_json_with_metadata(
        "model",
        "sensitive-system-prompt",
        {"content": "sensitive-user-content"},
    )

    assert result.content == {"result": "ok"}
    assert result.metadata.cache_read_status == "degraded"
    assert result.metadata.cache_read_error_type == "ConnectionException"
    assert result.metadata.cache_retry_count == 2
    assert cache.get_calls == 3
    assert len(provider.calls) == 1
    serialized_logs = repr(logger.calls)
    assert "sensitive-system-prompt" not in serialized_logs
    assert "sensitive-user-content" not in serialized_logs
    degraded_log = next(
        call.kwargs
        for call in logger.calls
        if call.kwargs.get("event") == "llm_cache_read_degraded"
    )
    assert degraded_log["provider_invoked"] is True
    assert degraded_log["cache_read_status"] == "degraded"


def test_provider_failure_after_degraded_read_is_not_reinvoked() -> None:
    """Cache retries do not duplicate or bypass one mapped Provider failure."""

    cache = InMemoryCache()
    cache.transient_read_failures = 3
    provider = FakeLLMProvider({}, error=LLMTimeoutError("provider timeout"))
    bound_logger, logger = _capturing_logger()
    gateway = LLMGateway(
        cache,
        provider=provider,
        logger=bound_logger,
        sleeper=lambda _: None,
    )

    with pytest.raises(LLMTimeoutError):
        gateway.invoke_json("model", "system", {"value": 1})

    assert len(provider.calls) == 1
    failure = logger.calls[-1].kwargs
    assert failure["cache_read_status"] == "degraded"
    assert failure["provider_invoked"] is True


def test_transient_cache_write_retries_then_succeeds() -> None:
    """A transient write retry persists without changing business output."""

    cache = InMemoryCache()
    cache.transient_write_failures = 1
    provider = FakeLLMProvider({"result": "ok"})
    result = LLMGateway(
        cache,
        provider=provider,
        sleeper=lambda _: None,
    ).invoke_json_with_metadata("model", "system", {"value": 1})

    assert result.content == {"result": "ok"}
    assert result.metadata.cache_write_status == "success"
    assert result.metadata.cache_retry_count == 1
    assert cache.put_calls == 2
    assert len(provider.calls) == 1


@pytest.mark.parametrize("transient", [False, True])
def test_cache_write_failure_is_observable_but_returns_response(
    transient: bool,
) -> None:
    """Permanent and exhausted transient cache writes remain best effort."""

    cache = InMemoryCache()
    if transient:
        cache.transient_write_failures = 2
    else:
        cache.write_error = True
    provider = FakeLLMProvider({"result": "ok"})
    bound_logger, logger = _capturing_logger()
    result = LLMGateway(
        cache,
        provider=provider,
        logger=bound_logger,
        sleeper=lambda _: None,
    ).invoke_json_with_metadata("model", "system", {"value": 1})

    assert result.content == {"result": "ok"}
    assert result.metadata.cache_write_status == "degraded"
    assert result.metadata.cache_write_error_type == (
        "SerializationException" if transient else "ConstraintException"
    )
    assert len(provider.calls) == 1
    warning = next(
        call.kwargs
        for call in logger.calls
        if call.kwargs.get("event") == "llm_cache_write_degraded"
    )
    assert warning["provider_invoked"] is True


def test_cache_retries_do_not_change_request_fingerprint() -> None:
    """The fingerprint remains the canonical key across degraded cache access."""

    cache = InMemoryCache()
    cache.transient_read_failures = 3
    expected = LLMGateway.build_cache_key(
        "model", "system", {"value": 1}, provider="fake"
    )
    result = LLMGateway(
        cache,
        provider=FakeLLMProvider({"result": "ok"}),
        cache_policy=LLMCacheReliabilityPolicy(read_max_retries=2),
        sleeper=lambda _: None,
    ).invoke_json_with_metadata("model", "system", {"value": 1})

    assert result.metadata.request_fingerprint == expected


def test_gateway_maps_unexpected_provider_failure() -> None:
    """Provider implementation exceptions become a stable generic error."""

    class BrokenProvider:
        provider_name = "broken"
        capabilities = FakeLLMProvider({}).capabilities

        def invoke_json(
            self,
            model: str,
            system_prompt: str,
            input_payload: JsonObject,
            *,
            response_schema: JsonObject | None = None,
            schema_name: str = "deepinsight_response",
        ) -> LLMProviderResult:
            del model, system_prompt, input_payload, response_schema, schema_name
            raise RuntimeError("unsafe provider detail")

    gateway = LLMGateway(
        InMemoryCache(),
        OpenAISettings(),
        provider=BrokenProvider(),
    )

    with pytest.raises(LLMProviderError, match="provider request failed") as raised:
        gateway.invoke_json("model", "system", {"value": 1})

    assert "unsafe provider detail" not in str(raised.value)
