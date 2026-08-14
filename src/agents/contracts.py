"""Agent-layer execution contracts for the Phase One research chain."""

from __future__ import annotations

from pydantic import Field, model_validator

from src.memory.contracts import ResearchContextBundle
from src.models.enums import AgentName, AgentStatus, ClaimIntent
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import AgentContext
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.llm import LLMRunMetadata
from src.schemas.memory import MemorySearchRequest
from src.schemas.research_data import ResearchDataBundle


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
    """Resolved provenance retained for one accepted Claim."""

    claim_path: str = Field(min_length=1)
    citations: list[SourceReference] = Field(min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.FACT
    claim_id: str | None = Field(default=None, min_length=1)
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    numeric_literals: tuple[str, ...] = ()


class AgentExecutionResult(DomainModel):
    """Unified, auditable output envelope for every Agent invocation."""

    run_id: str = Field(min_length=1)
    agent_name: AgentName
    status: AgentStatus
    output: JsonObject | None = None
    evidence: list[EvidenceLink] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    llm_run_metadata: LLMRunMetadata | None = None
    error: ErrorInfo | None = None
    rejected_claims: list[JsonObject] = Field(default_factory=list)
    structured_output_attempts: int = Field(default=1, ge=1, le=2)
    repair_attempted: bool = False

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
    data_bundle: ResearchDataBundle | None = None
    context_bundle: ResearchContextBundle | None = None

    @model_validator(mode="after")
    def validate_phase3_bundles(self) -> ResearchTaskRequest:
        """Require aligned Data and Memory bundles or the legacy pair-free path."""

        if (self.data_bundle is None) is not (self.context_bundle is None):
            raise ValueError("Data and Memory bundles must be supplied together")
        if self.data_bundle is None or self.context_bundle is None:
            return self
        metadata = self.context_bundle.retrieval_metadata
        if self.data_bundle.asset_id != self.input_context.asset_id:
            raise ValueError("Data bundle asset does not match Agent context")
        if metadata.asset_id != self.input_context.asset_id:
            raise ValueError("Memory bundle asset does not match Agent context")
        if metadata.market.value != self.input_context.market_scope.value:
            raise ValueError("Memory bundle market does not match Agent context")
        if self.data_bundle.as_of != metadata.as_of:
            raise ValueError("Data and Memory bundle as_of values must match")
        if self.data_bundle.window_end != self.input_context.report_date:
            raise ValueError("Data bundle window must end on the report date")
        return self


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
