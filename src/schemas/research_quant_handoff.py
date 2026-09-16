"""Versioned Research-to-Quant handoff contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import Market, SectorId
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonScalar
from src.schemas.opportunity import (
    OpportunityCandidate,
    OpportunityCandidateStatus,
    ResearchHorizon,
)
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import (
    ResearchEpisode,
    ResearchEpisodeVersionReference,
)
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.research_state_transition import ResearchStateTransition
from src.schemas.satellite_alpha import (
    SatelliteAlphaComparisonScope,
    SatelliteAlphaComponent,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SatelliteAlphaUsage,
)
from src.schemas.temporal import require_utc_aware


class HandoffSatelliteReference(DomainModel):
    """Compact Quant-facing reference plus faithful Satellite descriptor."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    observation_id: str = Field(pattern=r"^satellite_alpha_[0-9a-f]{24}$")
    satellite_alpha_id: SatelliteAlphaFamily
    family: SatelliteAlphaFamily
    usage: SatelliteAlphaUsage
    comparison_scope: SatelliteAlphaComparisonScope
    coverage_status: SatelliteAlphaCoverageStatus
    value: JsonScalar = None
    value_components: tuple[SatelliteAlphaComponent, ...] = ()
    quality: DataQualityStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    missing_reasons: tuple[str, ...] = ()
    definition_version: str = Field(min_length=1)
    transform_version: str = Field(min_length=1)
    available_at: datetime

    @field_validator("available_at")
    @classmethod
    def normalize_available_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC availability clock."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_descriptor(self) -> Self:
        """Preserve source Observation identity and missing-value semantics."""

        if self.satellite_alpha_id is not self.family:
            raise ValueError("handoff Satellite family identity is inconsistent")
        if len(self.value_components) != len(set(self.value_components)):
            raise ValueError("handoff Satellite components must be unique")
        if self.missing_reasons != tuple(sorted(set(self.missing_reasons))):
            raise ValueError("handoff Satellite missing reasons must be canonical")
        has_content = self.value is not None or bool(self.value_components)
        if self.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE:
            if not has_content or self.missing_reasons:
                raise ValueError(
                    "available handoff Satellite requires complete content"
                )
        elif self.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL:
            if not has_content or not self.missing_reasons:
                raise ValueError(
                    "partial handoff Satellite requires content and reasons"
                )
        elif has_content:
            raise ValueError("unavailable handoff Satellite cannot contain a value")
        elif not self.missing_reasons:
            raise ValueError("unavailable handoff Satellite requires a reason")
        return self


class ResearchQuantHandoffProvenance(DomainModel):
    """Reference-only provenance index retained at the repository boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    source_sector_claim_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Require unique, canonically ordered boundary references."""

        groups = (
            self.source_claim_ids,
            self.source_evidence_ids,
            self.source_event_ids,
            self.source_sector_claim_ids,
            self.source_artifact_ids,
        )
        if any(tuple(sorted(values)) != values for values in groups):
            raise ValueError("handoff provenance must use canonical ordering")
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("handoff provenance references must be unique")
        return self


class ResearchQuantHandoffVersionManifest(DomainModel):
    """Versions required to interpret one immutable handoff."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    research_state_schema_version: str = Field(min_length=1)
    research_state_version: str = Field(min_length=1)
    research_episode_schema_version: str = Field(min_length=1)
    satellite_observation_schema_version: str = Field(min_length=1)
    satellite_definition_versions: tuple[ResearchEpisodeVersionReference, ...] = ()
    candidate_version: str | None = Field(default=None, min_length=1)
    transition_version: str | None = Field(default=None, min_length=1)
    handoff_build_version: Literal["research_quant_handoff_build_v1"] = (
        "research_quant_handoff_build_v1"
    )

    @model_validator(mode="after")
    def validate_versions(self) -> Self:
        """Require one canonically ordered version per Satellite family."""

        names = tuple(item.name for item in self.satellite_definition_versions)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("Satellite definition versions must be canonical")
        return self


class ResearchQuantHandoffBuildInput(DomainModel):
    """Frozen Research artifacts accepted by the deterministic handoff builder."""

    research_state: ResearchStateSnapshot
    research_episode: ResearchEpisode
    selection_observations: tuple[SatelliteAlphaObservation, ...] = ()
    timing_observations: tuple[SatelliteAlphaObservation, ...] = ()
    opportunity_candidate: OpportunityCandidate | None = None
    research_state_transition: ResearchStateTransition | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC export-materialization clock."""

        return require_utc_aware(value)


