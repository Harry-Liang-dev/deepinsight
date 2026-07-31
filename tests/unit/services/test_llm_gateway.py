"""Unit tests for cached LLM gateway behavior and safe metadata logging."""

from __future__ import annotations

from typing import Any, cast

import pytest
import structlog
from pydantic import SecretStr
from structlog.testing import CapturingLogger

from src.core.settings import OpenAISettings
from src.models.types import JsonObject
from src.repositories.base import RepositoryError
from src.repositories.records import LLMCacheRecord
from src.services.llm_gateway import LLMCacheError, LLMGateway
from src.services.llm_provider import (
    FakeLLMProvider,
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

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        self.get_calls += 1
        if self.read_error:
            raise RepositoryError("unsafe database detail")
        return self.records.get(cache_key)

    def put(self, record: LLMCacheRecord) -> None:
        self.put_calls += 1
        if self.write_error:
            raise RepositoryError("unsafe database detail")
        self.records[record.cache_key] = record.model_copy(deep=True)


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


def test_cache_hit_skips_provider_and_returns_defensive_copy() -> None:
    """A matching cache entry bypasses all remote provider work."""

    cache = InMemoryCache()
    provider = FakeLLMProvider({"must": "not run"})
    key = LLMGateway.build_cache_key("model", "system", {"value": 1})
    cache.records[key] = LLMCacheRecord(
        cache_key=key,
        provider="openai",
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


@pytest.mark.parametrize("operation", ["read", "write"])
def test_gateway_maps_cache_failures(operation: str) -> None:
    """Repository implementation details are hidden behind a cache error."""

    cache = InMemoryCache()
    cache.read_error = operation == "read"
    cache.write_error = operation == "write"
    gateway = LLMGateway(
        cache,
        OpenAISettings(),
        provider=FakeLLMProvider({"result": "ok"}),
    )

    with pytest.raises(LLMCacheError, match=f"cache {operation} failed"):
        gateway.invoke_json("model", "system", {"value": 1})


def test_gateway_maps_unexpected_provider_failure() -> None:
    """Provider implementation exceptions become a stable generic error."""

    class BrokenProvider:
        provider_name = "broken"

        def invoke_json(
            self,
            model: str,
            system_prompt: str,
            input_payload: JsonObject,
        ) -> LLMProviderResult:
            raise RuntimeError("unsafe provider detail")

    gateway = LLMGateway(
        InMemoryCache(),
        OpenAISettings(),
        provider=BrokenProvider(),
    )

    with pytest.raises(LLMProviderError, match="provider request failed") as raised:
        gateway.invoke_json("model", "system", {"value": 1})

    assert "unsafe provider detail" not in str(raised.value)
