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
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    PromptLoadError,
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
from src.models.types import DomainModel, JsonObject
from src.repositories.records import AgentRunRecord
from src.schemas.agents import (
    AgentContext,
    AgentRequest,
    AnalystAnalysis,
    AnalystDraftClaim,
    AnalystResponse,
    FundamentalAnalysis,
    FundamentalAnalystResponse,
    NewsDraftResponse,
    RoleEvidenceManifest,
    RoleEvidenceManifestEntry,
    SentimentDraftResponse,
    TechnicalDraftResponse,
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
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[DomainModel],
    ) -> JsonObject:
        del model, system_prompt, prompt_version, schema_version, response_model
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
    assert logger.records[0].prompt_template_ver == "v10"
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

    request = _agent_request(agent_name)
    if agent_name is AgentName.SENTIMENT_ANALYST:
        evidence_id = "ev_sentiment_fixture"
        request.input_context.role_evidence_manifest = RoleEvidenceManifest(
            agent_name=agent_name,
            entries=(
                RoleEvidenceManifestEntry(
                    evidence_id=evidence_id,
                    evidence_type="document",
                    source=_citation(),
                    short_description="Evidence-backed sentiment point.",
                ),
            ),
        )
        raw_response: JsonObject = {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "claims": [
                    {
                        "claim_path": "analysis.key_points[0]",
                        "claim_text": "Evidence-backed sentiment point.",
                        "numeric_literals": [],
                        "evidence_ids": [evidence_id],
                        "derivation_type": "direct_evidence",
                    }
                ],
                "uncertainties": ["Coverage is limited."],
            },
        }
    else:
        response = _analyst_output(agent_name)
        raw_response = cast(JsonObject, response.model_dump(mode="json"))
    result, _, logger = _run(
        agent_class,
        agent_name,
        raw_response,
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.OK
    assert len(result.evidence) == (
        1 if agent_name is AgentName.SENTIMENT_ANALYST else 2
    )
    assert logger.records[0].agent_name is agent_name
    expected_prompt_version = (
        "v8" if agent_name is AgentName.SENTIMENT_ANALYST else "v9"
    )
    assert logger.records[0].prompt_template_ver == expected_prompt_version


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
    assert "status:missing" in (schema_logger.records[0].error_message or "")
    assert "unexpected value" not in (schema_logger.records[0].error_message or "")
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


def test_numeric_claim_absent_from_evidence_is_rejected() -> None:
    """A cited chunk cannot legitimize a number that it does not contain."""

    response = _analyst_output(AgentName.TECHNICAL_TEXT_ANALYST)
    response.analysis.key_points = [
        "Share-based compensation was $10.5 billion for the quarter."
    ]
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
    assert "numeric claim was absent" in (logger.records[0].error_message or "")


def test_sell_through_business_metric_is_not_a_trading_instruction() -> None:
    """A hyphenated operating metric must not trigger the trade guard."""

    response = _analyst_output(AgentName.TECHNICAL_TEXT_ANALYST)
    response.analysis.key_points = ["Quarterly sell-through rates declined."]
    request = _agent_request(AgentName.TECHNICAL_TEXT_ANALYST)

    result, _, logger = _run(
        TechnicalTextAnalystAgent,
        AgentName.TECHNICAL_TEXT_ANALYST,
        cast(JsonObject, response.model_dump(mode="json")),
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.OK
    assert logger.records[0].status == "ok"


def test_attributed_analyst_price_target_is_not_an_execution_instruction() -> None:
    """A reported analyst target is research evidence, not an executable order."""

    response = _analyst_output(AgentName.NEWS_EVENT_ANALYST)
    response.analysis.key_points = [
        "The cited media report states an analyst price target was reduced."
    ]
    request = _agent_request(AgentName.NEWS_EVENT_ANALYST)

    result, _, logger = _run(
        NewsEventAnalystAgent,
        AgentName.NEWS_EVENT_ANALYST,
        cast(JsonObject, response.model_dump(mode="json")),
        cast(JsonObject, request.model_dump(mode="json")),
    )

    assert result.status is AgentStatus.OK
    assert logger.records[0].status == "ok"


def test_gateway_receives_compact_evidence_while_audit_keeps_full_contract() -> None:
    """Inference de-duplicates lineage without weakening durable validation."""

    response = _analyst_output(AgentName.TECHNICAL_TEXT_ANALYST)
    request = _agent_request(AgentName.TECHNICAL_TEXT_ANALYST)
    payload = cast(JsonObject, request.model_dump(mode="json"))
    payload["research_contract"] = {
        "data": {"sections": [{"capability": "technical_features", "items": [1]}]},
        "data_evidence_index": {
            "ev-1": {
                "evidence_id": "ev-1",
                "field_path": "technical_features.sma_20",
                "effective_at": "2026-07-31T00:00:00Z",
                "value": 205.0,
                "unit": "USD",
                "parent_evidence_ids": ["ev-parent"],
                "content_hash": "sensitive-duplicate-lineage",
                "source": {
                    "provider_name": "fixture",
                    "normalized_record_key": "bar-1",
                    "provider_locator": "fixture:bar:1",
                    "content_hash": "duplicate-source-metadata",
                },
            }
        },
    }
    gateway = FixedGateway(cast(JsonObject, response.model_dump(mode="json")))
    logger = CapturingRunLogger()
    agent = TechnicalTextAnalystAgent(
        gateway,
        MemoryFake(),
        PromptLoader(PROMPT_ROOT),
        logger,
        clock=lambda: NOW,
    )

    result = agent.run(
        AgentInvocation(
            run_id="run-compact-contract",
            model_name="fake-model",
            input_payload=payload,
        )
    )

    assert result.status is AgentStatus.OK
    inference_contract = gateway.calls[0]["research_contract"]
    assert isinstance(inference_contract, dict)
    inference_data = inference_contract["data"]
    assert isinstance(inference_data, dict)
    inference_sections = inference_data["sections"]
    assert isinstance(inference_sections, list)
    assert isinstance(inference_sections[0], dict)
    assert inference_sections[0].get("items") is None
    inference_index = inference_contract["data_evidence_index"]
    assert isinstance(inference_index, dict)
    compact = inference_index["ev-1"]
    assert isinstance(compact, dict)
    assert compact["value"] == 205.0
    assert "parent_evidence_ids" not in compact
    audit_payload = logger.records[0].input_payload["input_payload"]
    assert isinstance(audit_payload, dict)
    audit_contract = audit_payload["research_contract"]
    assert isinstance(audit_contract, dict)
    audit_data = audit_contract["data"]
    assert isinstance(audit_data, dict)
    audit_sections = audit_data["sections"]
    assert isinstance(audit_sections, list)
    assert isinstance(audit_sections[0], dict)
    assert audit_sections[0]["items"] == [1]
    audit_index = audit_contract["data_evidence_index"]
    assert isinstance(audit_index, dict)
    audit_item = audit_index["ev-1"]
    assert isinstance(audit_item, dict)
    assert audit_item["parent_evidence_ids"] == ["ev-parent"]


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
        "structured_evidence": [],
    }


def test_prompts_are_versioned_and_missing_prompt_is_explicit(tmp_path: Path) -> None:
    """Prompt text must be centralized, versioned, and validated."""

    prompt = PromptLoader(PROMPT_ROOT).load(AgentName.RISK_MANAGER)

    assert prompt.version == "v7"
    assert "trade" in prompt.system_prompt
    archived = PromptLoader(PROMPT_ROOT / "archive" / "pre_agent_contract_v1").load(
        AgentName.RISK_MANAGER
    )
    assert archived.version == "v4"
    candidate_v1 = PromptLoader(
        PROMPT_ROOT / "archive" / "agent_contract_candidate_v1"
    ).load(AgentName.RISK_MANAGER)
    assert candidate_v1.version == "v5"
    candidate_v2 = PromptLoader(
        PROMPT_ROOT / "archive" / "agent_contract_candidate_v2"
    ).load(AgentName.RISK_MANAGER)
    assert candidate_v2.version == "v6"
    candidate_v3 = PromptLoader(
        PROMPT_ROOT / "archive" / "agent_contract_candidate_v3"
    ).load(AgentName.RISK_MANAGER)
    assert candidate_v3.version == "v7"
    with pytest.raises(PromptLoadError, match="unavailable"):
        PromptLoader(tmp_path).load(AgentName.RISK_MANAGER)


@pytest.mark.parametrize(
    "agent_name",
    [
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    ],
)
def test_prompts_define_the_role_manifest_and_numeric_contract(
    agent_name: AgentName,
) -> None:
    """Only Analysts receive the strict raw-Evidence contract."""

    prompt = " ".join(PromptLoader(PROMPT_ROOT).load(agent_name).system_prompt.split())

    assert "RoleEvidenceManifest is the sole citation namespace" in prompt
    assert "Absence of evidence is not evidence of absence" in prompt
    assert "never invent, shorten, alias, or repair an Evidence ID" in prompt
    assert "Do not calculate percentages, ratios, unit conversions" in prompt


@pytest.mark.parametrize(
    "agent_name",
    [
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    ],
)
def test_analyst_prompt_claim_fields_match_draft_contract(
    agent_name: AgentName,
) -> None:
    """Active Analyst prompts must not require fields forbidden by the Draft."""

    prompt = PromptLoader(PROMPT_ROOT).load(agent_name).system_prompt
    normalized_prompt = " ".join(prompt.split())
    allowed = set(AnalystDraftClaim.model_fields)
    expected = {
        "claim_id",
        "claim_type",
        "claim_path",
        "claim_text",
        "numeric_literals",
        "evidence_ids",
        "confidence",
    }

    assert expected <= allowed
    assert '"derivation_type"' not in prompt
    assert "do not return a derivation_type field" in normalized_prompt


@pytest.mark.parametrize(
    ("agent_name", "response_model"),
    [
        (AgentName.TECHNICAL_TEXT_ANALYST, TechnicalDraftResponse),
        (AgentName.SENTIMENT_ANALYST, SentimentDraftResponse),
        (AgentName.NEWS_EVENT_ANALYST, NewsDraftResponse),
    ],
)
def test_live_style_analyst_claim_matches_draft_schema(
    agent_name: AgentName,
    response_model: type[DomainModel],
) -> None:
    """The active Prompt example shape validates at the Gateway boundary."""

    parsed = response_model.model_validate(
        {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "claims": [
                    {
                        "claim_path": "analysis.facts[0]",
                        "claim_text": "Evidence-backed fact.",
                        "numeric_literals": [],
                        "evidence_ids": ["canonical-evidence-id"],
                    }
                ],
                "uncertainties": [],
            },
        }
    )

    assert parsed.model_dump(mode="json")["analysis"]["claims"]


