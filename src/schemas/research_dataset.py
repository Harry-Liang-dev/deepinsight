"""Reference-only point-in-time research dataset contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import Market
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.research_attribution import ResearchEpisodeAttribution
from src.schemas.research_episode import (
    ResearchEpisode,
    ResearchEpisodeVersionReference,
)
from src.schemas.research_state import ResearchStateSnapshot


class ResearchDatasetLabelStatus(StrEnum):
    """Legal Day42 label states before an Outcome factory exists."""

    PENDING = "pending"
    NOT_AVAILABLE = "not_available"


class ResearchDatasetQualityStatus(StrEnum):
    """Overall usability of one immutable research sample."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    EMPTY_VALID = "empty_valid"
    INVALID = "invalid"


class ResearchDatasetComponentStatus(StrEnum):
    """Availability of an optional context component in its source run."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    EMPTY_VALID = "empty_valid"
    NOT_AVAILABLE_IN_SOURCE_RUN = "not_available_in_source_run"


class ResearchDatasetQuality(DomainModel):
    """Explicit sample completeness without turning absence into invalidity."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    status: ResearchDatasetQualityStatus
    state_status: ResearchDatasetComponentStatus
    episode_status: ResearchDatasetComponentStatus
    sector_context_status: ResearchDatasetComponentStatus
    memory_context_status: ResearchDatasetComponentStatus
    attribution_status: ResearchDatasetComponentStatus
    missing_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_quality(self) -> Self:
        """Require explicit reasons for incomplete sample branches."""

        if len(self.missing_reasons) != len(set(self.missing_reasons)):
            raise ValueError("dataset missing reasons must be unique")
        if (
            self.status is ResearchDatasetQualityStatus.AVAILABLE
            and self.missing_reasons
        ):
            raise ValueError("available dataset sample cannot declare missing reasons")
        if (
            self.status
            in {
                ResearchDatasetQualityStatus.PARTIAL,
                ResearchDatasetQualityStatus.INVALID,
            }
            and not self.missing_reasons
        ):
            raise ValueError("incomplete dataset sample requires missing reasons")
        return self


class ResearchDatasetVersionLineage(DomainModel):
    """Central version identity inherited from frozen research artifacts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    research_state_schema_version: str = Field(min_length=1)
    research_state_version: str = Field(min_length=1)
    research_episode_schema_version: str = Field(min_length=1)
    research_episode_trace_quality: str = Field(min_length=1)
    source_dataset_version: str = Field(min_length=1)
    attribution_version: str | None = Field(default=None, min_length=1)
    model_versions: tuple[ResearchEpisodeVersionReference, ...] = ()
    prompt_versions: tuple[ResearchEpisodeVersionReference, ...] = ()
    feature_versions: tuple[ResearchEpisodeVersionReference, ...] = ()


class ResearchDatasetBuildInput(DomainModel):
    """Frozen artifact references accepted by the deterministic builder."""

    research_state: ResearchStateSnapshot
    research_episode: ResearchEpisode
    attribution: ResearchEpisodeAttribution | None = None
    dataset_build_version: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC dataset materialization time."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset created_at must be timezone-aware")
        return value.astimezone(UTC)


class ResearchDatasetSample(DomainModel):
    """One stable, replayable Asset research sample made only of references."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    dataset_schema_version: Literal["research_dataset_sample_v1"] = (
        "research_dataset_sample_v1"
    )
    sample_id: str = Field(pattern=r"^research_sample_[0-9a-f]{24}$")
    asset_id: AssetId
    market: Market
    sector_id: str | None = Field(default=None, min_length=1)
    industry_chain_ids: tuple[str, ...] = ()
    research_as_of: datetime
    research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    research_episode_id: str = Field(pattern=r"^research_episode_[0-9a-f]{24}$")
    data_snapshot_id: str = Field(min_length=1)
    sector_context_id: str | None = Field(default=None, min_length=1)
    memory_context_id: str | None = Field(default=None, min_length=1)
    attribution_bundle_id: str | None = Field(
        default=None,
        pattern=r"^research_attribution_[0-9a-f]{24}$",
    )
    agent_run_ids: tuple[str, ...]
    versions: ResearchDatasetVersionLineage
    label_status: ResearchDatasetLabelStatus
    label_ids: tuple[str, ...] = ()
    quality: ResearchDatasetQuality
    dataset_build_version: str = Field(min_length=1)
    created_at: datetime
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("research_as_of", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require UTC-aware research and build times."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        """Keep references unique and labels empty before Day43."""

        for values in (self.industry_chain_ids, self.agent_run_ids, self.label_ids):
            if len(values) != len(set(values)):
                raise ValueError("dataset sample references must be unique")
        if self.label_ids:
            raise ValueError("Day42 dataset samples cannot contain Outcome labels")
        if self.label_status not in {
            ResearchDatasetLabelStatus.PENDING,
            ResearchDatasetLabelStatus.NOT_AVAILABLE,
        }:
            raise ValueError("unsupported Day42 label status")
        return self


class ResearchDatasetArtifactManifest(DomainModel):
    """Credential-free manifest for one persisted dataset artifact."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    manifest_schema_version: Literal["research_dataset_manifest_v1"] = (
        "research_dataset_manifest_v1"
    )
    manifest_id: str = Field(pattern=r"^research_dataset_manifest_[0-9a-f]{24}$")
    sample_id: str = Field(pattern=r"^research_sample_[0-9a-f]{24}$")
    sample_artifact: str = Field(min_length=1)
    repository_table: Literal["research_dataset_samples"] = "research_dataset_samples"
    dataset_schema_version: str = Field(min_length=1)
    dataset_build_version: str = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_manifest_time(cls, value: datetime) -> datetime:
        """Require UTC-aware manifest creation time."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset manifest created_at must be timezone-aware")
        return value.astimezone(UTC)
