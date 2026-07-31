"""Agent-layer execution contracts for the Phase One research chain."""

from __future__ import annotations

from pydantic import Field, model_validator

from src.models.enums import AgentName, AgentStatus
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import AgentContext
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.memory import MemorySearchRequest


class PromptTemplate(DomainModel):
    """One versioned system prompt loaded from configuration."""

    name: AgentName
    version: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)


class AgentInvocation(DomainModel):
    """Unified input supplied to every analyst and manager agent."""

    run_id: str = Field(min_length=1)
    report_id: str | None = None
    model_name: str = Field(min_length=1)
    input_payload: JsonObject
    memory_query: MemorySearchRequest | None = None


class EvidenceLink(DomainModel):
    """Evidence retained for one output claim identified by JSON path."""

    claim_path: str = Field(min_length=1)
    citations: list[SourceReference] = Field(min_length=1)


class AgentExecutionResult(DomainModel):
    """Unified, auditable output envelope for every Agent invocation."""

    run_id: str = Field(min_length=1)
    agent_name: AgentName
    status: AgentStatus
    output: JsonObject | None = None
    evidence: list[EvidenceLink] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> AgentExecutionResult:
        """Keep successful outputs and failed errors mutually consistent."""

        if self.status is AgentStatus.OK:
            if self.output is None or self.error is not None:
                raise ValueError("successful Agent result requires output and no error")
        elif self.output is not None or self.error is None:
            raise ValueError("failed Agent result requires an error and no output")
        return self


class ResearchTaskRequest(DomainModel):
    """Input for the fixed Phase One multi-Agent research chain."""

    task_id: str = Field(min_length=1)
    report_id: str | None = None
    model_name: str = Field(min_length=1)
    input_context: AgentContext
    memory_query: MemorySearchRequest | None = None


class ResearchTaskResult(DomainModel):
    """Complete result of one fixed Phase One Agent collaboration."""

    task_id: str = Field(min_length=1)
    status: AgentStatus
    analyst_results: dict[AgentName, AgentExecutionResult]
    research_manager: AgentExecutionResult | None = None
    bull_manager: AgentExecutionResult | None = None
    bear_manager: AgentExecutionResult | None = None
    risk_manager: AgentExecutionResult | None = None
    missing_agents: list[AgentName] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
