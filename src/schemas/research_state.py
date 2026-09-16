"""Immutable machine-facing ResearchStateSnapshot contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import AgentName
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonScalar
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_data import DataQualityStatus, ResearchDataBundle
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class ResearchStateFeatureType(StrEnum):
    """Closed v1 feature families with distinct provenance requirements."""

    DETERMINISTIC_NUMERIC = "deterministic_numeric"
    NORMALIZED_RESEARCH_STATE = "normalized_research_state"
    SEMANTIC_CATEGORICAL = "semantic_categorical"


class ResearchStateSectionStatus(StrEnum):
    """Availability of one machine-state section at the source cutoff."""

    PRESENT = "present"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_AVAILABLE_AT_SOURCE_RUN = "not_available_at_source_run"


class ResearchStateSectionName(StrEnum):
    """Stable v1 hierarchy and asset-state section names."""

    IDENTITY = "identity"
    MACRO = "macro_state"
    SECTOR = "sector_state"
    INDUSTRY_CHAIN = "industry_chain_state"
    FUNDAMENTAL = "fundamental_state"
    VALUATION = "valuation_state"
    TECHNICAL = "technical_state"
    SENTIMENT = "sentiment_state"
    EVENT = "event_state"
    MARKET_CONTEXT = "market_context_state"
    DEBATE = "debate_state"
    RISK = "risk_state"
    THESIS = "thesis_state"
    DATA_QUALITY = "data_quality_state"
    MEMORY_CONTEXT = "memory_context_state"


class ResearchStateFeature(DomainModel):
    """One compact state value referencing, never copying, its provenance."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    feature_name: str = Field(min_length=1)
    value: JsonScalar = None
    feature_type: ResearchStateFeatureType
    as_of: datetime
    available_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality: DataQualityStatus
    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    feature_version: str = Field(min_length=1)
    transform_name: str | None = None
    transform_version: str | None = None
    missing_reason: str | None = None

    @field_validator("as_of", "available_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        """Require explicit aware UTC feature timestamps."""

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchState feature timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_feature_contract(self) -> Self:
        """Enforce value, type, transform, and reference-only lineage rules."""

        reference_groups = (
            self.source_claim_ids,
            self.source_evidence_ids,
            self.source_artifact_ids,
        )
        for values in reference_groups:
            if len(values) != len(set(values)):
                raise ValueError("ResearchState provenance references must be unique")
        if self.value is None:
            if not self.missing_reason:
                raise ValueError("missing ResearchState feature requires a reason")
            if self.transform_name is not None or self.transform_version is not None:
                raise ValueError("missing feature cannot claim a transform")
            return self
        if self.missing_reason is not None:
            raise ValueError("available ResearchState feature cannot be marked missing")
        if not any(reference_groups):
            raise ValueError("available ResearchState feature requires provenance")
        if self.feature_type is ResearchStateFeatureType.DETERMINISTIC_NUMERIC:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("deterministic numeric feature requires a number")
        elif self.feature_type is ResearchStateFeatureType.NORMALIZED_RESEARCH_STATE:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("normalized research feature requires a number")
            if not self.transform_name or not self.transform_version:
                raise ValueError(
                    "normalized research feature requires versioned transform"
                )
        elif not isinstance(self.value, (str, bool)):
            raise ValueError(
                "semantic/categorical feature requires string or boolean value"
            )
        if (
            self.feature_type is not ResearchStateFeatureType.NORMALIZED_RESEARCH_STATE
            and (self.transform_name is not None or self.transform_version is not None)
        ):
            raise ValueError(
                "only normalized research features declare a state transform"
            )
        return self


class ResearchStateSection(DomainModel):
    """One explicit state section with stable missing semantics."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    section_name: ResearchStateSectionName
    status: ResearchStateSectionStatus
    features: tuple[ResearchStateFeature, ...] = ()
    missing_reason: str | None = None

    @model_validator(mode="after")
    def validate_section_branch(self) -> Self:
        """Keep present, partial, and unavailable branches unambiguous."""

        names = tuple(item.feature_name for item in self.features)
        if len(names) != len(set(names)):
            raise ValueError("ResearchState feature names must be unique per section")
        available = self.status in {
            ResearchStateSectionStatus.PRESENT,
            ResearchStateSectionStatus.PARTIAL,
        }
        if available and not self.features:
            raise ValueError("available ResearchState section requires features")
        if not available and self.features:
            raise ValueError(
                "unavailable ResearchState section cannot contain features"
            )
        if self.status is ResearchStateSectionStatus.PRESENT and self.missing_reason:
            raise ValueError("present ResearchState section cannot be marked missing")
        if (
            self.status is not ResearchStateSectionStatus.PRESENT
            and not self.missing_reason
        ):
            raise ValueError("non-present ResearchState section requires a reason")
        return self


class ResearchStateHierarchy(DomainModel):
    """Resolved Macro → Sector → Chain → Asset identities at the cutoff."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    macro_scope_ids: tuple[str, ...] = ()
    sector_scope_id: str | None = None
    industry_chain_scope_ids: tuple[str, ...] = ()
    asset_scope_id: str = Field(pattern=r"^ASSET:.+$")


class ResearchStateVersionReference(DomainModel):
    """One centrally stored upstream implementation version."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    component: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ResearchStateLineage(DomainModel):
    """Compact frozen-artifact lineage without embedded Provider payloads."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    source_run_id: str = Field(min_length=1)
    data_bundle_id: str = Field(min_length=1)
    data_snapshot_id: str | None = None
    dataset_version: str = Field(min_length=1)
    sector_context_id: str | None = None
    memory_context_id: str | None = None
    agent_run_ids: tuple[str, ...] = ()
    versions: tuple[ResearchStateVersionReference, ...] = ()
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchStateClaimInput(DomainModel):
    """Accepted Claim plus producing role/run identity for State projection."""

    agent_role: AgentName
    agent_run_id: str = Field(min_length=1)
    claim: ClaimEvidenceBinding

    @model_validator(mode="after")
    def require_stable_claim_id(self) -> Self:
        """State materialization never assigns missing Claim identities."""

        if self.claim.claim_id is None:
            raise ValueError("ResearchState input Claim requires claim_id")
        return self


class NormalizedResearchFeatureInput(DomainModel):
    """Explicit versioned transform output accepted by the pure builder."""

    section_name: ResearchStateSectionName
    feature_name: str = Field(min_length=1)
    value: float
    as_of: datetime
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality: DataQualityStatus = DataQualityStatus.PASS
    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    transform_name: str = Field(min_length=1)
    transform_version: str = Field(min_length=1)


class ResearchStateMemoryContextInput(DomainModel):
    """Minimal immutable projection of an already completed Memory retrieval."""

    snapshot_id: str = Field(min_length=1)
    as_of: datetime
    status: str = Field(min_length=1)
    result_count: int = Field(ge=0)

    @field_validator("as_of")
    @classmethod
    def normalize_memory_as_of(cls, value: datetime) -> datetime:
        """Require the Memory projection to share an explicit UTC cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchState Memory as_of must be timezone-aware")
        return value.astimezone(UTC)


class ResearchStateSectorContextInput(DomainModel):
    """Minimal projection of a frozen SectorContextBundle for State building."""

    context_id: str = Field(min_length=1)
    asset_id: AssetId
    sector_id: str = Field(min_length=1)
    sector_scope_id: str = Field(pattern=r"^SECTOR:[A-Z0-9_]+$")
    research_as_of: datetime
    active_chain_ids: tuple[str, ...] = ()
    cycle_phase: str = Field(min_length=1)
    cycle_confidence: float = Field(ge=0.0, le=1.0)
    cycle_supporting_claim_ids: tuple[str, ...] = Field(min_length=1)
    accepted_claims: tuple[ClaimEvidenceBinding, ...] = Field(min_length=1)
    macro_claim_ids: tuple[str, ...] = ()
    sector_snapshot_id: str = Field(min_length=1)
    macro_snapshot_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)

    @field_validator("research_as_of")
    @classmethod
    def normalize_sector_as_of(cls, value: datetime) -> datetime:
        """Require the Sector projection to share an explicit UTC cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchState Sector as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_macro_claim_subset(self) -> Self:
        """Macro projection may only reference accepted Sector Claims."""

        accepted = {item.claim_id for item in self.accepted_claims}
        if not set(self.macro_claim_ids) <= accepted:
            raise ValueError("Sector macro projection references an unknown Claim")
        return self


class ResearchStateBuildInput(DomainModel):
    """Frozen structured inputs; intentionally excludes reports and Providers."""

    research_data_bundle: ResearchDataBundle
    sector_context: ResearchStateSectorContextInput | None = None
    accepted_claims: tuple[ResearchStateClaimInput, ...] = ()
    normalized_features: tuple[NormalizedResearchFeatureInput, ...] = ()
    memory_context: ResearchStateMemoryContextInput | None = None
    prompt_versions: tuple[ResearchStateVersionReference, ...] = ()
    model_versions: tuple[ResearchStateVersionReference, ...] = ()
    source_run_id: str = Field(min_length=1)


class ResearchStateSnapshot(DomainModel):
    """Immutable, versioned, point-in-time machine research state."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_state_snapshot_v1"] = "research_state_snapshot_v1"
    research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    research_state_version: Literal["research_state_v1"] = "research_state_v1"
    feature_version: Literal["research_state_feature_v1"] = "research_state_feature_v1"
    asset_id: AssetId
    research_as_of: datetime
    hierarchy: ResearchStateHierarchy
    identity: ResearchStateSection
    macro_state: ResearchStateSection
    sector_state: ResearchStateSection
    industry_chain_state: ResearchStateSection
    fundamental_state: ResearchStateSection
    valuation_state: ResearchStateSection
    technical_state: ResearchStateSection
    sentiment_state: ResearchStateSection
    event_state: ResearchStateSection
    market_context_state: ResearchStateSection
    debate_state: ResearchStateSection
    risk_state: ResearchStateSection
    thesis_state: ResearchStateSection
    data_quality_state: ResearchStateSection
    memory_context_state: ResearchStateSection
    lineage: ResearchStateLineage

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require the one UTC replay cutoff for the whole snapshot."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchState research_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        """Validate section identity, PIT access, and referenced Claim closure."""

        sections = (
            self.identity,
            self.macro_state,
            self.sector_state,
            self.industry_chain_state,
            self.fundamental_state,
            self.valuation_state,
            self.technical_state,
            self.sentiment_state,
            self.event_state,
            self.market_context_state,
            self.debate_state,
            self.risk_state,
            self.thesis_state,
            self.data_quality_state,
            self.memory_context_state,
        )
        expected = tuple(ResearchStateSectionName)
        actual = tuple(section.section_name for section in sections)
        if actual != expected:
            raise ValueError("ResearchState sections are not in the canonical v1 order")
        for section in sections:
            for feature in section.features:
                validate_temporal_access(
                    TemporalMetadata(
                        event_time=feature.as_of,
                        available_at=feature.available_at or feature.as_of,
                    ),
                    self.research_as_of,
                )
        return self
