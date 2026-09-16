"""Provider-independent structured research data bundle contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.common import SourceReference
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class DataCapability(StrEnum):
    """Structured research capability groups exposed by the Data layer."""

    ASSET_IDENTITY = "asset_identity"
    MARKET_CONTEXT = "market_context"
    OHLCV = "ohlcv"
    TECHNICAL_FEATURES = "technical_features"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    CORPORATE_EVENTS = "corporate_events"
    FILINGS = "filings"
    MACRO_INDICATORS = "macro_indicators"
    INDUSTRY_SECTOR_CONTEXT = "industry_sector_context"
    NEWS_EVIDENCE = "news_evidence"
    SENTIMENT_EVIDENCE = "sentiment_evidence"


class DataAvailabilityStatus(StrEnum):
    """Explicit availability state for one capability section."""

    PRESENT = "present"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class FreshnessStatus(StrEnum):
    """Freshness state evaluated against a named policy."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class DataQualityStatus(StrEnum):
    """Independent validation outcome for one capability section."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class MissingDataReason(StrEnum):
    """Closed first-version reasons for unavailable research data."""

    NO_PROVIDER = "no_provider"
    NO_OBSERVATION = "no_observation"
    OUT_OF_WINDOW = "out_of_window"
    INSUFFICIENT_HISTORY = "insufficient_history"
    STALE_OBSERVATION = "stale_observation"
    INVALID_RECORD = "invalid_record"
    UPSTREAM_FAILED = "upstream_failed"
    UNAUTHORIZED = "unauthorized"
    UNSUPPORTED_MARKET = "unsupported_market"
    NOT_APPLICABLE = "not_applicable"


class DataSourceReference(DomainModel):
    """Stable source locator without Provider response fields."""

    provider_name: str = Field(min_length=1)
    normalized_record_type: str = Field(min_length=1)
    normalized_record_key: str = Field(min_length=1)
    provider_locator: str = Field(min_length=1)
    source_url: str | None = None
    authorization_class: str = Field(default="public", min_length=1)
    retention_class: str = Field(default="normalized_facts", min_length=1)


class MetricCrossCheck(DomainModel):
    """One transparent primary-versus-secondary metric comparison."""

    primary_provider: str = Field(min_length=1)
    secondary_provider: str = Field(min_length=1)
    primary_value: float
    secondary_value: float
    absolute_difference: float = Field(ge=0.0)
    tolerance: float = Field(ge=0.0)
    conflict: bool


class ResearchEvidenceItem(DomainModel):
    """One attributable structured value in a research bundle."""

    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    subject_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    effective_at: datetime
    observed_at: datetime
    value: str | int | float | bool
    unit: str | None = None
    currency: str | None = None
    source: DataSourceReference
    transformation_name: str | None = None
    transformation_version: str | None = None
    parent_evidence_ids: tuple[str, ...] = ()
    quality: DataQualityStatus = DataQualityStatus.PASS
    cross_check: MetricCrossCheck | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("effective_at", "observed_at")
    @classmethod
    def normalize_evidence_time(cls, value: datetime) -> datetime:
        """Require unambiguous UTC timestamps at the Data boundary."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("research Evidence timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_transformation(self) -> Self:
        """Require complete lineage for derived values only."""

        fields = (self.transformation_name, self.transformation_version)
        if any(fields) and (not all(fields) or not self.parent_evidence_ids):
            raise ValueError(
                "derived evidence requires transformation name, version, and parents"
            )
        if not any(fields) and self.parent_evidence_ids:
            raise ValueError("raw evidence cannot declare parent evidence IDs")
        return self

    def to_source_reference(self) -> SourceReference:
        """Return the sole report/Agent citation shape for this evidence item."""

        return SourceReference(
            document_id=self.source.normalized_record_key,
            excerpt_ref=self.evidence_id,
            provider=self.source.provider_name,
            source_url=self.source.source_url,
        )


class MissingData(DomainModel):
    """Explicitly describe one absent, stale, or failed data field."""

    capability: DataCapability
    field_path: str = Field(min_length=1)
    status: DataAvailabilityStatus
    reason_code: MissingDataReason
    reason: str = Field(min_length=1)
    required: bool
    as_of: datetime
    expected_start: date | None = None
    expected_end: date | None = None
    providers_checked: tuple[str, ...] = ()
    impact: str = Field(min_length=1)
    retryable: bool = False

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require the same aware UTC cutoff used by the research bundle."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MissingData as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_missing_status(self) -> Self:
        """Reject availability states that do not describe missing data."""

        if self.status is DataAvailabilityStatus.PRESENT:
            raise ValueError("MissingData status cannot be present")
        return self


class DataFreshness(DomainModel):
    """Freshness evaluation for one capability section."""

    status: FreshnessStatus
    evaluated_at: datetime
    policy_name: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    latest_effective_at: datetime | None = None
    age_days: int | None = Field(default=None, ge=0)
    maximum_age_days: int | None = Field(default=None, ge=0)
    reason: str | None = None

    @field_validator("evaluated_at", "latest_effective_at")
    @classmethod
    def normalize_freshness_time(cls, value: datetime | None) -> datetime | None:
        """Normalize optional freshness timestamps to aware UTC."""

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("DataFreshness timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_branch(self) -> Self:
        """Keep measured and unmeasured freshness branches unambiguous."""

        measured = self.status in {FreshnessStatus.FRESH, FreshnessStatus.STALE}
        measures = (
            self.latest_effective_at,
            self.age_days,
            self.maximum_age_days,
        )
        if measured and any(value is None for value in measures):
            raise ValueError("measured freshness requires all age fields")
        if not measured and any(value is not None for value in measures):
            raise ValueError("unmeasured freshness cannot contain age fields")
        if not measured and not self.reason:
            raise ValueError("unmeasured freshness requires a reason")
        return self


class DataQuality(DomainModel):
    """Quality and lineage coverage independent from availability."""

    status: DataQualityStatus
    observation_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    completeness_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    validity_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    lineage_coverage_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    temporal_coverage_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_unknown_quality(self) -> Self:
        """Do not attach fabricated ratios to an unknown quality result."""

        ratios = (
            self.completeness_ratio,
            self.validity_ratio,
            self.lineage_coverage_ratio,
            self.temporal_coverage_ratio,
        )
        if self.status is DataQualityStatus.UNKNOWN:
            if any(value is not None for value in ratios) or not self.reason:
                raise ValueError("unknown quality requires a reason and no ratios")
        elif any(value is None for value in ratios):
            raise ValueError("evaluated quality requires all coverage ratios")
        return self


class ResearchDataSection(DomainModel):
    """One capability with explicit presence, freshness, and quality."""

    capability: DataCapability
    status: DataAvailabilityStatus
    as_of: datetime
    freshness: DataFreshness
    quality: DataQuality
    requested_field_count: int = Field(ge=0)
    available_field_count: int = Field(ge=0)
    items: tuple[ResearchEvidenceItem, ...] = ()
    missing_data: tuple[MissingData, ...] = ()

    @field_validator("as_of")
    @classmethod
    def normalize_section_as_of(cls, value: datetime) -> datetime:
        """Normalize the section cutoff to aware UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchDataSection as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_availability_branch(self) -> Self:
        """Keep available and unavailable branches semantically distinct."""

        available = self.status in {
            DataAvailabilityStatus.PRESENT,
            DataAvailabilityStatus.PARTIAL,
            DataAvailabilityStatus.STALE,
        }
        if available and not self.items:
            raise ValueError("available section requires evidence items")
        if not available and self.items:
            raise ValueError("unavailable section cannot contain evidence items")
        if self.available_field_count > self.requested_field_count:
            raise ValueError("available fields cannot exceed requested fields")
        if self.available_field_count != len({item.field_path for item in self.items}):
            raise ValueError("available field count must match unique evidence paths")
        if self.status is DataAvailabilityStatus.PARTIAL and not self.missing_data:
            raise ValueError("partial section requires missing-data entries")
        for item in self.items:
            validate_temporal_access(
                TemporalMetadata(
                    event_time=item.effective_at,
                    available_at=item.observed_at,
                ),
                self.as_of,
            )
        return self


class ResearchDataBundleRequest(DomainModel):
    """Point-in-time request for one serializable research data bundle."""

    asset_id: AssetId
    as_of: datetime
    window_start: date
    window_end: date
    dataset_version: str = Field(min_length=1)
    snapshot_id: str | None = None
    requested_capabilities: tuple[DataCapability, ...] = (
        DataCapability.ASSET_IDENTITY,
        DataCapability.FUNDAMENTALS,
    )

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        """Require a timezone-aware as-of and a valid inclusive window."""

        if self.as_of.tzinfo is None:
            raise ValueError("ResearchDataBundle as_of must include a timezone")
        if self.window_end < self.window_start:
            raise ValueError("bundle window_end cannot precede window_start")
        if self.window_end > self.as_of.date():
            raise ValueError("bundle window cannot extend beyond as_of")
        if DataCapability.ASSET_IDENTITY not in self.requested_capabilities:
            raise ValueError("asset identity is required for every bundle")
        if len(set(self.requested_capabilities)) != len(self.requested_capabilities):
            raise ValueError("requested capabilities must be unique")
        return self


class ResearchDataBundle(DomainModel):
    """Serializable provider-independent structured research input."""

    schema_version: str = Field(default="1.0", min_length=1)
    bundle_id: str = Field(pattern=r"^rdb_[0-9a-f]{24}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_id: AssetId
    as_of: datetime
    window_start: date
    window_end: date
    dataset_version: str = Field(min_length=1)
    snapshot_id: str | None = None
    asset_identity: ResearchDataSection
    market_context: ResearchDataSection
    ohlcv: ResearchDataSection
    technical_features: ResearchDataSection
    fundamentals: ResearchDataSection
    valuation: ResearchDataSection
    corporate_events: ResearchDataSection
    filings: ResearchDataSection
    macro_indicators: ResearchDataSection
    industry_sector_context: ResearchDataSection
    news_evidence: ResearchDataSection
    sentiment_evidence: ResearchDataSection

    @field_validator("as_of")
    @classmethod
    def normalize_bundle_as_of(cls, value: datetime) -> datetime:
        """Normalize the shared Data cutoff to aware UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchDataBundle as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_capability_slots(self) -> Self:
        """Prevent capability data from being placed in the wrong slot."""

        expected = {
            "asset_identity": DataCapability.ASSET_IDENTITY,
            "market_context": DataCapability.MARKET_CONTEXT,
            "ohlcv": DataCapability.OHLCV,
            "technical_features": DataCapability.TECHNICAL_FEATURES,
            "fundamentals": DataCapability.FUNDAMENTALS,
            "valuation": DataCapability.VALUATION,
            "corporate_events": DataCapability.CORPORATE_EVENTS,
            "filings": DataCapability.FILINGS,
            "macro_indicators": DataCapability.MACRO_INDICATORS,
            "industry_sector_context": DataCapability.INDUSTRY_SECTOR_CONTEXT,
            "news_evidence": DataCapability.NEWS_EVIDENCE,
            "sentiment_evidence": DataCapability.SENTIMENT_EVIDENCE,
        }
        for field_name, capability in expected.items():
            section = getattr(self, field_name)
            if section.capability is not capability:
                raise ValueError(f"{field_name} has the wrong capability")
            if section.as_of != self.as_of:
                raise ValueError(f"{field_name} has a different as_of")
        return self
