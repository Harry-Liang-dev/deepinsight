"""Unit coverage for explicit market-data Bundle quality states."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.models.enums import Market
from src.models.identifiers import AssetId
from src.orchestration.research_workflow import _project_bundle_features
from src.repositories import DuckDBDatabase, InstrumentRepository, MarketDataRepository
from src.schemas import (
    DataAvailabilityStatus,
    DataCapability,
    DataQualityStatus,
    EodBarRecord,
    FreshnessStatus,
    FundamentalRecord,
    InstrumentRecord,
    MissingDataReason,
    ResearchDataBundleRequest,
)
from src.services import ResearchDataBundleService

ASSET_ID = AssetId("US:AAPL")
INGESTED_AT = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)


def _builder(tmp_path: Path) -> tuple[ResearchDataBundleService, MarketDataRepository]:
    database = DuckDBDatabase(tmp_path / "research-data-bundle.duckdb")
    database.bootstrap()
    instruments = InstrumentRepository(database)
    instruments.upsert(
        InstrumentRecord(
            asset_id=ASSET_ID,
            market=Market.US,
            ticker="AAPL",
            exchange_code="NASDAQ",
            currency="USD",
            source_primary="sec_edgar",
        )
    )
    market_data = MarketDataRepository(database)
    return (
        ResearchDataBundleService(
            instruments=instruments,
            market_data=market_data,
        ),
        market_data,
    )


def _request(
    *,
    as_of: datetime,
    window_start: date,
    window_end: date,
) -> ResearchDataBundleRequest:
    return ResearchDataBundleRequest(
        asset_id=ASSET_ID,
        as_of=as_of,
        window_start=window_start,
        window_end=window_end,
        dataset_version="technical_quality_fixture_v1",
        requested_capabilities=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.OHLCV,
            DataCapability.TECHNICAL_FEATURES,
        ),
    )


def _persist_complete_bars(
    repository: MarketDataRepository,
    *,
    end_date: date,
    count: int,
) -> list[date]:
    dates = [end_date - timedelta(days=count - index - 1) for index in range(count)]
    for index, trade_date in enumerate(dates):
        close = 100.0 + index
        repository.upsert_eod_bar(
            EodBarRecord(
                asset_id=ASSET_ID,
                trade_date=trade_date,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                adj_close=close,
                volume=1_000_000 + index,
                turnover=close * (1_000_000 + index),
                vwap=close + 0.1,
                feed_identity="iex",
                coverage_scope=(
                    "IEX single-exchange US equity feed; not consolidated SIP"
                ),
                source_id="alpaca_market_data",
                ingestion_ts=INGESTED_AT,
            )
        )
    return dates


def test_missing_bars_are_explicit_for_every_market_field(tmp_path: Path) -> None:
    """No observations produce MISSING rather than zero or neutral values."""

    builder, _ = _builder(tmp_path)
    request = _request(
        as_of=datetime(2026, 8, 9, 23, 59, tzinfo=UTC),
        window_start=date(2026, 5, 1),
        window_end=date(2026, 8, 8),
    )

    bundle = builder.build(request)

    assert bundle.ohlcv.status is DataAvailabilityStatus.MISSING
    assert bundle.ohlcv.quality.status is DataQualityStatus.UNKNOWN
    assert bundle.ohlcv.available_field_count == 0
    assert len(bundle.ohlcv.missing_data) == 10
    assert bundle.technical_features.status is DataAvailabilityStatus.MISSING
    assert len(bundle.technical_features.missing_data) == 20
    assert all(
        item.reason_code is MissingDataReason.INSUFFICIENT_HISTORY
        for item in bundle.technical_features.missing_data
    )


def test_short_history_is_partial_and_never_invents_long_window_features(
    tmp_path: Path,
) -> None:
    """Twenty closes expose SMA20 while longer-window values stay missing."""

    builder, market_data = _builder(tmp_path)
    dates = _persist_complete_bars(
        market_data,
        end_date=date(2026, 8, 7),
        count=20,
    )
    request = _request(
        as_of=datetime(2026, 8, 9, 23, 59, tzinfo=UTC),
        window_start=dates[0],
        window_end=dates[-1],
    )

    bundle = builder.build(request)

    assert bundle.ohlcv.status is DataAvailabilityStatus.PRESENT
    assert bundle.ohlcv.quality.completeness_ratio == 1.0
    assert bundle.technical_features.status is DataAvailabilityStatus.PARTIAL
    assert {item.field_path for item in bundle.technical_features.items} == {
        "technical_features.close",
        "technical_features.return_1d",
        "technical_features.return_5d",
        "technical_features.sma_20",
        "technical_features.distance_to_sma20",
        "technical_features.rsi_14",
        "technical_features.atr_14",
        "technical_features.volume_ratio_20d",
    }
    assert {item.field_path for item in bundle.technical_features.missing_data} == {
        "technical_features.return_20d",
        "technical_features.return_60d",
        "technical_features.sma_60",
        "technical_features.distance_to_sma60",
        "technical_features.realized_vol_20d",
        "technical_features.realized_vol_60d",
        "technical_features.max_drawdown_60d",
        "technical_features.macd",
        "technical_features.relative_strength_vs_spy",
        "technical_features.relative_strength_vs_qqq",
        "technical_features.relative_strength_vs_xlk",
        "technical_features.trend_label",
    }
    assert all(
        item.reason_code is MissingDataReason.INSUFFICIENT_HISTORY
        for item in bundle.technical_features.missing_data
    )


def test_available_market_data_can_be_classified_stale(tmp_path: Path) -> None:
    """Old but valid bars remain attributable and carry a STALE state."""

    builder, market_data = _builder(tmp_path)
    dates = _persist_complete_bars(
        market_data,
        end_date=date(2026, 7, 31),
        count=60,
    )
    request = _request(
        as_of=datetime(2026, 8, 10, 23, 59, tzinfo=UTC),
        window_start=dates[0],
        window_end=dates[-1],
    )

    bundle = builder.build(request)

    assert bundle.ohlcv.status is DataAvailabilityStatus.STALE
    assert bundle.ohlcv.freshness.status is FreshnessStatus.STALE
    assert bundle.ohlcv.freshness.age_days == 10
    assert bundle.ohlcv.quality.status is DataQualityStatus.WARNING
    assert bundle.technical_features.status is DataAvailabilityStatus.STALE
    assert bundle.technical_features.available_field_count == 15
    assert all(item.value is not None for item in bundle.technical_features.items)


def test_fmp_is_primary_and_conflicting_sec_metric_remains_audit_visible(
    tmp_path: Path,
) -> None:
    """Standard ratios prefer FMP without averaging away an SEC disagreement."""

    builder, market_data = _builder(tmp_path)
    market_data.upsert_fundamental(
        FundamentalRecord(
            asset_id=ASSET_ID,
            fiscal_period_end=date(2026, 6, 27),
            report_type="10-Q",
            revenue=100.0,
            gross_profit=20.0,
            accepted_at=datetime(2026, 7, 31, 6, tzinfo=UTC),
            source_id="sec_edgar",
            ingestion_ts=INGESTED_AT,
        )
    )
    market_data.upsert_fundamental(
        FundamentalRecord(
            asset_id=ASSET_ID,
            fiscal_period_end=date(2026, 6, 27),
            report_type="TTM_STANDARDIZED",
            revenue_yoy=-0.015,
            net_income_yoy=0.007,
            gross_margin=0.48,
            eps_ttm=8.77,
            market_cap=4_483_462_292_560.0,
            pe_ttm=34.84,
            source_locator="fmp:stable:standardized-metrics:AAPL",
            quality="provider_standardized",
            accepted_at=datetime(2026, 7, 31, 6, 1, tzinfo=UTC),
            source_id="financial_modeling_prep",
            ingestion_ts=INGESTED_AT,
        )
    )
    request = ResearchDataBundleRequest(
        asset_id=ASSET_ID,
        as_of=datetime(2026, 8, 9, 23, 59, tzinfo=UTC),
        window_start=date(2026, 5, 1),
        window_end=date(2026, 8, 8),
        dataset_version="fmp-priority-fixture-v1",
        requested_capabilities=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.FUNDAMENTALS,
            DataCapability.VALUATION,
        ),
    )

    bundle = builder.build(request)

    margin = next(
        item
        for item in bundle.fundamentals.items
        if item.field_path == "fundamentals.gross_margin"
    )
    assert margin.value == 0.48
    assert margin.source.provider_name == "financial_modeling_prep"
    assert margin.quality is DataQualityStatus.CONFLICT
    assert margin.cross_check is not None
    assert margin.cross_check.secondary_provider == "sec_edgar"
    assert margin.cross_check.secondary_value == 0.2
    assert all(
        item.field_path
        not in {
            "fundamentals.revenue_yoy",
            "fundamentals.net_income_yoy",
            "fundamentals.eps_ttm",
            "fundamentals.market_cap",
            "fundamentals.pe_ttm",
        }
        for item in bundle.fundamentals.missing_data
    )
    valuation = {item.field_path: item for item in bundle.valuation.items}
    assert valuation["valuation.eps_ttm"].value == 8.77
    assert valuation["valuation.market_cap"].value == 4_483_462_292_560.0
    assert valuation["valuation.pe_ttm"].value == 34.84
    assert valuation["valuation.pe_ttm"].evidence_id != margin.evidence_id

    projected = _project_bundle_features(
        bundle,
        {
            "gross_margin": None,
            "pe_ttm": None,
            "fundamental_missing_data": ["gross_margin", "pe_ttm"],
            "technical_missing_data": ["return_60d"],
        },
    )
    assert projected["gross_margin"] == 0.48
    assert projected["pe_ttm"] == 34.84
    projected_missing = projected["fundamental_missing_data"]
    assert isinstance(projected_missing, list)
    assert "gross_margin" not in projected_missing
    assert "pe_ttm" not in projected_missing
