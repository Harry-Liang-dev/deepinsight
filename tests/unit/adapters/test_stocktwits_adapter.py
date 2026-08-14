"""Offline tests for Stocktwits MCP transport injection and canonical mapping."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.adapters import (
    FakeMCPTransport,
    LocalFileMCPTokenStorage,
    MCPAuthorizationRequiredError,
    MCPInitializationError,
    MCPToolError,
    ProviderRecord,
    ProviderUnavailableError,
    StocktwitsSentimentProvider,
    StreamableHTTPMCPTransport,
)


def _results() -> dict[str, dict[str, object]]:
    return {
        "get_sentiment": {
            "symbol": "AAPL",
            "score": 70,
            "label": "BULLISH",
            "bullish_pct": 75,
            "bearish_pct": 25,
            "updated_at": "2026-08-10T20:00:00Z",
        },
        "get_sentiment_history": {
            "symbol": "AAPL",
            "series": [
                {
                    "time": "2026-08-09T20:00:00Z",
                    "value": 65,
                    "label": "BULLISH",
                }
            ],
        },
        "get_message_volume": {
            "symbol": "AAPL",
            "series": [
                {
                    "timeframe": "now",
                    "normalized_value": 46,
                    "normalized_label": "NORMAL",
                }
            ],
        },
        "get_message_volume_history": {
            "symbol": "AAPL",
            "series": [
                {
                    "time": "2026-08-09T20:00:00Z",
                    "value": 40,
                    "label": "NORMAL",
                }
            ],
        },
        "get_symbol_messages": {
            "messages": [
                {
                    "id": 123,
                    "created_at": "2026-08-10T19:00:00Z",
                    "body": "Community opinion, not a verified filing fact.",
                    "sentiment": "Bullish",
                }
            ],
            "more": False,
        },
    }


def _provider(
    transport: FakeMCPTransport | None = None,
) -> tuple[StocktwitsSentimentProvider, FakeMCPTransport]:
    fake = transport or FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=_results(),
    )
    return (
        StocktwitsSentimentProvider(
            transport=fake,
            clock=lambda: datetime(2026, 8, 10, 21, tzinfo=UTC),
        ),
        fake,
    )


def _fetch(provider: StocktwitsSentimentProvider) -> list[ProviderRecord]:
    return list(
        provider.fetch_sentiment_range(
            ("US:AAPL",),
            date(2026, 8, 9),
            date(2026, 8, 10),
        )
    )


def test_provider_calls_exact_advertised_tools_and_maps_canonical_records() -> None:
    provider, transport = _provider()

    records = _fetch(provider)

    assert [record["record_type"] for record in records] == [
        "sentiment_snapshot",
        "sentiment_snapshot",
        "sentiment_evidence",
    ]
    assert [name for name, _ in transport.calls] == list(
        StocktwitsSentimentProvider.required_tools
    )
    assert transport.calls[1][1] == {"symbol": "AAPL", "zoom": "1M"}
    assert transport.calls[4][1] == {"symbol": "AAPL", "limit": 50}
    assert transport.closed
    current = records[1]
    assert current["asset_id"] == "US:AAPL"
    assert current["message_volume_score"] == 46
    assert current["source_locator"] == "stocktwits:symbol:AAPL:current"
    message = records[2]
    assert message["message_id"] == "123"
    assert message["source_locator"] == "https://stocktwits.com/message/123"
    assert "user" not in message


def test_provider_depends_only_on_transport_protocol() -> None:
    provider, transport = _provider()

    _fetch(provider)

    assert provider.available_tools == StocktwitsSentimentProvider.required_tools


def test_missing_required_tool_fails_before_any_tool_call() -> None:
    transport = FakeMCPTransport(
        tools=("get_sentiment",),
        results=_results(),
    )
    provider, _ = _provider(transport)

    with pytest.raises(ProviderUnavailableError, match="missing required tools"):
        _fetch(provider)

    assert not transport.calls
    assert transport.closed


@pytest.mark.parametrize(
    "error",
    [
        MCPAuthorizationRequiredError("authorization required"),
        MCPAuthorizationRequiredError("expired token"),
        MCPInitializationError("network failure"),
        MCPInitializationError("initialization failure"),
    ],
)
def test_authorization_network_and_initialization_failures_are_explicit(
    error: MCPInitializationError | MCPAuthorizationRequiredError,
) -> None:
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=_results(),
        initialize_error=error,
    )
    provider, _ = _provider(transport)

    with pytest.raises(ProviderUnavailableError, match="Stocktwits MCP"):
        _fetch(provider)

    assert transport.closed


def test_tool_call_failure_is_not_silently_swallowed() -> None:
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=_results(),
        call_errors={"get_message_volume": MCPToolError("tool failure")},
    )
    provider, _ = _provider(transport)

    with pytest.raises(ProviderUnavailableError, match="request failed"):
        _fetch(provider)


def test_invalid_symbol_response_is_rejected() -> None:
    results = _results()
    results["get_sentiment"] = {**results["get_sentiment"], "symbol": "MSFT"}
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=results,
    )
    provider, _ = _provider(transport)

    with pytest.raises(ProviderUnavailableError, match="different symbol"):
        _fetch(provider)


def test_empty_current_sentiment_and_volume_are_explicitly_rejected() -> None:
    results = _results()
    results["get_sentiment"] = {"symbol": "AAPL"}
    results["get_message_volume"] = {"symbol": "AAPL", "series": []}
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=results,
    )
    provider, _ = _provider(transport)

    with pytest.raises(ProviderUnavailableError, match="are empty"):
        _fetch(provider)


def test_empty_messages_preserve_available_signal_without_fake_evidence() -> None:
    results = _results()
    results["get_symbol_messages"] = {"messages": [], "more": False}
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=results,
    )
    provider, _ = _provider(transport)

    records = _fetch(provider)

    assert all(record["record_type"] == "sentiment_snapshot" for record in records)


def test_recent_message_sample_stops_at_explicit_page_cap() -> None:
    results = _results()
    messages = results["get_symbol_messages"]
    messages["more"] = True
    messages["cursor"] = {"max": 100}
    transport = FakeMCPTransport(
        tools=StocktwitsSentimentProvider.required_tools,
        results=results,
    )
    provider = StocktwitsSentimentProvider(
        transport=transport,
        max_message_pages=1,
        clock=lambda: datetime(2026, 8, 10, 21, tzinfo=UTC),
    )

    records = _fetch(provider)

    assert any(record["record_type"] == "sentiment_evidence" for record in records)
    assert [name for name, _ in transport.calls].count("get_symbol_messages") == 1


@pytest.mark.asyncio
async def test_sync_provider_can_be_called_from_running_async_runtime() -> None:
    provider, _ = _provider()

    records = _fetch(provider)

    assert records


@pytest.mark.asyncio
async def test_concrete_transport_requires_oauth_state_before_network(
    tmp_path: Path,
) -> None:
    transport = StreamableHTTPMCPTransport(
        url="https://mcp.stocktwits.com/mcp",
        token_storage=LocalFileMCPTokenStorage(tmp_path / "missing"),
        redirect_uri="http://127.0.0.1:8765/callback",
    )

    with pytest.raises(MCPAuthorizationRequiredError, match="authorization required"):
        await transport.initialize()


@pytest.mark.asyncio
async def test_malformed_oauth_state_is_safely_reported(tmp_path: Path) -> None:
    directory = tmp_path / "invalid"
    directory.mkdir()
    (directory / "oauth_state.json").write_text("not-json", encoding="utf-8")
    storage = LocalFileMCPTokenStorage(directory)

    assert storage.is_configured() is False
    with pytest.raises(MCPAuthorizationRequiredError, match="authorization required"):
        await storage.get_tokens()
