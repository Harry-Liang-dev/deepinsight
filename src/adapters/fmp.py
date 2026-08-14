"""Financial Modeling Prep standardized US fundamental metrics adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import cast
from urllib.parse import urlencode

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.http import ProviderHTTPClient, ProviderHTTPTransport
from src.models.types import JsonObject

_RATIOS_FIELDS = {
    "gross_margin": "grossProfitMarginTTM",
    "operating_margin": "operatingProfitMarginTTM",
    "net_margin": "netProfitMarginTTM",
    "debt_to_equity": "debtToEquityRatioTTM",
    "current_ratio": "currentRatioTTM",
    "eps_ttm": "netIncomePerShareTTM",
    "book_value_per_share": "bookValuePerShareTTM",
    "pe_ttm": "priceToEarningsRatioTTM",
    "pb": "priceToBookRatioTTM",
}
_KEY_METRIC_FIELDS = {
    "roe": "returnOnEquityTTM",
    "roa": "returnOnAssetsTTM",
    "market_cap": "marketCap",
    "earnings_yield": "earningsYieldTTM",
}
_GROWTH_FIELDS = {
    "revenue_yoy": "growthRevenue",
    "net_income_yoy": "growthNetIncome",
}


class FinancialModelingPrepAdapter(BaseProviderAdapter):
    """Fetch point-in-time standardized US ratios from FMP Stable APIs."""

    provider_name = "financial_modeling_prep"
    market_scope = "US"
    access_mode = "authenticated_api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://financialmodelingprep.com/stable",
        user_agent: str = "DeepInsight/0.1",
        request_timeout: float = 30.0,
        max_retries: int = 2,
        requests_per_second: float = 2.0,
        http_transport: ProviderHTTPTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """Configure bounded FMP access without exposing the credential."""

        if not api_key.strip():
            raise ValueError("FMP API key is required")
        normalized_base = base_url.rstrip("/")
        if not normalized_base.startswith("https://"):
            raise ValueError("FMP base URL must use HTTPS")
        self._api_key = api_key
        self._base_url = normalized_base
        self._http = ProviderHTTPClient(
            user_agent=user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            transport=http_transport,
            clock=clock,
            sleeper=sleeper,
        )

    def healthcheck(self) -> JsonObject:
        """Return credential-free configured capability metadata."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "network_attempted": False,
            "capabilities": ["standardized_fundamentals_ttm", "growth"],
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return no identity rows because SEC remains the identity authority."""

        return ()

    def fetch_eod_bars(
        self, asset_ids: list[str], target_date: date
    ) -> Iterable[ProviderRecord]:
        """Return no prices because Alpaca remains the price authority."""

        del asset_ids, target_date
        return ()

    def fetch_documents(
        self, asset_ids: list[str], start_date: date, end_date: date
    ) -> Iterable[ProviderRecord]:
        """Return no documents because SEC remains the filing authority."""

        del asset_ids, start_date, end_date
        return ()

    def fetch_fundamentals_range(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return one standardized TTM record per supported US asset."""

        records: list[ProviderRecord] = []
        for asset_id in asset_ids:
            symbol = _us_symbol(asset_id)
            statement = self._first(
                "income-statement", symbol=symbol, period="quarter", limit="1"
            )
            period_end = _date_value(statement.get("date"), "date")
            filing_date = _optional_date(statement.get("filingDate"))
            accepted_at = _optional_datetime(statement.get("acceptedDate"))
            if period_end < start_date or period_end > end_date:
                continue
            ratios = self._first("ratios-ttm", symbol=symbol)
            key_metrics = self._first("key-metrics-ttm", symbol=symbol)
            growth = self._first(
                "income-statement-growth",
                symbol=symbol,
                period="quarter",
                limit="1",
            )
            values: JsonObject = {
                "asset_id": asset_id,
                "market": "US",
                "exchange_code": "US",
                "fiscal_period_end": period_end.isoformat(),
                "report_type": "TTM_STANDARDIZED",
                "filing_date": None if filing_date is None else filing_date.isoformat(),
                "accepted_at": None if accepted_at is None else accepted_at.isoformat(),
                "source_locator": f"fmp:stable:standardized-metrics:{symbol}",
                "quality": "provider_standardized",
            }
            _map_numeric(values, ratios, _RATIOS_FIELDS)
            _map_numeric(values, key_metrics, _KEY_METRIC_FIELDS)
            _map_numeric(values, growth, _GROWTH_FIELDS)
            records.append(values)
        return records

    def _first(self, endpoint: str, **parameters: str) -> JsonObject:
        url = f"{self._base_url}/{endpoint}?{urlencode(parameters)}"
        text = self._http.get_text(
            url,
            accept="application/json",
            headers={"apikey": self._api_key},
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError(
                f"FMP {endpoint} returned invalid JSON"
            ) from exc
        if (
            not isinstance(payload, list)
            or not payload
            or not isinstance(payload[0], dict)
        ):
            raise ProviderUnavailableError(f"FMP {endpoint} returned no records")
        return cast(JsonObject, payload[0])


def _map_numeric(
    target: JsonObject, source: JsonObject, mapping: dict[str, str]
) -> None:
    for canonical, provider_field in mapping.items():
        value = source.get(provider_field)
        if isinstance(value, int | float) and not isinstance(value, bool):
            target[canonical] = float(value)


def _us_symbol(asset_id: str) -> str:
    normalized = asset_id.upper()
    if not normalized.startswith("US:") or len(normalized) <= 3:
        raise ValueError("FMP adapter supports canonical US asset IDs only")
    return normalized.removeprefix("US:")


def _date_value(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ProviderUnavailableError(f"FMP response omitted {field}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderUnavailableError(
            f"FMP response contained invalid {field}"
        ) from exc


def _optional_date(value: object) -> date | None:
    return None if value is None else _date_value(value, "filingDate")


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderUnavailableError("FMP response contained invalid acceptedDate")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderUnavailableError(
            "FMP response contained invalid acceptedDate"
        ) from exc
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )
