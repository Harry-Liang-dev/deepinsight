"""Offline regression tests for role-local Evidence and numeric grounding."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from src.agents import (
    AgentInvocation,
    BearManagerAgent,
    BullManagerAgent,
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    ResearchManagerAgent,
    SentimentAnalystAgent,
    TechnicalTextAnalystAgent,
)
from src.agents.analysts import _append_deterministic_manifest_claims
from src.agents.base import BaseAgent, _citation_text
from src.agents.contracts import AgentExecutionResult
from src.agents.coordinator import _parse_analyst_output, _versioned_output
from src.agents.evidence import numeric_literals
from src.models.enums import AgentName, AgentStatus, ReportMarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject, JsonValue
from src.repositories.records import AgentRunRecord
from src.schemas.agents import (
    AgentContext,
    AnalystAnalysis,
    AnalystResponse,
    BearManagerRequest,
    BullManagerRequest,
    ClaimEvidenceBinding,
    FundamentalAnalysis,
    FundamentalAnalystResponse,
    ResearchManagerRequest,
    ResearchSummary,
    RoleEvidenceManifest,
    RoleEvidenceManifestEntry,
)
from src.schemas.common import SourceReference
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse

PROMPT_ROOT = Path("config/prompts")
FIXTURE_PATH = Path("tests/fixtures/agents/final_gate_evidence_v1.json")
NOW = datetime(2026, 8, 13, tzinfo=UTC)


class FixedGateway:
    """Return one deterministic structured response."""

    def __init__(self, response: JsonObject) -> None:
        self.response = response

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
        del (
            model,
            system_prompt,
            input_payload,
            prompt_version,
            schema_version,
            response_model,
        )
        return self.response


class EmptyMemory:
    """Provide deterministic offline Memory behavior."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        del request
        return MemorySearchResponse(results=[])


class CapturingLogger:
    """Retain the credential-free Agent audit record."""

    def __init__(self) -> None:
        self.records: list[AgentRunRecord] = []

    def save(self, record: AgentRunRecord) -> None:
        self.records.append(record)


def _fixture(name: str) -> dict[str, str]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return cast(dict[str, str], payload["entries"][name])


def _entry(
    fixture_name: str,
    *,
    evidence_type: str = "structured_direct",
    description: str | None = None,
) -> RoleEvidenceManifestEntry:
    item = _fixture(fixture_name)
    text = description or item["description"]
    return RoleEvidenceManifestEntry.model_validate(
        {
            "evidence_id": item["evidence_id"],
            "evidence_type": evidence_type,
            "source": {
                "document_id": item["document_id"],
                "excerpt_ref": item["evidence_id"],
                "provider": item["provider"],
            },
            "as_of": NOW,
            "short_description": text,
            "numeric_tokens": numeric_literals(text),
            "citation_allowed": True,
        }
    )


def _response(
    agent_name: AgentName,
    claim: str,
    evidence_ids: list[str],
    *,
    numeric_values: tuple[str, ...] | None = None,
) -> JsonObject:
    binding = {
        "claim_path": "analysis.facts[0]",
        "claim_text": claim,
        "numeric_literals": list(
            numeric_literals(claim) if numeric_values is None else numeric_values
        ),
        "evidence_ids": evidence_ids,
        "derivation_type": "direct_evidence",
    }
    if agent_name is AgentName.SENTIMENT_ANALYST:
        return cast(
            JsonObject,
            {
                "agent_name": agent_name.value,
                "status": "ok",
                "analysis": {"claims": [binding], "uncertainties": []},
            },
        )
    return cast(
        JsonObject,
        {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "facts": [claim],
                "key_points": [],
                "risk_points": [],
                "uncertainties": [],
                "claim_evidence": [binding],
            },
        },
    )


def _run(
    agent_name: AgentName,
    response: JsonObject,
    entries: list[RoleEvidenceManifestEntry],
) -> tuple[AgentStatus, AgentRunRecord]:
    context = AgentContext(
        report_date=date(2026, 8, 13),
        market_scope=ReportMarketScope.US,
        asset_id=AssetId("US:AAPL"),
        structured_features={"fixture": True},
        role_evidence_manifest=RoleEvidenceManifest(
            agent_name=agent_name,
            entries=tuple(entries),
        ),
    )
    logger = CapturingLogger()
    agent_class = {
        AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystAgent,
        AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystAgent,
        AgentName.SENTIMENT_ANALYST: SentimentAnalystAgent,
    }[agent_name]
    result = agent_class(
        FixedGateway(response),
        EmptyMemory(),
        PromptLoader(PROMPT_ROOT),
        logger,
        clock=lambda: NOW,
    ).run(
        AgentInvocation(
            run_id=f"contract-{agent_name.value}",
            model_name="fake-model",
            input_payload={
                "run_id": f"contract-{agent_name.value}",
                "agent_name": agent_name.value,
                "model_name": "fake-model",
                "input_context": cast(JsonObject, context.model_dump(mode="json")),
            },
        )
    )
    return result.status, logger.records[0]


