"""Five-level memory request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import AgentStatus, MemoryLevel
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.common import SourceReference


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

    @field_validator("namespace_key", "summary_text", "memory_type", "created_by")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        """Reject values that satisfy length checks with whitespace only."""

        if not value.strip():
            raise ValueError("memory text fields cannot be blank")
        return value


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

    @model_validator(mode="after")
    def reject_empty_asset_filter(self) -> Self:
        """Require an optional asset filter to contain at least one asset."""

        if self.asset_ids == []:
            raise ValueError("asset_ids cannot be empty when supplied")
        return self


class MemorySearchResult(DomainModel):
    """One ranked memory search result."""

    memory_id: str = Field(min_length=1)
    memory_level: MemoryLevel
    namespace_key: str = Field(min_length=1)
    summary_text: str = Field(min_length=1)
    score: float
    effective_ts: datetime
    asset_id: AssetId | None = None
    memory_type: str = Field(min_length=1)
    importance_score: float = Field(ge=0.0, le=1.0)
    source_ref_json: SourceReference
    created_by: str = Field(min_length=1)


class MemorySearchResponse(DomainModel):
    """Collection of ranked memory search results."""

    results: list[MemorySearchResult]
