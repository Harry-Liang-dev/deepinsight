"""Deterministic tests for SectorResearchSnapshot v1."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.models.enums import SectorCapabilityStatus, SectorId
from src.models.identifiers import AssetId
from src.operators import SectorStateInputError, SectorStateOperator
from src.schemas.market_data import EodBarRecord, FundamentalRecord
from src.schemas.research_data import DataQualityStatus
from src.schemas.sectors import SectorUniverseCoverage, SectorUniverseSnapshot

_AS_OF = date(2026, 8, 30)


def _universe(*assets: str, benchmark: str = "US:SOXX") -> SectorUniverseSnapshot:
    return SectorUniverseSnapshot(
        snapshot_id="sector_universe_0123456789abcdef01234567",
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF,
        asset_ids=tuple(AssetId(item) for item in assets),
        benchmark_ids=(AssetId(benchmark),),
        membership_version="sector_universe_membership_v1",
        source="test",
        coverage=SectorUniverseCoverage(
            membership_count=len(assets),
            classified_asset_count=len(assets),
            benchmark_count=1,
            classification_ratio=1.0,
        ),
        quality=DataQualityStatus.PASS,
    )


def _bars(asset_id: str, *, slope: float, count: int = 80) -> list[EodBarRecord]:
    start = _AS_OF - timedelta(days=count)
    return [
        EodBarRecord(
            asset_id=AssetId(asset_id),
            trade_date=start + timedelta(days=index),
            open=100.0 + slope * index,
            high=101.0 + slope * index,
            low=99.0 + slope * index,
            close=100.0 + slope * index,
            adj_close=100.0 + slope * index,
            volume=1_000_000.0 + index * 1_000.0,
            source_id="alpaca_market_data",
            ingestion_ts=datetime(2026, 8, 30, 12, tzinfo=UTC),
        )
        for index in range(count)
    ]


def _fundamental(
    asset_id: str,
    *,
    revenue_yoy: float,
    pe_ttm: float,
) -> FundamentalRecord:
    return FundamentalRecord(
        asset_id=AssetId(asset_id),
        fiscal_period_end=date(2026, 6, 30),
        report_type="TTM_STANDARDIZED",
        revenue_yoy=revenue_yoy,
        net_income_yoy=revenue_yoy / 2.0,
        gross_margin=0.5,
        roe=0.3,
        roa=0.2,
        pe_ttm=pe_ttm,
        pb=8.0,
        source_id="financial_modeling_prep",
        source_locator=f"fmp:{asset_id}",
        accepted_at=datetime(2026, 7, 1, tzinfo=UTC),
        ingestion_ts=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )


def _complete_inputs() -> tuple[
    SectorUniverseSnapshot,
    dict[str, list[EodBarRecord]],
    dict[str, list[FundamentalRecord]],
]:
    assets = ("US:AMD", "US:NVDA", "US:TSM")
    universe = _universe(*assets)
    bars = {
        "US:AMD": _bars("US:AMD", slope=0.4),
        "US:NVDA": _bars("US:NVDA", slope=0.8),
        "US:TSM": _bars("US:TSM", slope=-0.1),
        "US:SPY": _bars("US:SPY", slope=0.2),
        "US:SOXX": _bars("US:SOXX", slope=0.3),
    }
    fundamentals = {
        "US:AMD": [_fundamental("US:AMD", revenue_yoy=0.1, pe_ttm=30.0)],
        "US:NVDA": [_fundamental("US:NVDA", revenue_yoy=0.3, pe_ttm=40.0)],
        "US:TSM": [_fundamental("US:TSM", revenue_yoy=0.2, pe_ttm=20.0)],
    }
    return universe, bars, fundamentals


def test_sector_state_is_deterministic_and_order_independent() -> None:
    """Input mapping and observation order cannot change deterministic output."""

    universe, bars, fundamentals = _complete_inputs()
    operator = SectorStateOperator()

    first = operator.compute(
        universe=universe,
        bars_by_asset=bars,
        fundamentals_by_asset=fundamentals,
    )
    second = operator.compute(
        universe=universe,
        bars_by_asset={
            key: list(reversed(value)) for key, value in reversed(bars.items())
        },
        fundamentals_by_asset=dict(reversed(fundamentals.items())),
    )

    assert first == second
    assert first.status is SectorCapabilityStatus.AVAILABLE
    assert first.market_state.return_20d.value is not None
    assert first.market_state.excess_return_vs_market.value is not None
    assert first.breadth_state.pct_above_sma20.coverage_count == 3
    assert first.fundamental_state.median_revenue_yoy.value == pytest.approx(0.2)
    assert first.valuation_state.median_pe.value == pytest.approx(30.0)
    assert first.coverage.market_coverage_count == 3
    assert first.coverage.fundamental_coverage_count == 3


def test_small_sector_is_partial_and_does_not_emit_aggregate() -> None:
    """A one-name Sector discloses coverage instead of presenting a median."""

    universe = _universe("US:MU")
    snapshot = SectorStateOperator().compute(
        universe=universe,
        bars_by_asset={
            "US:MU": _bars("US:MU", slope=0.2),
            "US:SPY": _bars("US:SPY", slope=0.1),
            "US:SOXX": _bars("US:SOXX", slope=0.15),
        },
        fundamentals_by_asset={
            "US:MU": [_fundamental("US:MU", revenue_yoy=0.2, pe_ttm=18.0)]
        },
    )

    assert snapshot.status is SectorCapabilityStatus.PARTIAL
    assert snapshot.market_state.return_20d.value is None
    assert snapshot.market_state.return_20d.coverage_count == 1
    assert snapshot.market_state.return_20d.universe_count == 1
    assert snapshot.fundamental_state.median_revenue_yoy.value is None
    assert snapshot.fundamental_state.median_revenue_yoy.status is (
        SectorCapabilityStatus.PARTIAL
    )


def test_missing_inputs_are_safe_and_coverage_is_zero() -> None:
    """An empty data projection produces explicit MISSING metrics."""

    snapshot = SectorStateOperator().compute(
        universe=_universe("US:AMD", "US:NVDA"),
        bars_by_asset={},
        fundamentals_by_asset={},
    )

    assert snapshot.status is SectorCapabilityStatus.MISSING
    assert snapshot.market_state.return_20d.status is SectorCapabilityStatus.MISSING
    assert snapshot.market_state.return_20d.coverage_count == 0
    assert snapshot.market_state.return_20d.universe_count == 2
    assert snapshot.valuation_state.median_pe.value is None
    assert snapshot.coverage.market_coverage_count == 0


def test_future_market_observation_is_rejected() -> None:
    """A bar later than snapshot as_of cannot leak into Sector state."""

    future = _bars("US:AMD", slope=0.2)
    future[-1] = future[-1].model_copy(
        update={"trade_date": _AS_OF + timedelta(days=1)}
    )

    with pytest.raises(SectorStateInputError, match="future EOD"):
        SectorStateOperator().compute(
            universe=_universe("US:AMD", "US:NVDA"),
            bars_by_asset={"US:AMD": future},
            fundamentals_by_asset={},
        )


def test_future_fundamental_acceptance_is_rejected() -> None:
    """A filing accepted after snapshot as_of cannot enter an aggregate."""

    future = _fundamental("US:AMD", revenue_yoy=0.2, pe_ttm=20.0).model_copy(
        update={"accepted_at": datetime(2026, 8, 31, tzinfo=UTC)}
    )

    with pytest.raises(SectorStateInputError, match="future accepted filing"):
        SectorStateOperator().compute(
            universe=_universe("US:AMD", "US:NVDA"),
            bars_by_asset={},
            fundamentals_by_asset={"US:AMD": [future]},
        )


def test_naive_repository_timestamp_retains_utc_point_in_time_semantics() -> None:
    """DuckDB UTC-naive round trips remain valid but still honor the cutoff."""

    bars = _bars("US:AMD", slope=0.2)
    bars = [
        item.model_copy(update={"ingestion_ts": item.ingestion_ts.replace(tzinfo=None)})
        for item in bars
    ]
    snapshot = SectorStateOperator().compute(
        universe=_universe("US:AMD", "US:NVDA"),
        bars_by_asset={"US:AMD": bars},
        fundamentals_by_asset={},
    )

    assert snapshot.coverage.market_coverage_count == 1


def test_fmp_standardized_record_has_fundamental_priority() -> None:
    """A newer raw SEC row cannot replace canonical FMP Sector ratios."""

    universe, bars, fundamentals = _complete_inputs()
    for asset_id, records in fundamentals.items():
        records.append(
            records[0].model_copy(
                update={
                    "fiscal_period_end": date(2026, 7, 31),
                    "revenue_yoy": 9.0,
                    "pe_ttm": 999.0,
                    "source_id": "sec_edgar",
                }
            )
        )

    snapshot = SectorStateOperator().compute(
        universe=universe,
        bars_by_asset=bars,
        fundamentals_by_asset=fundamentals,
    )

    assert snapshot.fundamental_state.median_revenue_yoy.value == pytest.approx(0.2)
    assert snapshot.valuation_state.median_pe.value == pytest.approx(30.0)