def _fundamental_claim_response(
    claims: object,
    *,
    score_metadata: object | None = None,
) -> JsonObject:
    """Build one Claim-first Fundamental generation response."""

    return {
        "agent_name": "fundamental_analyst",
        "status": "ok",
        "analysis": {
            "claims": cast(JsonValue, claims),
            "normalized_scores": {
                "quality_score": 0.6,
                "growth_score": 0.7,
                "valuation_score": 0.5,
                "metadata": cast(JsonValue, score_metadata)
                or {
                    "quality_score": {"source_type": "assessment_score"},
                    "growth_score": {"source_type": "assessment_score"},
                    "valuation_score": {"source_type": "assessment_score"},
                },
            },
            "uncertainties": ["Coverage is limited."],
            "metadata": {},
        },
    }


def _bear_claim_response(claims: object) -> JsonObject:
    """Build one Claim-first Bear generation response."""

    return {
        "claims": cast(JsonValue, claims),
        "confidence": 0.5,
    }


def _context_for_role(
    agent_name: AgentName,
    entry: RoleEvidenceManifestEntry,
) -> AgentContext:
    return AgentContext(
        report_date=date(2026, 8, 13),
        market_scope=ReportMarketScope.US,
        asset_id=AssetId("US:AAPL"),
        structured_features={"fixture": True},
        role_evidence_manifest=RoleEvidenceManifest(
            agent_name=agent_name,
            entries=(entry,),
        ),
    )


def _execute(
    agent_class: type[BaseAgent],
    agent_name: AgentName,
    response: JsonObject,
    payload: JsonObject,
) -> tuple[AgentStatus, JsonObject | None]:
    logger = CapturingLogger()
    result = agent_class(
        FixedGateway(response),
        EmptyMemory(),
        PromptLoader(PROMPT_ROOT),
        logger,
        clock=lambda: NOW,
    ).run(
        AgentInvocation(
            run_id=f"fixed-seven-{agent_name.value}",
            model_name="fake-model",
            input_payload=payload,
        )
    )
    return result.status, result.output


def test_sentiment_role_manifest_accepts_valid_stocktwits_citation() -> None:
    """A canonical Stocktwits ID should pass without alias correction."""

    entry = _entry("stocktwits_score")
    claim = "The supplied community sentiment score was 64.0."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.OK
    assert record.error_message is None
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    citations = cast(list[JsonValue], analysis["supporting_citations"])
    citation = cast(JsonObject, citations[0])
    assert citation["excerpt_ref"] == entry.evidence_id


def test_unknown_evidence_id_is_rejected_without_fuzzy_repair() -> None:
    """Dropping the canonical prefix must remain a hard failure."""

    entry = _entry("stocktwits_label")
    alias = entry.evidence_id.removeprefix("ev_")
    claim = "The supplied community label was BULLISH."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [alias]),
        [entry],
    )

    assert status is AgentStatus.ERROR
    assert record.output_payload is None
    assert record.error_message is not None


def test_numeric_direct_evidence_is_accepted() -> None:
    """Exact numeric literals may bind to direct Evidence."""

    entry = _entry("stocktwits_bullish_score")
    claim = "The supplied bullish score was 74.01."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(
            AgentName.SENTIMENT_ANALYST,
            claim,
            [entry.evidence_id],
            numeric_values=(),
        ),
        [entry],
    )

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    bindings = cast(list[JsonValue], analysis["claim_evidence"])
    binding = cast(JsonObject, bindings[0])
    assert binding["numeric_literals"] == ["74.01"]


