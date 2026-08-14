"""Offline integration test for LLMGateway and temporary DuckDB caching."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.settings import OpenAISettings
from src.repositories import DuckDBDatabase, LLMCacheRepository
from src.services import FakeLLMProvider, LLMGateway

pytestmark = pytest.mark.integration


def test_gateway_round_trips_fake_response_through_duckdb(tmp_path: Path) -> None:
    """A real cache Repository prevents a second provider invocation."""

    database = DuckDBDatabase(tmp_path / "llm-gateway.duckdb")
    database.bootstrap()
    cache = LLMCacheRepository(database)
    provider = FakeLLMProvider({"analysis": {"quality_score": 0.8}})
    gateway = LLMGateway(cache, OpenAISettings(), provider=provider)

    first = gateway.invoke_json(
        "configured-model",
        "Return structured research JSON.",
        {"asset_id": "US:AAPL"},
    )
    second = gateway.invoke_json(
        "configured-model",
        "Return structured research JSON.",
        {"asset_id": "US:AAPL"},
    )

    assert first == second == {"analysis": {"quality_score": 0.8}}
    assert len(provider.calls) == 1
    key = LLMGateway.build_cache_key(
        "configured-model",
        "Return structured research JSON.",
        {"asset_id": "US:AAPL"},
        provider="fake",
    )
    stored = cache.get(key)
    assert stored is not None
    assert stored.response == first
