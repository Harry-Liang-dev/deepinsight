"""Offline contract tests for data provider adapters."""

from __future__ import annotations

from datetime import date

import pytest

from src.adapters import (
    AlpacaAdapter,
    BloombergLicensedAdapter,
    CNINFOAdapter,
    FakeProviderAdapter,
    FREDAdapter,
    HKEXNewsAdapter,
    LSEGLicensedAdapter,
    ProviderUnavailableError,
    SECEDGARAdapter,
    WindAdapter,
    XSearchAdapter,
)


@pytest.mark.parametrize(
    "adapter_type",
    [
        WindAdapter,
        CNINFOAdapter,
        HKEXNewsAdapter,
        SECEDGARAdapter,
        FREDAdapter,
        AlpacaAdapter,
        XSearchAdapter,
        LSEGLicensedAdapter,
        BloombergLicensedAdapter,
    ],
)
def test_real_provider_boundaries_never_attempt_network(adapter_type: type) -> None:
    """Unconfigured provider boundaries fail explicitly and offline."""

    adapter = adapter_type()
    health = adapter.healthcheck()

    assert health["status"] == "unavailable"
    assert health["network_attempted"] is False
    with pytest.raises(ProviderUnavailableError, match="not configured"):
        list(adapter.fetch_instruments())


def test_fake_provider_filters_fixed_records() -> None:
    """The fake provider supplies deterministic requested records."""

    adapter = FakeProviderAdapter(
        eod_bars=[
            {
                "asset_id": "US:AAPL",
                "market": "US",
                "trade_date": "2026-07-30",
                "close": 210.0,
            },
            {
                "asset_id": "US:MSFT",
                "market": "US",
                "trade_date": "2026-07-30",
                "close": 500.0,
            },
        ]
    )

    result = list(adapter.fetch_eod_bars(["US:AAPL"], date(2026, 7, 30)))

    assert adapter.healthcheck()["mode"] == "offline"
    assert [item["asset_id"] for item in result] == ["US:AAPL"]


def test_fake_provider_can_fail_after_partial_yield() -> None:
    """A configured failure can model a provider stream interruption."""

    adapter = FakeProviderAdapter(
        instruments=[
            {"asset_id": "US:AAPL"},
            {"asset_id": "US:MSFT"},
        ],
        fail_stream="instruments",
        fail_after=1,
    )
    stream = iter(adapter.fetch_instruments())

    assert next(stream)["asset_id"] == "US:AAPL"
    with pytest.raises(ProviderUnavailableError, match="configured failure"):
        next(stream)
