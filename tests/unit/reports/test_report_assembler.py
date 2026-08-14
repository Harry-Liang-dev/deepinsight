"""Tests for standard report assembly and evidence validation."""

from __future__ import annotations

from typing import cast

import pytest

from src.agents import EvidenceLink
from src.models.enums import AgentName, AgentStatus, ClaimIntent, TaskStatus
from src.models.types import JsonObject
from src.reports import (
    STANDARD_SECTION_NAMES,
    EmptyAgentOutputError,
    MissingReportSectionError,
    ReportAssembler,
    ReportAssemblyError,
    StandardReportSection,
)
from src.schemas.agents import BullManagerResponse
from src.schemas.common import ErrorInfo, SourceReference
from tests.fixtures.report_data import make_report_input


def test_complete_report_has_standard_markdown_json_and_epistemic_sections() -> None:
    """A complete Agent result should produce one consistent standard report."""

    payload = make_report_input()
    report = ReportAssembler().assemble(payload)

    assert report.status is TaskStatus.RUNNING
    assert [section.section_name for section in report.sections] == list(
        STANDARD_SECTION_NAMES
    )
    assert set(report.report_json) == set(STANDARD_SECTION_NAMES)
    assert len(report.source_trace) == 1
    assert "Revenue increased." in report.report_markdown
    assert "### Facts" in report.report_markdown
    assert "### Inferences" in report.report_markdown
    assert "### Risk Warnings" in report.report_markdown
    assert "### Uncertainties" in report.report_markdown

    fundamentals = StandardReportSection.model_validate(
        report.report_json["fundamentals"]
    )
    assert fundamentals.facts[0].text == "Revenue increased."
    assert fundamentals.inferences[0].text == "Revenue trend may support growth."
    assert fundamentals.risk_warnings[0].text == "Valuation remained elevated."
    assert fundamentals.uncertainties
    assert fundamentals.facts[0].text in report.report_markdown
    assert fundamentals.inferences[0].text in report.report_markdown


def test_report_allows_sell_through_operating_metric() -> None:
    """A sell-through metric is analysis, not a trading instruction."""

    payload = make_report_input()
    risk_result = payload.agent_result.risk_manager
    assert risk_result is not None
    assert risk_result.output is not None
    output = dict(risk_result.output)
    output["watch_items"] = ["Monitor quarterly sell-through rates."]
    payload.agent_result.risk_manager = risk_result.model_copy(
        update={"output": output}
    )

    report = ReportAssembler().assemble(payload)

    assert "sell-through rates" in report.report_markdown


@pytest.mark.parametrize(
    "text",
    [
        "Jefferies lowered its price target for Apple to $250.",
        "Goldman Sachs reiterated its Buy rating on Apple.",
        "Morgan Stanley raised its target price from $220 to $240.",
    ],
)
def test_report_allows_attributed_third_party_opinion(text: str) -> None:
    """Attributed ratings and targets remain cited research evidence."""

    payload = make_report_input()
    result = payload.agent_result.analyst_results[AgentName.NEWS_EVENT_ANALYST]
    assert result.output is not None
    analysis = result.output["analysis"]
    assert isinstance(analysis, dict)
    analysis["key_points"] = [text]
    result.evidence[0] = result.evidence[0].model_copy(
        update={"claim_intent": ClaimIntent.THIRD_PARTY_OPINION}
    )

    report = ReportAssembler().assemble(payload)
    section = StandardReportSection.model_validate(report.report_json["news_events"])

    assert section.inferences[0].text == text
    assert section.inferences[0].claim_intent is ClaimIntent.THIRD_PARTY_OPINION
    assert section.inferences[0].citations == [result.evidence[0].citations[0]]
    assert f"[Third-party opinion] {text}" in report.report_markdown


@pytest.mark.parametrize(
    "text",
    [
        "DeepInsight recommends buying AAPL.",
        "Our price target for AAPL is $320.",
        "Buy AAPL at $300.",
        "Allocate 20% of the portfolio to AAPL.",
        "Short AAPL with a stop loss at $330.",
    ],
)
def test_report_rejects_system_recommendation_or_execution(text: str) -> None:
    """The report boundary rejects system advice and executable actions."""

    payload = make_report_input()
    result = payload.agent_result.analyst_results[AgentName.NEWS_EVENT_ANALYST]
    assert result.output is not None
    analysis = result.output["analysis"]
    assert isinstance(analysis, dict)
    analysis["key_points"] = [text]

    with pytest.raises(ReportAssemblyError, match="trading instruction"):
        ReportAssembler().assemble(payload)


def test_report_does_not_create_new_claim_or_render_rejected_claim() -> None:
    """Report prose is limited to accepted claims plus presentation labels."""

    payload = make_report_input()
    bear = payload.agent_result.bear_manager
    assert bear is not None
    assert bear.output is not None
    bear.output["metadata"] = {
        "rejected_claims": [
            {
                "claim_path": "bear_thesis[9]",
                "claim_text": "Rejected claim must never render.",
                "reason": "unknown_or_cross_role_evidence_id",
            }
        ]
    }

    report = ReportAssembler().assemble(payload)
    accepted = {
        statement
        for result in (
            *payload.agent_result.analyst_results.values(),
            payload.agent_result.research_manager,
            payload.agent_result.bull_manager,
            payload.agent_result.bear_manager,
            payload.agent_result.risk_manager,
        )
        if result is not None and result.output is not None
        for statement in _claim_texts(result.output)
    }
    rendered_claims = {
        statement.text
        for value in report.report_json.values()
        for section in [StandardReportSection.model_validate(value)]
        for group in (section.facts, section.inferences, section.risk_warnings)
        for statement in group
    }

    assert rendered_claims <= accepted
    assert "Rejected claim must never render." not in report.report_markdown


