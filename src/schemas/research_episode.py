"""Immutable audit contract for one completed structured research process."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import AgentName, AgentStatus, Market
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.sector_usage import SectorContextUsageDiagnostic


class ResearchEpisodeTraceQuality(StrEnum):
    """Completeness of identities retained by the historical source run."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class ResearchEpisodeVersionReference(DomainModel):
    """One model, Prompt, or feature version used by the research process."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class AgentExecutionTrace(DomainModel):
    """Structured Agent execution metadata without private model reasoning."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    agent_role: AgentName
    agent_run_id: str = Field(min_length=1)
    status: AgentStatus
    input_context_ids: tuple[str, ...] = ()
    provided_claim_ids: tuple[str, ...] = ()
    output_claim_ids: tuple[str, ...] = ()
    accepted_claim_ids: tuple[str, ...] = ()
    rejected_claim_ids: tuple[str, ...] = ()
    accepted_claim_count: int = Field(ge=0)
    rejected_claim_count: int = Field(ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    trace_quality: ResearchEpisodeTraceQuality
    missing_metadata: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        """Validate known identities while allowing explicit legacy gaps."""

        identity_groups = (
            self.input_context_ids,
            self.provided_claim_ids,
            self.output_claim_ids,
            self.accepted_claim_ids,
            self.rejected_claim_ids,
            self.missing_metadata,
        )
        if any(len(values) != len(set(values)) for values in identity_groups):
            raise ValueError("Agent execution trace identities must be unique")
        if set(self.accepted_claim_ids) & set(self.rejected_claim_ids):
            raise ValueError("accepted and rejected Claim identities must be disjoint")
        if not set((*self.accepted_claim_ids, *self.rejected_claim_ids)) <= set(
            self.output_claim_ids
        ):
            raise ValueError("Agent output Claim identities are incomplete")
        if self.accepted_claim_count < len(self.accepted_claim_ids):
            raise ValueError("accepted Claim count is smaller than retained identities")
        if self.rejected_claim_count < len(self.rejected_claim_ids):
            raise ValueError("rejected Claim count is smaller than retained identities")
        if self.trace_quality is ResearchEpisodeTraceQuality.COMPLETE:
            if self.missing_metadata:
                raise ValueError("complete Agent trace cannot declare missing metadata")
            if self.accepted_claim_count != len(self.accepted_claim_ids):
                raise ValueError("complete Agent trace requires all accepted Claim IDs")
            if self.rejected_claim_count != len(self.rejected_claim_ids):
                raise ValueError("complete Agent trace requires all rejected Claim IDs")
        elif not self.missing_metadata:
            raise ValueError("partial Agent trace requires explicit missing metadata")
        return self


class ResearchEpisodeBuildInput(DomainModel):
    """Frozen process metadata plus the referenced ResearchState identity."""

    research_state: ResearchStateSnapshot
    agent_traces: tuple[AgentExecutionTrace, ...]
    sector_usage: tuple[SectorContextUsageDiagnostic, ...] = ()
    report_id: str | None = Field(default=None, min_length=1)
    created_at: datetime
    source_artifact_ids: tuple[str, ...] = ()
    missing_metadata: tuple[str, ...] = ()

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC source-run creation timestamp."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchEpisode created_at must be timezone-aware")
        return value.astimezone(UTC)


