"""Analyst and manager agent input and output contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from src.models.enums import AgentName, AgentStatus, ReportMarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.memory import MemorySearchResult


class AgentContext(DomainModel):
    """Evidence and structured features supplied to an agent."""

    report_date: date
    market_scope: ReportMarketScope
    asset_id: AssetId
    structured_features: JsonObject
    retrieved_memories: list[MemorySearchResult] = Field(default_factory=list)
    retrieved_documents: list[RetrievedDocument] = Field(default_factory=list)


class AgentRequest(DomainModel):
    """Common validated request for a Phase One agent."""

    run_id: str = Field(min_length=1)
    agent_name: AgentName
    model_name: str = Field(min_length=1)
    input_context: AgentContext


class FundamentalAnalysis(DomainModel):
    """Fundamental analyst output defined by MASTER_SPEC."""

    quality_score: float = Field(ge=0.0, le=1.0)
    growth_score: float = Field(ge=0.0, le=1.0)
    valuation_score: float = Field(ge=0.0, le=1.0)
    facts: list[str] = Field(default_factory=list)
    key_points: list[str]
    risk_points: list[str]
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)


class FundamentalAnalystResponse(DomainModel):
    """Fundamental analyst response envelope."""

    agent_name: Literal[AgentName.FUNDAMENTAL_ANALYST] = AgentName.FUNDAMENTAL_ANALYST
    status: AgentStatus
    analysis: FundamentalAnalysis


class AnalystAnalysis(DomainModel):
    """Minimum common output for analyst roles without a fixed schema."""

    facts: list[str] = Field(default_factory=list)
    key_points: list[str]
    risk_points: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)


class AnalystResponse(DomainModel):
    """Response envelope for non-fundamental analyst roles."""

    agent_name: Literal[
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    ]
    status: AgentStatus
    analysis: AnalystAnalysis


type AnalystOutput = FundamentalAnalystResponse | AnalystResponse


class ResearchManagerRequest(DomainModel):
    """Research Manager input after all analyst roles complete."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)


class ResearchSummary(DomainModel):
    """Minimum synthesis contract for the Research Manager."""

    summary_points: list[str]
    conflicts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)


class ResearchManagerResponse(DomainModel):
    """Research Manager response envelope."""

    agent_name: Literal[AgentName.RESEARCH_MANAGER] = AgentName.RESEARCH_MANAGER
    status: AgentStatus
    analysis: ResearchSummary


class BullManagerRequest(DomainModel):
    """Bull Manager evidence and Research Manager synthesis."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary


class BullManagerResponse(DomainModel):
    """Constructive thesis output defined by MASTER_SPEC."""

    bull_thesis: list[str]
    conditions_required: list[str]
    invalidators: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class BearManagerRequest(DomainModel):
    """Bear Manager evidence and Research Manager synthesis."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary


class BearManagerResponse(DomainModel):
    """Cautious thesis output defined by MASTER_SPEC."""

    bear_thesis: list[str]
    conditions_required: list[str]
    invalidators: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class RiskManagerRequest(DomainModel):
    """Risk Manager input after constructive and cautious review."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary
    bull_output: BullManagerResponse
    bear_output: BearManagerResponse


class RiskManagerResponse(DomainModel):
    """Risk review output defined by MASTER_SPEC."""

    confirmed_risks: list[str]
    scenario_risks: list[str]
    watch_items: list[str]
    narrative_risk_score: float = Field(ge=0.0, le=1.0)
