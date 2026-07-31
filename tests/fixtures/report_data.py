"""Deterministic structured Agent output for report tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from src.agents import AgentExecutionResult, EvidenceLink, ResearchTaskResult
from src.models.enums import (
    AgentName,
    AgentStatus,
    MemoryLevel,
    ReportMarketScope,
    ReportType,
)
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.reports import STANDARD_SECTION_NAMES, ReportAssemblyInput
from src.schemas.agents import (
    AgentContext,
    AnalystAnalysis,
    AnalystResponse,
    BearManagerResponse,
    BullManagerResponse,
    FundamentalAnalysis,
    FundamentalAnalystResponse,
    ResearchManagerResponse,
    ResearchSummary,
    RiskManagerResponse,
)
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.memory import MemorySearchResult
from src.schemas.reports import GenerateReportRequest

NOW = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)
ASSET_ID = AssetId("US:AAPL")


def make_report_input() -> ReportAssemblyInput:
    """Return one complete, repeatedly cited single-asset report input."""

    citation = SourceReference(document_id="doc-1", excerpt_ref="chunk-1")
    context = AgentContext(
        report_date=date(2026, 7, 31),
        market_scope=ReportMarketScope.US,
        asset_id=ASSET_ID,
        structured_features={
            "revenue_yoy": 0.1,
            "sma_20": 205.0,
            "sma_60": 198.0,
        },
        retrieved_documents=[
            RetrievedDocument(
                document_id="doc-1",
                chunk_id="chunk-1",
                title="10-Q filing",
                chunk_text="Revenue increased while valuation remained elevated.",
            )
        ],
        retrieved_memories=[
            MemorySearchResult(
                memory_id="memory-1",
                memory_level=MemoryLevel.L1,
                namespace_key="US",
                summary_text="Policy conditions remained restrictive.",
                score=0.9,
                effective_ts=NOW,
                asset_id=ASSET_ID,
                memory_type="macro_event",
                importance_score=0.8,
                source_ref_json=citation,
                created_by="system",
            )
        ],
    )

    fundamental = FundamentalAnalystResponse(
        status=AgentStatus.OK,
        analysis=FundamentalAnalysis(
            quality_score=0.8,
            growth_score=0.7,
            valuation_score=0.5,
            key_points=["Revenue increased."],
            risk_points=["Valuation remained elevated."],
            uncertainties=["Only one filing period was supplied."],
            supporting_citations=[citation],
        ),
    )
    technical = _analyst_response(
        AgentName.TECHNICAL_TEXT_ANALYST,
        "The observed trend remained positive.",
        "Momentum may reverse.",
        citation,
    )
    sentiment = _analyst_response(
        AgentName.SENTIMENT_ANALYST,
        "Observed sentiment was constructive.",
        "Sample coverage was limited.",
        citation,
    )
    news = _analyst_response(
        AgentName.NEWS_EVENT_ANALYST,
        "No material filing surprise was identified.",
        "Event coverage may be incomplete.",
        citation,
    )
    research = ResearchManagerResponse(
        status=AgentStatus.OK,
        analysis=ResearchSummary(
            summary_points=["Growth was positive but valuation was elevated."],
            conflicts=["Growth quality and valuation point in different directions."],
            uncertainties=["The evidence window was limited."],
            supporting_citations=[citation],
        ),
    )
    bull = BullManagerResponse(
        bull_thesis=["Growth remained positive."],
        conditions_required=["Demand remains stable."],
        invalidators=["Revenue contracts."],
        confidence=0.6,
    )
    bear = BearManagerResponse(
        bear_thesis=["Valuation remained elevated."],
        conditions_required=["Growth slows."],
        invalidators=["Growth accelerates."],
        confidence=0.5,
    )
    risk = RiskManagerResponse(
        confirmed_risks=["Valuation remained elevated."],
        scenario_risks=["Demand may slow."],
        watch_items=["Revenue growth requires monitoring."],
        narrative_risk_score=0.5,
    )

    analyst_results = {
        AgentName.FUNDAMENTAL_ANALYST: _execution_result(
            AgentName.FUNDAMENTAL_ANALYST,
            cast(JsonObject, fundamental.model_dump(mode="json")),
            (
                "analysis.key_points[0]",
                "analysis.risk_points[0]",
            ),
            citation,
        ),
        AgentName.TECHNICAL_TEXT_ANALYST: _execution_result(
            AgentName.TECHNICAL_TEXT_ANALYST,
            cast(JsonObject, technical.model_dump(mode="json")),
            (
                "analysis.key_points[0]",
                "analysis.risk_points[0]",
            ),
            citation,
        ),
        AgentName.SENTIMENT_ANALYST: _execution_result(
            AgentName.SENTIMENT_ANALYST,
            cast(JsonObject, sentiment.model_dump(mode="json")),
            (
                "analysis.key_points[0]",
                "analysis.risk_points[0]",
            ),
            citation,
        ),
        AgentName.NEWS_EVENT_ANALYST: _execution_result(
            AgentName.NEWS_EVENT_ANALYST,
            cast(JsonObject, news.model_dump(mode="json")),
            (
                "analysis.key_points[0]",
                "analysis.risk_points[0]",
            ),
            citation,
        ),
    }
    task_result = ResearchTaskResult(
        task_id="task-report-1",
        status=AgentStatus.OK,
        analyst_results=analyst_results,
        research_manager=_execution_result(
            AgentName.RESEARCH_MANAGER,
            cast(JsonObject, research.model_dump(mode="json")),
            (
                "analysis.summary_points[0]",
                "analysis.conflicts[0]",
            ),
            citation,
        ),
        bull_manager=_execution_result(
            AgentName.BULL_MANAGER,
            cast(JsonObject, bull.model_dump(mode="json")),
            (
                "bull_thesis[0]",
                "conditions_required[0]",
                "invalidators[0]",
            ),
            citation,
        ),
        bear_manager=_execution_result(
            AgentName.BEAR_MANAGER,
            cast(JsonObject, bear.model_dump(mode="json")),
            (
                "bear_thesis[0]",
                "conditions_required[0]",
                "invalidators[0]",
            ),
            citation,
        ),
        risk_manager=_execution_result(
            AgentName.RISK_MANAGER,
            cast(JsonObject, risk.model_dump(mode="json")),
            (
                "confirmed_risks[0]",
                "scenario_risks[0]",
                "watch_items[0]",
            ),
            citation,
        ),
    )
    return ReportAssemblyInput(
        report_id="report-1",
        request=GenerateReportRequest(
            report_date=context.report_date,
            market_scope=context.market_scope,
            report_type=ReportType.SINGLE_ASSET,
            asset_ids=[context.asset_id],
            language="en",
            include_sections=list(STANDARD_SECTION_NAMES),
        ),
        input_context=context,
        agent_result=task_result,
        created_at=NOW,
    )


def _analyst_response(
    agent_name: AgentName,
    key_point: str,
    risk_point: str,
    citation: SourceReference,
) -> AnalystResponse:
    return AnalystResponse.model_validate(
        {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": AnalystAnalysis(
                key_points=[key_point],
                risk_points=[risk_point],
                uncertainties=["Coverage remained limited."],
                supporting_citations=[citation],
            ).model_dump(mode="json"),
        }
    )


def _execution_result(
    agent_name: AgentName,
    output: JsonObject,
    claim_paths: tuple[str, ...],
    citation: SourceReference,
) -> AgentExecutionResult:
    return AgentExecutionResult(
        run_id=f"run-{agent_name.value}",
        agent_name=agent_name,
        status=AgentStatus.OK,
        output=output,
        evidence=[
            EvidenceLink(
                claim_path=path,
                citations=[citation, citation],
            )
            for path in claim_paths
        ],
    )
