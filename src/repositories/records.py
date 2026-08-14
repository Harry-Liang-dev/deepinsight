"""Repository-owned persistence records without public domain counterparts."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import (
    AgentName,
    IngestionJobType,
    MarketScope,
    MemoryLevel,
    TaskStatus,
)
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.evaluation import EvaluationResult
from src.schemas.reports import GenerateReportRequest


class PersistenceRecord(BaseModel):
    """Strict base model for records owned by the DuckDB layer."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceRegistryRecord(PersistenceRecord):
    """Configured external source metadata stored in ``source_registry``."""

    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    market_scope: MarketScope
    source_type: str = Field(min_length=1)
    auth_mode: str = Field(min_length=1)
    base_url: str | None = None
    enabled: bool = True
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryItemRecord(PersistenceRecord):
    """Complete DuckDB sidecar record for one Memory item."""

    memory_id: str = Field(min_length=1)
    memory_level: MemoryLevel
    namespace_key: str = Field(min_length=1)
    asset_id: AssetId | None = None
    effective_ts: datetime
    memory_type: str = Field(min_length=1)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    summary_text: str = Field(min_length=1)
    source_ref: SourceReference | None = None
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    faiss_namespace: str = Field(min_length=1)
    faiss_vector_id: int = Field(ge=0)
    created_by: str = Field(min_length=1)
    created_at: datetime | None = None
    expires_at: datetime | None = None


class AgentRunRecord(PersistenceRecord):
    """Auditable persistence record for one Agent invocation."""

    run_id: str = Field(min_length=1)
    report_id: str | None = None
    agent_name: AgentName
    agent_role: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_template_ver: str = Field(min_length=1)
    input_payload: JsonObject
    retrieved_context: JsonObject | None = None
    output_payload: JsonObject | None = None
    status: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cache_hit: bool = False
    error_message: str | None = None
    created_at: datetime | None = None


class LLMCacheRecord(PersistenceRecord):
    """Provider-independent structured LLM cache record."""

    cache_key: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_hash: str = Field(min_length=1)
    response: JsonObject
    created_at: datetime | None = None
    expires_at: datetime | None = None


class IngestionJobRecord(PersistenceRecord):
    """Persistence record for one ingestion job lifecycle."""

    job_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    job_type: IngestionJobType
    market_scope: MarketScope
    status: str = Field(min_length=1)
    target_date: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rows_written: int = Field(default=0, ge=0)
    error_message: str | None = None
    created_at: datetime | None = None


class ReportJobRecord(PersistenceRecord):
    """Durable request and lifecycle state for one report job."""

    job_id: str = Field(min_length=1)
    request: GenerateReportRequest
    status: TaskStatus
    report_id: str | None = None
    error: ErrorInfo | None = None
    attempt_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationRecord(PersistenceRecord):
    """Repository-owned row mapping for one complete evaluation."""

    evaluation_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    overall_score: float = Field(ge=0.0, le=1.0)
    deterministic_score: float = Field(ge=0.0, le=1.0)
    judge_score: float = Field(ge=0.0, le=1.0)
    result: EvaluationResult
    created_at: datetime
