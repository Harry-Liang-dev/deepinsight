"""Financial Modeling Prep standardized US fundamental metrics adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
from typing import cast
from urllib.parse import urlencode

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.http import ProviderHTTPClient, ProviderHTTPTransport
from src.models.types import JsonObject, JsonValue

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
_ACQUISITION_CONTRACT_VERSION = "fmp_standardized_fundamentals_v1"


@dataclass(frozen=True, slots=True)
class FMPProviderSnapshot:
    """One credential-free canonical FMP acquisition retained for one run."""

    snapshot_id: str
    provider: str
    asset_ids: tuple[str, ...]
    research_as_of: datetime
    start_date: date
    end_date: date
    acquisition_contract_version: str
    acquired_at: datetime
    records: tuple[ProviderRecord, ...]

    def to_payload(self) -> JsonObject:
        """Serialize the run-scoped snapshot without authentication material."""

        return {
            "snapshot_id": self.snapshot_id,
            "provider": self.provider,
            "asset_ids": list(self.asset_ids),
            "research_as_of": self.research_as_of.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "acquisition_contract_version": self.acquisition_contract_version,
            "acquired_at": self.acquired_at.isoformat(),
            "records": [deepcopy(record) for record in self.records],
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
        research_as_of: datetime | None = None,
        acquisition_clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Configure bounded FMP access without exposing the credential."""

        if not api_key.strip():
            raise ValueError("FMP API key is required")
        normalized_base = base_url.rstrip("/")
        if not normalized_base.startswith("https://"):
            raise ValueError("FMP base URL must use HTTPS")
        self._api_key = api_key
        self._base_url = normalized_base
        if research_as_of is not None:
            research_as_of = _utc_instant(research_as_of, "research_as_of")
        self._research_as_of = research_as_of
        self._acquisition_clock = acquisition_clock or (lambda: datetime.now(UTC))
        self._snapshots: dict[
            tuple[tuple[str, ...], date, date, datetime, str],
            FMPProviderSnapshot,
        ] = {}
        self._external_acquisition_count = 0
        self._snapshot_reuse_count = 0
        self._endpoint_call_counts: dict[str, int] = {}
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
        """Return one same-run snapshot per exact acquisition contract."""

        research_as_of = self._research_as_of or datetime.combine(
            end_date,
            time.max,
            tzinfo=UTC,
        )
        return self.fetch_fundamentals_range_at(
            asset_ids,
            start_date,
            end_date,
            research_as_of=research_as_of,
        )

    def fetch_fundamentals_range_at(
        self,
        asset_ids: Sequence[str],
        start_date: date,
        end_date: date,
        *,
        research_as_of: datetime,
    ) -> Iterable[ProviderRecord]:
        """Acquire or reuse an exact run-scoped, PIT-keyed FMP snapshot."""

        normalized_as_of = _utc_instant(research_as_of, "research_as_of")
        if end_date < start_date:
            raise ValueError("FMP end_date cannot precede start_date")
        if end_date > normalized_as_of.date():
            raise ValueError("FMP fundamental window cannot exceed research_as_of")
        normalized_assets = tuple(
            sorted({_canonical_asset_id(item) for item in asset_ids})
        )
        key = (
            normalized_assets,
            start_date,
            end_date,
            normalized_as_of,
            _ACQUISITION_CONTRACT_VERSION,
        )
        existing = self._snapshots.get(key)
        if existing is not None:
            self._snapshot_reuse_count += 1
            return tuple(deepcopy(record) for record in existing.records)

        self._external_acquisition_count += 1
        records = tuple(
            self._fetch_fundamentals_uncached(
                normalized_assets,
                start_date,
                end_date,
            )
        )
        acquired_at = _utc_instant(self._acquisition_clock(), "acquired_at")
        snapshot = FMPProviderSnapshot(
            snapshot_id=_snapshot_id(key),
            provider=self.provider_name,
            asset_ids=normalized_assets,
            research_as_of=normalized_as_of,
            start_date=start_date,
            end_date=end_date,
            acquisition_contract_version=_ACQUISITION_CONTRACT_VERSION,
            acquired_at=acquired_at,
            records=tuple(deepcopy(record) for record in records),
        )
        self._snapshots[key] = snapshot
        return tuple(deepcopy(record) for record in records)

    def acquisition_snapshot(
        self,
        asset_ids: Sequence[str],
        start_date: date,
        end_date: date,
        *,
        research_as_of: datetime | None = None,
    ) -> FMPProviderSnapshot | None:
        """Return an already-acquired exact snapshot without fetching."""

        cutoff = research_as_of or self._research_as_of
        if cutoff is None:
            cutoff = datetime.combine(end_date, time.max, tzinfo=UTC)
        key = (
            tuple(sorted({_canonical_asset_id(item) for item in asset_ids})),
            start_date,
            end_date,
            _utc_instant(cutoff, "research_as_of"),
            _ACQUISITION_CONTRACT_VERSION,
        )
        return self._snapshots.get(key)

    def acquisition_diagnostics(self) -> JsonObject:
        """Return credential-free same-run acquisition and retry counters."""

        return {
            "provider": self.provider_name,
            "acquisition_contract_version": _ACQUISITION_CONTRACT_VERSION,
            "external_acquisition_count": self._external_acquisition_count,
            "snapshot_reuse_count": self._snapshot_reuse_count,
            "physical_http_request_count": self._http.request_count,
            "retry_count": self._http.retry_count,
            "endpoint_call_counts": dict(sorted(self._endpoint_call_counts.items())),
            "snapshot_ids": cast(
                list[JsonValue],
                sorted(snapshot.snapshot_id for snapshot in self._snapshots.values()),
            ),
        }

    def _fetch_fundamentals_uncached(
        self,
        asset_ids: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Perform the four documented Stable endpoint calls per asset."""

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
        self._endpoint_call_counts[endpoint] = (
            self._endpoint_call_counts.get(endpoint, 0) + 1
        )
        try:
            text = self._http.get_text(
                url,
                accept="application/json",
                headers={"apikey": self._api_key},
            )
        except ProviderUnavailableError as exc:
            raise ProviderUnavailableError(
                f"FMP {endpoint} request failed: {exc}"
            ) from None
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


def _canonical_asset_id(asset_id: str) -> str:
    return f"US:{_us_symbol(asset_id)}"


def _utc_instant(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"FMP {field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _snapshot_id(
    key: tuple[tuple[str, ...], date, date, datetime, str],
) -> str:
    assets, start_date, end_date, research_as_of, contract_version = key
    payload = json.dumps(
        {
            "provider": FinancialModelingPrepAdapter.provider_name,
            "asset_ids": assets,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "research_as_of": research_as_of.isoformat(),
            "acquisition_contract_version": contract_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"fmp_snapshot_{sha256(payload.encode()).hexdigest()[:24]}"
