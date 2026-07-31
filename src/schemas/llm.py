"""Structured LLM gateway request and response schemas."""

from __future__ import annotations

from pydantic import Field

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