class ResearchQuantHandoffBundle(DomainModel):
    """Stable Research output consumed by a future Quant repository."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_quant_handoff_bundle_v1"] = (
        "research_quant_handoff_bundle_v1"
    )
    bundle_id: str = Field(pattern=r"^research_quant_handoff_[0-9a-f]{24}$")
    asset_id: AssetId
    market: Market
    research_as_of: datetime
    sector_id: SectorId | None = None
    chain_ids: tuple[str, ...] = ()
    opportunity_candidate_id: str | None = Field(
        default=None,
        pattern=r"^opportunity_[0-9a-f]{24}$",
    )
    opportunity_candidate_status: OpportunityCandidateStatus | None = None
    research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    research_episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    research_state_transition_id: str | None = Field(
        default=None,
        pattern=r"^research_state_transition_[0-9a-f]{24}$",
    )
    selection_satellite_observations: tuple[HandoffSatelliteReference, ...] = ()
    timing_satellite_observations: tuple[HandoffSatelliteReference, ...] = ()
    catalyst_refs: tuple[str, ...] = ()
    risk_refs: tuple[str, ...] = ()
    invalidator_refs: tuple[str, ...] = ()
    expected_horizon: ResearchHorizon | None = None
    coverage_status: SatelliteAlphaCoverageStatus
    data_quality: DataQualityStatus
    missing_reasons: tuple[str, ...] = ()
    data_snapshot_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    versions: ResearchQuantHandoffVersionManifest
    provenance: ResearchQuantHandoffProvenance
    created_at: datetime

    @field_validator("research_as_of", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require UTC-aware research and artifact clocks."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        """Validate canonical ordering, coverage, and reference-only closure."""

        if self.market is not self.asset_id.market:
            raise ValueError("handoff market does not match canonical asset")
        groups = (
            self.chain_ids,
            self.selection_satellite_observations,
            self.timing_satellite_observations,
            self.catalyst_refs,
            self.risk_refs,
            self.invalidator_refs,
            self.missing_reasons,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("handoff values and references must be unique")
        if self.chain_ids != tuple(sorted(self.chain_ids)):
            raise ValueError("handoff Chain references must be canonical")
        for string_references in (
            self.catalyst_refs,
            self.risk_refs,
            self.invalidator_refs,
            self.missing_reasons,
        ):
            if string_references != tuple(sorted(string_references)):
                raise ValueError("handoff references must use canonical ordering")
        for satellite_references in (
            self.selection_satellite_observations,
            self.timing_satellite_observations,
        ):
            ids = tuple(item.observation_id for item in satellite_references)
            if ids != tuple(sorted(ids)):
                raise ValueError("handoff Satellite references must be canonical")
        selection_ids = {
            item.observation_id for item in self.selection_satellite_observations
        }
        timing_ids = {
            item.observation_id for item in self.timing_satellite_observations
        }
        if selection_ids & timing_ids:
            raise ValueError("handoff Satellite branches must be disjoint")
        if not selection_ids and not timing_ids:
            raise ValueError("handoff requires at least one Satellite reference")
        if any(
            item.usage not in {SatelliteAlphaUsage.SELECTION, SatelliteAlphaUsage.BOTH}
            for item in self.selection_satellite_observations
        ):
            raise ValueError("selection handoff contains a Timing-only descriptor")
        if any(
            item.usage not in {SatelliteAlphaUsage.TIMING, SatelliteAlphaUsage.BOTH}
            for item in self.timing_satellite_observations
        ):
            raise ValueError("timing handoff contains a Selection-only descriptor")
        has_candidate = self.opportunity_candidate_id is not None
        if has_candidate != (self.opportunity_candidate_status is not None):
            raise ValueError("candidate identity and status must coexist")
        if not has_candidate and self.expected_horizon is not None:
            raise ValueError("expected horizon requires a source Candidate")
        has_transition = self.research_state_transition_id is not None
        if has_transition != (self.versions.transition_version is not None):
            raise ValueError("transition identity and version must coexist")
        if has_candidate != (self.versions.candidate_version is not None):
            raise ValueError("candidate identity and version must coexist")
        if self.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE:
            if self.missing_reasons:
                raise ValueError("available handoff cannot declare missing reasons")
        elif not self.missing_reasons:
            raise ValueError("incomplete handoff requires explicit missing reasons")
        required_artifacts = {
            self.research_state_id,
            self.research_episode_id,
            *(
                ()
                if self.opportunity_candidate_id is None
                else (self.opportunity_candidate_id,)
            ),
            *(
                ()
                if self.research_state_transition_id is None
                else (self.research_state_transition_id,)
            ),
        }
        if not required_artifacts <= set(self.provenance.source_artifact_ids):
            raise ValueError("handoff provenance omits a primary source artifact")
        return self


class ResearchQuantHandoffCoverageCount(DomainModel):
    """One mixed-batch coverage count."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    status: SatelliteAlphaCoverageStatus
    count: int = Field(gt=0)


