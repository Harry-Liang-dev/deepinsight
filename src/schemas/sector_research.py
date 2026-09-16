"""Day35 contracts for claim-first Sector research synthesis."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.memory.contracts import ResearchContextBundle, ResearchContextSection
from src.models.enums import AgentStatus, ClaimIntent, SectorCapabilityStatus, SectorId
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import RejectedClaim, RoleEvidenceManifestEntry, ValidatedClaim
from src.schemas.common import ErrorInfo
from src.schemas.llm import LLMRunMetadata
from src.schemas.sectors import (
    IndustryChainDefinition,
    SectorAnomalyEvent,
    SectorBenchmarkMapping,
    SectorEdge,
    SectorMacroSnapshot,
    SectorMembership,
    SectorNode,
    SectorResearchSnapshot,
    SectorUniverseSnapshot,
)


class SectorClaimCategory(StrEnum):
    """Stable research sections produced only through validated Claims."""

    TREND = "trend"
    BREADTH = "breadth"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    MACRO_ENVIRONMENT = "macro_environment"
    MACRO_SENSITIVITY = "macro_sensitivity"
    INDUSTRY_CHAINS = "industry_chains"
    ANOMALIES = "anomalies"
    LEADERS_LAGGARDS = "leaders_laggards"
    CATALYSTS = "catalysts"
    RISKS = "risks"
    CYCLE = "cycle"


class SectorCycleAssessmentPhase(StrEnum):
    """Interpretive Sector cycle phase, distinct from Day33 macro state."""

    ACCELERATING = "accelerating"
    EXPANDING = "expanding"
    MATURE = "mature"
    SLOWING = "slowing"
    CONTRACTING = "contracting"
    RECOVERING = "recovering"
    UNCERTAIN = "uncertain"


class SectorResearchValidationStage(StrEnum):
    """Stable, safe failure stages for Sector research diagnostics."""

    SCHEMA_PARSE = "SCHEMA_PARSE"
    REQUIRED_FIELD = "REQUIRED_FIELD"
    ENUM = "ENUM"
    CARDINALITY = "CARDINALITY"
    CLAIM_LINEAGE = "CLAIM_LINEAGE"
    EVENT_LINEAGE = "EVENT_LINEAGE"
    NUMERIC_GROUNDING = "NUMERIC_GROUNDING"
    PIT = "PIT"
    SECTOR_SCOPE = "SECTOR_SCOPE"
    CHAIN_SCOPE = "CHAIN_SCOPE"
    DUPLICATE_ID = "DUPLICATE_ID"
    UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
    OTHER = "OTHER"


class SectorEvidenceKind(StrEnum):
    """Compact projection kinds over existing canonical upstream objects."""

    MARKET_STATE = "market_state"
    BREADTH_STATE = "breadth_state"
    FUNDAMENTAL_STATE = "fundamental_state"
    VALUATION_STATE = "valuation_state"
    MACRO_STATE = "macro_state"
    MACRO_SENSITIVITY = "macro_sensitivity"
    ANOMALY_EVENT = "anomaly_event"
    INDUSTRY_CHAIN = "industry_chain"
    MEMBERSHIP = "membership"
    GRAPH_RELATION = "graph_relation"
    MEMORY = "memory"
    COVERAGE = "coverage"


class SectorResearchEvidence(DomainModel):
    """One compact Evidence entry plus non-factual interpretation constraints."""

    entry: RoleEvidenceManifestEntry
    kind: SectorEvidenceKind
    status: SectorCapabilityStatus | None = None
    chain_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    association_only: bool = False
    candidate_only: bool = False
    requires_degradation: bool = False


class SectorResearchInput(DomainModel):
    """Point-in-time Day35 input composed only from existing Phase 4 outputs."""

    schema_version: Literal["sector_research_input_v1"] = "sector_research_input_v1"
    research_as_of: datetime
    sector_id: SectorId
    sector_name: str = Field(min_length=1)
    sector_scope_id: str = Field(pattern=r"^SECTOR:[A-Z0-9_]+$")
    chain_scope_ids: tuple[str, ...] = ()
    macro_scope_ids: tuple[str, ...] = ()
    universe_snapshot: SectorUniverseSnapshot
    sector_snapshot: SectorResearchSnapshot
    macro_snapshot: SectorMacroSnapshot
    benchmark_mapping: SectorBenchmarkMapping | None = None
    anomaly_events: tuple[SectorAnomalyEvent, ...] = ()
    industry_chains: tuple[IndustryChainDefinition, ...] = ()
    memberships: tuple[SectorMembership, ...] = ()
    graph_nodes: tuple[SectorNode, ...] = ()
    graph_edges: tuple[SectorEdge, ...] = ()
    memory_context: ResearchContextBundle

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require one unambiguous UTC research cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sector research_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("chain_scope_ids")
    @classmethod
    def validate_chain_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require canonical, unique Industry Chain scope identities."""

        if len(values) != len(set(values)) or any(
            not value.startswith("CHAIN:") for value in values
        ):
            raise ValueError("Sector research chain scopes are invalid")
        return values

    @model_validator(mode="after")
    def validate_direct_upstream_alignment(self) -> Self:
        """Reuse upstream PIT contracts and enforce one Sector/date boundary."""

        as_of_date = self.research_as_of.date()
        identities = {
            (self.universe_snapshot.sector_id, self.universe_snapshot.as_of),
            (self.sector_snapshot.sector_id, self.sector_snapshot.as_of),
            (self.macro_snapshot.sector_id, self.macro_snapshot.as_of),
        }
        if identities != {(self.sector_id, as_of_date)}:
            raise ValueError("Sector research snapshots do not share research_as_of")
        if (
            self.macro_snapshot.source_sector_snapshot_id
            != self.sector_snapshot.snapshot_id
        ):
            raise ValueError("Sector macro snapshot does not derive from Sector state")
        if self.benchmark_mapping is not None:
            mapping = self.benchmark_mapping
            if mapping.sector_id is not self.sector_id or not mapping.is_effective(
                as_of_date
            ):
                raise ValueError("Sector benchmark mapping is not effective at cutoff")
            if mapping.benchmark_ids != self.universe_snapshot.benchmark_ids:
                raise ValueError("Sector benchmark mapping and universe disagree")
        if any(
            event.sector_id is not self.sector_id or event.as_of != self.research_as_of
            for event in self.anomaly_events
        ):
            raise ValueError("Sector Radar events do not share research_as_of")
        if any(
            chain.sector_id is not self.sector_id or not chain.is_effective(as_of_date)
            for chain in self.industry_chains
        ):
            raise ValueError("Industry Chain context is not effective for Sector")
        if any(
            membership.sector_id is not self.sector_id
            or not membership.is_effective(as_of_date)
            for membership in self.memberships
        ):
            raise ValueError("Sector memberships are not effective at cutoff")
        if any(not node.is_effective(as_of_date) for node in self.graph_nodes) or any(
            not edge.is_effective(as_of_date) for edge in self.graph_edges
        ):
            raise ValueError("Sector graph context is not effective at cutoff")
        if self.memory_context.retrieval_metadata.as_of != self.research_as_of:
            raise ValueError("Sector Memory context does not share research_as_of")
        allowed_scopes = {
            self.sector_scope_id,
            *self.chain_scope_ids,
            *self.macro_scope_ids,
        }
        memory_items = [
            item
            for section in ResearchContextSection
            for item in self.memory_context.items_for_section(section)
        ]
        if any(item.namespace_key not in allowed_scopes for item in memory_items):
            raise ValueError("Sector Memory contains an unrelated hierarchical scope")
        return self


