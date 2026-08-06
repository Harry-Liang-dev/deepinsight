"""Tests for standard report assembly and evidence validation."""

from __future__ import annotations

from typing import cast

import pytest

from src.agents import EvidenceLink
from src.models.enums import AgentName, AgentStatus, TaskStatus
from src.models.types import JsonObject
from src.reports import (
    STANDARD_SECTION_NAMES,
    EmptyAgentOutputError,
    MissingReportSectionError,
    ReportAssembler,
    ReportAssemblyError,
    ReportCitationError,
    StandardReportSection,
)
from src.schemas.agents import BullManagerResponse
from src.schemas.common import SourceReference
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


def test_unknown_agent_citation_is_rejected() -> None:
    """The assembler must not pass through evidence absent from input context."""

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

    with pytest.raises(ReportCitationError, match="absent"):
        ReportAssembler().assemble(payload)
