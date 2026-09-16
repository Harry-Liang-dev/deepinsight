"""Cross-module tests for Unified Temporal Contract v1."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.memory.contracts import (
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import (
    AnomalyDirection,
    ClaimIntent,
    EventSeverity,
    Market,
    MarketScope,
    MemoryLevel,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorId,
    SectorMembershipRole,
)
from src.models.identifiers import AssetId
from src.repositories.records import MemoryItemRecord
from src.schemas.common import SourceReference
from src.schemas.market_data import (
    EodBarRecord,
    FundamentalRecord,
    MacroObservationRecord,
    NewsEvidenceRecord,
)
from src.schemas.sector_research import SectorClaimCategory, SectorValidatedClaim
from src.schemas.sectors import SectorAnomalyEvent, SectorMembership
from src.schemas.temporal import (
    TemporalAccessMode,
    TemporalAccessReason,
    TemporalLeakageError,
    TemporalMetadata,
    is_usable_at,
    temporal_access_decision,
    utc_from_storage,
    validate_temporal_access,
)
from src.services.temporal import (
    sector_claim_temporal_metadata,
    temporal_metadata_for,
)

AS_OF = datetime(2026, 8, 30, 20, tzinfo=UTC)
ASSET = AssetId("US:AAPL")


def test_naive_datetime_is_rejected_but_storage_compatibility_is_explicit() -> None:
    """Public inputs reject naive time; DuckDB compatibility names UTC explicitly."""

    with pytest.raises(ValueError, match="timezone-aware"):
        TemporalMetadata(available_at=datetime(2026, 8, 30, 12))

    restored = utc_from_storage(datetime(2026, 8, 30, 12))
    assert restored == datetime(2026, 8, 30, 12, tzinfo=UTC)


@pytest.mark.parametrize("source_id", ["sec_edgar", "financial_modeling_prep"])
def test_future_filing_or_standardized_fundamental_is_rejected(
    source_id: str,
) -> None:
    """Fiscal period end never substitutes for accepted/ingested availability."""

    record = FundamentalRecord(
        asset_id=ASSET,
        fiscal_period_end=date(2026, 6, 30),
        report_type="quarterly",
        accepted_at=AS_OF + timedelta(hours=2),
        source_id=source_id,
        ingestion_ts=AS_OF + timedelta(hours=3),
    )

    decision = temporal_access_decision(temporal_metadata_for(record), AS_OF)
    assert decision.reason is TemporalAccessReason.FUTURE_AVAILABLE


def test_daily_bar_requires_completed_ingested_observation() -> None:
    """A daily price record is visible only after its attributable ingestion."""

    bar = EodBarRecord(
        asset_id=ASSET,
        trade_date=AS_OF.date(),
        close=100.0,
        source_id="alpaca_market_data",
        ingestion_ts=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(TemporalLeakageError):
        validate_temporal_access(temporal_metadata_for(bar), AS_OF)


def test_future_news_is_rejected_even_when_event_date_is_in_window() -> None:
    """Publication and system ingestion both participate in news visibility."""

    news = NewsEvidenceRecord(
        news_id="news-1",
        asset_id=ASSET,
        headline="Public headline",
        created_at=AS_OF - timedelta(minutes=1),
        source_url="https://example.test/news-1",
        provider="alpaca_market_data",
        original_source="Example",
        source_locator="alpaca:news:1",
        ingestion_ts=AS_OF + timedelta(minutes=1),
    )

    decision = temporal_access_decision(temporal_metadata_for(news), AS_OF)
    assert decision.reason is TemporalAccessReason.FUTURE_INGESTION


def test_live_acquisition_uses_availability_not_fetch_completion() -> None:
    """A live fetch after T may expose only source information available by T."""

    metadata = TemporalMetadata(
        available_at=AS_OF - timedelta(minutes=1),
        ingested_at=AS_OF + timedelta(minutes=1),
    )
    decision = temporal_access_decision(
        metadata, AS_OF, mode=TemporalAccessMode.LIVE_ACQUISITION
    )
    assert decision.usable is True
    assert decision.usable_at == AS_OF - timedelta(minutes=1)


def test_live_acquisition_rejects_future_source_information() -> None:
    """Live mode never admits information published after the frozen cutoff."""

    metadata = TemporalMetadata(
        available_at=AS_OF + timedelta(microseconds=1),
        ingested_at=AS_OF + timedelta(minutes=1),
    )
    decision = temporal_access_decision(
        metadata, AS_OF, mode=TemporalAccessMode.LIVE_ACQUISITION
    )
    assert decision.reason is TemporalAccessReason.FUTURE_AVAILABLE


def test_fred_vintage_not_observation_date_controls_visibility() -> None:
    """An old observation with a future ALFRED vintage remains unavailable."""

    observation = MacroObservationRecord(
        series_key="CPIAUCSL",
        region_code=MarketScope.US,
        observation_date=date(2026, 6, 1),
        indicator_name="CPI",
        value=100.0,
        realtime_start=date(2026, 8, 31),
        source_id="fred",
        ingestion_ts=AS_OF - timedelta(hours=1),
    )

    assert not is_usable_at(temporal_metadata_for(observation), AS_OF)


def test_membership_uses_half_open_effective_interval() -> None:
    """Historical membership is valid on start and invalid on valid_to."""

    membership = SectorMembership(
        asset_id=ASSET,
        sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
        chain_ids=("APPLE_CHAIN",),
        role=SectorMembershipRole.CORE,
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 9, 1),
        weight=1.0,
        confidence=1.0,
        source="fixture",
        version="membership_v1",
    )

    assert is_usable_at(temporal_metadata_for(membership), AS_OF)
    assert not is_usable_at(
        temporal_metadata_for(membership),
        datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_future_sector_radar_event_is_rejected_by_shared_rule() -> None:
    """A valid later Radar snapshot cannot leak into an earlier research run."""

    later = AS_OF + timedelta(hours=1)
    event = SectorAnomalyEvent(
        event_id="sector_anomaly_1234567890abcdef12345678",
        event_type=SectorAnomalyType.NEWS_EVENT,
        sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
        source_asset_ids=(ASSET,),
        affected_asset_ids=(ASSET,),
        direction=AnomalyDirection.UNKNOWN,
        severity=EventSeverity.HIGH,
        confidence=0.8,
        event_time=later,
        published_at=later,
        available_at=later,
        ingested_at=later,
        as_of=later,
        source_evidence_ids=("news:1",),
        summary="A later attributable event.",
        status=SectorAnomalyStatus.DETECTED,
    )

    with pytest.raises(TemporalLeakageError):
        validate_temporal_access(temporal_metadata_for(event), AS_OF)


def test_sector_claim_inherits_containing_research_cutoff() -> None:
    """Sector Claim visibility comes from its producing research output."""

    claim = SectorValidatedClaim(
        claim_path="claims[0]",
        category=SectorClaimCategory.TREND,
        claim_id="sector:S03:claim:0",
        claim_text="Sector trend is mixed.",
        evidence_ids=("sector-state:trend",),
        source_references=(SourceReference(document_id="sector-state"),),
        claim_intent=ClaimIntent.ANALYTICAL_INFERENCE,
        confidence=0.7,
    )

    metadata = sector_claim_temporal_metadata(
        claim,
        research_as_of=AS_OF + timedelta(minutes=1),
    )
    assert not is_usable_at(metadata, AS_OF)


def test_future_created_memory_cannot_backfill_an_old_effective_time() -> None:
    """Memory creation/availability prevents retroactive replay leakage."""

    record = MemoryItemRecord(
        memory_id="memory-1",
        memory_level=MemoryLevel.L2,
        namespace_key="US:AAPL",
        asset_id=ASSET,
        effective_ts=AS_OF - timedelta(days=1),
        memory_type="issuer_event",
        summary_text="Historical-looking item created later.",
        source_ref=SourceReference(document_id="doc-1"),
        embedding_model="fake",
        embedding_dim=3,
        faiss_namespace="memory-L2-v1",
        faiss_vector_id=1,
        created_by="fixture",
        created_at=AS_OF + timedelta(minutes=1),
    )

    decision = temporal_access_decision(temporal_metadata_for(record), AS_OF)
    assert decision.reason is TemporalAccessReason.FUTURE_AVAILABLE


def test_research_context_rejects_future_memory_availability() -> None:
    """Context assembly applies the same rule after retrieval projection."""

    future = ResearchContextMemory(
        memory_id="memory-1",
        section=ResearchContextSection.ASSET_EVENTS,
        memory_level=MemoryLevel.L2,
        namespace_key="US:AAPL",
        asset_id=ASSET,
        market=MarketScope.US,
        memory_type="issuer_event",
        summary_text="Unavailable at cutoff.",
        effective_ts=AS_OF - timedelta(days=1),
        available_at=AS_OF + timedelta(minutes=1),
        importance_score=0.8,
        retrieval_score=0.9,
        retrieval_reason="fixture",
        source=SourceReference(document_id="doc-1"),
        created_by="fixture",
    )

    with pytest.raises(ValidationError, match="future_available"):
        _context_bundle([future])


def _context_bundle(asset_events: list[ResearchContextMemory]) -> ResearchContextBundle:
    return ResearchContextBundle(
        current_snapshot=[],
        macro_events=[],
        asset_events=asset_events,
        prior_research=[],
        prior_risk=[],
        historical_analogs=[],
        regime_context=[],
        retrieval_metadata=RetrievalMetadata(
            query_id="query-1",
            query_text="AAPL",
            as_of=AS_OF,
            market=Market.US,
            asset_id=ASSET,
            namespace_keys=["US:AAPL"],
            requested_levels=list(MemoryLevel),
            min_importance_score=0.0,
            top_k_per_section=4,
            snapshot_id="snapshot-1",
            candidate_count=len(asset_events),
            eligible_count=len(asset_events),
            result_count=len(asset_events),
            excluded_future_count=0,
            excluded_namespace_count=0,
            excluded_asset_count=0,
            excluded_market_count=0,
            excluded_importance_count=0,
            excluded_expired_count=0,
            excluded_current_report_count=0,
            section_counts={
                section: (
                    len(asset_events)
                    if section is ResearchContextSection.ASSET_EVENTS
                    else 0
                )
                for section in ResearchContextSection
            },
            status=RetrievalStatus.PARTIAL,
            no_relevant_memory=False,
        ),
        missing_context=[],
    )