class SectorResearchDraftClaim(DomainModel):
    """Permissive LLM Claim draft validated against direct upstream Evidence."""

    claim_path: str = Field(pattern=r"^claims\[\d+\]$")
    claim_text: str = Field(min_length=1)
    category: SectorClaimCategory
    evidence_ids: tuple[str, ...] = ()
    numeric_literals: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    claim_intent: ClaimIntent = ClaimIntent.ANALYTICAL_INFERENCE


class SectorCycleAssessmentDraft(DomainModel):
    """LLM cycle interpretation referencing Claim paths, never raw prose facts."""

    phase: SectorCycleAssessmentPhase
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_claim_paths: tuple[str, ...] = Field(min_length=1)
    uncertainty: str = Field(min_length=1)


class SectorResearchDraftResponse(DomainModel):
    """Structured Gateway response before strict local Claim promotion."""

    claims: tuple[SectorResearchDraftClaim, ...]
    cycle_assessment: SectorCycleAssessmentDraft
    uncertainties: tuple[str, ...] = ()


class SectorValidatedClaim(ValidatedClaim):
    """Existing ValidatedClaim enriched only with a Sector presentation category."""

    claim_path: str = Field(pattern=r"^claims\[\d+\]$")
    category: SectorClaimCategory


class SectorCycleAssessment(DomainModel):
    """Interpretive cycle result backed exclusively by accepted Claim IDs."""

    phase: SectorCycleAssessmentPhase
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_claim_ids: tuple[str, ...] = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    status: SectorCapabilityStatus = SectorCapabilityStatus.AVAILABLE
    dropped_support_claim_paths: tuple[str, ...] = ()
    degradation_reasons: tuple[Literal["REJECTED_SUPPORT_CLAIM"], ...] = ()

    @model_validator(mode="after")
    def validate_dependent_lineage_status(self) -> Self:
        """Require explicit PARTIAL semantics when support was quarantined."""

        has_dropped_support = bool(self.dropped_support_claim_paths)
        if has_dropped_support:
            if self.status is not SectorCapabilityStatus.PARTIAL:
                raise ValueError("Dropped cycle support requires PARTIAL status")
            if "REJECTED_SUPPORT_CLAIM" not in self.degradation_reasons:
                raise ValueError("Dropped cycle support requires a degradation reason")
        elif (
            self.status is not SectorCapabilityStatus.AVAILABLE
            or self.degradation_reasons
        ):
            raise ValueError("Complete cycle support requires AVAILABLE status")
        return self