def _claim_texts(value: object) -> list[str]:
    """Return business prose fields from one fixture output."""

    if not isinstance(value, dict):
        return []
    analysis = value.get("analysis")
    root = analysis if isinstance(analysis, dict) else value
    fields = (
        "facts",
        "key_points",
        "risk_points",
        "summary_points",
        "conflicts",
        "bull_thesis",
        "bear_thesis",
        "conditions_required",
        "invalidators",
        "confirmed_risks",
        "scenario_risks",
        "watch_items",
    )
    return [
        item
        for field in fields
        for items in [root.get(field)]
        if isinstance(items, list)
        for item in items
        if isinstance(item, str)
    ]


def test_missing_or_duplicate_standard_section_is_rejected() -> None:
    """The first standard report must contain each fixed section exactly once."""

    payload = make_report_input()
    payload.request.include_sections.remove("risk_review")

    with pytest.raises(MissingReportSectionError, match="risk_review"):
        ReportAssembler().assemble(payload)

    duplicate = make_report_input()
    duplicate.request.include_sections[-1] = "executive_view"
    with pytest.raises(MissingReportSectionError):
        ReportAssembler().assemble(duplicate)


def test_duplicate_references_are_stably_deduplicated() -> None:
    """Repeated Agent evidence should remain one section and global reference."""

    report = ReportAssembler().assemble(make_report_input())

    assert len(report.source_trace) == 1
    for section in report.sections:
        assert len(section.citations) <= 1
    fundamentals = StandardReportSection.model_validate(
        report.report_json["fundamentals"]
    )
    assert len(fundamentals.facts[0].citations) == 1
    assert len(fundamentals.inferences[0].citations) == 1


def test_empty_required_agent_output_is_rejected() -> None:
    """A structurally valid but content-free Manager output is not a report."""

    payload = make_report_input()
    empty_bull = BullManagerResponse(
        bull_thesis=[],
        conditions_required=[],
        invalidators=[],
        confidence=0.5,
    )
    bull_result = payload.agent_result.bull_manager
    assert bull_result is not None
    payload.agent_result.bull_manager = bull_result.model_copy(
        update={
            "output": cast(
                JsonObject,
                empty_bull.model_dump(mode="json"),
            )
        }
    )

    with pytest.raises(EmptyAgentOutputError, match="bull_manager"):
        ReportAssembler().assemble(payload)


def test_failed_agent_collaboration_cannot_become_a_report() -> None:
    """A failed research chain must not be assembled as a completed artifact."""

    payload = make_report_input()
    payload.agent_result.status = AgentStatus.ERROR

    with pytest.raises(ReportAssemblyError, match="did not complete"):
        ReportAssembler().assemble(payload)


def test_failed_analyst_becomes_explicit_unavailable_section() -> None:
    """A degraded collaboration must disclose, not fabricate, Analyst content."""

    payload = make_report_input()
    failed_name = AgentName.TECHNICAL_TEXT_ANALYST
    successful = payload.agent_result.analyst_results[failed_name]
    payload.agent_result.analyst_results[failed_name] = successful.model_copy(
        update={
            "status": AgentStatus.ERROR,
            "output": None,
            "evidence": [],
            "missing_data": ["validated technical evidence"],
            "error": ErrorInfo(
                code="schema_validation",
                message="Agent input or output failed schema validation.",
            ),
        }
    )
    payload.agent_result.missing_agents = [failed_name]
    payload.agent_result.uncertainties = ["technical_text_analyst was unavailable."]

    report = ReportAssembler().assemble(payload)

    section = StandardReportSection.model_validate(report.report_json["technical_text"])
    assert section.facts == []
    assert section.inferences == []
    assert section.risk_warnings == []
    assert "technical_text_analyst output was unavailable." in section.uncertainties
    assert "Missing data: validated technical evidence." in section.uncertainties
    assert "technical_text_analyst output was unavailable." in report.report_markdown


def test_manager_sections_do_not_repeat_global_missing_data() -> None:
    """Coverage gaps belong to their owning Analyst or global limitations view."""

    payload = make_report_input()
    for name in ("bull_manager", "bear_manager", "risk_manager"):
        result = getattr(payload.agent_result, name)
        assert result is not None
        setattr(
            payload.agent_result,
            name,
            result.model_copy(
                update={"missing_data": ["fundamentals.roe", "ohlcv.adj_close"]}
            ),
        )

    report = ReportAssembler().assemble(payload)

    for section_name in ("bull_case", "bear_case", "risk_review"):
        section = StandardReportSection.model_validate(report.report_json[section_name])
        assert not any("fundamentals.roe" in item for item in section.uncertainties)
        assert not any("ohlcv.adj_close" in item for item in section.uncertainties)


def test_report_does_not_revalidate_accepted_claim_citation() -> None:
    """Report preserves accepted Claim provenance without raw re-grounding."""

    payload = make_report_input()
    result = payload.agent_result.analyst_results[AgentName.FUNDAMENTAL_ANALYST]
    fabricated = SourceReference(
        document_id="invented-document",
        excerpt_ref="invented-chunk",
    )
    key_point_index = next(
        index
        for index, evidence in enumerate(result.evidence)
        if evidence.claim_path == "analysis.key_points[0]"
    )
    result.evidence[key_point_index] = EvidenceLink(
        claim_path="analysis.key_points[0]",
        citations=[fabricated],
    )

    report = ReportAssembler().assemble(payload)

    section = StandardReportSection.model_validate(report.report_json["fundamentals"])
    assert section.inferences[0].citations == [fabricated]
    assert section.inferences[0].claim_status == "accepted"
