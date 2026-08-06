"""Offline integration tests for the fixed Phase One Agent collaboration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.agents import (
    BearManagerAgent,
    BullManagerAgent,
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    ResearchCoordinator,
    ResearchManagerAgent,
    ResearchTaskRequest,
    RiskManagerAgent,
    SentimentAnalystAgent,
    TechnicalTextAnalystAgent,
)
from src.agents.base import BaseAgent
from src.models.enums import AgentName, AgentStatus, ReportMarketScope
from src.models.identifiers import AssetId
from src.models.types import JsonObject, JsonValue
from src.repositories import AgentRunRepository, DuckDBDatabase
from src.schemas.agents import AgentContext
from src.schemas.documents import RetrievedDocument
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 31, tzinfo=UTC)
PROMPT_ROOT = Path("config/prompts")


class SequencedGateway:
    """Return one role response and append to a shared call trace."""

    def __init__(
        self,
        agent_name: AgentName,
        response: JsonObject,
        calls: list[AgentName],
    ) -> None:
        self._agent_name = agent_name
        self._response = response
        self._calls = calls

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        self._calls.append(self._agent_name)
        return self._response


class EmptyMemory:
    """Offline public Memory test double."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        return MemorySearchResponse(results=[])


def _context() -> AgentContext:
    return AgentContext(
        report_date=date(2026, 7, 31),
        market_scope=ReportMarketScope.US,
        asset_id=AssetId("US:AAPL"),
        structured_features={
            "revenue_yoy": 0.1,
            "sma_20": 205.0,
            "sma_60": 198.0,
        },
        retrieved_documents=[
            RetrievedDocument(
                document_id="doc-1",
                chunk_id="chunk-1",
                title="10-Q and market update",
                chunk_text="Revenue increased while valuation remained elevated.",
            )
        ],
    )


def _responses() -> dict[AgentName, JsonObject]:
    citation: list[JsonValue] = [{"document_id": "doc-1", "excerpt_ref": "chunk-1"}]
    return {
        AgentName.FUNDAMENTAL_ANALYST: {
            "agent_name": "fundamental_analyst",
            "status": "ok",
            "analysis": {
                "quality_score": 0.8,
                "growth_score": 0.7,
                "valuation_score": 0.5,
                "key_points": ["Revenue increased."],
                "risk_points": ["Valuation remained elevated."],
                "uncertainties": [],
                "supporting_citations": citation,
            },
        },
        AgentName.TECHNICAL_TEXT_ANALYST: _analyst_response(
            "technical_text_analyst",
            citation,
        ),
        AgentName.SENTIMENT_ANALYST: _analyst_response(
            "sentiment_analyst",
            citation,
        ),
        AgentName.NEWS_EVENT_ANALYST: _analyst_response(
            "news_event_analyst",
            citation,
        ),
        AgentName.RESEARCH_MANAGER: {
            "agent_name": "research_manager",
            "status": "ok",
            "analysis": {
                "summary_points": ["Growth was positive."],
                "conflicts": ["Valuation offsets growth quality."],
                "uncertainties": [],
                "supporting_citations": citation,
            },
        },
        AgentName.BULL_MANAGER: {
            "bull_thesis": ["Growth remained positive."],
            "conditions_required": ["Demand remains stable."],
            "invalidators": ["Revenue contracts."],
            "confidence": 0.6,
        },
        AgentName.BEAR_MANAGER: {
            "bear_thesis": ["Valuation remained elevated."],
            "conditions_required": ["Growth slows."],
            "invalidators": ["Growth accelerates."],
            "confidence": 0.5,
        },
        AgentName.RISK_MANAGER: {
            "confirmed_risks": ["Valuation remained elevated."],
            "scenario_risks": ["Demand may slow."],
            "watch_items": ["Revenue growth."],
            "narrative_risk_score": 0.5,
        },
    }


def _analyst_response(
    agent_name: str,
    citation: list[JsonValue],
) -> JsonObject:
    return {
        "agent_name": agent_name,
        "status": "ok",
        "analysis": {
            "key_points": ["Evidence-backed observation."],
            "risk_points": ["Evidence-backed limitation."],
            "uncertainties": [],
            "supporting_citations": citation,
        },
    }


