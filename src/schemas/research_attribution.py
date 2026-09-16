"""Unified context attribution contracts for one ResearchEpisode."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import AgentName, MemoryLevel, ResearchScopeType
from src.models.types import DomainModel
from src.schemas.common import SourceReference
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class ResearchContextType(StrEnum):
    """Context families sharing the Day41 attribution boundary."""

    MEMORY = "memory"
    SECTOR_CLAIM = "sector_claim"
    RADAR_EVENT = "radar_event"


class ClaimLinkStatus(StrEnum):
    """Whether exact accepted Claim identities survived the source run."""

    COMPLETE = "complete"
    NOT_AVAILABLE_AT_SOURCE_RUN = "not_available_at_source_run"


class FutureEvaluationStatus(StrEnum):
    """Only legal Day41 states for not-yet-implemented Outcome evaluation."""

    PENDING = "pending"
    NOT_AVAILABLE = "not_available"


class ContextClaimLinkStatus(StrEnum):
    """Downstream disposition of one explicit context-to-Claim reference."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ResearchContextClaimLink(DomainModel):
    """One explicit structured reference from a context item to a Claim."""

    agent_role: AgentName
    agent_run_id: str = Field(min_length=1)
    context_type: ResearchContextType
    context_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    claim_status: ContextClaimLinkStatus


class MemoryRetrievalScopeFilters(DomainModel):
    """Exact filters applied to one Memory retrieval operation."""

    namespace_keys: tuple[str, ...] = Field(min_length=1)
    memory_levels: tuple[MemoryLevel, ...] = Field(min_length=1)
    scope_types: tuple[ResearchScopeType, ...] = ()
    scope_ids: tuple[str, ...] = ()
    usage_classes: tuple[str, ...] = ()
    episode_ids: tuple[str, ...] = ()
    asset_id: str | None = Field(default=None, min_length=1)
    market: str = Field(min_length=1)
    min_importance_score: float = Field(ge=0.0, le=1.0)


