"""Deterministic rules and point-in-time tests for Sector Anomaly Radar."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.models.enums import (
    AnomalyDirection,
    EventSeverity,
    MacroCycleDirection,
    Market,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorCapabilityStatus,
    SectorId,
)
from src.models.identifiers import AssetId
from src.operators import SectorAnomalyRadar, SectorRadarInputError
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    NewsEvidenceRecord,
)
from src.schemas.sectors import (
    CoveredSectorMetric,
    MacroCycleDimensionState,
    MacroSensitivity,
    MacroSensitivityEstimate,
    MacroSeriesCycleSignal,
    SectorBreadthState,
    SectorCycleState,
    SectorFundamentalState,
    SectorMacroSnapshot,
    SectorMarketState,
    SectorMembership,
    SectorResearchCoverage,
    SectorResearchSnapshot,
    SectorValuationState,
)
from src.services import build_sector_ontology_seed_v1

_AS_OF_DATE = date(2026, 8, 30)
_AS_OF = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)


def _metric(value: float | None, count: int = 3) -> CoveredSectorMetric:
    return CoveredSectorMetric(
        value=value,
        coverage_count=0 if value is None else count,
        universe_count=3,
        status=(
            SectorCapabilityStatus.MISSING
            if value is None
            else SectorCapabilityStatus.AVAILABLE
        ),
    )


def _sector_state(*, breadth_divergence: bool = False) -> SectorResearchSnapshot:
    market = SectorMarketState(
        **{name: _metric(0.02) for name in SectorMarketState.model_fields}
    )
    breadth_values = {name: _metric(0.5) for name in SectorBreadthState.model_fields}
    if breadth_divergence:
        breadth_values["pct_above_sma20"] = _metric(0.9)
        breadth_values["pct_above_sma60"] = _metric(0.2)
    fundamentals = SectorFundamentalState(
        **{name: _metric(0.1) for name in SectorFundamentalState.model_fields}
    )
    valuation = SectorValuationState(median_pe=_metric(25.0), median_pb=_metric(6.0))
    return SectorResearchSnapshot(
        snapshot_id="sector_research_0123456789abcdef01234567",
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF_DATE,
        market_state=market,
        breadth_state=SectorBreadthState(**breadth_values),
        fundamental_state=fundamentals,
        valuation_state=valuation,
        coverage=SectorResearchCoverage(
            universe_count=3,
            market_coverage_count=3,
            fundamental_coverage_count=3,
            benchmark_coverage_count=1,
        ),
        source_ids=("alpaca_market_data", "fmp"),
        feature_version="sector_state_features_v1",
        status=SectorCapabilityStatus.AVAILABLE,
    )


def _macro_state(*, shock: bool = False) -> SectorMacroSnapshot:
    signal = MacroSeriesCycleSignal(
        series_id="FEDFUNDS",
        transformation="monthly_level_change",
        latest_observation_date=date(2026, 8, 1),
        latest_value=4.0,
        change_3m=1.0 if shock else 0.1,
        change_12m=1.2,
        direction=MacroCycleDirection.RISING,
        source_id="fred",
    )
    dimension = MacroCycleDimensionState(
        direction=MacroCycleDirection.RISING,
        signals=(signal,),
        coverage_count=1,
        expected_count=1,
        status=SectorCapabilityStatus.AVAILABLE,
    )
    cycle = SectorCycleState(
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF_DATE,
        rates=dimension,
        inflation=dimension,
        labor=dimension,
        growth=dimension,
        financial_stress=dimension,
        sector_momentum=_metric(0.02),
        source_ids=("fred",),
        feature_version="sector_macro_features_v1",
        status=SectorCapabilityStatus.AVAILABLE,
    )
    sensitivity = MacroSensitivity(
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF_DATE,
        benchmark_id=AssetId("US:SOXX"),
        estimates=(
            MacroSensitivityEstimate(
                series_id="FEDFUNDS",
                transformation="monthly_level_change",
                beta=0.5,
                correlation=0.5,
                observation_count=36,
                source_id="fred",
                status=SectorCapabilityStatus.AVAILABLE,
            ),
        ),
        source_ids=("fred",),
        feature_version="sector_macro_features_v1",
        status=SectorCapabilityStatus.AVAILABLE,
    )
    return SectorMacroSnapshot(
        snapshot_id="sector_macro_0123456789abcdef01234567",
        sector_id=SectorId.SEMICONDUCTORS_AI_COMPUTE,
        as_of=_AS_OF_DATE,
        cycle_state=cycle,
        macro_sensitivity=sensitivity,
        source_sector_snapshot_id="sector_research_0123456789abcdef01234567",
        feature_version="sector_macro_features_v1",
        status=SectorCapabilityStatus.AVAILABLE,
    )


def _bars() -> list[EodBarRecord]:
    asset = AssetId("US:NVDA")
    start = _AS_OF_DATE - timedelta(days=70)
    bars = [
        EodBarRecord(
            asset_id=asset,
            trade_date=start + timedelta(days=index),
            close=100.0 + index * 0.1,
            adj_close=100.0 + index * 0.1,
            volume=1_000_000.0,
            source_id="alpaca_market_data",
            ingestion_ts=_AS_OF - timedelta(hours=1),
        )
        for index in range(70)
    ]
    bars[-1] = bars[-1].model_copy(
        update={"close": 130.0, "adj_close": 130.0, "volume": 4_000_000.0}
    )
    return bars


def _memberships() -> tuple[SectorMembership, ...]:
    return tuple(
        item
        for item in build_sector_ontology_seed_v1().memberships
        if item.sector_id is SectorId.SEMICONDUCTORS_AI_COMPUTE
    )


def test_price_breadth_and_macro_anomalies_are_deterministic() -> None:
    """Price spike, breadth divergence, and macro shock remain reproducible."""

    operator = SectorAnomalyRadar()
    first = operator.detect(
        sector_state=_sector_state(breadth_divergence=True),
        macro_state=_macro_state(shock=True),
        bars_by_asset={"US:NVDA": _bars()},
        memberships=_memberships(),
    )
    second = operator.detect(
        sector_state=_sector_state(breadth_divergence=True),
        macro_state=_macro_state(shock=True),
        bars_by_asset={"US:NVDA": _bars()},
        memberships=_memberships(),
    )

    assert first == second
    types = {item.event_type for item in first}
    assert SectorAnomalyType.PRICE_VOLUME in types
    assert SectorAnomalyType.BREADTH in types
    assert SectorAnomalyType.MACRO_SHOCK in types
    assert all(item.available_at <= item.as_of for item in first)


def test_earnings_beat_and_graph_propagation_are_separate_events() -> None:
    """Structured surprise creates an event; graph propagation stays a candidate."""

    seed = build_sector_ontology_seed_v1()
    earnings = CorporateEventRecord(
        event_id="nvda-earnings",
        asset_id=AssetId("US:NVDA"),
        market=Market.US,
        event_date=_AS_OF - timedelta(hours=2),
        event_type="earnings",
        severity=EventSeverity.HIGH,
        title="Quarterly earnings",
        source_document_id="earnings:nvda:2026q2",
        source_id="sec_edgar",
        tags_json={"actual_eps": 1.2, "expected_eps": 1.0},
    )
    events = SectorAnomalyRadar().detect(
        sector_state=_sector_state(),
        macro_state=_macro_state(),
        bars_by_asset={},
        corporate_events=(earnings,),
        memberships=_memberships(),
        nodes=seed.nodes,
        edges=seed.edges,
    )

    earnings_event = next(
        item for item in events if item.event_type is SectorAnomalyType.EARNINGS
    )
    propagation = next(
        item
        for item in events
        if item.event_type is SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION
    )
    assert earnings_event.direction is AnomalyDirection.POSITIVE
    assert propagation.status is SectorAnomalyStatus.PROPAGATION_CANDIDATE
    assert AssetId("US:AMD") in propagation.affected_asset_ids
    assert propagation.direction is AnomalyDirection.UNKNOWN


def test_future_price_is_rejected() -> None:
    """Radar cannot detect an event from a future observation."""

    bars = _bars()
    bars[-1] = bars[-1].model_copy(
        update={"trade_date": _AS_OF_DATE + timedelta(days=1)}
    )
    with pytest.raises(SectorRadarInputError, match="future price"):
        SectorAnomalyRadar().detect(
            sector_state=_sector_state(),
            macro_state=_macro_state(),
            bars_by_asset={"US:NVDA": bars},
            memberships=_memberships(),
        )


def test_material_news_candidate_retains_source_identity() -> None:
    """Material news is detected without inventing impact direction."""

    news = NewsEvidenceRecord(
        news_id="alpaca-news-1",
        asset_id=AssetId("US:NVDA"),
        headline="Company issues earnings guidance update",
        created_at=_AS_OF - timedelta(hours=2),
        source_url="https://publisher.example/news-1",
        provider="alpaca_market_data",
        original_source="Example Publisher",
        source_locator="alpaca:news:1",
        ingestion_ts=_AS_OF - timedelta(hours=1),
    )

    events = SectorAnomalyRadar().detect(
        sector_state=_sector_state(),
        macro_state=_macro_state(),
        bars_by_asset={},
        news=(news,),
        memberships=_memberships(),
    )
    event = next(
        item for item in events if item.event_type is SectorAnomalyType.NEWS_EVENT
    )

    assert event.direction is AnomalyDirection.UNKNOWN
    assert event.source_evidence_ids == ("news:alpaca-news-1",)
