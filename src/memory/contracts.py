"""Point-in-time contracts for structured research Memory context."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import Market, MarketScope, MemoryLevel, ResearchScopeType
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.common import SourceReference
from src.schemas.memory import LearningMemoryMetadata, LearningMemoryUsageClass
from src.schemas.research_attribution import MemoryRetrievalCandidate
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class ResearchContextSection(StrEnum):
    """Stable sections exposed by ``ResearchContextBundle``."""

    CURRENT_SNAPSHOT = "current_snapshot"
    MACRO_EVENTS = "macro_events"
    ASSET_EVENTS = "asset_events"
    PRIOR_RESEARCH = "prior_research"
    PRIOR_RISK = "prior_risk"
    HISTORICAL_ANALOGS = "historical_analogs"
    REGIME_CONTEXT = "regime_context"


class RetrievalStatus(StrEnum):
    """Overall point-in-time retrieval coverage."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"


class MissingContextReason(StrEnum):
    """Explicit reason why a context section has no Memory evidence."""

    NO_RELEVANT_MEMORY = "no_relevant_memory"
    NOT_REQUESTED = "not_requested"


class ResearchContextRequest(DomainModel):
    """Time-safe filters used to build one research context bundle."""

    query_text: str = Field(min_length=1)
    as_of: datetime
    market: Market
    namespace_keys: list[str] = Field(min_length=1)
    asset_id: AssetId | None = None
    memory_levels: list[MemoryLevel] = Field(
        default_factory=lambda: list(MemoryLevel),
        min_length=1,
    )
    top_k_per_section: int = Field(default=4, gt=0)
    min_importance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    include_prior_reports: bool = True
    current_report_id: str | None = None
    scope_ids: list[str] | None = None
    scope_types: list[ResearchScopeType] | None = None
    usage_classes: list[LearningMemoryUsageClass] | None = None
    episode_ids: list[str] | None = None

    @field_validator("query_text")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject a whitespace-only semantic query."""

        if not value.strip():
            raise ValueError("query_text cannot be blank")
        return value

    @field_validator("namespace_keys")
    @classmethod
    def reject_blank_namespaces(cls, value: list[str]) -> list[str]:
        """Reject blank namespace isolation keys."""

        if any(not namespace.strip() for namespace in value):
            raise ValueError("namespace_keys cannot contain blank values")
        return value

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        """Require an unambiguous timezone-aware point-in-time cutoff."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @field_validator("current_report_id")
    @classmethod
    def reject_blank_report_id(cls, value: str | None) -> str | None:
        """Reject a supplied whitespace-only current report identifier."""

        if value is not None and not value.strip():
            raise ValueError("current_report_id cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_asset_market(self) -> Self:
        """Require an optional asset to belong to the requested market."""

        if self.asset_id is not None and self.asset_id.market is not self.market:
            raise ValueError("asset_id market does not match requested market")
        for name, value in (
            ("scope_ids", self.scope_ids),
            ("scope_types", self.scope_types),
            ("usage_classes", self.usage_classes),
            ("episode_ids", self.episode_ids),
        ):
            if value == []:
                raise ValueError(f"{name} cannot be empty when supplied")
        return self


class ResearchContextMemory(DomainModel):
    """One attributable Memory item selected for a context section."""

    memory_id: str = Field(min_length=1)
    section: ResearchContextSection
    memory_level: MemoryLevel
    namespace_key: str = Field(min_length=1)
    asset_id: AssetId | None = None
    market: MarketScope
    memory_type: str = Field(min_length=1)
    summary_text: str = Field(min_length=1)
    effective_ts: datetime
    available_at: datetime | None = None
    importance_score: float = Field(ge=0.0, le=1.0)
    retrieval_score: float
    retrieval_reason: str = Field(min_length=1)
    source: SourceReference
    created_by: str = Field(min_length=1)
    metadata: LearningMemoryMetadata | None = None

    @field_validator("effective_ts", "available_at")
    @classmethod
    def normalize_effective_time(cls, value: datetime | None) -> datetime | None:
        """Require unambiguous UTC time before Memory crosses its boundary."""

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory effective_ts must be timezone-aware")
        return value.astimezone(UTC)


class MissingContext(DomainModel):
    """Explicit absence record for one structured context section."""

    section: ResearchContextSection
    reason: MissingContextReason
    detail: str = Field(min_length=1)
    requested_levels: list[MemoryLevel] = Field(min_length=1)


class RetrievalMetadata(DomainModel):
    """Auditable metadata for one point-in-time retrieval operation."""

    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    as_of: datetime
    market: Market
    asset_id: AssetId | None = None
    namespace_keys: list[str] = Field(min_length=1)
    requested_levels: list[MemoryLevel] = Field(min_length=1)
    current_report_id: str | None = None
    scope_ids: list[str] | None = None
    scope_types: list[ResearchScopeType] | None = None
    usage_classes: list[LearningMemoryUsageClass] | None = None
    episode_ids: list[str] | None = None
    min_importance_score: float = Field(ge=0.0, le=1.0)
    top_k_per_section: int = Field(gt=0)
    snapshot_id: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    excluded_future_count: int = Field(ge=0)
    excluded_namespace_count: int = Field(ge=0)
    excluded_asset_count: int = Field(ge=0)
    excluded_market_count: int = Field(ge=0)
    excluded_importance_count: int = Field(ge=0)
    excluded_expired_count: int = Field(ge=0)
    excluded_current_report_count: int = Field(ge=0)
    excluded_learning_metadata_count: int = Field(default=0, ge=0)
    eligible_candidates: tuple[MemoryRetrievalCandidate, ...] = ()
    section_counts: dict[ResearchContextSection, int]
    status: RetrievalStatus
    no_relevant_memory: bool
    empty_valid: bool = False

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        """Normalize the retrieval cutoff to aware UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieval as_of must be timezone-aware")
        return value.astimezone(UTC)


class ResearchContextBundle(DomainModel):
    """Structured, attributable context supplied by the Memory layer."""

    schema_version: str = Field(default="research_context_v1", min_length=1)
    current_snapshot: list[ResearchContextMemory]
    macro_events: list[ResearchContextMemory]
    asset_events: list[ResearchContextMemory]
    prior_research: list[ResearchContextMemory]
    prior_risk: list[ResearchContextMemory]
    historical_analogs: list[ResearchContextMemory]
    regime_context: list[ResearchContextMemory]
    retrieval_metadata: RetrievalMetadata
    missing_context: list[MissingContext]

    @model_validator(mode="after")
    def validate_temporal_boundary(self) -> Self:
        """Require one aware cutoff and reject future Memory in every section."""

        as_of = self.retrieval_metadata.as_of
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("ResearchContextBundle as_of must be timezone-aware")
        items = [
            item
            for section in ResearchContextSection
            for item in self.items_for_section(section)
        ]
        for item in items:
            validate_temporal_access(
                TemporalMetadata(
                    event_time=item.effective_ts,
                    available_at=item.available_at or item.effective_ts,
                    effective_from=item.effective_ts,
                ),
                as_of,
            )
            if item.metadata is not None:
                validate_temporal_access(item.metadata.temporal, as_of)
        return self

    def items_for_section(
        self,
        section: ResearchContextSection,
    ) -> list[ResearchContextMemory]:
        """Return a copy of the items belonging to one stable section."""

        return list(getattr(self, section.value))