class SectorResearchOutput(DomainModel):
    """Authoritative Day35 output; narrative is deliberately not factual state."""

    schema_version: Literal["sector_research_output_v1"] = "sector_research_output_v1"
    sector_id: SectorId
    sector_scope_id: str = Field(pattern=r"^SECTOR:[A-Z0-9_]+$")
    research_as_of: datetime
    claims: tuple[SectorValidatedClaim, ...] = Field(min_length=1)
    cycle_assessment: SectorCycleAssessment
    uncertainties: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    rejected_claims: tuple[RejectedClaim, ...] = ()
    evidence_manifest: tuple[SectorResearchEvidence, ...]
    model_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_claim_collection(self) -> Self:
        """Require stable accepted IDs, direct Evidence, and cycle lineage."""

        ids = tuple(claim.claim_id for claim in self.claims)
        if any(item is None for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Sector Claims require unique stable claim IDs")
        expected_paths = tuple(f"claims[{index}]" for index in range(len(self.claims)))
        if tuple(item.claim_path for item in self.claims) != expected_paths:
            raise ValueError("Sector Claim paths must be contiguous and ordered")
        if any(
            not claim.evidence_ids or claim.upstream_claim_ids for claim in self.claims
        ):
            raise ValueError("Sector Claims require direct upstream Evidence only")
        accepted_ids = {item for item in ids if item is not None}
        if not set(self.cycle_assessment.supporting_claim_ids) <= accepted_ids:
            raise ValueError("Sector cycle references an unknown accepted Claim")
        return self


class SectorResearchExecutionResult(DomainModel):
    """Auditable execution envelope separate from the eight-Agent chain."""

    run_id: str = Field(min_length=1)
    status: AgentStatus
    output: SectorResearchOutput | None = None
    error: ErrorInfo | None = None
    llm_run_metadata: LLMRunMetadata | None = None
    diagnostics: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status_branch(self) -> Self:
        """Keep success output and failure error mutually exclusive."""

        if self.status is AgentStatus.OK:
            if self.output is None or self.error is not None:
                raise ValueError("successful Sector research requires output only")
        elif self.output is not None or self.error is None:
            raise ValueError("failed Sector research requires error only")
        return self
