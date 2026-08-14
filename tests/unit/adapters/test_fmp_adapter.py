"""Offline tests for FMP Stable standardized-fundamentals mapping."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlparse
from urllib.request import Request

from src.adapters import FinancialModelingPrepAdapter
from src.adapters.http import ProviderHTTPResponse


class _FMPTransport:
    """Return fixed official-shaped Stable API payloads without network access."""

    def __init__(self, *, omit_pb: bool = False) -> None:
        self.omit_pb = omit_pb
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        assert timeout == 7.0
        self.requests.append(request)
        endpoint = urlparse(request.full_url).path.rsplit("/", maxsplit=1)[-1]
        payload: dict[str, object]
        if endpoint == "income-statement":
            payload = {
                "date": "2026-06-27",
                "filingDate": "2026-07-31",
                "acceptedDate": "2026-07-31 06:01:02",
            }
        elif endpoint == "ratios-ttm":
            payload = {
                "grossProfitMarginTTM": 0.48,
                "operatingProfitMarginTTM": 0.33,
                "netProfitMarginTTM": 0.27,
                "debtToEquityRatioTTM": 0.78,
                "currentRatioTTM": 1.0,
                "netIncomePerShareTTM": 8.77,
                "bookValuePerShareTTM": 7.31,
                "priceToEarningsRatioTTM": 34.84,
            }
            if not self.omit_pb:
                payload["priceToBookRatioTTM"] = 41.71
        elif endpoint == "key-metrics-ttm":
            payload = {
                "returnOnEquityTTM": 1.37,
                "returnOnAssetsTTM": 0.33,
                "marketCap": 4_483_462_292_560,
                "earningsYieldTTM": 0.028,
            }
        else:
            payload = {"growthRevenue": -0.015, "growthNetIncome": 0.007}
        return ProviderHTTPResponse(200, {}, json.dumps([payload]).encode())


def test_fmp_maps_stable_fields_and_preserves_period_metadata() -> None:
    """Canonical fields come directly from official standardized responses."""

    transport = _FMPTransport()
    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    records = list(
        adapter.fetch_fundamentals_range(
            ["US:AAPL"], date(2025, 1, 1), date(2026, 8, 14)
        )
    )

    assert records == [
        {
            "asset_id": "US:AAPL",
            "market": "US",
            "exchange_code": "US",
            "fiscal_period_end": "2026-06-27",
            "report_type": "TTM_STANDARDIZED",
            "filing_date": "2026-07-31",
            "accepted_at": "2026-07-31T06:01:02+00:00",
            "source_locator": "fmp:stable:standardized-metrics:AAPL",
            "quality": "provider_standardized",
            "gross_margin": 0.48,
            "operating_margin": 0.33,
            "net_margin": 0.27,
            "debt_to_equity": 0.78,
            "current_ratio": 1.0,
            "eps_ttm": 8.77,
            "book_value_per_share": 7.31,
            "pe_ttm": 34.84,
            "pb": 41.71,
            "roe": 1.37,
            "roa": 0.33,
            "market_cap": 4_483_462_292_560.0,
            "earnings_yield": 0.028,
            "revenue_yoy": -0.015,
            "net_income_yoy": 0.007,
        }
    ]
    assert len(transport.requests) == 4
    assert all(
        request.get_header("Apikey") == "fixture-secret"
        for request in transport.requests
    )


def test_fmp_omits_missing_provider_field_instead_of_estimating() -> None:
    """An absent standardized field remains absent for Bundle missing-data logic."""

    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=_FMPTransport(omit_pb=True),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    record = next(
        iter(
            adapter.fetch_fundamentals_range(
                ["US:AAPL"], date(2025, 1, 1), date(2026, 8, 14)
            )
        )
    )

    assert "pb" not in record
