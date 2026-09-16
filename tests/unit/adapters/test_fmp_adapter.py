"""Offline tests for FMP Stable standardized-fundamentals mapping."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.parse import urlparse
from urllib.request import Request

import pytest

from src.adapters import FinancialModelingPrepAdapter, ProviderUnavailableError
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


def test_fmp_same_run_reuses_one_canonical_snapshot_with_provenance() -> None:
    """Preflight and formal consumption must share one real acquisition."""

    transport = _FMPTransport()
    research_as_of = datetime(2026, 8, 14, 20, tzinfo=UTC)
    acquired_at = datetime(2026, 8, 14, 20, 1, tzinfo=UTC)
    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        research_as_of=research_as_of,
        acquisition_clock=lambda: acquired_at,
    )
    args = (["US:AAPL"], date(2025, 1, 1), date(2026, 8, 14))

    preflight = list(adapter.fetch_fundamentals_range(*args))
    formal = list(adapter.fetch_fundamentals_range(*args))
    snapshot = adapter.acquisition_snapshot(
        args[0],
        args[1],
        args[2],
        research_as_of=research_as_of,
    )

    assert formal == preflight
    assert snapshot is not None
    assert snapshot.research_as_of == research_as_of
    assert snapshot.acquired_at == acquired_at
    assert snapshot.records[0]["accepted_at"] == "2026-07-31T06:01:02+00:00"
    assert snapshot.records[0]["source_locator"] == (
        "fmp:stable:standardized-metrics:AAPL"
    )
    assert adapter.acquisition_diagnostics() == {
        "provider": "financial_modeling_prep",
        "acquisition_contract_version": "fmp_standardized_fundamentals_v1",
        "external_acquisition_count": 1,
        "snapshot_reuse_count": 1,
        "physical_http_request_count": 4,
        "retry_count": 0,
        "endpoint_call_counts": {
            "income-statement": 1,
            "income-statement-growth": 1,
            "key-metrics-ttm": 1,
            "ratios-ttm": 1,
        },
        "snapshot_ids": [snapshot.snapshot_id],
    }


def test_fmp_different_cutoff_requires_new_acquisition() -> None:
    """A snapshot from another research cutoff cannot be reused."""

    transport = _FMPTransport()
    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    for hour in (20, 21):
        list(
            adapter.fetch_fundamentals_range_at(
                ["US:AAPL"],
                date(2025, 1, 1),
                date(2026, 8, 14),
                research_as_of=datetime(2026, 8, 14, hour, tzinfo=UTC),
            )
        )

    diagnostics = adapter.acquisition_diagnostics()
    assert diagnostics["external_acquisition_count"] == 2
    assert diagnostics["snapshot_reuse_count"] == 0
    assert diagnostics["physical_http_request_count"] == 8


def test_fmp_different_asset_requires_new_acquisition() -> None:
    """Canonical asset identity participates in the same-run snapshot key."""

    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=_FMPTransport(),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        research_as_of=datetime(2026, 8, 14, 20, tzinfo=UTC),
    )
    for asset_id in ("US:AAPL", "US:MSFT"):
        list(
            adapter.fetch_fundamentals_range(
                [asset_id], date(2025, 1, 1), date(2026, 8, 14)
            )
        )

    diagnostics = adapter.acquisition_diagnostics()
    assert diagnostics["external_acquisition_count"] == 2
    assert diagnostics["physical_http_request_count"] == 8


class _TransientRateLimitTransport(_FMPTransport):
    def __init__(self) -> None:
        super().__init__()
        self.rate_limited = False

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        if not self.rate_limited:
            self.rate_limited = True
            self.requests.append(request)
            return ProviderHTTPResponse(429, {"Retry-After": "2"}, b"")
        return super().send(request, timeout)


def test_fmp_429_respects_retry_after_and_succeeds_bounded() -> None:
    """A transient 429 retries once and leaves explicit counters."""

    sleeps: list[float] = []
    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        max_retries=1,
        http_transport=_TransientRateLimitTransport(),
        clock=lambda: 0.0,
        sleeper=sleeps.append,
    )

    records = list(
        adapter.fetch_fundamentals_range(
            ["US:AAPL"], date(2025, 1, 1), date(2026, 8, 14)
        )
    )

    assert records
    assert 2.0 in sleeps
    diagnostics = adapter.acquisition_diagnostics()
    assert diagnostics["physical_http_request_count"] == 5
    assert diagnostics["retry_count"] == 1


@pytest.mark.parametrize("status", (401, 403, 429))
def test_fmp_permanent_or_persistent_http_failure_fails_closed(status: int) -> None:
    """Auth errors never retry; a persistent 429 stops at the configured bound."""

    class FailureTransport:
        def __init__(self) -> None:
            self.count = 0

        def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
            del request, timeout
            self.count += 1
            return ProviderHTTPResponse(status, {"Retry-After": "1"}, b"")

    transport = FailureTransport()
    adapter = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        max_retries=1,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(ProviderUnavailableError, match=f"status {status}"):
        list(
            adapter.fetch_fundamentals_range(
                ["US:AAPL"], date(2025, 1, 1), date(2026, 8, 14)
            )
        )

    assert transport.count == (2 if status == 429 else 1)
    assert adapter.acquisition_diagnostics()["retry_count"] == (
        1 if status == 429 else 0
    )
