"""Tests for agent, manager, and report contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import (
    AgentName,
    AgentStatus,
    ReportMarketScope,
    ReportType,
    TaskStatus,
)
from src.models.identifiers import AssetId
from src.schemas.agents import (
    AgentContext,
    AgentRequest,
    AnalystAnalysis,
    AnalystResponse,
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    FundamentalAnalysis,
    FundamentalAnalystResponse,
    ResearchManagerRequest,
    ResearchSummary,
    RiskManagerRequest,
    RiskManagerResponse,
)
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.reports import GenerateReportRequest, ReportSection, ResearchReport

REPORT_DATE = date(2026, 7, 23)
NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _agent_context() -> AgentContext:
    """Build a minimal reusable agent context."""
    return AgentContext(
        report_date=REPORT_DATE,
        market_scope=ReportMarketScope.US,
        asset_id=AssetId("US:AAPL"),
        structured_features={"revenue_yoy": 0.081},
        retrieved_documents=[
            RetrievedDocument(
                document_id="doc-1",
                chunk_id="chunk-1",
                title="10-Q filing",
                chunk_text="Revenue increased.",
            )
        ],
    )


def _fundamental_response() -> FundamentalAnalystResponse:
    """Build a valid fundamental analyst response."""
    return FundamentalAnalystResponse(
        status=AgentStatus.OK,
        analysis=FundamentalAnalysis(
            quality_score=0.86,
            growth_score=0.74,
            valuation_score=0.58,
            key_points=["Revenue growth remains positive."],
            risk_points=["Valuation remains elevated."],
            supporting_citations=[
                SourceReference(document_id="doc-1", excerpt_ref="chunk-1")
            ],
        ),
    )


def test_agent_and_research_manager_contracts_compose() -> None:
    """Analyst responses should feed the Research Manager request."""
    technical = AnalystResponse(
        agent_name=AgentName.TECHNICAL_TEXT_ANALYST,
        status=AgentStatus.OK,
        analysis=AnalystAnalysis(key_points=["Trend remains constructive."]),
    )
    request = ResearchManagerRequest(
        input_context=_agent_context(),
        analyst_outputs=[_fundamental_response(), technical],
    )

    assert len(request.analyst_outputs) == 2


def test_common_agent_and_manager_requests_compose() -> None:
    """Typed outputs should become the next manager stage's inputs."""
    context = _agent_context()
    analyst_output = _fundamental_response()
    agent_request = AgentRequest(
        run_id="run-1",
        agent_name=AgentName.FUNDAMENTAL_ANALYST,
        model_name="gpt-5",
        input_context=context,
    )
    summary = ResearchSummary(summary_points=["Fundamentals remain resilient."])
    bull = BullManagerResponse(
        bull_thesis=["Margins remain resilient."],
        conditions_required=["Demand remains stable."],
        invalidators=["Guidance is reduced."],
        confidence=0.7,
    )
    bear = BearManagerResponse(
        bear_thesis=["Valuation is elevated."],
        conditions_required=["Growth continues to slow."],
        invalidators=["Growth reaccelerates."],
        confidence=0.6,
    )

    bull_request = BullManagerRequest(
        input_context=context,
        analyst_outputs=[analyst_output],
        research_summary=summary,
    )
    bear_request = BearManagerRequest(
        input_context=context,
        analyst_outputs=[analyst_output],
        research_summary=summary,
    )
    risk_request = RiskManagerRequest(
        input_context=context,
        analyst_outputs=[analyst_output],
        research_summary=summary,
        bull_output=bull,
        bear_output=bear,
    )

    assert agent_request.agent_name is AgentName.FUNDAMENTAL_ANALYST
    assert bull_request.research_summary == bear_request.research_summary
    assert risk_request.bull_output.confidence == 0.7


def test_fundamental_scores_are_bounded() -> None:
    """Analyst scores outside zero-to-one should be rejected."""
    with pytest.raises(ValidationError):
        FundamentalAnalysis(
            quality_score=1.1,
            growth_score=0.5,
            valuation_score=0.5,
            key_points=[],
            risk_points=[],
        )


def test_manager_confidence_and_risk_scores_are_bounded() -> None:
    """Manager confidence and narrative risk scores use zero-to-one bounds."""
    with pytest.raises(ValidationError):
        BullManagerResponse(
            bull_thesis=[],
            conditions_required=[],
            invalidators=[],
            confidence=-0.1,
        )
    with pytest.raises(ValidationError):
        RiskManagerResponse(
            confirmed_risks=[],
            scenario_risks=[],
            watch_items=[],
            narrative_risk_score=1.1,
        )


def test_bull_and_bear_outputs_follow_master_spec() -> None:
    """Constructive and cautious thesis outputs should retain their semantics."""
    bull = BullManagerResponse(
        bull_thesis=["Margins remain resilient."],
        conditions_required=["Demand remains stable."],
        invalidators=["Guidance is reduced."],
        confidence=0.7,
    )
    bear = BearManagerResponse(
        bear_thesis=["Valuation leaves little room for error."],
        conditions_required=["Growth continues to slow."],
        invalidators=["Growth reaccelerates."],
        confidence=0.6,
    )

    assert bull.confidence > bear.confidence


def test_generate_report_request_validates_enums_and_dates() -> None:
    """Report requests should use typed market and report values."""
    request = GenerateReportRequest(
        report_date=REPORT_DATE,
        market_scope=ReportMarketScope.US,
        report_type=ReportType.SINGLE_ASSET,
        asset_ids=[AssetId("US:AAPL")],
        include_sections=["executive_view", "risk_review"],
    )

    assert request.report_date == REPORT_DATE
    assert request.asset_ids is not None
    assert request.asset_ids[0].market.value == "US"

    with pytest.raises(ValidationError):
        GenerateReportRequest.model_validate(
            {
                "report_date": "not-a-date",
                "market_scope": "US",
                "report_type": "trade_signal",
                "asset_ids": ["US:AAPL"],
                "include_sections": [],
            }
        )


def test_final_report_serializes_phase_two_fields_as_null() -> None:
    """Reserved fields should remain nullable and uninterpreted in Phase One."""
    section = ReportSection(
        report_id="rep-1",
        section_name="executive_view",
        section_order=1,
        section_markdown="## Executive view",
        citations=[SourceReference(document_id="doc-1")],
    )
    report = ResearchReport(
        report_id="rep-1",
        report_date=REPORT_DATE,
        market_scope=ReportMarketScope.US,
        report_type=ReportType.SINGLE_ASSET,
        asset_id=AssetId("US:AAPL"),
        title="AAPL Research Note",
        final_recommendation="Maintain a constructive but risk-aware stance.",
        report_markdown="# AAPL Research Note",
        report_json={"executive_view": "Constructive"},
        source_trace=[SourceReference(document_id="doc-1")],
        sections=[section],
        status=TaskStatus.COMPLETED,
        created_at=NOW,
    )
    serialized = report.model_dump(mode="json")

    assert serialized["asset_id"] == "US:AAPL"
    assert serialized["p2_strategy_hint_json"] is None
    assert serialized["p2_signal_stub_json"] is None


def test_research_summary_uses_only_minimum_unconfirmed_fields() -> None:
    """The provisional Research Manager schema should remain intentionally small."""
    summary = ResearchSummary(
        summary_points=["Growth is positive but slowing."],
        conflicts=["Valuation and quality signals diverge."],
    )

    assert summary.uncertainties == []
