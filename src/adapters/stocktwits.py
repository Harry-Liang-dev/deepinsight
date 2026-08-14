"""Stocktwits remote-MCP backed community sentiment Provider boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.mcp import (
    MCPAuthorizationRequiredError,
    MCPTransport,
    MCPTransportError,
)
from src.models.enums import Market
from src.models.identifiers import AssetId
from src.models.types import JsonObject


class StocktwitsSentimentProvider(BaseProviderAdapter):
    """Map official MCP tools into stable community-signal records."""

    provider_name = "stocktwits_mcp"
    market_scope = "US"
    access_mode = "mcp"
    required_tools = (
        "get_sentiment",
        "get_sentiment_history",
        "get_message_volume",
        "get_message_volume_history",
        "get_symbol_messages",
    )

    def __init__(
        self,
        *,
        transport: MCPTransport,
        history_zoom: str = "1M",
        message_limit: int = 50,
        max_message_pages: int = 5,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind an SDK-independent MCP transport supplied by composition."""

        if history_zoom not in {
            "1D",
            "1W",
            "1M",
            "3M",
            "6M",
            "1Y",
            "5Y",
            "YTD",
            "All",
        }:
            raise ValueError("unsupported Stocktwits history zoom")
        if not 1 <= message_limit <= 50:
            raise ValueError("Stocktwits message_limit must be between one and 50")
        if max_message_pages <= 0:
            raise ValueError("Stocktwits max_message_pages must be positive")
        self._transport = transport
        self._history_zoom = history_zoom
        self._message_limit = message_limit
        self._max_message_pages = max_message_pages
        self._clock = clock or (lambda: datetime.now(UTC))
        self._available_tools: tuple[str, ...] = ()

    @property
    def available_tools(self) -> tuple[str, ...]:
        """Return tool names observed during the latest MCP session."""

        return self._available_tools

    def healthcheck(self) -> JsonObject:
        """Report composition without accessing network or OAuth state."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "access_mode": self.access_mode,
            "network_attempted": False,
            "history_zoom": self._history_zoom,
            "message_limit": self._message_limit,
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return no security master records from community data."""

        return ()

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return no prices from community data."""

        del asset_ids, target_date
        return ()

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return no documents; messages use canonical social records."""

        del asset_ids, start_date, end_date
        return ()

    def fetch_sentiment_range(
        self,
        asset_ids: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Run one complete MCP session and return canonical Provider records."""

        if end_date < start_date:
            raise ValueError("Stocktwits end_date cannot precede start_date")
        return _run_async(
            lambda: self._fetch_sentiment_range_async(
                asset_ids,
                start_date,
                end_date,
            )
        )

    async def _fetch_sentiment_range_async(
        self,
        asset_ids: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> list[ProviderRecord]:
        collected_at = self._clock().astimezone(UTC)
        records: list[ProviderRecord] = []
        active_error: BaseException | None = None
        try:
            await self._transport.initialize()
            self._available_tools = await self._transport.list_tools()
            missing = sorted(set(self.required_tools) - set(self._available_tools))
            if missing:
                raise ProviderUnavailableError(
                    "Stocktwits MCP is missing required tools: " + ", ".join(missing)
                )
            for raw_asset_id in asset_ids:
                asset_id = AssetId(raw_asset_id)
                if asset_id.market is not Market.US:
                    raise ValueError("Stocktwits v1 supports canonical US assets only")
                records.extend(
                    await self._fetch_asset(
                        asset_id,
                        start_date,
                        end_date,
                        collected_at,
                    )
                )
            return records
        except MCPAuthorizationRequiredError as exc:
            active_error = exc
            raise ProviderUnavailableError(
                "Stocktwits MCP authorization required"
            ) from None
        except MCPTransportError as exc:
            active_error = exc
            raise ProviderUnavailableError("Stocktwits MCP request failed") from None
        except BaseException as exc:
            active_error = exc
            raise
        finally:
            try:
                await self._transport.close()
            except MCPTransportError:
                if active_error is None:
                    raise ProviderUnavailableError(
                        "Stocktwits MCP transport close failed"
                    ) from None

    async def _fetch_asset(
        self,
        asset_id: AssetId,
        start_date: date,
        end_date: date,
        collected_at: datetime,
    ) -> list[ProviderRecord]:
        symbol = str(asset_id).split(":", maxsplit=1)[1]
        sentiment = await self._call("get_sentiment", {"symbol": symbol})
        sentiment_history = await self._call(
            "get_sentiment_history",
            {"symbol": symbol, "zoom": self._history_zoom},
        )
        volume = await self._call("get_message_volume", {"symbol": symbol})
        volume_history = await self._call(
            "get_message_volume_history",
            {"symbol": symbol, "zoom": self._history_zoom},
        )
        for payload in (sentiment, sentiment_history, volume, volume_history):
            _require_symbol(payload, symbol)
        records = _history_records(
            asset_id,
            symbol,
            sentiment_history,
            volume_history,
            start_date,
            end_date,
        )
        records.append(
            _current_record(asset_id, symbol, sentiment, volume, collected_at)
        )
        records.extend(
            await self._message_records(asset_id, symbol, start_date, end_date)
        )
        return records

    async def _call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Mapping[str, object]:
        result = await self._transport.call_tool(tool_name, arguments)
        return result.data

    async def _message_records(
        self,
        asset_id: AssetId,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[ProviderRecord]:
        records: list[ProviderRecord] = []
        max_id: int | None = None
        seen_cursors: set[int] = set()
        for _ in range(self._max_message_pages):
            arguments: dict[str, Any] = {
                "symbol": symbol,
                "limit": self._message_limit,
            }
            if max_id is not None:
                arguments["max"] = max_id
            payload = await self._call("get_symbol_messages", arguments)
            messages = payload.get("messages")
            if messages is None:
                return records
            if not isinstance(messages, list):
                raise ProviderUnavailableError(
                    "Stocktwits messages response must contain an array"
                )
            oldest_date: date | None = None
            for message in messages:
                if not isinstance(message, dict):
                    raise ProviderUnavailableError(
                        "Stocktwits message must be an object"
                    )
                created_at = _aware_datetime(message.get("created_at"), "created_at")
                oldest_date = (
                    created_at.date()
                    if oldest_date is None
                    else min(oldest_date, created_at.date())
                )
                if not start_date <= created_at.date() <= end_date:
                    continue
                message_id = _required_identifier(message.get("id"), "message id")
                body = str(message.get("body") or "").strip()
                if not body:
                    continue
                records.append(
                    {
                        "record_type": "sentiment_evidence",
                        "message_id": message_id,
                        "asset_id": str(asset_id),
                        "market": "US",
                        "created_at": created_at.isoformat(),
                        "text": body,
                        "declared_sentiment": (
                            str(message["sentiment"])
                            if message.get("sentiment") is not None
                            else None
                        ),
                        "source_locator": f"https://stocktwits.com/message/{message_id}",
                    }
                )
            if oldest_date is not None and oldest_date < start_date:
                return records
            if not bool(payload.get("more")):
                return records
            cursor = payload.get("cursor")
            next_max = cursor.get("max") if isinstance(cursor, dict) else None
            if not isinstance(next_max, int) or next_max in seen_cursors:
                raise ProviderUnavailableError(
                    "Stocktwits message pagination cursor is invalid"
                )
            seen_cursors.add(next_max)
            max_id = next_max
        # ``get_symbol_messages`` is a bounded recent-evidence sample, while
        # sentiment/volume history provides the complete configured signal
        # window. Reaching the explicit page cap is therefore a normal stop;
        # invalid or looping cursors above still fail closed.
        return records


def _history_records(
    asset_id: AssetId,
    symbol: str,
    sentiment_payload: Mapping[str, object],
    volume_payload: Mapping[str, object],
    start_date: date,
    end_date: date,
) -> list[ProviderRecord]:
    sentiment = _history_points(sentiment_payload, "sentiment")
    volume = _history_points(volume_payload, "message volume")
    records: list[ProviderRecord] = []
    for timestamp in sorted(set(sentiment) | set(volume)):
        if not start_date <= timestamp.date() <= end_date:
            continue
        sentiment_value = sentiment.get(timestamp)
        volume_value = volume.get(timestamp)
        records.append(
            {
                "record_type": "sentiment_snapshot",
                "asset_id": str(asset_id),
                "market": "US",
                "as_of": timestamp.isoformat(),
                "score": None if sentiment_value is None else sentiment_value[0],
                "label": None if sentiment_value is None else sentiment_value[1],
                "bullish_pct": None,
                "bearish_pct": None,
                "message_volume_score": (
                    None if volume_value is None else volume_value[0]
                ),
                "message_volume_label": (
                    None if volume_value is None else volume_value[1]
                ),
                "source_timestamp": timestamp.isoformat(),
                "quality": "historical_normalized_signal",
                "source_locator": (
                    f"stocktwits:symbol:{symbol}:history:{timestamp.isoformat()}"
                ),
            }
        )
    return records


def _current_record(
    asset_id: AssetId,
    symbol: str,
    sentiment: Mapping[str, object],
    volume: Mapping[str, object],
    collected_at: datetime,
) -> ProviderRecord:
    current_volume: Mapping[str, object] | None = None
    series = volume.get("series")
    if isinstance(series, list):
        current_volume = next(
            (
                value
                for value in series
                if isinstance(value, dict) and value.get("timeframe") == "now"
            ),
            None,
        )
    updated_at = sentiment.get("updated_at")
    source_timestamp = (
        _aware_datetime(updated_at, "updated_at")
        if updated_at is not None
        else collected_at
    )
    values = {
        "score": _optional_number(sentiment.get("score"), "score"),
        "bullish_pct": _optional_number(sentiment.get("bullish_pct"), "bullish_pct"),
        "bearish_pct": _optional_number(sentiment.get("bearish_pct"), "bearish_pct"),
        "message_volume_score": (
            None
            if current_volume is None
            else _optional_number(
                current_volume.get("normalized_value"),
                "message volume score",
            )
        ),
    }
    if all(value is None for value in values.values()):
        raise ProviderUnavailableError(
            "Stocktwits current sentiment and message volume are empty"
        )
    return {
        "record_type": "sentiment_snapshot",
        "asset_id": str(asset_id),
        "market": "US",
        "as_of": collected_at.isoformat(),
        **values,
        "label": _optional_string(sentiment.get("label")),
        "message_volume_label": (
            None
            if current_volume is None
            else _optional_string(current_volume.get("normalized_label"))
        ),
        "source_timestamp": source_timestamp.isoformat(),
        "quality": "current_community_signal",
        "source_locator": f"stocktwits:symbol:{symbol}:current",
    }


def _history_points(
    payload: Mapping[str, object],
    label: str,
) -> dict[datetime, tuple[float, str]]:
    raw_series = payload.get("series")
    if raw_series is None:
        return {}
    if not isinstance(raw_series, list):
        raise ProviderUnavailableError(f"Stocktwits {label} history must be an array")
    points: dict[datetime, tuple[float, str]] = {}
    for raw in raw_series:
        if not isinstance(raw, dict):
            raise ProviderUnavailableError(
                f"Stocktwits {label} history point must be an object"
            )
        timestamp = _aware_datetime(raw.get("time"), "history time")
        value = raw.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ProviderUnavailableError(
                f"Stocktwits {label} history value must be numeric"
            )
        points[timestamp] = (float(value), str(raw.get("label") or "unknown"))
    return points


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ProviderUnavailableError(f"Stocktwits {field} must be numeric")
    return float(value)


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _require_symbol(payload: Mapping[str, object], expected: str) -> None:
    if str(payload.get("symbol") or "").upper() != expected:
        raise ProviderUnavailableError("Stocktwits returned a different symbol")


def _aware_datetime(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderUnavailableError(
            f"Stocktwits {field} must be an ISO datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderUnavailableError(f"Stocktwits {field} must include a timezone")
    return parsed.astimezone(UTC)


def _required_identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProviderUnavailableError(f"Stocktwits {field} is required")
    return text


def _run_async[ResultT](
    factory: Callable[[], Coroutine[Any, Any, ResultT]],
) -> ResultT:
    """Run one complete async MCP session from sync or async callers."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stocktwits-mcp") as pool:
        return pool.submit(asyncio.run, factory()).result()
