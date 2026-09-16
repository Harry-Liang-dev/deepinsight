"""Unified point-in-time metadata and access rules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self

from pydantic import field_validator, model_validator

from src.models.types import DomainModel


class TemporalSourceKind(StrEnum):
    """Stable temporal mapping identities used by research inputs."""

    GENERIC = "generic"
    SEC_FILING = "sec_filing"
    FMP_FUNDAMENTAL = "fmp_fundamental"
    ALPACA_DAILY_BAR = "alpaca_daily_bar"
    ALPACA_NEWS = "alpaca_news"
    FRED_VINTAGE = "fred_vintage"
    SECTOR_MEMBERSHIP = "sector_membership"
    SECTOR_ANOMALY = "sector_anomaly"
    SECTOR_RESEARCH_CLAIM = "sector_research_claim"
    MEMORY = "memory"
    RESEARCH_CONTEXT = "research_context"
    RESEARCH_EVIDENCE = "research_evidence"


class TemporalAccessReason(StrEnum):
    """Closed reasons returned by the unified PIT access decision."""

    USABLE = "usable"
    FUTURE_AVAILABLE = "future_available"
    FUTURE_INGESTION = "future_ingestion"
    FUTURE_SNAPSHOT = "future_snapshot"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    NO_LONGER_EFFECTIVE = "no_longer_effective"
    UNKNOWN_AVAILABILITY = "unknown_availability"


class TemporalAccessMode(StrEnum):
    """Select historical-observation or live-acquisition visibility semantics."""

    HISTORICAL_REPLAY = "historical_replay"
    LIVE_ACQUISITION = "live_acquisition"


class TemporalMetadata(DomainModel):
    """Provider-independent temporal meaning for one research input.

    Event and period fields describe when something happened. Availability,
    ingestion, effective interval, and snapshot fields determine whether the
    object may be consumed by a research run.
    """

    source_kind: TemporalSourceKind = TemporalSourceKind.GENERIC
    event_time: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    published_at: datetime | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None
    effective_from: datetime | date | None = None
    effective_to: datetime | date | None = None
    as_of: datetime | None = None

    @field_validator(
        "event_time",
        "published_at",
        "available_at",
        "ingested_at",
        "as_of",
    )
    @classmethod
    def normalize_optional_datetime(cls, value: datetime | None) -> datetime | None:
        """Require UTC-aware datetimes at the public temporal boundary."""

        return None if value is None else require_utc_aware(value)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def normalize_effective_bound(
        cls,
        value: datetime | date | None,
    ) -> datetime | date | None:
        """Normalize datetime bounds while preserving date-only memberships."""

        if isinstance(value, datetime):
            return require_utc_aware(value)
        return value

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """Validate period, publication, and half-open interval ordering."""

        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end cannot precede period_start")
        if (
            self.published_at is not None
            and self.available_at is not None
            and self.available_at < self.published_at
        ):
            raise ValueError("available_at cannot precede published_at")
        if self.effective_from is not None and self.effective_to is not None:
            if _comparable_effective(self.effective_to) <= _comparable_effective(
                self.effective_from
            ):
                raise ValueError("effective_to must be later than effective_from")
        return self


class TemporalAccessDecision(DomainModel):
    """Auditable result of one unified temporal access check."""

    usable: bool
    reason: TemporalAccessReason
    research_as_of: datetime
    usable_at: datetime | None = None

    @field_validator("research_as_of", "usable_at")
    @classmethod
    def normalize_decision_time(cls, value: datetime | None) -> datetime | None:
        """Keep decisions unambiguous and UTC-normalized."""

        return None if value is None else require_utc_aware(value)


class TemporalLeakageError(ValueError):
    """Raised when an input is not legally visible at the research cutoff."""

    def __init__(self, decision: TemporalAccessDecision) -> None:
        """Retain the safe, structured rejection decision."""

        super().__init__(f"temporal access rejected: {decision.reason.value}")
        self.decision = decision


def temporal_access_decision(
    metadata: TemporalMetadata,
    research_as_of: datetime,
    *,
    require_availability: bool = True,
    mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> TemporalAccessDecision:
    """Evaluate one object under the shared half-open PIT policy."""

    cutoff = require_utc_aware(research_as_of)
    if metadata.available_at is not None and metadata.available_at > cutoff:
        return _rejected(TemporalAccessReason.FUTURE_AVAILABLE, cutoff)
    if (
        mode is TemporalAccessMode.HISTORICAL_REPLAY
        and metadata.ingested_at is not None
        and metadata.ingested_at > cutoff
    ):
        return _rejected(TemporalAccessReason.FUTURE_INGESTION, cutoff)
    if metadata.as_of is not None and metadata.as_of > cutoff:
        return _rejected(TemporalAccessReason.FUTURE_SNAPSHOT, cutoff)
    if metadata.effective_from is not None and not _bound_reached(
        metadata.effective_from,
        cutoff,
    ):
        return _rejected(TemporalAccessReason.NOT_YET_EFFECTIVE, cutoff)
    if metadata.effective_to is not None and _bound_reached(
        metadata.effective_to,
        cutoff,
    ):
        return _rejected(TemporalAccessReason.NO_LONGER_EFFECTIVE, cutoff)
    visibility = tuple(
        value
        for value in (
            metadata.available_at,
            (
                metadata.ingested_at
                if mode is TemporalAccessMode.HISTORICAL_REPLAY
                else None
            ),
            metadata.as_of,
        )
        if value is not None
    )
    has_effective_gate = metadata.effective_from is not None
    if require_availability and not visibility and not has_effective_gate:
        return _rejected(TemporalAccessReason.UNKNOWN_AVAILABILITY, cutoff)
    return TemporalAccessDecision(
        usable=True,
        reason=TemporalAccessReason.USABLE,
        research_as_of=cutoff,
        usable_at=max(visibility) if visibility else None,
    )


def is_usable_at(
    metadata: TemporalMetadata,
    research_as_of: datetime,
    *,
    require_availability: bool = True,
    mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> bool:
    """Return whether one temporal object is visible at the cutoff."""

    return temporal_access_decision(
        metadata,
        research_as_of,
        require_availability=require_availability,
        mode=mode,
    ).usable


def validate_temporal_access(
    metadata: TemporalMetadata,
    research_as_of: datetime,
    *,
    require_availability: bool = True,
    mode: TemporalAccessMode = TemporalAccessMode.HISTORICAL_REPLAY,
) -> TemporalAccessDecision:
    """Return a successful decision or raise one typed leakage error."""

    decision = temporal_access_decision(
        metadata,
        research_as_of,
        require_availability=require_availability,
        mode=mode,
    )
    if not decision.usable:
        raise TemporalLeakageError(decision)
    return decision


def require_utc_aware(value: datetime) -> datetime:
    """Reject naive input and normalize an aware datetime to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("temporal datetime must be timezone-aware")
    return value.astimezone(UTC)


def utc_from_storage(value: datetime) -> datetime:
    """Decode a legacy DuckDB naive TIMESTAMP with explicit UTC semantics.

    This compatibility function is restricted to persistence boundaries. It
    never interprets a naive value as local time.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bound_reached(bound: datetime | date, cutoff: datetime) -> bool:
    return cutoff >= _comparable_effective(bound)


def _comparable_effective(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return require_utc_aware(value)
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


def _rejected(
    reason: TemporalAccessReason,
    cutoff: datetime,
) -> TemporalAccessDecision:
    return TemporalAccessDecision(
        usable=False,
        reason=reason,
        research_as_of=cutoff,
    )
