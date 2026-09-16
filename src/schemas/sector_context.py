"""Day36 contracts connecting Sector Intelligence to asset research."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import AgentName, SectorCapabilityStatus, SectorId
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.sector_research import (
    SectorClaimCategory,
    SectorCycleAssessment,
    SectorValidatedClaim,
)
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class SectorContextClaimSummary(DomainModel):
    """Presentation-only view of an authoritative accepted Sector Claim."""

    claim_id: str = Field(min_length=1)
    category: SectorClaimCategory
    claim_text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SectorContextEventReference(DomainModel):
    """Compact Radar identity linked to accepted Sector Claims."""

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    status: str = Field(min_length=1)
    available_at: datetime
    chain_ids: tuple[str, ...] = ()
    supporting_sector_claim_ids: tuple[str, ...] = ()

    @field_validator("available_at")
    @classmethod
    def normalize_available_at(cls, value: datetime) -> datetime:
        """Require an unambiguous UTC availability timestamp."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sector event available_at must be timezone-aware")
        return value.astimezone(UTC)


class SectorContextCoverage(DomainModel):
    """Small auditable coverage record, not a research conclusion."""

    membership_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    chain_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    sector_state: SectorCapabilityStatus
    macro_state: SectorCapabilityStatus
    seed_only_membership: bool = False


class SectorContextBundle(DomainModel):
    """Compact PIT-safe upstream Sector context for one asset research run."""

    schema_version: Literal["sector_context_bundle_v1"] = "sector_context_bundle_v1"
    context_id: str = Field(pattern=r"^sector_context_[0-9a-f]{24}$")
    asset_id: AssetId
    sector_id: SectorId
    sector_name: str = Field(min_length=1)
    sector_scope_id: str = Field(pattern=r"^SECTOR:[A-Z0-9_]+$")
    research_as_of: datetime
    membership_versions: tuple[str, ...] = Field(min_length=1)
    membership_sources: tuple[str, ...] = Field(min_length=1)
    membership_confidence: float = Field(ge=0.0, le=1.0)
    active_chain_ids: tuple[str, ...] = ()
    cycle_assessment: SectorCycleAssessment
    accepted_claims: tuple[SectorValidatedClaim, ...] = Field(min_length=1)
    active_events: tuple[SectorContextEventReference, ...] = ()
    sector_snapshot_id: str = Field(min_length=1)
    macro_snapshot_id: str = Field(min_length=1)
    coverage: SectorContextCoverage
    quality: SectorCapabilityStatus
    uncertainties: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    sector_context_version: Literal["sector_context_v1"] = "sector_context_v1"

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require one UTC cutoff shared by Sector and asset research."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sector context research_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        """Reject duplicate, future, rejected, or disconnected Sector context."""

        claim_ids = tuple(item.claim_id for item in self.accepted_claims)
        if any(item is None for item in claim_ids) or len(claim_ids) != len(
            set(claim_ids)
        ):
            raise ValueError("Sector context requires unique accepted Claim IDs")
        if len(self.active_chain_ids) != len(set(self.active_chain_ids)):
            raise ValueError("Sector context chain IDs must be unique")
        if len(self.membership_versions) != len(set(self.membership_versions)):
            raise ValueError("Sector membership versions must be unique")
        event_ids = tuple(item.event_id for item in self.active_events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Sector context event IDs must be unique")
        accepted = {item for item in claim_ids if item is not None}
        for event in self.active_events:
            validate_temporal_access(
                TemporalMetadata(available_at=event.available_at),
                self.research_as_of,
            )
            if not set(event.supporting_sector_claim_ids) <= accepted:
                raise ValueError("Sector event references an unknown Sector Claim")
        if self.coverage.claim_count != len(self.accepted_claims):
            raise ValueError("Sector context Claim coverage is inconsistent")
        if self.coverage.chain_count != len(self.active_chain_ids):
            raise ValueError("Sector context chain coverage is inconsistent")
        if self.coverage.event_count != len(self.active_events):
            raise ValueError("Sector context event coverage is inconsistent")
        return self


class SectorRoleContext(DomainModel):
    """Least-privilege Sector projection for one existing Agent role."""

    schema_version: Literal["sector_role_context_v1"] = "sector_role_context_v1"
    context_id: str = Field(pattern=r"^sector_context_[0-9a-f]{24}$")
    agent_role: AgentName
    asset_id: AssetId
    sector_id: SectorId
    sector_name: str = Field(min_length=1)
    research_as_of: datetime
    quality: SectorCapabilityStatus
    cycle_assessment: SectorCycleAssessment | None = None
    active_chain_ids: tuple[str, ...] = ()
    context_claims: tuple[SectorContextClaimSummary, ...] = ()
    validated_claims: tuple[ClaimEvidenceBinding, ...] = ()
    event_references: tuple[SectorContextEventReference, ...] = ()
    uncertainties: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    usage_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        """Keep Analyst presentation and Manager upstream routes disjoint."""

        analyst_roles = {
            AgentName.FUNDAMENTAL_ANALYST,
            AgentName.TECHNICAL_TEXT_ANALYST,
            AgentName.SENTIMENT_ANALYST,
            AgentName.NEWS_EVENT_ANALYST,
        }
        if self.agent_role in analyst_roles and self.validated_claims:
            raise ValueError("Analyst Sector projection cannot alter raw Evidence mode")
        if self.agent_role not in analyst_roles and self.context_claims:
            raise ValueError("Manager Sector projection must use upstream Claims")
        if self.research_as_of.tzinfo is None:
            raise ValueError("Sector role context requires timezone-aware as_of")
        return self


class SectorContextResolution(DomainModel):
    """Explicit routing result that supports safe Phase 3 degradation."""

    asset_id: AssetId
    research_as_of: datetime
    status: SectorCapabilityStatus
    bundle: SectorContextBundle | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_branch(self) -> Self:
        """Require a bundle only for available or partial resolution."""

        if self.status is SectorCapabilityStatus.MISSING:
            if self.bundle is not None or not self.reason:
                raise ValueError("missing Sector resolution requires only a reason")
        elif self.bundle is None:
            raise ValueError("resolved Sector context requires a bundle")
        return self
