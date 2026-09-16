"""Neutral compatibility mappings into the unified Temporal Contract v1.

This module intentionally lives outside the eager ``src.services`` package
exports so deterministic operators can reuse the mapping without creating an
Operators -> Services -> ResearchDataBundle -> Operators import cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.repositories.records import MemoryItemRecord
from src.schemas.documents import TextDocumentRecord
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    FundamentalRecord,
    MacroObservationRecord,
    NewsEvidenceRecord,
    SentimentEvidenceRecord,
    SentimentSnapshotRecord,
)
from src.schemas.research_data import ResearchEvidenceItem
from src.schemas.sectors import SectorAnomalyEvent, SectorMembership
from src.schemas.temporal import (
    TemporalMetadata,
    TemporalSourceKind,
    utc_from_storage,
)

if TYPE_CHECKING:
    from src.schemas.sector_research import SectorValidatedClaim


class TemporalMappingError(ValueError):
    """Raised when a legacy record cannot be mapped without guessing time."""


def temporal_metadata_for(record: object) -> TemporalMetadata:
    """Map one supported existing record into Temporal Contract v1."""

    if isinstance(record, EodBarRecord):
        ingested_at = utc_from_storage(record.ingestion_ts)
        if ingested_at.date() < record.trade_date:
            raise TemporalMappingError("daily bar was ingested before its trade date")
        return TemporalMetadata(
            source_kind=TemporalSourceKind.ALPACA_DAILY_BAR,
            period_start=record.trade_date,
            period_end=record.trade_date,
            available_at=datetime.combine(
                record.trade_date,
                time(16),
                tzinfo=ZoneInfo("America/New_York"),
            ).astimezone(UTC),
            ingested_at=ingested_at,
        )
    if isinstance(record, FundamentalRecord):
        ingested_at = utc_from_storage(record.ingestion_ts)
        published_at = _filing_publication(record)
        source_kind = (
            TemporalSourceKind.FMP_FUNDAMENTAL
            if record.source_id == "financial_modeling_prep"
            else TemporalSourceKind.SEC_FILING
        )
        return TemporalMetadata(
            source_kind=source_kind,
            period_end=record.fiscal_period_end,
            published_at=published_at,
            available_at=published_at or ingested_at,
            ingested_at=ingested_at,
        )
    if isinstance(record, MacroObservationRecord):
        ingested_at = utc_from_storage(record.ingestion_ts)
        vintage_at = (
            None
            if record.realtime_start is None
            else datetime.combine(record.realtime_start, time.min, tzinfo=UTC)
        )
        return TemporalMetadata(
            source_kind=TemporalSourceKind.FRED_VINTAGE,
            period_end=record.observation_date,
            published_at=vintage_at,
            available_at=vintage_at or ingested_at,
            ingested_at=ingested_at,
        )
    if isinstance(record, NewsEvidenceRecord):
        published_at = utc_from_storage(record.created_at)
        ingested_at = utc_from_storage(record.ingestion_ts)
        return TemporalMetadata(
            source_kind=TemporalSourceKind.ALPACA_NEWS,
            event_time=published_at,
            published_at=published_at,
            available_at=published_at,
            ingested_at=ingested_at,
        )
    if isinstance(record, CorporateEventRecord):
        event_time = utc_from_storage(record.event_date)
        return TemporalMetadata(
            event_time=event_time,
            available_at=event_time,
        )
    if isinstance(record, SentimentSnapshotRecord):
        event_time = utc_from_storage(record.source_timestamp)
        ingested_at = utc_from_storage(record.ingestion_ts)
        return TemporalMetadata(
            event_time=event_time,
            published_at=event_time,
            available_at=event_time,
            ingested_at=ingested_at,
            as_of=utc_from_storage(record.as_of),
        )
    if isinstance(record, SentimentEvidenceRecord):
        published_at = utc_from_storage(record.created_at)
        ingested_at = utc_from_storage(record.ingestion_ts)
        return TemporalMetadata(
            event_time=published_at,
            published_at=published_at,
            available_at=published_at,
            ingested_at=ingested_at,
        )
    if isinstance(record, TextDocumentRecord):
        published_at = (
            None if record.publish_ts is None else utc_from_storage(record.publish_ts)
        )
        ingested_at = utc_from_storage(record.created_at)
        return TemporalMetadata(
            source_kind=(
                TemporalSourceKind.SEC_FILING
                if record.source_id == "sec_edgar"
                else TemporalSourceKind.GENERIC
            ),
            published_at=published_at,
            available_at=published_at or ingested_at,
            ingested_at=ingested_at,
        )
    if isinstance(record, ResearchEvidenceItem):
        return TemporalMetadata(
            source_kind=TemporalSourceKind.RESEARCH_EVIDENCE,
            event_time=record.effective_at,
            available_at=record.observed_at,
        )
    if isinstance(record, SectorMembership):
        return TemporalMetadata(
            source_kind=TemporalSourceKind.SECTOR_MEMBERSHIP,
            effective_from=record.valid_from,
            effective_to=record.valid_to,
        )
    if isinstance(record, SectorAnomalyEvent):
        return TemporalMetadata(
            source_kind=TemporalSourceKind.SECTOR_ANOMALY,
            event_time=record.event_time,
            published_at=record.published_at,
            available_at=record.available_at,
            ingested_at=record.ingested_at,
            as_of=record.as_of,
        )
    if type(record).__module__ == "src.schemas.sector_research":
        from src.schemas.sector_research import SectorResearchOutput

        if isinstance(record, SectorResearchOutput):
            return TemporalMetadata(
                source_kind=TemporalSourceKind.SECTOR_RESEARCH_CLAIM,
                available_at=record.research_as_of,
                as_of=record.research_as_of,
            )
    if isinstance(record, MemoryItemRecord):
        effective_at = utc_from_storage(record.effective_ts)
        created_at = (
            effective_at
            if record.created_at is None
            else utc_from_storage(record.created_at)
        )
        structured = None if record.metadata is None else record.metadata.temporal
        structured_available = None if structured is None else structured.available_at
        structured_ingested = None if structured is None else structured.ingested_at
        return TemporalMetadata(
            source_kind=TemporalSourceKind.MEMORY,
            event_time=(
                effective_at
                if structured is None or structured.event_time is None
                else structured.event_time
            ),
            period_start=None if structured is None else structured.period_start,
            period_end=None if structured is None else structured.period_end,
            published_at=None if structured is None else structured.published_at,
            available_at=max(
                value
                for value in (effective_at, created_at, structured_available)
                if value is not None
            ),
            ingested_at=max(
                value
                for value in (created_at, structured_ingested)
                if value is not None
            ),
            effective_from=(
                effective_at
                if structured is None or structured.effective_from is None
                else structured.effective_from
            ),
            effective_to=(
                (None if structured is None else structured.effective_to)
                if record.expires_at is None
                else utc_from_storage(record.expires_at)
            ),
        )
    if type(record).__module__ == "src.memory.contracts":
        from src.memory.contracts import ResearchContextBundle, ResearchContextMemory

        if isinstance(record, ResearchContextMemory):
            structured = None if record.metadata is None else record.metadata.temporal
            base_available = record.available_at or record.effective_ts
            return TemporalMetadata(
                source_kind=TemporalSourceKind.MEMORY,
                event_time=record.effective_ts,
                period_start=None if structured is None else structured.period_start,
                period_end=None if structured is None else structured.period_end,
                published_at=None if structured is None else structured.published_at,
                available_at=(
                    base_available
                    if structured is None or structured.available_at is None
                    else max(base_available, structured.available_at)
                ),
                ingested_at=None if structured is None else structured.ingested_at,
                effective_from=record.effective_ts,
                effective_to=None if structured is None else structured.effective_to,
            )
        if isinstance(record, ResearchContextBundle):
            return TemporalMetadata(
                source_kind=TemporalSourceKind.RESEARCH_CONTEXT,
                available_at=record.retrieval_metadata.as_of,
                as_of=record.retrieval_metadata.as_of,
            )
    raise TemporalMappingError(
        f"no Temporal Contract mapping for {type(record).__name__}"
    )


def sector_claim_temporal_metadata(
    claim: SectorValidatedClaim,
    *,
    research_as_of: datetime,
) -> TemporalMetadata:
    """Bind one accepted Sector Claim to its containing research cutoff."""

    del claim
    cutoff = utc_from_storage(research_as_of)
    return TemporalMetadata(
        source_kind=TemporalSourceKind.SECTOR_RESEARCH_CLAIM,
        available_at=cutoff,
        as_of=cutoff,
    )


def _filing_publication(record: FundamentalRecord) -> datetime | None:
    if record.accepted_at is not None:
        return utc_from_storage(record.accepted_at)
    if record.filing_date is not None:
        return datetime.combine(record.filing_date, time.min, tzinfo=UTC)
    return None


def _latest(*values: datetime | None) -> datetime:
    present = tuple(value for value in values if value is not None)
    if not present:
        raise TemporalMappingError("record has no attributable availability time")
    return max(present)
