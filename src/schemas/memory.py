"""Five-level memory request and response schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import AgentStatus, MemoryLevel, ResearchScopeType
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.common import SourceReference
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind


class LearningMemoryUsageClass(StrEnum):
    """Intended research use of one Learning Memory record."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PERFORMANCE = "performance"


class SemanticMemoryLifecycleStatus(StrEnum):
    """Explicit lifecycle for durable semantic knowledge candidates."""

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    RETIRED = "retired"


class EpisodicMemoryContentKind(StrEnum):
    """Structured Episode content eligible for selective Memory storage."""

    VALIDATED_CLAIM = "validated_claim"
    THESIS = "thesis"
    RISK = "risk"
    CATALYST = "catalyst"
    IMPORTANT_EVENT = "important_event"
    STATE_REFERENCE = "state_reference"
    EPISODE_REFERENCE = "episode_reference"


_SCOPE_PREFIX = {
    ResearchScopeType.GLOBAL: "GLOBAL:",
    ResearchScopeType.MACRO: "MACRO:",
    ResearchScopeType.SECTOR: "SECTOR:",
    ResearchScopeType.INDUSTRY_CHAIN: "CHAIN:",
    ResearchScopeType.ASSET: "ASSET:",
    ResearchScopeType.RESEARCH_EPISODE: "EPISODE:",
}
_CLAIM_CONTENT = frozenset(
    {
        EpisodicMemoryContentKind.VALIDATED_CLAIM,
        EpisodicMemoryContentKind.THESIS,
        EpisodicMemoryContentKind.RISK,
        EpisodicMemoryContentKind.CATALYST,
    }
)


class LearningMemoryMetadata(DomainModel):
    """Versioned Scope, Episode, temporal, and provenance metadata."""

    schema_version: Literal["learning_memory_metadata_v1"] = (
        "learning_memory_metadata_v1"
    )
    memory_version: str = Field(default="learning_memory_v1", min_length=1)
    usage_class: LearningMemoryUsageClass
    scope_type: ResearchScopeType
    scope_id: str = Field(min_length=3, max_length=160)
    parent_scope_id: str | None = Field(default=None, max_length=160)
    episode_id: str | None = Field(
        default=None,
        pattern=r"^research_episode_[0-9a-f]{24}$",
    )
    research_state_id: str | None = Field(
        default=None,
        pattern=r"^research_state_[0-9a-f]{24}$",
    )
    source_claim_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    temporal: TemporalMetadata
    content_kind: EpisodicMemoryContentKind | None = None
    semantic_status: SemanticMemoryLifecycleStatus | None = None
    outcome_id: str | None = Field(default=None, min_length=1)
    factor_reference: str | None = Field(default=None, min_length=1)
    research_reference: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_learning_metadata(self) -> Self:
        """Keep Scope identity and usage-specific lifecycle explicit."""

        if not self.scope_id.startswith(_SCOPE_PREFIX[self.scope_type]):
            raise ValueError("Learning Memory scope_id does not match scope_type")
        if self.scope_type is ResearchScopeType.GLOBAL:
            if self.parent_scope_id is not None:
                raise ValueError("GLOBAL Learning Memory scope cannot have a parent")
        elif self.parent_scope_id is None:
            raise ValueError("non-GLOBAL Learning Memory scope requires a parent")
        if self.scope_id == self.parent_scope_id:
            raise ValueError("Learning Memory scope cannot parent itself")
        if len(self.source_claim_ids) != len(set(self.source_claim_ids)):
            raise ValueError("source_claim_ids must be unique")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source_event_ids must be unique")
        if any(not value.strip() for value in self.source_claim_ids):
            raise ValueError("source_claim_ids cannot contain blank values")
        if any(not value.strip() for value in self.source_event_ids):
            raise ValueError("source_event_ids cannot contain blank values")
        if self.temporal.source_kind is not TemporalSourceKind.MEMORY:
            raise ValueError("Learning Memory temporal source_kind must be memory")
        if self.temporal.available_at is None:
            raise ValueError("Learning Memory requires temporal.available_at")
        if self.scope_type is ResearchScopeType.RESEARCH_EPISODE and (
            self.episode_id is None or self.scope_id != f"EPISODE:{self.episode_id}"
        ):
            raise ValueError("Episode scope must match episode_id")

        if self.usage_class is LearningMemoryUsageClass.EPISODIC:
            if self.episode_id is None or self.research_state_id is None:
                raise ValueError("episodic Memory requires Episode and State linkage")
            if self.content_kind is None:
                raise ValueError("episodic Memory requires a structured content kind")
            if self.semantic_status is not None:
                raise ValueError("episodic Memory cannot declare semantic lifecycle")
            if any(
                value is not None
                for value in (
                    self.outcome_id,
                    self.factor_reference,
                    self.research_reference,
                )
            ):
                raise ValueError(
                    "episodic Memory cannot declare performance references"
                )
            if self.content_kind in _CLAIM_CONTENT and not self.source_claim_ids:
                raise ValueError(
                    "claim-based episodic Memory requires source Claim IDs"
                )
            if (
                self.content_kind is EpisodicMemoryContentKind.IMPORTANT_EVENT
                and not self.source_event_ids
            ):
                raise ValueError("event episodic Memory requires source Event IDs")
        elif self.usage_class is LearningMemoryUsageClass.SEMANTIC:
            if self.semantic_status is None:
                raise ValueError("semantic Memory requires an explicit lifecycle")
            if self.content_kind is not None:
                raise ValueError("semantic Memory cannot masquerade as Episode content")
            if (
                self.episode_id is not None
                and self.semantic_status is not SemanticMemoryLifecycleStatus.CANDIDATE
            ):
                raise ValueError(
                    "single-Episode semantic Memory must remain a candidate"
                )
        else:
            if self.episode_id is None:
                raise ValueError("performance Memory requires an Episode reference")
            if self.content_kind is not None or self.semantic_status is not None:
                raise ValueError(
                    "performance Memory cannot declare Episode content or "
                    "semantic state"
                )
        return self


