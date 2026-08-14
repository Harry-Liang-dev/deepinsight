"""Deterministic valuation and relative-context operator tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.models.identifiers import AssetId
from src.operators import MarketContextOperator, ValuationOperator
from src.schemas.market_data import EodBarRecord, FundamentalRecord


def _bars(asset_id: str, multiplier: float) -> list[EodBarRecord]:
    return [
        EodBarRecord(
            asset_id=AssetId(asset_id),
            trade_date=date(2026, 7, 1) + timedelta(days=index),
            close=(100 + index) * multiplier,
            source_id="alpaca_market_data",
            ingestion_ts=datetime(2026, 8, 10, tzinfo=UTC),
        )
        for index in range(21)
    ]


def test_market_context_uses_canonical_benchmark_bars() -> None:
    values = MarketContextOperator().compute(
        {
            "US:AAPL": _bars("US:AAPL", 1.2),
            "US:SPY": _bars("US:SPY", 1.0),
            "US:QQQ": _bars("US:QQQ", 1.1),
            "US:XLK": _bars("US:XLK", 1.15),
        },
        target_asset="US:AAPL",
        market_benchmark="US:SPY",
        growth_benchmark="US:QQQ",
        sector_benchmark="US:XLK",
    )
    assert values["asset_return_20d"] is not None
    assert values["market_volatility"] is not None
    assert values["benchmark_trend"] == "up"


def test_valuation_never_estimates_missing_inputs() -> None:
    bars = _bars("US:AAPL", 1.0)
    fundamental = FundamentalRecord(
        asset_id=AssetId("US:AAPL"),
        fiscal_period_end=date(2026, 6, 30),
        report_type="10-K",
        eps_basic=6.0,
        shareholders_equity=1000.0,
        shares_outstanding=100.0,
        source_id="sec_edgar",
        ingestion_ts=datetime(2026, 8, 10, tzinfo=UTC),
    )
    values = ValuationOperator().compute(bars, [fundamental])
    assert values["market_cap"] == 12_000.0
    assert values["eps_ttm"] == 6.0
    assert values["book_value_per_share"] == 10.0
    assert values["pe_ttm"] == 20.0
    assert values["pb"] == 12.0
    assert (
        ValuationOperator().compute(
            bars, [fundamental.model_copy(update={"eps_basic": None})]
        )["pe_ttm"]
        is None
    )


def test_valuation_uses_latest_available_canonical_input_per_field() -> None:
    """Shares and equity may arrive in distinct SEC Company Facts rows."""

    base = FundamentalRecord(
        asset_id=AssetId("US:AAPL"),
        fiscal_period_end=date(2025, 9, 30),
        report_type="10-K",
        eps_basic=5.0,
        shareholders_equity=900.0,
        source_id="sec_edgar",
        ingestion_ts=datetime(2026, 8, 10, tzinfo=UTC),
    )
    shares = FundamentalRecord(
        asset_id=AssetId("US:AAPL"),
        fiscal_period_end=date(2026, 7, 17),
        report_type="10-Q",
        shares_outstanding=90.0,
        source_id="sec_edgar",
        ingestion_ts=datetime(2026, 8, 10, tzinfo=UTC),
    )

    values = ValuationOperator().compute(_bars("US:AAPL", 1.0), [base, shares])

    assert values["market_cap"] == 10_800.0
    assert values["book_value_per_share"] == 10.0
    assert values["pb"] == 12.0


def test_valuation_does_not_label_stale_annual_eps_as_current_ttm() -> None:
    """A newer quarter requires four discrete quarters before TTM valuation."""

    annual = FundamentalRecord(
        asset_id=AssetId("US:AAPL"),
        fiscal_period_end=date(2025, 9, 30),
        report_type="10-K",
        eps_basic=5.0,
        source_id="sec_edgar",
        ingestion_ts=datetime(2026, 8, 10, tzinfo=UTC),
    )
    quarter = annual.model_copy(
        update={
            "fiscal_period_end": date(2026, 6, 30),
            "report_type": "10-Q",
            "eps_basic": 1.5,
        }
    )

    values = ValuationOperator().compute(_bars("US:AAPL", 1.0), [annual, quarter])

    assert values["eps_ttm"] is None
    assert values["pe_ttm"] is None
    assert values["earnings_yield"] is None
