"""Reference-only ResearchState transition and Timing build contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonScalar
from src.schemas.memory import MemorySearchResult
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import (
    ResearchStateSectionName,
    ResearchStateSnapshot,
)
from src.schemas.satellite_alpha import SatelliteAlphaCoverageStatus
from src.schemas.temporal import require_utc_aware


class ResearchStateTransitionDirection(StrEnum):
    """Descriptive change in research maturity, never a trade decision."""

    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    UNCHANGED = "unchanged"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ThesisTransitionStatus(StrEnum):
    """Structured thesis change across two frozen States."""

    UPGRADED = "upgraded"
    UNCHANGED = "unchanged"
    DOWNGRADED = "downgraded"
    INVALIDATED = "invalidated"
    UNCERTAIN = "uncertain"


class RiskTransitionStatus(StrEnum):
    """One component-level risk transition."""

    NEW_RISK = "new_risk"
    ESCALATING = "escalating"
    STABLE = "stable"
    DEESCALATING = "deescalating"
    RESOLVED = "resolved"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"


class EvidenceTransitionStatus(StrEnum):
    """Later structured evidence disposition for a prior hypothesis."""

    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"
    MIXED = "mixed"


class ExpectationChangeOrder(StrEnum):
    """Second-order expectation semantics requiring at least three points."""

    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"
    STEADY = "steady"
    MIXED = "mixed"


class EventWindowPosition(StrEnum):
    """Deterministic relation between cutoff and a known event time."""

    PRE_EVENT = "pre_event"
    EVENT_WINDOW = "event_window"
    POST_EVENT = "post_event"
    OUTSIDE_WINDOW = "outside_window"


class CatalystProximity(StrEnum):
    """Versioned calendar proximity to a known catalyst."""

    IMMINENT = "imminent"
    NEAR_TERM = "near_term"
    MEDIUM_TERM = "medium_term"
    DISTANT = "distant"
    UNKNOWN = "unknown"


class TimingEventKind(StrEnum):
    """Role of an existing canonical Event in Timing projection."""

    EVENT = "event"
    CATALYST = "catalyst"


class ResearchStateValueChange(DomainModel):
    """One comparable structured feature change with compact provenance."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    change_key: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{1,159}$")
    previous_value: JsonScalar = None
    current_value: JsonScalar = None
    classification: str = Field(min_length=1)
    source_state_feature_refs: tuple[str, ...] = Field(min_length=1)
    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        """Require unique, section-qualified, reference-only provenance."""

        groups = (
            self.source_state_feature_refs,
            self.source_claim_ids,
            self.source_evidence_ids,
            self.source_artifact_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("transition change provenance must be unique")
        if any("::" not in value for value in self.source_state_feature_refs):
            raise ValueError("transition feature references must be section-qualified")
        return self


class TimingEventReference(DomainModel):
    """Compact temporal reference to an existing Event or catalyst."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    event_id: str = Field(min_length=1)
    kind: TimingEventKind
    event_time: datetime
    available_at: datetime
    source_state_feature_ref: str = Field(pattern=r"^[a-z_]+::.+$")
    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    outcome_disposition: str | None = Field(default=None, min_length=1)
    outcome_available_at: datetime | None = None

    @field_validator("event_time", "available_at", "outcome_available_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        """Require UTC-aware Event clocks."""

        return None if value is None else require_utc_aware(value)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Require an availability clock for any separately learned outcome."""

        if bool(self.outcome_disposition) != bool(self.outcome_available_at):
            raise ValueError("Event outcome and outcome_available_at must coexist")
        for values in (self.source_claim_ids, self.source_evidence_ids):
            if len(values) != len(set(values)):
                raise ValueError("Timing Event provenance must be unique")
        return self


class ResearchStateTransition(DomainModel):
    """Deterministic comparison of two immutable PIT-valid ResearchStates."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_state_transition_v1"] = (
        "research_state_transition_v1"
    )
    transition_id: str = Field(pattern=r"^research_state_transition_[0-9a-f]{24}$")
    asset_id: AssetId
    previous_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    current_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    previous_episode_id: str | None = Field(
        default=None, pattern=r"^research_episode_[0-9a-f]{24}$"
    )
    current_episode_id: str | None = Field(
        default=None, pattern=r"^research_episode_[0-9a-f]{24}$"
    )
    previous_as_of: datetime
    current_as_of: datetime
    changed_dimensions: tuple[ResearchStateSectionName, ...] = ()
    direction: ResearchStateTransitionDirection
    logic_stage_from: str | None = None
    logic_stage_to: str | None = None
    expectation_changes: tuple[ResearchStateValueChange, ...] = ()
    thesis_change: ThesisTransitionStatus | None = None
    risk_changes: tuple[ResearchStateValueChange, ...] = ()
    catalyst_changes: tuple[ResearchStateValueChange, ...] = ()
    evidence_changes: tuple[ResearchStateValueChange, ...] = ()
    source_claim_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = Field(min_length=2)
    coverage_status: SatelliteAlphaCoverageStatus
    missing_reasons: tuple[str, ...] = ()
    available_at: datetime
    transition_version: Literal["research_state_transition_v1"] = (
        "research_state_transition_v1"
    )
    comparison_version: Literal["research_state_comparison_v1"] = (
        "research_state_comparison_v1"
    )
    created_at: datetime

    @field_validator("previous_as_of", "current_as_of", "available_at", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require UTC-aware transition clocks."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        """Enforce strict history order, coverage, and immutable references."""

        if self.previous_state_id == self.current_state_id:
            raise ValueError("transition requires two distinct ResearchStates")
        if self.previous_as_of >= self.current_as_of:
            raise ValueError("transition requires previous_as_of < current_as_of")
        if self.available_at < self.current_as_of:
            raise ValueError("transition availability cannot predate current State")
        if self.created_at < self.available_at:
            raise ValueError("transition created_at cannot predate availability")
        groups = (
            self.changed_dimensions,
            self.expectation_changes,
            self.risk_changes,
            self.catalyst_changes,
            self.evidence_changes,
            self.source_claim_ids,
            self.source_event_ids,
            self.source_evidence_ids,
            self.source_artifact_ids,
            self.missing_reasons,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("transition values and provenance must be unique")
        if self.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE:
            if self.missing_reasons:
                raise ValueError("available transition cannot declare missing reasons")
        elif self.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL:
            if not self.missing_reasons:
                raise ValueError("partial transition requires missing reasons")
        else:
            raise ValueError("a materialized transition is AVAILABLE or PARTIAL")
        return self


class TimingSatelliteBuildInput(DomainModel):
    """Frozen history and references consumed by the deterministic builder."""

    current_state: ResearchStateSnapshot
    historical_states: tuple[ResearchStateSnapshot, ...] = ()
    current_episode: ResearchEpisode | None = None
    historical_episodes: tuple[ResearchEpisode, ...] = ()
    events: tuple[TimingEventReference, ...] = ()
    retrieved_memories: tuple[MemorySearchResult, ...] = ()
    available_at: datetime
    created_at: datetime

    @field_validator("available_at", "created_at")
    @classmethod
    def normalize_build_time(cls, value: datetime) -> datetime:
        """Require UTC-aware build clocks."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_build_input(self) -> Self:
        """Keep exact State/Episode identities and audit clocks aligned."""

        if self.available_at < self.current_state.research_as_of:
            raise ValueError("Timing availability cannot predate current State")
        if self.created_at < self.available_at:
            raise ValueError("Timing created_at cannot predate availability")
        episodes = (*self.historical_episodes, self.current_episode)
        for episode in (item for item in episodes if item is not None):
            states = (*self.historical_states, self.current_state)
            if not any(
                episode.research_state_id == state.research_state_id
                and episode.asset_id == state.asset_id
                and episode.research_as_of == state.research_as_of
                for state in states
            ):
                raise ValueError("Timing Episode does not match an input State")
            if episode.created_at > self.available_at:
                raise ValueError("Timing availability cannot predate an Episode")
        ids = tuple(item.research_state_id for item in self.historical_states)
        if len(ids) != len(set(ids)):
            raise ValueError("Timing history contains duplicate State identities")
        event_ids = tuple(item.event_id for item in self.events)
        memory_ids = tuple(item.memory_id for item in self.retrieved_memories)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Timing Event identities must be unique")
        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("Timing Memory identities must be unique")
        return self