def _coordinator(
    database: DuckDBDatabase,
    responses: dict[AgentName, JsonObject],
    calls: list[AgentName],
) -> ResearchCoordinator:
    logger = AgentRunRepository(database)
    memory = EmptyMemory()
    prompts = PromptLoader(PROMPT_ROOT)
    classes: dict[AgentName, type[BaseAgent]] = {
        AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystAgent,
        AgentName.TECHNICAL_TEXT_ANALYST: TechnicalTextAnalystAgent,
        AgentName.SENTIMENT_ANALYST: SentimentAnalystAgent,
        AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystAgent,
        AgentName.RESEARCH_MANAGER: ResearchManagerAgent,
        AgentName.BULL_MANAGER: BullManagerAgent,
        AgentName.BEAR_MANAGER: BearManagerAgent,
        AgentName.RISK_MANAGER: RiskManagerAgent,
    }
    registry = {
        name: agent_class(
            SequencedGateway(name, responses[name], calls),
            memory,
            prompts,
            logger,
            clock=lambda: NOW,
        )
        for name, agent_class in classes.items()
    }
    return ResearchCoordinator(registry)


def _request(task_id: str) -> ResearchTaskRequest:
    return ResearchTaskRequest(
        task_id=task_id,
        report_id=f"report-{task_id}",
        model_name="fake-model",
        input_context=_context(),
    )


def test_full_research_chain_is_ordered_cited_and_audited(tmp_path: Path) -> None:
    """Four Analysts should feed synthesis, two theses, and final risk review."""

    database = DuckDBDatabase(tmp_path / "agents.duckdb")
    database.bootstrap()
    calls: list[AgentName] = []
    coordinator = _coordinator(database, _responses(), calls)

    result = coordinator.run(_request("task-complete"))

    assert result.status is AgentStatus.OK
    assert calls == [
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
        AgentName.RESEARCH_MANAGER,
        AgentName.BULL_MANAGER,
        AgentName.BEAR_MANAGER,
        AgentName.RISK_MANAGER,
    ]
    all_results = [
        *result.analyst_results.values(),
        result.research_manager,
        result.bull_manager,
        result.bear_manager,
        result.risk_manager,
    ]
    assert all(item is not None and item.evidence for item in all_results)
    repository = AgentRunRepository(database)
    for agent_name in calls:
        record = repository.get(f"task-complete:{agent_name.value}")
        assert record is not None
        assert record.status == "ok"
        assert record.model_name == "fake-model"
        expected_version = (
            "v3"
            if agent_name
            in {
                AgentName.FUNDAMENTAL_ANALYST,
                AgentName.BULL_MANAGER,
                AgentName.BEAR_MANAGER,
                AgentName.RISK_MANAGER,
            }
            else "v2"
        )
        assert record.prompt_template_ver == expected_version
        assert record.output_payload is not None


def test_one_analyst_failure_is_explicit_but_chain_can_degrade(
    tmp_path: Path,
) -> None:
    """One invalid Analyst should remain visible while other evidence proceeds."""

    database = DuckDBDatabase(tmp_path / "degraded-agents.duckdb")
    database.bootstrap()
    calls: list[AgentName] = []
    responses = _responses()
    responses[AgentName.SENTIMENT_ANALYST] = {"invalid": "response"}
    coordinator = _coordinator(database, responses, calls)

    result = coordinator.run(_request("task-degraded"))

    assert result.status is AgentStatus.OK
    assert AgentName.SENTIMENT_ANALYST in result.missing_agents
    assert "sentiment_analyst was unavailable." in result.uncertainties
    failed = result.analyst_results[AgentName.SENTIMENT_ANALYST]
    assert failed.status is AgentStatus.ERROR
    assert failed.error is not None
    assert failed.error.code == "schema_validation"
    assert calls[-1] is AgentName.RISK_MANAGER
    stored = AgentRunRepository(database).get("task-degraded:sentiment_analyst")
    assert stored is not None
    assert stored.status == "error"
