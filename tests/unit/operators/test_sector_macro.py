"""Deterministic tests for SectorCycleState and MacroSensitivity."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.models.enums import (
    MacroCycleDirection,
    MarketScope,
    SectorCapabilityStatus,
    SectorId,
)
from src.models.identifiers import AssetId
from src.operators import (
    SectorMacroInputError,
    SectorMacroOperator,
    SectorStateOperator,
)
from src.repositories import DuckDBDatabase, SectorOntologyRepository
from src.schemas.market_data import EodBarRecord, MacroObservationRecord
from src.schemas.research_data import DataQualityStatus
from src.schemas.sectors import (
    SectorResearchSnapshot,
    SectorUniverseCoverage,
    SectorUniverseSnapshot,
)

_AS_OF = date(2026, 8, 30)
_SERIES = (
    "FEDFUNDS",
    "DGS2",
    "DGS10",
    "T10Y2Y",
    "CPIAUCSL",
    "PCEPILFE",
    "UNRATE",
    "PAYEMS",
    "GDP",
    "INDPRO",
    "VIXCLS",
    "BAMLH0A0HYM2",
)


def _universe() -> SectorUniverseSnapshot:
    return SectorUniverseSnapshot(
        snapshot_id="sector_universe_0123456789abcdef01234567",
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF,
        asset_ids=(AssetId("US:AMD"), AssetId("US:NVDA")),
        benchmark_ids=(AssetId("US:SOXX"),),
        membership_version="sector_universe_membership_v1",
        source="test",
        coverage=SectorUniverseCoverage(
            membership_count=2,
            classified_asset_count=2,
            benchmark_count=1,
            classification_ratio=1.0,
        ),
        quality=DataQualityStatus.PASS,
    )


def _bars(asset_id: str, count: int = 1_300) -> list[EodBarRecord]:
    start = _AS_OF - timedelta(days=count)
    return [
        EodBarRecord(
            asset_id=AssetId(asset_id),
            trade_date=start + timedelta(days=index),
            close=100.0 + index * 0.03 + math.sin(index / 13.0) * 4.0,
            adj_close=100.0 + index * 0.03 + math.sin(index / 13.0) * 4.0,
            source_id="alpaca_market_data",
            ingestion_ts=datetime(2026, 8, 30, 12, tzinfo=UTC),
        )
        for index in range(count)
    ]


def _macro_records(months: int = 60) -> list[MacroObservationRecord]:
    records: list[MacroObservationRecord] = []
    start_year, start_month = 2021, 9
    for series_index, series_id in enumerate(_SERIES):
        step = 3 if series_id == "GDP" else 1
        for index in range(0, months, step):
            month_index = start_month - 1 + index
            year = start_year + month_index // 12
            month = month_index % 12 + 1
            observation_date = date(year, month, 1)
            if observation_date > _AS_OF:
                continue
            value = 100.0 + index * 0.2 + math.sin(index / 3.0 + series_index)
            records.append(
                MacroObservationRecord(
                    series_key=series_id,
                    region_code=MarketScope.US,
                    observation_date=observation_date,
                    indicator_name=series_id,
                    value=value,
                    unit="index",
                    frequency="Quarterly" if series_id == "GDP" else "Monthly",
                    realtime_start=observation_date,
                    realtime_end=_AS_OF,
                    source_locator=f"fred:{series_id}:{observation_date}",
                    source_id="fred",
                    ingestion_ts=datetime(2026, 8, 30, 12, tzinfo=UTC),
                )
            )
    return records


def _inputs() -> tuple[
    SectorUniverseSnapshot,
    SectorResearchSnapshot,
    list[EodBarRecord],
    list[MacroObservationRecord],
]:
    universe = _universe()
    constituent = {
        "US:AMD": _bars("US:AMD", 100),
        "US:NVDA": _bars("US:NVDA", 100),
        "US:SOXX": _bars("US:SOXX", 100),
        "US:SPY": _bars("US:SPY", 100),
    }
    sector_state = SectorStateOperator().compute(
        universe=universe,
        bars_by_asset=constituent,
        fundamentals_by_asset={},
    )
    return universe, sector_state, _bars("US:SOXX"), _macro_records()


def test_sector_macro_output_is_deterministic_and_order_independent() -> None:
    """Historical input order cannot change cycle or sensitivity results."""

    universe, sector_state, bars, macro = _inputs()
    operator = SectorMacroOperator()

    first = operator.compute(
        universe=universe,
        sector_state=sector_state,
        benchmark_bars=bars,
        macro_observations=macro,
    )
    second = operator.compute(
        universe=universe,
        sector_state=sector_state,
        benchmark_bars=list(reversed(bars)),
        macro_observations=list(reversed(macro)),
    )

    assert first == second
    assert first.cycle_state.rates.coverage_count == 4
    assert first.cycle_state.inflation.coverage_count == 2
    assert first.cycle_state.rates.direction is not MacroCycleDirection.UNKNOWN
    estimates = {item.series_id: item for item in first.macro_sensitivity.estimates}
    assert estimates["FEDFUNDS"].observation_count >= 24
    assert estimates["FEDFUNDS"].status is SectorCapabilityStatus.AVAILABLE
    assert estimates["GDP"].status is SectorCapabilityStatus.PARTIAL


def test_short_history_is_partial_not_extrapolated() -> None:
    """Sensitivity remains PARTIAL below the 24-observation gate."""

    universe, sector_state, bars, _ = _inputs()
    recent_macro = [
        item for item in _macro_records() if item.observation_date >= date(2025, 8, 1)
    ]
    snapshot = SectorMacroOperator().compute(
        universe=universe,
        sector_state=sector_state,
        benchmark_bars=bars[-400:],
        macro_observations=recent_macro,
    )

    assert snapshot.macro_sensitivity.status is SectorCapabilityStatus.PARTIAL
    assert all(item.beta is None for item in snapshot.macro_sensitivity.estimates)
    assert all(
        item.observation_count < 24 for item in snapshot.macro_sensitivity.estimates
    )


def test_future_macro_vintage_is_rejected() -> None:
    """A macro vintage later than as_of cannot enter the Sector state."""

    universe, sector_state, bars, macro = _inputs()
    macro[0] = macro[0].model_copy(
        update={"realtime_start": _AS_OF + timedelta(days=1)}
    )

    with pytest.raises(SectorMacroInputError, match="future macro vintage"):
        SectorMacroOperator().compute(
            universe=universe,
            sector_state=sector_state,
            benchmark_bars=bars,
            macro_observations=macro,
        )


def test_sector_macro_snapshot_repository_round_trip(tmp_path: Path) -> None:
    """Cycle and sensitivity outputs retain their typed immutable structure."""

    universe, sector_state, bars, macro = _inputs()
    snapshot = SectorMacroOperator().compute(
        universe=universe,
        sector_state=sector_state,
        benchmark_bars=bars,
        macro_observations=macro,
    )
    database = DuckDBDatabase(tmp_path / "sector-macro.duckdb")
    database.bootstrap()
    repository = SectorOntologyRepository(database)

    repository.save_macro_snapshot(snapshot)

    assert repository.get_macro_snapshot(snapshot.snapshot_id) == snapshot