@pytest.mark.parametrize(
    "agent_name",
    [
        AgentName.RESEARCH_MANAGER,
        AgentName.BULL_MANAGER,
        AgentName.BEAR_MANAGER,
        AgentName.RISK_MANAGER,
    ],
)
def test_manager_prompts_use_upstream_claims_not_raw_evidence(
    agent_name: AgentName,
) -> None:
    """Managers must consume Claim IDs and never reconstruct raw grounding."""

    prompt = " ".join(PromptLoader(PROMPT_ROOT).load(agent_name).system_prompt.split())

    assert "upstream claim_id" in prompt
    assert "Never reference raw Evidence IDs" in prompt
    assert "RoleEvidenceManifest is the sole citation namespace" not in prompt


@pytest.mark.parametrize(
    "agent_name",
    [
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.BULL_MANAGER,
        AgentName.BEAR_MANAGER,
        AgentName.RISK_MANAGER,
    ],
)
def test_normalized_score_prompts_define_range_and_forbid_other_scales(
    agent_name: AgentName,
) -> None:
    """Score-producing prompts must state the domain model's exact scale."""

    prompt = PromptLoader(PROMPT_ROOT).load(agent_name)
    normalized_prompt = " ".join(prompt.system_prompt.split())

    expected_version = {
        AgentName.FUNDAMENTAL_ANALYST: "v10",
        AgentName.BULL_MANAGER: "v8",
        AgentName.BEAR_MANAGER: "v10",
        AgentName.RISK_MANAGER: "v7",
    }[agent_name]
    assert prompt.version == expected_version
    assert "between 0.0 and 1.0 inclusive" in normalized_prompt
    assert "Never use a 1-to-5 or 0-to-100 scale" in normalized_prompt
    assert "not 3 or 60" in normalized_prompt
    if agent_name is AgentName.BEAR_MANAGER:
        assert '"claim_type"' not in prompt.system_prompt


def test_completion_prompts_require_available_research_categories() -> None:
    """Live report coverage must consume, rather than relabel, available data."""

    fundamental = " ".join(
        PromptLoader(PROMPT_ROOT)
        .load(AgentName.FUNDAMENTAL_ANALYST)
        .system_prompt.split()
    )
    technical = " ".join(
        PromptLoader(PROMPT_ROOT)
        .load(AgentName.TECHNICAL_TEXT_ANALYST)
        .system_prompt.split()
    )
    news = " ".join(
        PromptLoader(PROMPT_ROOT)
        .load(AgentName.NEWS_EVENT_ANALYST)
        .system_prompt.split()
    )

    for category in (
        "Growth",
        "Margins",
        "Profitability",
        "Balance Sheet/Liquidity",
        "Valuation",
    ):
        assert category in fundamental
    for category in (
        "Trend",
        "Momentum",
        "Volatility",
        "Volume",
        "Relative Strength",
        "Drawdown",
    ):
        assert category in technical
    for category in ("rates", "inflation", "labor", "growth", "financial-stress"):
        assert category in news


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