class ResearchEpisode(DomainModel):
    """Immutable reference-only record of one actual research execution."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["research_episode_v1"] = "research_episode_v1"
    episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    asset_id: AssetId
    market: Market
    research_as_of: datetime
    research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    data_snapshot_id: str = Field(min_length=1)
    sector_context_id: str | None = None
    memory_context_id: str | None = None
    agent_run_ids: tuple[str, ...]
    provided_claim_ids: tuple[str, ...]
    accepted_claim_ids: tuple[str, ...]
    rejected_claim_ids: tuple[str, ...]
    accepted_claim_count: int = Field(ge=0)
    rejected_claim_count: int = Field(ge=0)
    sector_claim_ids: tuple[str, ...]
    bull_claim_ids: tuple[str, ...]
    bear_claim_ids: tuple[str, ...]
    risk_claim_ids: tuple[str, ...]
    final_research_claim_ids: tuple[str, ...]
    report_id: str | None = None
    model_versions: tuple[ResearchEpisodeVersionReference, ...]
    prompt_versions: tuple[ResearchEpisodeVersionReference, ...]
    feature_versions: tuple[ResearchEpisodeVersionReference, ...]
    agent_traces: tuple[AgentExecutionTrace, ...]
    sector_usage: tuple[SectorContextUsageDiagnostic, ...] = ()
    trace_quality: ResearchEpisodeTraceQuality
    missing_metadata: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    created_at: datetime
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("research_as_of", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Keep Episode timestamps unambiguous and UTC-aware."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ResearchEpisode timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        """Validate immutable identity closure without inspecting model prose."""

        groups = (
            self.agent_run_ids,
            self.provided_claim_ids,
            self.accepted_claim_ids,
            self.rejected_claim_ids,
            self.sector_claim_ids,
            self.bull_claim_ids,
            self.bear_claim_ids,
            self.risk_claim_ids,
            self.final_research_claim_ids,
            self.missing_metadata,
            self.source_artifact_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("ResearchEpisode identities must be unique")
        traces = {item.agent_run_id: item for item in self.agent_traces}
        if len(traces) != len(self.agent_traces):
            raise ValueError("ResearchEpisode Agent runs must be unique")
        if tuple(traces) != self.agent_run_ids:
            raise ValueError("ResearchEpisode Agent run index is inconsistent")
        accepted = {
            item for trace in self.agent_traces for item in trace.accepted_claim_ids
        }
        rejected = {
            item for trace in self.agent_traces for item in trace.rejected_claim_ids
        }
        provided = {
            item for trace in self.agent_traces for item in trace.provided_claim_ids
        }
        provided.update(
            claim_id
            for usage in self.sector_usage
            for claim_id in usage.provided_sector_claim_ids
        )
        if set(self.accepted_claim_ids) != accepted:
            raise ValueError("ResearchEpisode accepted Claim index is inconsistent")
        if set(self.rejected_claim_ids) != rejected:
            raise ValueError("ResearchEpisode rejected Claim index is inconsistent")
        if set(self.provided_claim_ids) != provided:
            raise ValueError("ResearchEpisode provided Claim index is inconsistent")
        if self.accepted_claim_count != sum(
            trace.accepted_claim_count for trace in self.agent_traces
        ):
            raise ValueError("ResearchEpisode accepted Claim count is inconsistent")
        if self.rejected_claim_count != sum(
            trace.rejected_claim_count for trace in self.agent_traces
        ):
            raise ValueError("ResearchEpisode rejected Claim count is inconsistent")
        role_claims = set(
            (*self.bull_claim_ids, *self.bear_claim_ids, *self.risk_claim_ids)
        )
        if not role_claims <= set(self.accepted_claim_ids):
            raise ValueError("role Claim index contains an unknown accepted Claim")
        if not set(self.final_research_claim_ids) <= set(self.accepted_claim_ids):
            raise ValueError("final research index contains an unknown accepted Claim")
        if self.trace_quality is ResearchEpisodeTraceQuality.COMPLETE:
            if self.missing_metadata or any(
                trace.trace_quality is not ResearchEpisodeTraceQuality.COMPLETE
                for trace in self.agent_traces
            ):
                raise ValueError(
                    "complete Episode cannot contain partial trace metadata"
                )
            if self.accepted_claim_count != len(self.accepted_claim_ids):
                raise ValueError("complete Episode requires every accepted Claim ID")
            if self.rejected_claim_count != len(self.rejected_claim_ids):
                raise ValueError("complete Episode requires every rejected Claim ID")
        elif not self.missing_metadata:
            raise ValueError("partial Episode requires explicit missing metadata")
        return self
