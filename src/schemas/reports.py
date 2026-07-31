"""Research request, section, and final report schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from src.models.enums import ReportMarketScope, ReportType, TaskStatus
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject
from src.schemas.common import SourceReference


class GenerateReportRequest(DomainModel):
    """Phase One report generation request."""

    report_date: date
    market_scope: ReportMarketScope
    report_type: ReportType
    asset_ids: list[AssetId] | None = Field(default=None, min_length=1)
    language: str = Field(default="en", min_length=2)
    include_sections: list[str] = Field(min_length=1)
    force_refresh: bool = False


class ReportSection(DomainModel):
    """Ordered Markdown section in a research report."""

    report_id: str = Field(min_length=1)
    section_name: str = Field(min_length=1)
    section_order: int = Field(ge=0)
    section_markdown: str = Field(min_length=1)
    citations: list[SourceReference] = Field(default_factory=list)


class ResearchReport(DomainModel):
    """Final standardized Phase One research report."""

    report_id: str = Field(min_length=1)
    report_date: date
    market_scope: ReportMarketScope
    report_type: ReportType
    asset_id: AssetId | None = None
    title: str = Field(min_length=1)
    thesis_bull_summary: str | None = None
    thesis_bear_summary: str | None = None
    risk_summary: str | None = None
    final_recommendation: str = Field(min_length=1)
    confidence_band: str | None = None
    report_markdown: str = Field(min_length=1)
    report_json: JsonObject
    source_trace: list[SourceReference] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    status: TaskStatus
    created_at: datetime
    p2_strategy_hint_json: JsonObject | None = None
    p2_signal_stub_json: JsonObject | None = None
