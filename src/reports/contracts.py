"""Typed contracts for deterministic Phase One report assembly."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from src.agents.contracts import ResearchTaskResult
from src.models.enums import ClaimIntent, ReportType
from src.models.types import DomainModel
from src.schemas.agents import AgentContext
from src.schemas.common import SourceReference
from src.schemas.reports import GenerateReportRequest
from src.schemas.sector_context import SectorContextBundle

STANDARD_SECTION_NAMES = (
    "executive_view",
    "macro_context",
    "fundamentals",
    "technical_text",
    "sentiment",
    "news_events",
    "bull_case",
    "bear_case",
    "risk_review",
    "final_synthesis",
)


class ReportStatement(DomainModel):
    """One attributable fact, inference, or risk statement."""

    text: str = Field(min_length=1)
    citations: list[SourceReference] = Field(min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.FACT
    claim_id: str = Field(min_length=1)
    upstream_claim_ids: tuple[str, ...] = ()
    numeric_literals: tuple[str, ...] = ()
    claim_status: str = "accepted"


class StandardReportSection(DomainModel):
    """One standard section with explicit epistemic categories."""

    section_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    section_order: int = Field(ge=0)
    facts: list[ReportStatement] = Field(default_factory=list)
    inferences: list[ReportStatement] = Field(default_factory=list)
    risk_warnings: list[ReportStatement] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content(self) -> Self:
        """Reject a section without evidence, analysis, risk, or uncertainty."""

        if not any(
            (
                self.facts,
                self.inferences,
                self.risk_warnings,
                self.uncertainties,
            )
        ):
            raise ValueError("report section cannot be empty")
        return self


class ReportAssemblyInput(DomainModel):
    """Validated boundary between Agent coordination and report generation."""

    report_id: str = Field(min_length=1)
    request: GenerateReportRequest
    input_context: AgentContext
    agent_result: ResearchTaskResult
    created_at: datetime
    sector_context: SectorContextBundle | None = None

    @model_validator(mode="after")
    def validate_single_asset_boundary(self) -> Self:
        """Enforce the only report shape implemented in Phase One."""

        if self.request.report_type is not ReportType.SINGLE_ASSET:
            raise ValueError("only single_asset reports are implemented")
        if self.request.asset_ids is None or len(self.request.asset_ids) != 1:
            raise ValueError("single_asset reports require exactly one asset")
        if self.request.asset_ids[0] != self.input_context.asset_id:
            raise ValueError("request asset does not match Agent context")
        if self.request.report_date != self.input_context.report_date:
            raise ValueError("request date does not match Agent context")
        if self.request.market_scope is not self.input_context.market_scope:
            raise ValueError("request market does not match Agent context")
        return self