def test_unit_conversion_is_rejected() -> None:
    """An LLM cannot convert one supplied billion into 1000 million."""

    entry = _entry(
        "stocktwits_score",
        description="A supplied operating value was 1 billion USD.",
    )
    claim = "The supplied operating value was 1000 million USD."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_percentage_derivation_is_rejected() -> None:
    """A ratio does not authorize an LLM-created percentage literal."""

    entry = _entry(
        "stocktwits_bullish_score",
        description="The deterministic source ratio was 0.7401 ratio.",
    )
    claim = "The supplied bullish share was 74.01%."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_rounded_numeric_literal_is_rejected() -> None:
    """A shortened valuation ratio must not pass exact-literal grounding."""

    entry = _entry("rounded_valuation_source", evidence_type="structured_derived")
    claim = "The supplied valuation ratio was 48.19."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_deterministic_derived_feature_exact_literal_is_accepted() -> None:
    """A deterministic derived Evidence item remains directly citable."""

    entry = _entry("derived_return", evidence_type="structured_derived")
    claim = "The deterministic return was -0.07756883814640692 ratio."

    status, _ = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.OK


def test_news_event_claim_requires_the_evidence_containing_both_literals() -> None:
    """The Final Gate price-target sentence passes only with its full source."""

    entry = _entry("news_target")
    claim = "An attributed report reduced a stated value to $263.66 from $285.56."

    status, _ = _run(
        AgentName.NEWS_EVENT_ANALYST,
        _response(AgentName.NEWS_EVENT_ANALYST, claim, [entry.evidence_id]),
        [entry],
    )

    assert status is AgentStatus.OK


def test_canonical_metric_claim_uses_exact_manifest_values() -> None:
    """Standardized facts are promoted without LLM numeric reformatting."""

    entry = RoleEvidenceManifestEntry(
        evidence_id="ev_metric_growth",
        evidence_type="structured_direct",
        source=SourceReference(
            document_id="US:AAPL|TTM",
            excerpt_ref="ev_metric_growth",
            provider="financial_modeling_prep",
        ),
        as_of=NOW,
        short_description="fundamentals.revenue_yoy -0.015 ratio",
        numeric_tokens=("-0.015",),
    )
    manifest = RoleEvidenceManifest(
        agent_name=AgentName.FUNDAMENTAL_ANALYST,
        entries=(entry,),
    )
    response: JsonObject = {
        "agent_name": "fundamental_analyst",
        "status": "ok",
        "analysis": {"claims": []},
    }

    enriched = _append_deterministic_manifest_claims(
        {"input_context": {"role_evidence_manifest": manifest.model_dump(mode="json")}},
        response,
        groups=(("Growth", ("fundamentals.revenue_yoy",)),),
        claim_id_prefix="fundamental:canonical",
    )

    analysis = cast(JsonObject, enriched["analysis"])
    claim = cast(list[JsonObject], analysis["claims"])[0]
    assert claim["claim_text"] == "Growth: fundamentals.revenue_yoy -0.015 ratio"
    assert claim["numeric_literals"] == ["-0.015"]
    assert claim["evidence_ids"] == [entry.evidence_id]


def test_news_quarantine_compacts_paths_without_changing_evidence() -> None:
    """A rejected Claim may leave sparse draft paths without killing the role."""

    entry = _entry("news_target")
    response: JsonObject = {
        "agent_name": "news_event_analyst",
        "status": "ok",
        "analysis": {
            "claims": [
                {
                    "claim_path": "analysis.facts[0]",
                    "claim_text": "This unsupported numeric claim was 999.",
                    "numeric_literals": ["999"],
                    "evidence_ids": [entry.evidence_id],
                },
                {
                    "claim_path": "analysis.facts[1]",
                    "claim_text": (
                        "An attributed report reduced a stated value to $263.66 "
                        "from $285.56."
                    ),
                    "numeric_literals": ["263.66", "285.56"],
                    "evidence_ids": [entry.evidence_id],
                },
            ],
            "uncertainties": [],
        },
    }

    status, record = _run(AgentName.NEWS_EVENT_ANALYST, response, [entry])

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    bindings = cast(list[JsonObject], analysis["claim_evidence"])
    assert bindings[0]["claim_path"] == "analysis.facts[0]"
    assert bindings[0]["evidence_ids"] == [entry.evidence_id]


