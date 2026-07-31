"""Offline tests for individual Phase One Agents and evidence enforcement."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, cast

import pytest

from src.agents import (
    AgentExecutionResult,
    AgentInvocation,
    BearManagerAgent,
    BullManagerAgent,
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    PromptLoadError,
    ResearchManagerAgent,
    RiskManagerAgent,
    SentimentAnalystAgent,
    TechnicalTextAnalystAgent,
)
from src.agents.base import BaseAgent
from src.models.enums import (
    AgentName,
    AgentStatus,
    MemoryLevel,
    ReportMarketScope,
)
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.repositories.records import AgentRunRecord
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
    ResearchManagerResponse,
    ResearchSummary,
    RiskManagerRequest,
)
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse

PROMPT_ROOT = Path("config/prompts")
NOW = datetime(2026, 7, 31, tzinfo=UTC)


class FixedGateway:
    """Return one deterministic JSON response and capture calls."""

    def __init__(self, response: JsonObject) -> None:
        self.response = response
        self.calls: list[JsonObject] = []

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        self.calls.append(input_payload)
        return self.response


class MemoryFake:
    """Return no memories or fail deterministically."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[MemorySearchRequest] = []

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("private memory detail")
        return MemorySearchResponse(results=[])


class CapturingRunLogger:
    """Capture Agent run records without a database."""

    def __init__(self) -> None:
        self.records: list[AgentRunRecord] = []

    def save(self, record: AgentRunRecord) -> None:
        self.records.append(record)


def _context() -> AgentContext:
    return AgentContext(
        report_date=date(2026, 7, 31),
        market_scope=ReportMarketScope.US,
        asset_id=AssetId("US:AAPL"),
        structured_features={"revenue_yoy": 0.1},
        retrieved_documents=[
            RetrievedDocument(
                document_id="doc-1",
                chunk_id="chunk-1",
                title="10-Q",
                chunk_text="Revenue increased.",
            )
        ],
    )


def _citation() -> SourceReference:
    return SourceReference(document_id="doc-1", excerpt_ref="chunk-1")


def _fundamental_output() -> FundamentalAnalystResponse:
    return FundamentalAnalystResponse(
        status=AgentStatus.OK,
        analysis=FundamentalAnalysis(
            quality_score=0.8,
            growth_score=0.7,
            valuation_score=0.5,
            key_points=["Revenue increased."],
            risk_points=["Valuation is elevated."],
            uncertainties=["Only one filing was supplied."],
            supporting_citations=[_citation()],
        ),
    )


def _analyst_output(agent_name: AgentName) -> AnalystResponse:
    validated_name = cast(
        Literal[
            AgentName.TECHNICAL_TEXT_ANALYST,
            AgentName.SENTIMENT_ANALYST,
            AgentName.NEWS_EVENT_ANALYST,
        ],
        agent_name,
    )
    return AnalystResponse(
        agent_name=validated_name,
        status=AgentStatus.OK,
        analysis=AnalystAnalysis(
            key_points=["Evidence-backed point."],
            risk_points=["Evidence-backed risk."],
            uncertainties=["Coverage is limited."],
            supporting_citations=[_citation()],
        ),
    )


def _agent_request(agent_name: AgentName) -> AgentRequest:
    return AgentRequest(
        run_id=f"run-{agent_name.value}",
        agent_name=agent_name,
        model_name="fake-model",
        input_context=_context(),
    )


def _run(
    agent_class: type[BaseAgent],
    agent_name: AgentName,
    response: JsonObject,
    input_payload: JsonObject,
    *,
    memory: MemoryFake | None = None,
) -> tuple[AgentExecutionResult, FixedGateway, CapturingRunLogger]:
    gateway = FixedGateway(response)
    logger = CapturingRunLogger()
    agent = agent_class(
        gateway,
        memory or MemoryFake(),
        PromptLoader(PROMPT_ROOT),
        logger,
        clock=lambda: NOW,
    )
    result = agent.run(
        AgentInvocation(
            run_id=f"run-{agent_name.value}",
            model_name="fake-model",
            input_payload=input_payload,
        )
    )
    return result, gateway, logger