class MemoryWriteRequest(DomainModel):
    """Validated request for one attributable memory write."""

    memory_level: MemoryLevel
    namespace_key: str = Field(min_length=1)
    effective_ts: datetime
    summary_text: str = Field(min_length=1)
    asset_id: AssetId | None = None
    memory_type: str = Field(default="generic", min_length=1)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    source_ref_json: SourceReference
    created_by: str = Field(default="system", min_length=1)
    metadata: LearningMemoryMetadata | None = None

    @field_validator("namespace_key", "summary_text", "memory_type", "created_by")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        """Reject values that satisfy length checks with whitespace only."""

        if not value.strip():
            raise ValueError("memory text fields cannot be blank")
        return value

    @field_validator("effective_ts")
    @classmethod
    def normalize_effective_ts(cls, value: datetime) -> datetime:
        """Require public Memory effective time to be UTC-aware."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory effective_ts must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_learning_scope(self) -> Self:
        """Align optional structured Scope metadata with legacy isolation fields."""

        if self.metadata is None:
            return self
        if self.namespace_key != self.metadata.scope_id:
            raise ValueError("namespace_key must match Learning Memory scope_id")
        if self.metadata.scope_type is ResearchScopeType.ASSET:
            expected_scope = None if self.asset_id is None else f"ASSET:{self.asset_id}"
            if self.asset_id is None or self.metadata.scope_id != expected_scope:
                raise ValueError("ASSET Memory scope must match asset_id")
        effective_from = self.metadata.temporal.effective_from
        if isinstance(effective_from, datetime):
            if effective_from != self.effective_ts:
                raise ValueError(
                    "Learning Memory temporal.effective_from must match effective_ts"
                )
        elif isinstance(effective_from, date):
            if effective_from != self.effective_ts.date():
                raise ValueError(
                    "Learning Memory effective date must match effective_ts date"
                )
        return self


class MemoryWriteResult(DomainModel):
    """Memory identifier and vector mapping returned after a write."""

    memory_id: str = Field(min_length=1)
    faiss_namespace: str = Field(min_length=1)
    faiss_vector_id: int = Field(ge=0)
    status: AgentStatus = AgentStatus.OK


class MemorySearchRequest(DomainModel):
    """Semantic memory search filters."""

    memory_levels: list[MemoryLevel] = Field(min_length=1)
    namespace_keys: list[str] = Field(min_length=1)
    query_text: str = Field(min_length=1)
    top_k: int = Field(default=8, gt=0)
    time_decay_days: int | None = Field(default=None, gt=0)
    min_importance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    asset_ids: list[AssetId] | None = None
    scope_ids: list[str] | None = None
    usage_classes: list[LearningMemoryUsageClass] | None = None
    episode_ids: list[str] | None = None
    as_of: datetime | None = None

    @field_validator("namespace_keys")
    @classmethod
    def reject_blank_namespaces(cls, value: list[str]) -> list[str]:
        """Reject blank namespace filters."""

        if any(not namespace.strip() for namespace in value):
            raise ValueError("namespace keys cannot be blank")
        return value

    @field_validator("query_text")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject a whitespace-only semantic query."""

        if not value.strip():
            raise ValueError("query text cannot be blank")
        return value

    @field_validator("as_of")
    @classmethod
    def normalize_optional_as_of(cls, value: datetime | None) -> datetime | None:
        """Normalize an explicit historical cutoff while retaining current search."""

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory search as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def reject_empty_asset_filter(self) -> Self:
        """Require an optional asset filter to contain at least one asset."""

        for name, value in (
            ("asset_ids", self.asset_ids),
            ("scope_ids", self.scope_ids),
            ("usage_classes", self.usage_classes),
            ("episode_ids", self.episode_ids),
        ):
            if value == []:
                raise ValueError(f"{name} cannot be empty when supplied")
        return self


class MemorySearchResult(DomainModel):
    """One ranked memory search result."""

    memory_id: str = Field(min_length=1)
    memory_level: MemoryLevel
    namespace_key: str = Field(min_length=1)
    summary_text: str = Field(min_length=1)
    score: float
    effective_ts: datetime
    available_at: datetime | None = None
    asset_id: AssetId | None = None
    memory_type: str = Field(min_length=1)
    importance_score: float = Field(ge=0.0, le=1.0)
    source_ref_json: SourceReference
    created_by: str = Field(min_length=1)
    metadata: LearningMemoryMetadata | None = None


class MemorySearchResponse(DomainModel):
    """Collection of ranked memory search results."""

    results: list[MemorySearchResult]