def test_multi_agent_evidence_namespaces_are_isolated() -> None:
    """A News ID cannot leak into a Sentiment role manifest."""

    sentiment = _entry("stocktwits_label")
    news = _entry("news_target")
    claim = "The supplied community label was BULLISH."

    status, record = _run(
        AgentName.SENTIMENT_ANALYST,
        _response(AgentName.SENTIMENT_ANALYST, claim, [news.evidence_id]),
        [sentiment],
    )

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_fundamental_uses_one_authoritative_claim_collection() -> None:
    """Fundamental public prose is deterministically assembled from Claims."""

    entries = [
        _entry("stocktwits_label"),
        _entry("stocktwits_score"),
        _entry("stocktwits_bullish_score"),
    ]
    claims = [
        {
            "claim_path": "analysis.facts[0]",
            "claim_text": "Community label was BULLISH.",
            "numeric_literals": [],
            "evidence_ids": [entries[0].evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.key_points[0]",
            "claim_text": "Community score was 64.0.",
            "numeric_literals": [],
            "evidence_ids": [entries[1].evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.risk_points[0]",
            "claim_text": "Bullish percentage was 74.01.",
            "numeric_literals": [],
            "evidence_ids": [entries[2].evidence_id],
            "derivation_type": "direct_evidence",
        },
    ]
    status, record = _run(
        AgentName.FUNDAMENTAL_ANALYST,
        _fundamental_claim_response(claims),
        entries,
    )

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    assert analysis["facts"] == ["Community label was BULLISH."]
    assert analysis["key_points"] == ["Community score was 64.0."]
    assert analysis["risk_points"] == ["Bullish percentage was 74.01."]
    assert len(cast(list[JsonValue], analysis["claim_evidence"])) == 3


def test_fundamental_score_metadata_is_not_a_factual_claim() -> None:
    """Assessment scores carry source metadata without citation requirements."""

    entry = _entry("stocktwits_label")
    response = _fundamental_claim_response(
        [
            {
                "claim_path": "analysis.facts[0]",
                "claim_text": "Community label was BULLISH.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            },
            {
                "claim_path": "analysis.key_points[0]",
                "claim_text": "Community label remained positive.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            },
            {
                "claim_path": "analysis.risk_points[0]",
                "claim_text": "The sample is limited.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            },
        ],
        score_metadata={
            "quality_score": {"source_type": "assessment_score"},
            "growth_score": {"source_type": "assessment_score"},
            "valuation_score": {
                "source_type": "deterministic_calculation",
                "calculation": "provided_operator_v1",
            },
        },
    )
    status, record = _run(AgentName.FUNDAMENTAL_ANALYST, response, [entry])

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    metadata = cast(JsonObject, analysis["metadata"])
    assert cast(JsonObject, metadata["score_metadata"])["valuation_score"] == {
        "source_type": "deterministic_calculation",
        "calculation": "provided_operator_v1",
        "evidence_ids": [],
    }


def test_fundamental_invalid_claim_is_quarantined_but_valid_minimum_passes() -> None:
    """One unsupported Claim is rejected while three valid Claims survive."""

    entry = _entry("stocktwits_label")
    claims = [
        {
            "claim_path": "analysis.facts[0]",
            "claim_text": "Community label was BULLISH.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.facts[1]",
            "claim_text": "Unsupported fact was 999.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.key_points[0]",
            "claim_text": "Community label remained positive.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.risk_points[0]",
            "claim_text": "The sample is limited.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
    ]
    status, record = _run(
        AgentName.FUNDAMENTAL_ANALYST,
        _fundamental_claim_response(claims),
        [entry],
    )

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    assert analysis["facts"] == ["Community label was BULLISH."]
    metadata = cast(JsonObject, analysis["metadata"])
    assert len(cast(list[JsonValue], metadata["rejected_claims"])) == 1


def test_fundamental_missing_binding_claim_is_quarantined() -> None:
    """A Claim with no Evidence IDs is rejected independently, not repaired."""

    entry = _entry("stocktwits_label")
    claims = [
        {
            "claim_path": "analysis.facts[0]",
            "claim_text": "Community label was BULLISH.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.facts[1]",
            "claim_text": "This claim omitted its binding.",
            "numeric_literals": [],
            "evidence_ids": [],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.key_points[0]",
            "claim_text": "Community label remained positive.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
        {
            "claim_path": "analysis.risk_points[0]",
            "claim_text": "The sample is limited.",
            "numeric_literals": [],
            "evidence_ids": [entry.evidence_id],
            "derivation_type": "direct_evidence",
        },
    ]
    status, record = _run(
        AgentName.FUNDAMENTAL_ANALYST,
        _fundamental_claim_response(claims),
        [entry],
    )

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    metadata = cast(
        JsonObject, cast(JsonObject, record.output_payload["analysis"])["metadata"]
    )
    rejected = cast(list[JsonValue], metadata["rejected_claims"])
    assert cast(JsonObject, rejected[0])["reason"] == "claim_schema_invalid"


def test_fundamental_two_valid_claims_meet_role_minimum() -> None:
    """Two strictly grounded Fundamental Claims meet the role availability floor."""

    entry = _entry("stocktwits_label")
    response = _fundamental_claim_response(
        [
            {
                "claim_path": "analysis.facts[0]",
                "claim_text": "Community label was BULLISH.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            },
            {
                "claim_path": "analysis.key_points[0]",
                "claim_text": "Community label remained positive.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            },
        ]
    )
    status, record = _run(AgentName.FUNDAMENTAL_ANALYST, response, [entry])

    assert status is AgentStatus.OK
    assert record.output_payload is not None


def test_fundamental_one_valid_claim_is_below_role_minimum() -> None:
    """A single retained Fundamental Claim remains insufficient for synthesis."""

    entry = _entry("stocktwits_label")
    response = _fundamental_claim_response(
        [
            {
                "claim_path": "analysis.facts[0]",
                "claim_text": "Community label was BULLISH.",
                "numeric_literals": [],
                "evidence_ids": [entry.evidence_id],
                "derivation_type": "direct_evidence",
            }
        ]
    )
    status, record = _run(AgentName.FUNDAMENTAL_ANALYST, response, [entry])

    assert status is AgentStatus.ERROR
    assert record.error_message is not None
    assert "minimum is 2" in record.error_message


def _bear_payload(entries: list[RoleEvidenceManifestEntry]) -> JsonObject:
    """Build a Bear payload with recursive upstream Claim provenance."""

    context = _context_for_role(AgentName.BEAR_MANAGER, entries[0])
    source = entries[0].source
    analyst_binding = ClaimEvidenceBinding.model_validate(
        {
            "claim_id": "analyst:base",
            "claim_path": "analysis.key_points[0]",
            "claim_text": "Upstream point.",
            "evidence_ids": [entries[0].evidence_id],
            "source_references": [source.model_dump(mode="json")],
        }
    )
    research_binding = ClaimEvidenceBinding.model_validate(
        {
            "claim_id": "research:base",
            "claim_path": "analysis.summary_points[0]",
            "claim_text": "Upstream summary.",
            "upstream_claim_ids": ["analyst:base"],
            "source_references": [source.model_dump(mode="json")],
        }
    )
    analyst = AnalystResponse(
        agent_name=AgentName.SENTIMENT_ANALYST,
        status=AgentStatus.OK,
        analysis=AnalystAnalysis(
            key_points=["Upstream point."],
            risk_points=[],
            uncertainties=[],
            supporting_citations=[],
            claim_evidence=[analyst_binding],
        ),
    )
    summary = ResearchSummary(
        summary_points=["Upstream summary."],
        conflicts=[],
        uncertainties=[],
        supporting_citations=[],
        claim_evidence=[research_binding],
    )
    return {
        "input_context": cast(JsonObject, context.model_dump(mode="json")),
        "analyst_outputs": [cast(JsonObject, analyst.model_dump(mode="json"))],
        "research_summary": cast(JsonObject, summary.model_dump(mode="json")),
        "research_contract": {
            "validated_upstream_claims": [
                cast(JsonObject, analyst_binding.model_dump(mode="json")),
                cast(JsonObject, research_binding.model_dump(mode="json")),
            ]
        },
    }


def test_bear_unsupported_numeric_claim_is_quarantined() -> None:
    """An ungrounded Bear number is rejected while two valid Claims pass."""

    entry = _entry("stocktwits_label")
    valid = {
        "claim_path": "bear_thesis[0]",
        "claim_text": "Community label was BULLISH.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    invalid = {
        "claim_path": "bear_thesis[1]",
        "claim_text": "Unsupported downside value was 999.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    second_valid = {
        "claim_path": "invalidators[0]",
        "claim_text": "The sample remains limited.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    status, output = _execute(
        BearManagerAgent,
        AgentName.BEAR_MANAGER,
        _bear_claim_response([valid, invalid, second_valid]),
        _bear_payload([entry]),
    )

    assert status is AgentStatus.OK
    assert output is not None
    assert output["bear_thesis"] == ["Community label was BULLISH."]
    assert output["invalidators"] == ["The sample remains limited."]


def test_bear_cannot_generate_new_numeric_literal() -> None:
    """Manager numbers absent from upstream Claims are quarantined."""

    entry = _entry("derived_return", evidence_type="structured_derived")
    first = {
        "claim_path": "bear_thesis[0]",
        "claim_text": "The deterministic return was -0.07756883814640692 ratio.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    second = {
        "claim_path": "conditions_required[0]",
        "claim_text": "The supplied return remains negative.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    status, output = _execute(
        BearManagerAgent,
        AgentName.BEAR_MANAGER,
        _bear_claim_response([first, second]),
        _bear_payload([entry]),
    )

    assert status is AgentStatus.ERROR
    assert output is None


def test_bear_public_narrative_cannot_introduce_a_new_number() -> None:
    """Bear public output contains only assembled Claim lists, not prose facts."""

    entry = _entry("stocktwits_label")
    claims = [
        {
            "claim_path": "bear_thesis[0]",
            "claim_text": "Community label was BULLISH.",
            "numeric_literals": [],
            "upstream_claim_ids": ["research:base"],
        },
        {
            "claim_path": "invalidators[0]",
            "claim_text": "The sample remains limited.",
            "numeric_literals": [],
            "upstream_claim_ids": ["research:base"],
        },
    ]
    status, output = _execute(
        BearManagerAgent,
        AgentName.BEAR_MANAGER,
        _bear_claim_response(claims),
        _bear_payload([entry]),
    )

    assert status is AgentStatus.OK
    assert output is not None
    assert "summary" not in output
    assert "rationale" not in output


def test_bear_minimum_valid_claims_failure_is_explicit() -> None:
    """One retained Bear Claim is below the configured minimum of two."""

    entry = _entry("stocktwits_label")
    only = {
        "claim_path": "bear_thesis[0]",
        "claim_text": "Community label was BULLISH.",
        "numeric_literals": [],
        "upstream_claim_ids": ["research:base"],
    }
    status, output = _execute(
        BearManagerAgent,
        AgentName.BEAR_MANAGER,
        _bear_claim_response([only]),
        _bear_payload([entry]),
    )

    assert status is AgentStatus.ERROR
    assert output is None


def test_rejected_claim_diagnostics_never_reach_manager_input() -> None:
    """Downstream parsing strips quarantine diagnostics and keeps valid claims."""

    output = cast(
        JsonObject,
        FundamentalAnalystResponse(
            status=AgentStatus.OK,
            analysis=FundamentalAnalysis(
                quality_score=0.5,
                growth_score=0.5,
                valuation_score=0.5,
                facts=["Valid fact."],
                key_points=[],
                risk_points=[],
                uncertainties=[],
                supporting_citations=[],
                claim_evidence=[],
                metadata={"rejected_claims": {"analysis.facts[1]": "bad"}},
            ),
        ).model_dump(mode="json"),
    )

    parsed = _parse_analyst_output(AgentName.FUNDAMENTAL_ANALYST, output)

    assert isinstance(parsed, FundamentalAnalystResponse)
    assert "rejected_claims" not in parsed.analysis.metadata
    execution = AgentExecutionResult(
        run_id="rejected-projection",
        agent_name=AgentName.FUNDAMENTAL_ANALYST,
        status=AgentStatus.OK,
        output=output,
    )
    slot = _versioned_output(execution)
    assert slot.output is not None
    metadata = cast(JsonObject, cast(JsonObject, slot.output["analysis"])["metadata"])
    assert "rejected_claims" not in metadata


def test_sentiment_business_claim_without_evidence_ids_fails_schema() -> None:
    """A business Claim cannot enter the Sentiment schema without Evidence IDs."""

    entry = _entry("stocktwits_label")
    response = _response(
        AgentName.SENTIMENT_ANALYST,
        "The supplied community label was BULLISH.",
        [entry.evidence_id],
    )
    analysis = cast(JsonObject, response["analysis"])
    claim = cast(JsonObject, cast(list[JsonValue], analysis["claims"])[0])
    claim.pop("evidence_ids")

    status, record = _run(AgentName.SENTIMENT_ANALYST, response, [entry])

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_sentiment_business_claim_with_empty_evidence_ids_fails_schema() -> None:
    """An empty Evidence list cannot satisfy a Sentiment business Claim."""

    entry = _entry("stocktwits_label")
    response = _response(
        AgentName.SENTIMENT_ANALYST,
        "The supplied community label was BULLISH.",
        [],
    )

    status, record = _run(AgentName.SENTIMENT_ANALYST, response, [entry])

    assert status is AgentStatus.ERROR
    assert record.output_payload is None


def test_sentiment_uncertainty_only_output_is_valid() -> None:
    """Non-factual uncertainty metadata may be returned without a citation."""

    response: JsonObject = {
        "agent_name": "sentiment_analyst",
        "status": "ok",
        "analysis": {
            "claims": [],
            "uncertainties": [
                "No attributable sentiment sample was supplied for this window."
            ],
        },
    }

    status, record = _run(AgentName.SENTIMENT_ANALYST, response, [])

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    analysis = cast(JsonObject, record.output_payload["analysis"])
    assert analysis["claim_evidence"] == []


def test_all_sentiment_business_claims_are_assembled_with_bindings() -> None:
    """Claim objects deterministically produce matching prose and bindings."""

    label = _entry("stocktwits_label")
    score = _entry("stocktwits_score")
    response = _response(
        AgentName.SENTIMENT_ANALYST,
        "The supplied community label was BULLISH.",
        [label.evidence_id],
    )
    analysis = cast(JsonObject, response["analysis"])
    claims = cast(list[JsonValue], analysis["claims"])
    claims.append(
        {
            "claim_path": "analysis.key_points[0]",
            "claim_text": "The supplied community sentiment score was 64.0.",
            "numeric_literals": [],
            "evidence_ids": [score.evidence_id],
            "derivation_type": "direct_evidence",
        }
    )

    status, record = _run(AgentName.SENTIMENT_ANALYST, response, [label, score])

    assert status is AgentStatus.OK
    assert record.output_payload is not None
    normalized = cast(JsonObject, record.output_payload["analysis"])
    business_claim_count = sum(
        len(cast(list[JsonValue], normalized[field]))
        for field in ("facts", "key_points", "risk_points")
    )
    assert len(cast(list[JsonValue], normalized["claim_evidence"])) == (
        business_claim_count
    )


def test_fixed_snapshot_seven_agent_contract_regression() -> None:
    """Seven pre-Risk roles pass citation and numeric contracts with Fake LLM."""

    valuation = _entry("rounded_valuation_source", evidence_type="structured_derived")
    technical = _entry("derived_return", evidence_type="structured_derived")
    sentiment = _entry("stocktwits_score")
    news = _entry("news_target")

    fundamental_claim = "The supplied valuation ratio was 48.192982456140356."
    fundamental_response: JsonObject = {
        "agent_name": "fundamental_analyst",
        "status": "ok",
        "analysis": {
            "quality_score": 0.5,
            "growth_score": 0.5,
            "valuation_score": 0.5,
            "facts": [fundamental_claim],
            "key_points": [],
            "risk_points": [],
            "uncertainties": [],
            "claim_evidence": [
                {
                    "claim_path": "analysis.facts[0]",
                    "claim_text": fundamental_claim,
                    "numeric_literals": list(numeric_literals(fundamental_claim)),
                    "evidence_ids": [valuation.evidence_id],
                    "derivation_type": "direct_evidence",
                }
            ],
        },
    }
    analyst_payloads = {
        AgentName.FUNDAMENTAL_ANALYST: (
            FundamentalAnalystAgent,
            fundamental_response,
            valuation,
        ),
        AgentName.TECHNICAL_TEXT_ANALYST: (
            TechnicalTextAnalystAgent,
            _response(
                AgentName.TECHNICAL_TEXT_ANALYST,
                "The deterministic return was -0.07756883814640692 ratio.",
                [technical.evidence_id],
            ),
            technical,
        ),
        AgentName.SENTIMENT_ANALYST: (
            SentimentAnalystAgent,
            _response(
                AgentName.SENTIMENT_ANALYST,
                "The supplied community sentiment score was 64.0.",
                [sentiment.evidence_id],
            ),
            sentiment,
        ),
        AgentName.NEWS_EVENT_ANALYST: (
            NewsEventAnalystAgent,
            _response(
                AgentName.NEWS_EVENT_ANALYST,
                "An attributed report reduced a stated value to $263.66 from $285.56.",
                [news.evidence_id],
            ),
            news,
        ),
    }
    outputs: dict[AgentName, JsonObject] = {}
    for role, (agent_class, response, entry) in analyst_payloads.items():
        context = _context_for_role(role, entry)
        status, output = _execute(
            agent_class,
            role,
            response,
            {
                "run_id": f"fixed-seven-{role.value}",
                "agent_name": role.value,
                "model_name": "fake-model",
                "input_context": cast(JsonObject, context.model_dump(mode="json")),
            },
        )
        assert status is AgentStatus.OK
        assert output is not None
        outputs[role] = output

    fundamental_output = FundamentalAnalystResponse.model_validate(
        outputs[AgentName.FUNDAMENTAL_ANALYST]
    )
    news_analysis = cast(JsonObject, outputs[AgentName.NEWS_EVENT_ANALYST]["analysis"])
    news_binding = cast(
        JsonObject,
        cast(list[JsonValue], news_analysis["claim_evidence"])[0],
    )
    news_claim_id = cast(str, news_binding["claim_id"])
    manager_claim = "The attributed report contained values of $263.66 and $285.56."
    manager_response: JsonObject = {
        "agent_name": "research_manager",
        "status": "ok",
        "analysis": {
            "claims": [
                {
                    "claim_id": "research:news-values",
                    "claim_path": "analysis.summary_points[0]",
                    "claim_text": manager_claim,
                    "upstream_claim_ids": [news_claim_id],
                }
            ],
            "uncertainties": [],
        },
    }
    research_request = ResearchManagerRequest(
        input_context=_context_for_role(AgentName.RESEARCH_MANAGER, news),
        analyst_outputs=[
            _parse_analyst_output(role, outputs[role])
            for role in (
                AgentName.FUNDAMENTAL_ANALYST,
                AgentName.TECHNICAL_TEXT_ANALYST,
                AgentName.SENTIMENT_ANALYST,
                AgentName.NEWS_EVENT_ANALYST,
            )
        ],
    )
    research_status, research_output = _execute(
        ResearchManagerAgent,
        AgentName.RESEARCH_MANAGER,
        manager_response,
        cast(JsonObject, research_request.model_dump(mode="json")),
    )
    assert research_status is AgentStatus.OK
    assert research_output is not None
    outputs[AgentName.RESEARCH_MANAGER] = research_output

    summary = ResearchSummary.model_validate(research_output["analysis"])
    research_analysis = cast(JsonObject, research_output["analysis"])
    research_binding = cast(
        JsonObject,
        cast(list[JsonValue], research_analysis["claim_evidence"])[0],
    )
    for role, agent_class, thesis_key in (
        (AgentName.BULL_MANAGER, BullManagerAgent, "bull_thesis"),
        (AgentName.BEAR_MANAGER, BearManagerAgent, "bear_thesis"),
    ):
        thesis = f"The evidence preserves $263.66 and $285.56 for the {role.value}."
        role_claims: list[JsonObject] = [
            {
                "claim_id": f"{role.value}:thesis",
                "claim_path": f"{thesis_key}[0]",
                "claim_text": thesis,
                "upstream_claim_ids": ["research:news-values"],
            }
        ]
        if role is AgentName.BEAR_MANAGER:
            role_claims.append(
                {
                    "claim_id": "bear_manager:invalidator",
                    "claim_path": "invalidators[0]",
                    "claim_text": (
                        "The stated third-party values may cease to be relevant."
                    ),
                    "upstream_claim_ids": ["research:news-values"],
                }
            )
        role_response: JsonObject = {
            "claims": cast(list[JsonValue], role_claims),
            "confidence": 0.5,
        }
        request_model = (
            BullManagerRequest if role is AgentName.BULL_MANAGER else BearManagerRequest
        )
        request = request_model(
            input_context=_context_for_role(role, news),
            analyst_outputs=[fundamental_output],
            research_summary=summary,
            research_contract={
                "schema_version": "validated_claim_collection_v1",
                "validated_upstream_claims": [research_binding],
            },
        )
        status, output = _execute(
            agent_class,
            role,
            role_response,
            cast(JsonObject, request.model_dump(mode="json")),
        )
        assert status is AgentStatus.OK
        assert output is not None
        outputs[role] = output

    assert set(outputs) == {
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
        AgentName.RESEARCH_MANAGER,
        AgentName.BULL_MANAGER,
        AgentName.BEAR_MANAGER,
    }
    bindings: list[JsonObject] = []
    for output in outputs.values():
        raw_bindings = output.get("claim_evidence")
        analysis_value = output.get("analysis")
        if raw_bindings is None and isinstance(analysis_value, dict):
            raw_bindings = analysis_value.get("claim_evidence")
        assert isinstance(raw_bindings, list)
        bindings.extend(item for item in raw_bindings if isinstance(item, dict))
    numeric_claims = sum(bool(binding.get("numeric_literals")) for binding in bindings)
    assert len(bindings) == 8
    assert numeric_claims == 7


def test_manager_no_longer_resolves_raw_evidence_index() -> None:
    """Manager factual input is upstream Claims, never the raw Evidence index."""

    item = _fixture("rounded_valuation_source")
    payload: JsonObject = {
        "input_context": {
            "report_date": "2026-08-13",
            "market_scope": "US",
            "asset_id": "US:AAPL",
            "structured_features": {},
        },
        "research_contract": {
            "context": {
                "data_evidence_index": {
                    item["evidence_id"]: {
                        "field_path": "valuation.price_to_earnings",
                        "value": 48.192982456140356,
                        "unit": "ratio",
                        "source": {"normalized_record_key": item["document_id"]},
                    }
                }
            }
        },
    }

    assert _citation_text(payload, []) == []