def test_fundamental_agent_validates_and_links_every_claim() -> None:
    """Fundamental output should be schema-valid, cited, and audited."""

    response = cast(JsonObject, _fundamental_output().model_dump(mode="json"))
    request = _agent_request(AgentName.FUNDAMENTAL_ANALYST)
    result, gateway, logger = _run(
        FundamentalAnalystAgent,
        AgentName.FUNDAMENTAL_ANALYST,
        response,
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.OK
    assert len(result.evidence) == 5
    assert result.uncertainties == ["Only one filing was supplied."]
    assert len(gateway.calls) == 1
    assert logger.records[0].prompt_template_ver == "v1"
    assert logger.records[0].status == "ok"


@pytest.mark.parametrize(
    ("agent_class", "agent_name"),
    [
        (TechnicalTextAnalystAgent, AgentName.TECHNICAL_TEXT_ANALYST),
        (SentimentAnalystAgent, AgentName.SENTIMENT_ANALYST),
        (NewsEventAnalystAgent, AgentName.NEWS_EVENT_ANALYST),
    ],
)
def test_each_nonfundamental_analyst_runs_with_fake_gateway(
    agent_class: type[BaseAgent],
    agent_name: AgentName,
) -> None:
    """Each remaining Analyst should run independently and offline."""

    response = _analyst_output(agent_name)
    request = _agent_request(agent_name)
    result, _, logger = _run(
        agent_class,
        agent_name,
        cast(JsonObject, response.model_dump(mode="json")),
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.OK
    assert len(result.evidence) == 2
    assert logger.records[0].agent_name is agent_name


def test_research_and_thesis_and_risk_managers_run_independently() -> None:
    """All four Managers should accept the preceding typed contracts."""

    analyst = _fundamental_output()
    summary = ResearchSummary(
        summary_points=["Revenue increased."],
        conflicts=[],
        supporting_citations=[_citation()],
    )
    research_request = ResearchManagerRequest(
        input_context=_context(),
        analyst_outputs=[analyst],
    )
    research_response = ResearchManagerResponse(
        status=AgentStatus.OK,
        analysis=summary,
    )
    research_result, _, _ = _run(
        ResearchManagerAgent,
        AgentName.RESEARCH_MANAGER,
        cast(JsonObject, research_response.model_dump(mode="json")),
        cast(JsonObject, research_request.model_dump(mode="json")),
    )

    bull = BullManagerResponse(
        bull_thesis=["Growth remains positive."],
        conditions_required=["Demand remains stable."],
        invalidators=["Revenue contracts."],
        confidence=0.6,
    )
    bear = BearManagerResponse(
        bear_thesis=["Valuation is elevated."],
        conditions_required=["Growth slows."],
        invalidators=["Growth accelerates."],
        confidence=0.5,
    )
    bull_request = BullManagerRequest(
        input_context=_context(),
        analyst_outputs=[analyst],
        research_summary=summary,
    )
    bear_request = BearManagerRequest(
        input_context=_context(),
        analyst_outputs=[analyst],
        research_summary=summary,
    )
    bull_result, _, _ = _run(
        BullManagerAgent,
        AgentName.BULL_MANAGER,
        cast(JsonObject, bull.model_dump(mode="json")),
        cast(JsonObject, bull_request.model_dump(mode="json")),
    )
    bear_result, _, _ = _run(
        BearManagerAgent,
        AgentName.BEAR_MANAGER,
        cast(JsonObject, bear.model_dump(mode="json")),
        cast(JsonObject, bear_request.model_dump(mode="json")),
    )
    risk_request = RiskManagerRequest(
        input_context=_context(),
        analyst_outputs=[analyst],
        research_summary=summary,
        bull_output=bull,
        bear_output=bear,
    )
    risk_result, _, _ = _run(
        RiskManagerAgent,
        AgentName.RISK_MANAGER,
        {
            "confirmed_risks": ["Valuation is elevated."],
            "scenario_risks": ["Demand may slow."],
            "watch_items": ["Revenue growth."],
            "narrative_risk_score": 0.5,
        },
        cast(JsonObject, risk_request.model_dump(mode="json")),
    )

    assert research_result.status is AgentStatus.OK
    assert bull_result.status is AgentStatus.OK
    assert bear_result.status is AgentStatus.OK
    assert risk_result.status is AgentStatus.OK
    assert all(result.evidence for result in (bull_result, bear_result, risk_result))


def test_invalid_schema_and_fabricated_citation_are_rejected() -> None:
    """Malformed or unknown evidence must never become a successful result."""

    request = _agent_request(AgentName.FUNDAMENTAL_ANALYST)
    invalid_schema, _, schema_logger = _run(
        FundamentalAnalystAgent,
        AgentName.FUNDAMENTAL_ANALYST,
        {"unexpected": "value"},
        cast(JsonObject, request.model_dump(mode="json")),
    )
    fabricated = _fundamental_output().model_copy(deep=True)
    fabricated.analysis.supporting_citations = [
        SourceReference(document_id="invented", excerpt_ref="invented-chunk")
    ]
    invalid_citation, _, citation_logger = _run(
        FundamentalAnalystAgent,
        AgentName.FUNDAMENTAL_ANALYST,
        cast(JsonObject, fabricated.model_dump(mode="json")),
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert invalid_schema.status is AgentStatus.ERROR
    assert invalid_schema.error is not None
    assert invalid_schema.error.code == "schema_validation"
    assert invalid_citation.status is AgentStatus.ERROR
    assert invalid_citation.error is not None
    assert invalid_citation.error.code == "evidence_validation"
    assert schema_logger.records[0].status == "error"
    assert citation_logger.records[0].output_payload is None


def test_trading_instruction_is_rejected_even_when_cited() -> None:
    """Phase One Agents must never pass through a trading instruction."""

    response = _analyst_output(AgentName.TECHNICAL_TEXT_ANALYST)
    response.analysis.key_points = ["Buy shares after the filing."]
    request = _agent_request(AgentName.TECHNICAL_TEXT_ANALYST)

    result, _, logger = _run(
        TechnicalTextAnalystAgent,
        AgentName.TECHNICAL_TEXT_ANALYST,
        cast(JsonObject, response.model_dump(mode="json")),
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.code == "evidence_validation"
    assert logger.records[0].output_payload is None


def test_memory_failure_is_explicit_and_existing_evidence_allows_degradation() -> None:
    """Unavailable Memory should be visible while document-backed work continues."""

    request = _agent_request(AgentName.FUNDAMENTAL_ANALYST)
    gateway = FixedGateway(
        cast(JsonObject, _fundamental_output().model_dump(mode="json"))
    )
    logger = CapturingRunLogger()
    agent = FundamentalAnalystAgent(
        gateway,
        MemoryFake(fail=True),
        PromptLoader(PROMPT_ROOT),
        logger,
        clock=lambda: NOW,
    )
    result = agent.run(
        AgentInvocation(
            run_id=request.run_id,
            model_name=request.model_name,
            input_payload=cast(JsonObject, request.model_dump(mode="json")),
            memory_query=MemorySearchRequest(
                memory_levels=[
                    MemoryLevel.L1,
                    MemoryLevel.L2,
                    MemoryLevel.L4,
                ],
                namespace_keys=["US", "US:AAPL"],
                query_text="AAPL research context",
            ),
        )
    )

    assert result.status is AgentStatus.OK
    assert "Memory retrieval was unavailable." in result.uncertainties
    assert "retrieved_memories" in result.missing_data
    assert logger.records[0].retrieved_context == {
        "documents": [
            {
                "document_id": "doc-1",
                "title": "10-Q",
                "chunk_text": "Revenue increased.",
                "chunk_id": "chunk-1",
            }
        ],
        "memories": [],
    }


def test_prompts_are_versioned_and_missing_prompt_is_explicit(tmp_path: Path) -> None:
    """Prompt text must be centralized, versioned, and validated."""

    prompt = PromptLoader(PROMPT_ROOT).load(AgentName.RISK_MANAGER)

    assert prompt.version == "v1"
    assert "trade" in prompt.system_prompt
    with pytest.raises(PromptLoadError, match="unavailable"):
        PromptLoader(tmp_path).load(AgentName.RISK_MANAGER)


def test_agent_modules_do_not_import_storage_provider_or_openai_boundaries() -> None:
    """Agent code must not bypass public service and Repository interfaces."""

    forbidden = (
        "duckdb",
        "faiss",
        "openai",
        "src.adapters",
        "src.repositories.database",
        "src.repositories.vector",
    )
    for path in Path("src/agents").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        imports.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in imports
            for prefix in forbidden
        )
