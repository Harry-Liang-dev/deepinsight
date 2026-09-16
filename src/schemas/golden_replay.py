"""Versioned contracts for the offline Golden point-in-time replay gate."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.identifiers import AssetId
from src.models.types import DomainModel


class GoldenReplayStatus(StrEnum):
    """Closed final state for one deterministic replay."""

    PASS = "pass"
    FAIL = "fail"


class GoldenReplayTraceStatus(StrEnum):
    """Whether every identity in one sampled trace survived the source run."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class GoldenReplayMemoryStatus(StrEnum):
    """Truthful Memory state retained by a historical source run."""

    AVAILABLE = "available"
    EMPTY_VALID = "empty_valid"
    NOT_AVAILABLE_AT_SOURCE_RUN = "not_available_at_source_run"


class GoldenReplayVersionReference(DomainModel):
    """One schema or builder version used by replay."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    component: str = Field(min_length=1)
    version: str = Field(min_length=1)


class GoldenReplayCheck(DomainModel):
    """One deterministic gate result with no hidden external side effect."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    check_name: str = Field(min_length=1)
    status: GoldenReplayStatus
    evidence_ids: tuple[str, ...] = ()
    details: str = Field(min_length=1)


class GoldenReplayTrace(DomainModel):
    """Sampled reference path proving existing provenance without re-grounding."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    trace_name: str = Field(min_length=1)
    status: GoldenReplayTraceStatus
    reference_path: tuple[str, ...] = Field(min_length=2)
    terminal_providers: tuple[str, ...] = ()
    limitation: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        """Require an explicit limitation only for partial historical traces."""

        if self.status is GoldenReplayTraceStatus.COMPLETE and self.limitation:
            raise ValueError("complete replay trace cannot declare a limitation")
        if self.status is GoldenReplayTraceStatus.PARTIAL and not self.limitation:
            raise ValueError("partial replay trace requires a limitation")
        return self


class GoldenReplayManifest(DomainModel):
    """Credential-free immutable result of one frozen-artifact replay."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    manifest_schema_version: Literal["golden_replay_manifest_v1"] = (
        "golden_replay_manifest_v1"
    )
    replay_id: str = Field(pattern=r"^golden_replay_[0-9a-f]{24}$")
    replay_name: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    asset_id: AssetId
    research_as_of: datetime
    source_artifact_ids: tuple[str, ...] = Field(min_length=1)
    research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    research_episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    research_dataset_sample_id: str = Field(pattern=r"^research_sample_[0-9a-f]{24}$")
    retrieval_ids: tuple[str, ...] = ()
    attribution_ids: tuple[str, ...] = ()
    accepted_claim_count: int = Field(ge=0)
    rejected_claim_count: int = Field(ge=0)
    final_research_claim_count: int = Field(ge=0)
    sector_claims_provided: int = Field(ge=0)
    sector_claims_used: int = Field(ge=0)
    events_provided: int = Field(ge=0)
    events_used: int = Field(ge=0)
    memory_retrieval_count: int = Field(ge=0)
    memory_empty_valid: bool
    memory_status: GoldenReplayMemoryStatus
    temporal_validation_status: GoldenReplayStatus
    provider_call_count: Literal[0] = 0
    llm_call_count: Literal[0] = 0
    versions: tuple[GoldenReplayVersionReference, ...] = Field(min_length=1)
    determinism_checks: tuple[GoldenReplayCheck, ...] = Field(min_length=3)
    leakage_checks: tuple[GoldenReplayCheck, ...] = Field(min_length=5)
    traceability_examples: tuple[GoldenReplayTrace, ...] = Field(min_length=3)
    replay_status: GoldenReplayStatus
    created_at: datetime
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("research_as_of", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require explicit UTC replay timestamps."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Golden replay timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        """Ensure PASS represents all mandatory deterministic checks."""

        groups = (
            self.source_artifact_ids,
            self.retrieval_ids,
            self.attribution_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("Golden replay references must be unique")
        checks = (*self.determinism_checks, *self.leakage_checks)
        if self.replay_status is GoldenReplayStatus.PASS and any(
            item.status is not GoldenReplayStatus.PASS for item in checks
        ):
            raise ValueError("passing replay requires every mandatory check to pass")
        if self.memory_status is GoldenReplayMemoryStatus.EMPTY_VALID:
            if self.memory_retrieval_count or not self.memory_empty_valid:
                raise ValueError("empty-valid Memory cannot contain retrieval results")
        return self
