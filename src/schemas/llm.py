"""Structured LLM gateway request and response schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from src.models.enums import AgentStatus
from src.models.types import DomainModel, JsonObject
from src.schemas.common import ErrorInfo


class LLMRequest(DomainModel):
    """Provider-independent structured LLM request."""

    model: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    input_payload: JsonObject


class LLMUsage(DomainModel):
    """Token usage reported by an LLM provider."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class LLMResponse(DomainModel):
    """Provider-independent structured LLM response."""

    status: AgentStatus
    model: str = Field(min_length=1)
    content: JsonObject
    usage: LLMUsage | None = None
    error: ErrorInfo | None = None


class LLMRunMetadata(DomainModel):
    """Provider-independent, credential-free metadata for one LLM run."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    cache_hit: bool
    retry_count: int = Field(ge=0)
    timestamp: datetime
    schema_version: str = Field(min_length=1)
    remote_storage_enabled: bool
    cache_read_status: Literal["hit", "miss", "degraded"] = "miss"
    cache_write_status: Literal["not_attempted", "success", "degraded"] = (
        "not_attempted"
    )
    cache_retry_count: int = Field(default=0, ge=0)
    cache_read_error_type: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$",
    )
    cache_write_error_type: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$",
    )
    structured_output_attempts: int = Field(default=1, ge=1, le=2)
    repair_attempted: bool = False

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Normalize the auditable run timestamp to timezone-aware UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LLM run timestamp requires a timezone")
        return value.astimezone(UTC)