class MemoryRetrievalCandidate(DomainModel):
    """One PIT-eligible candidate without vector implementation details."""

    memory_id: str = Field(min_length=1)
    rank: int = Field(gt=0)
    retrieval_score: float
    retrieval_reason: str = Field(min_length=1)
    selected: bool
    memory_level: MemoryLevel
    scope_type: ResearchScopeType | None = None
    scope_id: str | None = Field(default=None, min_length=1)
    effective_ts: datetime
    available_at: datetime
    source_references: tuple[SourceReference, ...] = Field(min_length=1)

    @field_validator("effective_ts", "available_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require an explicit UTC candidate time."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory retrieval candidate time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Keep optional structured Scope fields paired."""

        if (self.scope_type is None) != (self.scope_id is None):
            raise ValueError("Memory candidate Scope type and ID must be paired")
        return self


class MemoryRetrievalRecord(DomainModel):
    """Auditable Memory retrieval tied to one role in one Episode."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["memory_retrieval_record_v1"] = "memory_retrieval_record_v1"
    retrieval_id: str = Field(pattern=r"^memory_retrieval_[0-9a-f]{24}$")
    episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    research_as_of: datetime
    agent_role: AgentName
    agent_run_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    retrieval_purpose: str = Field(min_length=1)
    candidate_memory_ids: tuple[str, ...]
    selected_memory_ids: tuple[str, ...]
    candidates: tuple[MemoryRetrievalCandidate, ...]
    scope_filters: MemoryRetrievalScopeFilters
    snapshot_id: str = Field(min_length=1)
    excluded_future_count: int = Field(ge=0)
    empty_valid: bool
    retrieval_version: str = Field(default="memory_retrieval_v1", min_length=1)

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require an unambiguous UTC retrieval cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory retrieval research_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_retrieval(self) -> Self:
        """Validate ordering, selection, empty state, and PIT safety."""

        candidate_ids = tuple(item.memory_id for item in self.candidates)
        if self.candidate_memory_ids != candidate_ids:
            raise ValueError("Memory retrieval candidate index is inconsistent")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Memory retrieval candidates must be unique")
        if tuple(item.rank for item in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("Memory retrieval candidate ranks must be contiguous")
        selected = tuple(item.memory_id for item in self.candidates if item.selected)
        if self.selected_memory_ids != selected:
            raise ValueError("Memory retrieval selected index is inconsistent")
        if self.empty_valid != (not self.selected_memory_ids):
            raise ValueError("empty_valid must exactly represent no selected Memory")
        for candidate in self.candidates:
            validate_temporal_access(
                TemporalMetadata(
                    event_time=candidate.effective_ts,
                    available_at=candidate.available_at,
                    effective_from=candidate.effective_ts,
                ),
                self.research_as_of,
            )
        return self


class ResearchContextAttribution(DomainModel):
    """One context item's provided/selected/used state and Claim lineage."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_context_attribution_v1"] = (
        "research_context_attribution_v1"
    )
    attribution_id: str = Field(pattern=r"^context_attribution_[0-9a-f]{24}$")
    episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    research_as_of: datetime
    agent_role: AgentName
    agent_run_id: str = Field(min_length=1)
    context_type: ResearchContextType
    context_id: str = Field(min_length=1)
    provided: bool
    selected: bool
    used: bool
    used_by_claim_ids: tuple[str, ...] = ()
    rejected_by_claim_ids: tuple[str, ...] = ()
    claim_link_status: ClaimLinkStatus = ClaimLinkStatus.COMPLETE
    rank: int | None = Field(default=None, gt=0)
    retrieval_score: float | None = None
    retrieval_reason: str | None = Field(default=None, min_length=1)
    scope_type: ResearchScopeType
    scope_id: str = Field(min_length=1)
    retrieval_id: str | None = Field(
        default=None,
        pattern=r"^memory_retrieval_[0-9a-f]{24}$",
    )
    temporal: TemporalMetadata
    source_references: tuple[SourceReference, ...] = Field(min_length=1)
    attribution_version: str = Field(default="research_attribution_v1", min_length=1)
    outcome_status: FutureEvaluationStatus = FutureEvaluationStatus.NOT_AVAILABLE
    future_usefulness_status: FutureEvaluationStatus = (
        FutureEvaluationStatus.NOT_AVAILABLE
    )
    future_usefulness_score: None = None

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require an unambiguous UTC attribution cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attribution research_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_attribution(self) -> Self:
        """Enforce state semantics, identity uniqueness, and PIT safety."""

        if self.selected and not self.provided:
            raise ValueError("selected context must have been provided")
        if self.used and not self.selected:
            raise ValueError("used context must have been selected")
        if len(self.used_by_claim_ids) != len(set(self.used_by_claim_ids)):
            raise ValueError("used Claim IDs must be unique")
        if len(self.rejected_by_claim_ids) != len(set(self.rejected_by_claim_ids)):
            raise ValueError("rejected Claim IDs must be unique")
        if set(self.used_by_claim_ids) & set(self.rejected_by_claim_ids):
            raise ValueError("accepted and rejected context links must be disjoint")
        if not self.used and self.used_by_claim_ids:
            raise ValueError("unused context cannot reference accepted Claims")
        if (
            self.used
            and not self.used_by_claim_ids
            and (self.claim_link_status is ClaimLinkStatus.COMPLETE)
        ):
            raise ValueError("used context requires an accepted Claim link")
        if self.claim_link_status is ClaimLinkStatus.NOT_AVAILABLE_AT_SOURCE_RUN and (
            self.used_by_claim_ids or self.rejected_by_claim_ids
        ):
            raise ValueError("historically unavailable Claim linkage cannot be guessed")
        if self.context_type is ResearchContextType.MEMORY:
            if self.retrieval_id is None or self.rank is None:
                raise ValueError(
                    "Memory attribution requires retrieval identity and rank"
                )
        elif any(
            value is not None
            for value in (
                self.retrieval_id,
                self.rank,
                self.retrieval_score,
                self.retrieval_reason,
            )
        ):
            raise ValueError("non-Memory attribution cannot carry retrieval fields")
        validate_temporal_access(self.temporal, self.research_as_of)
        return self


class ResearchEpisodeAttribution(DomainModel):
    """Immutable unified attribution artifact for one ResearchEpisode."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_episode_attribution_v1"] = (
        "research_episode_attribution_v1"
    )
    attribution_bundle_id: str = Field(pattern=r"^research_attribution_[0-9a-f]{24}$")
    episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    research_as_of: datetime
    retrieval_records: tuple[MemoryRetrievalRecord, ...] = ()
    attributions: tuple[ResearchContextAttribution, ...] = ()
    attribution_version: str = Field(default="research_attribution_v1", min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("research_as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Require an unambiguous UTC Episode cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Episode attribution research_as_of must be timezone-aware"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        """Keep every retrieval and context attribution bound to one Episode."""

        if any(
            item.episode_id != self.episode_id for item in self.retrieval_records
        ) or any(item.episode_id != self.episode_id for item in self.attributions):
            raise ValueError("attribution child belongs to another Episode")
        if any(
            item.research_as_of != self.research_as_of
            for item in self.retrieval_records
        ) or any(
            item.research_as_of != self.research_as_of for item in self.attributions
        ):
            raise ValueError("attribution child uses a different research cutoff")
        retrieval_ids = tuple(item.retrieval_id for item in self.retrieval_records)
        if len(retrieval_ids) != len(set(retrieval_ids)):
            raise ValueError("Memory retrieval identities must be unique")
        attribution_ids = tuple(item.attribution_id for item in self.attributions)
        if len(attribution_ids) != len(set(attribution_ids)):
            raise ValueError("context attribution identities must be unique")
        if any(
            item.retrieval_id is not None
            and item.retrieval_id not in set(retrieval_ids)
            for item in self.attributions
        ):
            raise ValueError("Memory attribution references an unknown retrieval")
        return self
