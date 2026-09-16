"""Versioned research OpportunityCandidate contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import Market, SectorId
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.satellite_alpha import (
    LogicCertaintyStage,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaObservation,
    SatelliteAlphaUsage,
)
from src.schemas.temporal import TemporalMetadata, require_utc_aware


class OpportunityCandidateStatus(StrEnum):
    """Transparent research qualification outcome."""

    QUALIFIED = "qualified"
    INSUFFICIENT_RESEARCH = "insufficient_research"


class OpportunityType(StrEnum):
    """Rule-based reasons for further research consideration."""

    SECTOR_CHAIN = "sector_chain"
    EXPECTATION_CHANGE = "expectation_change"
    MATERIAL_EVENT = "material_event"
    MATERIAL_THESIS = "material_thesis"
    RESEARCH_DEBATE = "research_debate"
    RISK_RESEARCH = "risk_research"


class ThesisDirection(StrEnum):
    """Research thesis disposition without recommendation semantics."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"


class ResearchHorizon(StrEnum):
    """Optional explicitly supplied research horizon."""

    NEAR_TERM = "near_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    UNSPECIFIED = "unspecified"


class OpportunityCandidate(DomainModel):
    """PIT-safe reason to consider an asset for further Research or Quant."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["opportunity_candidate_v1"] = "opportunity_candidate_v1"
    candidate_id: str = Field(pattern=r"^opportunity_[0-9a-f]{24}$")
    status: OpportunityCandidateStatus
    asset_id: AssetId
    market: Market
    research_as_of: datetime
    available_at: datetime
    sector_id: SectorId | None = None
    chain_ids: tuple[str, ...] = ()
    opportunity_types: tuple[OpportunityType, ...] = ()
    thesis_direction: ThesisDirection
    logic_stage: LogicCertaintyStage | None = None
    expected_horizon: ResearchHorizon | None = None
    satellite_observation_ids: tuple[str, ...] = Field(min_length=1)
    catalyst_refs: tuple[str, ...] = ()
    risk_refs: tuple[str, ...] = ()
    invalidator_refs: tuple[str, ...] = ()
    source_research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    source_episode_id: str | None = Field(
        default=None,
        pattern=r"^research_episode_[0-9a-f]{24}$",
    )
    source_claim_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    source_sector_claim_ids: tuple[str, ...] = ()
    coverage_status: SatelliteAlphaCoverageStatus
    quality: DataQualityStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    qualification_reasons: tuple[str, ...] = ()
    missing_reasons: tuple[str, ...] = ()
    candidate_version: Literal["opportunity_candidate_v1"] = "opportunity_candidate_v1"
    created_at: datetime

    @field_validator("research_as_of", "available_at", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require explicit UTC candidate clocks."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        """Enforce identity, coverage, qualification, and reference closure."""

        if self.market is not self.asset_id.market:
            raise ValueError("Opportunity market does not match canonical asset")
        if self.available_at < self.research_as_of:
            raise ValueError("Opportunity cannot predate its research cutoff")
        if self.created_at < self.available_at:
            raise ValueError("Opportunity created_at cannot precede availability")
        groups = (
            self.chain_ids,
            self.opportunity_types,
            self.satellite_observation_ids,
            self.catalyst_refs,
            self.risk_refs,
            self.invalidator_refs,
            self.source_claim_ids,
            self.source_event_ids,
            self.source_sector_claim_ids,
            self.qualification_reasons,
            self.missing_reasons,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("Opportunity references must be unique")
        allowed_coverage = {
            SatelliteAlphaCoverageStatus.AVAILABLE,
            SatelliteAlphaCoverageStatus.PARTIAL,
            SatelliteAlphaCoverageStatus.MISSING_INPUT,
            SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
            SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
        }
        if self.coverage_status not in allowed_coverage:
            raise ValueError("Opportunity uses an invalid candidate coverage status")
        if self.status is OpportunityCandidateStatus.QUALIFIED:
            if not self.opportunity_types or not self.qualification_reasons:
                raise ValueError("qualified Opportunity requires rule-based reasons")
            if not (
                self.source_claim_ids
                or self.source_event_ids
                or self.source_sector_claim_ids
            ):
                raise ValueError("qualified Opportunity requires source lineage")
        elif self.opportunity_types or self.qualification_reasons:
            raise ValueError("insufficient Opportunity cannot claim qualification")
        if self.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE:
            if self.missing_reasons:
                raise ValueError("available Opportunity cannot declare missing data")
        elif not self.missing_reasons:
            raise ValueError("non-available Opportunity requires missing reasons")
        return self

    def temporal_metadata(self) -> TemporalMetadata:
        """Expose candidate visibility through Unified Temporal Contract v1."""

        return TemporalMetadata(
            event_time=self.research_as_of,
            available_at=self.available_at,
            as_of=self.research_as_of,
        )


class OpportunityCandidateBuildInput(DomainModel):
    """Frozen State, Episode, and Selection descriptors for qualification."""

    research_state: ResearchStateSnapshot
    source_episode: ResearchEpisode | None = None
    selection_observations: tuple[SatelliteAlphaObservation, ...] = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require a UTC materialization clock."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        """Close every descriptor to the same frozen research process."""

        state = self.research_state
        ids = tuple(item.observation_id for item in self.selection_observations)
        if len(ids) != len(set(ids)):
            raise ValueError("Opportunity source Observations must be unique")
        for observation in self.selection_observations:
            if observation.usage not in {
                SatelliteAlphaUsage.SELECTION,
                SatelliteAlphaUsage.BOTH,
            }:
                raise ValueError("Opportunity cannot consume Timing-only descriptors")
            if (
                observation.asset_id != state.asset_id
                or observation.research_as_of != state.research_as_of
                or observation.source_research_state_id != state.research_state_id
            ):
                raise ValueError("Opportunity Observation does not match State")
            if observation.created_at > self.created_at:
                raise ValueError("Opportunity cannot consume a future Observation")
        if self.source_episode is not None:
            episode = self.source_episode
            if (
                episode.research_state_id != state.research_state_id
                or episode.asset_id != state.asset_id
                or episode.research_as_of != state.research_as_of
            ):
                raise ValueError("Opportunity Episode does not match State")
            if episode.created_at > self.created_at:
                raise ValueError("Opportunity cannot consume a future Episode")
            if any(
                item.source_episode_id not in {None, episode.episode_id}
                for item in self.selection_observations
            ):
                raise ValueError("Opportunity Observation has a different Episode")
        elif any(
            item.source_episode_id is not None for item in self.selection_observations
        ):
            raise ValueError("Opportunity input omitted a referenced Episode")
        sector_ids = {
            item.sector_id
            for item in self.selection_observations
            if item.sector_id is not None
        }
        if len(sector_ids) > 1:
            raise ValueError("Opportunity Observations disagree on Sector")
        return self
