"""Offline DuckDB concurrency regression tests for the LLM cache runtime."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep

import pytest

from src.models.types import JsonObject
from src.repositories import DuckDBDatabase, LLMCacheRecord, LLMCacheRepository
from src.services import FakeLLMProvider, LLMCacheError, LLMGateway
from src.services.llm_provider import LLMProviderResult

pytestmark = pytest.mark.integration

_AGENT_COUNT = 8


class SlowFakeProvider(FakeLLMProvider):
    """Keep one Fake call open long enough to expose cache stampedes."""

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
    ) -> LLMProviderResult:
        """Delay without networking, then use deterministic Fake behavior."""

        sleep(0.05)
        return super().invoke_json(
            model,
            system_prompt,
            input_payload,
            response_schema=response_schema,
            schema_name=schema_name,
        )


def test_eight_concurrent_agent_requests_share_scoped_duckdb_cache(
    tmp_path: Path,
) -> None:
    """Eight Gateway requests remain stable across real scoped connections."""

    database = DuckDBDatabase(tmp_path / "concurrent-agents.duckdb")
    database.bootstrap()
    cache = LLMCacheRepository(database)
    provider = FakeLLMProvider({"analysis": "ok"})
    gateway = LLMGateway(cache, provider=provider)

    def invoke(agent_index: int) -> JsonObject:
        return gateway.invoke_json(
            "fake-model",
            "Return JSON.",
            {"agent_index": agent_index},
            prompt_version="cache-concurrency-v1",
        )

    with ThreadPoolExecutor(max_workers=_AGENT_COUNT) as executor:
        first = list(executor.map(invoke, range(_AGENT_COUNT)))
        second = list(executor.map(invoke, range(_AGENT_COUNT)))

    assert first == second == [{"analysis": "ok"}] * _AGENT_COUNT
    assert len(provider.calls) == _AGENT_COUNT
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM llm_cache").fetchone() == (
            _AGENT_COUNT,
        )


def test_concurrent_cache_reads_and_writes_are_operation_isolated(
    tmp_path: Path,
) -> None:
    """Parallel Repository operations use independent serialized connections."""

    database = DuckDBDatabase(tmp_path / "concurrent-cache.duckdb")
    database.bootstrap()
    cache = LLMCacheRepository(database)
    records = [
        LLMCacheRecord(
            cache_key=f"cache-key-{index}",
            provider="fake",
            model_name="fake-model",
            prompt_hash=f"prompt-hash-{index}",
            response={"index": index},
        )
        for index in range(_AGENT_COUNT)
    ]

    with ThreadPoolExecutor(max_workers=_AGENT_COUNT) as executor:
        list(executor.map(cache.put, records))

    def read_and_replace(index: int) -> JsonObject:
        record = cache.get(f"cache-key-{index}")
        assert record is not None
        cache.put(record)
        reread = cache.get(record.cache_key)
        assert reread is not None
        return reread.response

    with ThreadPoolExecutor(max_workers=_AGENT_COUNT) as executor:
        results = list(executor.map(read_and_replace, range(_AGENT_COUNT)))

    assert results == [{"index": index} for index in range(_AGENT_COUNT)]


def test_identical_concurrent_requests_invoke_provider_once(tmp_path: Path) -> None:
    """Per-fingerprint single-flight prevents an eight-request cache stampede."""

    database = DuckDBDatabase(tmp_path / "single-flight.duckdb")
    database.bootstrap()
    provider = SlowFakeProvider({"analysis": "coalesced"})
    gateway = LLMGateway(LLMCacheRepository(database), provider=provider)

    def invoke(_: int) -> JsonObject:
        return gateway.invoke_json(
            "fake-model",
            "Return JSON.",
            {"same_request": True},
            prompt_version="cache-single-flight-v1",
        )

    with ThreadPoolExecutor(max_workers=_AGENT_COUNT) as executor:
        results = list(executor.map(invoke, range(_AGENT_COUNT)))

    assert results == [{"analysis": "coalesced"}] * _AGENT_COUNT
    assert len(provider.calls) == 1


def test_corrupt_cache_payload_fails_without_provider_fallback(tmp_path: Path) -> None:
    """Stored serialization corruption remains a hard, observable read error."""

    database = DuckDBDatabase(tmp_path / "corrupt-cache.duckdb")
    database.bootstrap()
    key = LLMGateway.build_cache_key(
        "fake-model",
        "Return JSON.",
        {"same_request": True},
        provider="fake",
    )
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO llm_cache (
                cache_key, provider, model_name, prompt_hash, response_json
            ) VALUES (?, 'fake', 'fake-model', 'prompt-hash', 'not-json')
            """,
            (key,),
        )
    provider = FakeLLMProvider({"must": "not run"})
    gateway = LLMGateway(LLMCacheRepository(database), provider=provider)

    with pytest.raises(LLMCacheError, match="cache read failed"):
        gateway.invoke_json(
            "fake-model",
            "Return JSON.",
            {"same_request": True},
        )

    assert provider.calls == []