class ResearchQuantHandoffBatchManifest(DomainModel):
    """Credential-free manifest for one deterministic JSONL export."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    manifest_version: Literal["research_quant_handoff_manifest_v1"] = (
        "research_quant_handoff_manifest_v1"
    )
    export_id: str = Field(pattern=r"^research_quant_export_[0-9a-f]{24}$")
    research_as_of: datetime | None = None
    research_as_of_values: tuple[datetime, ...] = Field(min_length=1)
    asset_count: int = Field(gt=0)
    bundle_count: int = Field(gt=0)
    bundle_ids: tuple[str, ...] = Field(min_length=1)
    source_run_ids: tuple[str, ...] = Field(min_length=1)
    coverage_summary: tuple[ResearchQuantHandoffCoverageCount, ...] = Field(
        min_length=1
    )
    bundle_schema_version: Literal["research_quant_handoff_bundle_v1"] = (
        "research_quant_handoff_bundle_v1"
    )
    artifact_path: str = Field(min_length=1)
    generated_at: datetime

    @field_validator("research_as_of", "generated_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        """Require UTC-aware batch clocks."""

        return None if value is None else require_utc_aware(value)

    @field_validator("research_as_of_values")
    @classmethod
    def normalize_cutoffs(cls, values: tuple[datetime, ...]) -> tuple[datetime, ...]:
        """Require a canonical list of UTC-aware batch cutoffs."""

        normalized = tuple(require_utc_aware(value) for value in values)
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError("batch research cutoffs must be canonical and unique")
        return normalized

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        """Require canonical indexes and internally consistent counts."""

        if self.bundle_ids != tuple(sorted(self.bundle_ids)):
            raise ValueError("batch Bundle identities must be canonical")
        if len(self.bundle_ids) != len(set(self.bundle_ids)):
            raise ValueError("batch Bundle identities must be unique")
        if self.source_run_ids != tuple(sorted(self.source_run_ids)):
            raise ValueError("batch source runs must be canonical")
        statuses = tuple(item.status.value for item in self.coverage_summary)
        if statuses != tuple(sorted(statuses)) or len(statuses) != len(set(statuses)):
            raise ValueError("batch coverage summary must be canonical")
        if self.bundle_count != len(self.bundle_ids):
            raise ValueError("batch Bundle count is inconsistent")
        if sum(item.count for item in self.coverage_summary) != self.bundle_count:
            raise ValueError("batch coverage counts are inconsistent")
        if len(self.research_as_of_values) == 1:
            if self.research_as_of != self.research_as_of_values[0]:
                raise ValueError("single-cutoff batch must expose research_as_of")
        elif self.research_as_of is not None:
            raise ValueError("multi-cutoff batch must not expose one research_as_of")
        return self
