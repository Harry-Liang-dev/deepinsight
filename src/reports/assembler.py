"""Deterministic, evidence-preserving Phase One report assembly."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import cast

from pydantic import BaseModel, ValidationError

from src.agents.contracts import AgentExecutionResult
from src.models.enums import AgentName, AgentStatus, MemoryLevel, TaskStatus
from src.models.types import JsonObject, JsonValue
from src.reports.contracts import (
    STANDARD_SECTION_NAMES,
    ReportAssemblyInput,
    ReportStatement,
    StandardReportSection,
)
from src.schemas.agents import (
    AnalystResponse,
    BearManagerResponse,
    BullManagerResponse,
    FundamentalAnalystResponse,
    ResearchManagerResponse,
    RiskManagerResponse,
)
from src.schemas.common import SourceReference
from src.schemas.memory import MemoryWriteRequest
from src.schemas.reports import ReportSection, ResearchReport

_SECTION_TITLES = {
    "executive_view": "Executive View",
    "macro_context": "Macro Context",
    "fundamentals": "Fundamentals",
    "technical_text": "Technical Text",
    "sentiment": "Sentiment",
    "news_events": "News and Events",
    "bull_case": "Bull Case",
    "bear_case": "Bear Case",
    "risk_review": "Risk Review",
    "final_synthesis": "Final Synthesis",
}


class ReportAssemblyError(RuntimeError):
    """Base error for invalid or unattributable report inputs."""


class MissingReportSectionError(ReportAssemblyError):
    """Raised when the standard Phase One section set is incomplete."""


class EmptyAgentOutputError(ReportAssemblyError):
    """Raised when a required Agent provides no usable report content."""


class ReportCitationError(ReportAssemblyError):
    """Raised when a report claim cannot be linked to supplied evidence."""


class ReportAssembler:
    """Build Markdown and JSON from one validated structured Agent result."""

    def assemble(
        self,
        payload: ReportAssemblyInput,
        *,
        status: TaskStatus = TaskStatus.RUNNING,
    ) -> ResearchReport:
        """Assemble one single-asset standard research report.

        Args:
            payload: Request, context, Agent outputs, identity, and timestamp.
            status: Explicit lifecycle state assigned by orchestration.

        Returns:
            A standard report whose Markdown and JSON share one section model.

        Raises:
            ReportAssemblyError: If sections, Agent outputs, or evidence are
                incomplete or invalid.
        """

        self._validate_sections(payload.request.include_sections)
        allowed_citations = _allowed_citations(payload)
        outputs = _parse_outputs(payload)
        sections = self._build_sections(payload, outputs, allowed_citations)
        source_trace = _section_citations(sections)
        if not source_trace:
            raise ReportCitationError("report has no attributable source trace")

        title = (
            f"{payload.input_context.asset_id} Research Note | "
            f"{payload.request.report_date.isoformat()}"
        )
        markdown = _render_report_markdown(title, sections)
        report_json: JsonObject = {
            section.section_name: cast(
                JsonValue,
                section.model_dump(mode="json"),
            )
            for section in sections
        }
        report_sections = [
            ReportSection(
                report_id=payload.report_id,
                section_name=section.section_name,
                section_order=section.section_order,
                section_markdown=_render_section_markdown(section),
                citations=_statements_citations(section),
            )
            for section in sections
        ]

        research = outputs.research_manager.analysis
        bull = outputs.bull_manager
        bear = outputs.bear_manager
        risk = outputs.risk_manager
        final_recommendation = _final_recommendation(
            research.summary_points,
            risk.narrative_risk_score,
        )
        _reject_trading_text(final_recommendation)

        return ResearchReport(
            report_id=payload.report_id,
            report_date=payload.request.report_date,
            market_scope=payload.request.market_scope,
            report_type=payload.request.report_type,
            asset_id=payload.input_context.asset_id,
            title=title,
            thesis_bull_summary=_join_statements(bull.bull_thesis),
            thesis_bear_summary=_join_statements(bear.bear_thesis),
            risk_summary=_join_statements(
                [*risk.confirmed_risks, *risk.scenario_risks]
            ),
            final_recommendation=final_recommendation,
            report_markdown=markdown,
            report_json=report_json,
            source_trace=source_trace,
            sections=report_sections,
            status=status,
            created_at=payload.created_at,
        )

    def to_memory_request(self, report: ResearchReport) -> MemoryWriteRequest:
        """Create the attributable L3 trace written after report persistence.

        Args:
            report: Assembled report with a non-empty source trace.

        Returns:
            A Memory write request containing report synthesis and risk summary.

        Raises:
            ReportCitationError: If the report has no attributable source.
        """

        if not report.source_trace:
            raise ReportCitationError("report Memory requires a source reference")
        summary_parts = [report.final_recommendation]
        if report.risk_summary:
            summary_parts.append(f"Risk review: {report.risk_summary}")
        return MemoryWriteRequest(
            memory_level=MemoryLevel.L3,
            namespace_key=f"REPORT:{report.report_id}",
            asset_id=report.asset_id,
            effective_ts=report.created_at,
            memory_type="report_trace",
            summary_text=" ".join(summary_parts),
            source_ref_json=report.source_trace[0],
            created_by="report_pipeline",
        )

    @staticmethod
    def _validate_sections(include_sections: list[str]) -> None:
        if len(include_sections) != len(set(include_sections)):
            raise MissingReportSectionError("report sections cannot be duplicated")
        configured = set(include_sections)
        required = set(STANDARD_SECTION_NAMES)
        if configured != required:
            missing = sorted(required - configured)
            unsupported = sorted(configured - required)
            raise MissingReportSectionError(
                f"invalid standard section set; missing={missing}, "
                f"unsupported={unsupported}"
            )

    def _build_sections(
        self,
        payload: ReportAssemblyInput,
        outputs: _ParsedOutputs,
        allowed: set[tuple[str, str, str, str]],
    ) -> list[StandardReportSection]:
        result = payload.agent_result
        analysts = result.analyst_results
        fundamental_result = analysts[AgentName.FUNDAMENTAL_ANALYST]
        technical_result = analysts[AgentName.TECHNICAL_TEXT_ANALYST]
        sentiment_result = analysts[AgentName.SENTIMENT_ANALYST]
        news_result = analysts[AgentName.NEWS_EVENT_ANALYST]
        research_result = _manager_result(result.research_manager)
        bull_result = _manager_result(result.bull_manager)
        bear_result = _manager_result(result.bear_manager)
        risk_result = _manager_result(result.risk_manager)

        document_facts = [
            ReportStatement(
                text=f"Evidence source reviewed: {document.title}.",
                citations=[
                    SourceReference(
                        document_id=document.document_id,
                        excerpt_ref=document.chunk_id,
                    )
                ],
            )
            for document in payload.input_context.retrieved_documents
        ]
        macro_facts = [
            ReportStatement(
                text=memory.summary_text,
                citations=[memory.source_ref_json],
            )
            for memory in payload.input_context.retrieved_memories
            if memory.memory_level in {MemoryLevel.L1, MemoryLevel.L4}
        ]
        macro_uncertainties = (
            []
            if macro_facts
            else ["No attributable L1 or L4 macro Memory evidence was supplied."]
        )

        fundamental = outputs.fundamental.analysis
        technical = outputs.technical.analysis
        sentiment = outputs.sentiment.analysis
        news = outputs.news.analysis
        research = outputs.research_manager.analysis
        bull = outputs.bull_manager
        bear = outputs.bear_manager
        risk = outputs.risk_manager

        sections = [
            StandardReportSection(
                section_name="executive_view",
                title=_SECTION_TITLES["executive_view"],
                section_order=0,
                facts=_validated_statements(document_facts, allowed),
                inferences=_claims(
                    research_result,
                    "analysis.summary_points",
                    research.summary_points,
                    allowed,
                ),
                risk_warnings=_claims(
                    research_result,
                    "analysis.conflicts",
                    research.conflicts,
                    allowed,
                ),
                uncertainties=_unique(
                    [
                        *research.uncertainties,
                        *research_result.uncertainties,
                        *payload.agent_result.uncertainties,
                    ]
                ),
            ),
            StandardReportSection(
                section_name="macro_context",
                title=_SECTION_TITLES["macro_context"],
                section_order=1,
                facts=_validated_statements(macro_facts, allowed),
                uncertainties=macro_uncertainties,
            ),
            _analyst_section(
                "fundamentals",
                2,
                fundamental_result,
                fundamental.facts,
                fundamental.key_points,
                fundamental.risk_points,
                [*fundamental.uncertainties, *fundamental_result.uncertainties],
                allowed,
            ),
            _analyst_section(
                "technical_text",
                3,
                technical_result,
                technical.facts,
                technical.key_points,
                technical.risk_points,
                [*technical.uncertainties, *technical_result.uncertainties],
                allowed,
            ),
            _analyst_section(
                "sentiment",
                4,
                sentiment_result,
                sentiment.facts,
                sentiment.key_points,
                sentiment.risk_points,
                [*sentiment.uncertainties, *sentiment_result.uncertainties],
                allowed,
            ),
            _analyst_section(
                "news_events",
                5,
                news_result,
                news.facts,
                news.key_points,
                news.risk_points,
                [*news.uncertainties, *news_result.uncertainties],
                allowed,
            ),
            StandardReportSection(
                section_name="bull_case",
                title=_SECTION_TITLES["bull_case"],
                section_order=6,
                inferences=[
                    *_claims(
                        bull_result,
                        "bull_thesis",
                        bull.bull_thesis,
                        allowed,
                    ),
                    *_claims(
                        bull_result,
                        "conditions_required",
                        bull.conditions_required,
                        allowed,
                    ),
                ],
                risk_warnings=_claims(
                    bull_result,
                    "invalidators",
                    bull.invalidators,
                    allowed,
                ),
                uncertainties=_result_uncertainties(bull_result),
            ),
            StandardReportSection(
                section_name="bear_case",
                title=_SECTION_TITLES["bear_case"],
                section_order=7,
                inferences=[
                    *_claims(
                        bear_result,
                        "bear_thesis",
                        bear.bear_thesis,
                        allowed,
                    ),
                    *_claims(
                        bear_result,
                        "conditions_required",
                        bear.conditions_required,
                        allowed,
                    ),
                ],
                risk_warnings=_claims(
                    bear_result,
                    "invalidators",
                    bear.invalidators,
                    allowed,
                ),
                uncertainties=_result_uncertainties(bear_result),
            ),
            StandardReportSection(
                section_name="risk_review",
                title=_SECTION_TITLES["risk_review"],
                section_order=8,
                inferences=[
                    *_claims(
                        risk_result,
                        "scenario_risks",
                        risk.scenario_risks,
                        allowed,
                    ),
                    *_claims(
                        risk_result,
                        "watch_items",
                        risk.watch_items,
                        allowed,
                    ),
                ],
                risk_warnings=_claims(
                    risk_result,
                    "confirmed_risks",
                    risk.confirmed_risks,
                    allowed,
                ),
                uncertainties=_result_uncertainties(risk_result),
            ),
            StandardReportSection(
                section_name="final_synthesis",
                title=_SECTION_TITLES["final_synthesis"],
                section_order=9,
                inferences=_claims(
                    research_result,
                    "analysis.summary_points",
                    research.summary_points,
                    allowed,
                ),
                risk_warnings=[
                    *_claims(
                        research_result,
                        "analysis.conflicts",
                        research.conflicts,
                        allowed,
                    ),
                    *_claims(
                        risk_result,
                        "confirmed_risks",
                        risk.confirmed_risks,
                        allowed,
                    ),
                ],
                uncertainties=_unique(
                    [
                        *research.uncertainties,
                        *payload.agent_result.uncertainties,
                    ]
                ),
            ),
        ]
        return sections


class _ParsedOutputs:
    def __init__(
        self,
        *,
        fundamental: FundamentalAnalystResponse,
        technical: AnalystResponse,
        sentiment: AnalystResponse,
        news: AnalystResponse,
        research_manager: ResearchManagerResponse,
        bull_manager: BullManagerResponse,
        bear_manager: BearManagerResponse,
        risk_manager: RiskManagerResponse,
    ) -> None:
        self.fundamental = fundamental
        self.technical = technical
        self.sentiment = sentiment
        self.news = news
        self.research_manager = research_manager
        self.bull_manager = bull_manager
        self.bear_manager = bear_manager
        self.risk_manager = risk_manager


def _parse_outputs(payload: ReportAssemblyInput) -> _ParsedOutputs:
    result = payload.agent_result
    if result.status is not AgentStatus.OK:
        raise ReportAssemblyError("Agent collaboration did not complete")
    required_analysts = {
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    }
    if set(result.analyst_results) != required_analysts:
        raise ReportAssemblyError("report requires all four Analyst results")

    try:
        fundamental = _parse_result(
            result.analyst_results[AgentName.FUNDAMENTAL_ANALYST],
            AgentName.FUNDAMENTAL_ANALYST,
            FundamentalAnalystResponse,
        )
        technical = _parse_result(
            result.analyst_results[AgentName.TECHNICAL_TEXT_ANALYST],
            AgentName.TECHNICAL_TEXT_ANALYST,
            AnalystResponse,
        )
        sentiment = _parse_result(
            result.analyst_results[AgentName.SENTIMENT_ANALYST],
            AgentName.SENTIMENT_ANALYST,
            AnalystResponse,
        )
        news = _parse_result(
            result.analyst_results[AgentName.NEWS_EVENT_ANALYST],
            AgentName.NEWS_EVENT_ANALYST,
            AnalystResponse,
        )
        research = _parse_result(
            _manager_result(result.research_manager),
            AgentName.RESEARCH_MANAGER,
            ResearchManagerResponse,
        )
        bull = _parse_result(
            _manager_result(result.bull_manager),
            AgentName.BULL_MANAGER,
            BullManagerResponse,
        )
        bear = _parse_result(
            _manager_result(result.bear_manager),
            AgentName.BEAR_MANAGER,
            BearManagerResponse,
        )
        risk = _parse_result(
            _manager_result(result.risk_manager),
            AgentName.RISK_MANAGER,
            RiskManagerResponse,
        )
    except ValidationError as exc:
        raise ReportAssemblyError(
            "Agent output failed report schema validation"
        ) from exc

    _require_content(
        "fundamental_analyst",
        fundamental.analysis.facts,
        fundamental.analysis.key_points,
        fundamental.analysis.risk_points,
    )
    _require_content(
        "technical_text_analyst",
        technical.analysis.facts,
        technical.analysis.key_points,
        technical.analysis.risk_points,
    )
    _require_content(
        "sentiment_analyst",
        sentiment.analysis.facts,
        sentiment.analysis.key_points,
        sentiment.analysis.risk_points,
    )
    _require_content(
        "news_event_analyst",
        news.analysis.facts,
        news.analysis.key_points,
        news.analysis.risk_points,
    )
    _require_content(
        "research_manager",
        research.analysis.summary_points,
        research.analysis.conflicts,
    )
    _require_content(
        "bull_manager",
        bull.bull_thesis,
        bull.conditions_required,
        bull.invalidators,
    )
    _require_content(
        "bear_manager",
        bear.bear_thesis,
        bear.conditions_required,
        bear.invalidators,
    )
    _require_content(
        "risk_manager",
        risk.confirmed_risks,
        risk.scenario_risks,
        risk.watch_items,
    )

    return _ParsedOutputs(
        fundamental=fundamental,
        technical=technical,
        sentiment=sentiment,
        news=news,
        research_manager=research,
        bull_manager=bull,
        bear_manager=bear,
        risk_manager=risk,
    )


def _parse_result[OutputT: BaseModel](
    result: AgentExecutionResult,
    expected_name: AgentName,
    model_type: type[OutputT],
) -> OutputT:
    if result.agent_name is not expected_name:
        raise ReportAssemblyError("Agent result role does not match report section")
    if result.status is not AgentStatus.OK or result.output is None:
        raise ReportAssemblyError(f"{expected_name.value} did not complete")
    parsed = model_type.model_validate(result.output)
    configured_name: object = getattr(parsed, "agent_name", None)
    if isinstance(configured_name, AgentName) and configured_name is not expected_name:
        raise ReportAssemblyError("Agent output role does not match report section")
    return parsed


def _manager_result(
    result: AgentExecutionResult | None,
) -> AgentExecutionResult:
    if result is None:
        raise ReportAssemblyError("required Manager result is missing")
    return result


def _require_content(name: str, *groups: Sequence[str]) -> None:
    if not any(text.strip() for group in groups for text in group):
        raise EmptyAgentOutputError(f"{name} returned no report content")


def _analyst_section(
    section_name: str,
    order: int,
    result: AgentExecutionResult,
    facts: list[str],
    key_points: list[str],
    risk_points: list[str],
    uncertainties: list[str],
    allowed: set[tuple[str, str, str, str]],
) -> StandardReportSection:
    return StandardReportSection(
        section_name=section_name,
        title=_SECTION_TITLES[section_name],
        section_order=order,
        facts=_claims(
            result,
            "analysis.facts",
            facts,
            allowed,
        ),
        inferences=_claims(
            result,
            "analysis.key_points",
            key_points,
            allowed,
        ),
        risk_warnings=_claims(
            result,
            "analysis.risk_points",
            risk_points,
            allowed,
        ),
        uncertainties=_unique([*uncertainties, *_result_uncertainties(result)]),
    )


def _claims(
    result: AgentExecutionResult,
    claim_path: str,
    texts: Sequence[str],
    allowed: set[tuple[str, str, str, str]],
) -> list[ReportStatement]:
    statements: list[ReportStatement] = []
    for index, text in enumerate(texts):
        _reject_trading_text(text)
        path = f"{claim_path}[{index}]"
        citations = [
            citation
            for evidence in result.evidence
            if evidence.claim_path == path
            for citation in evidence.citations
        ]
        if not citations:
            raise ReportCitationError(f"report claim has no evidence: {path}")
        statements.append(
            ReportStatement(
                text=text,
                citations=_validate_citations(citations, allowed),
            )
        )
    return statements


def _validated_statements(
    statements: Sequence[ReportStatement],
    allowed: set[tuple[str, str, str, str]],
) -> list[ReportStatement]:
    validated: list[ReportStatement] = []
    for statement in statements:
        _reject_trading_text(statement.text)
        validated.append(
            statement.model_copy(
                update={
                    "citations": _validate_citations(
                        statement.citations,
                        allowed,
                    )
                }
            )
        )
    return validated


def _allowed_citations(
    payload: ReportAssemblyInput,
) -> set[tuple[str, str, str, str]]:
    allowed: set[tuple[str, str, str, str]] = set()
    for document in payload.input_context.retrieved_documents:
        citation = SourceReference(
            document_id=document.document_id,
            excerpt_ref=document.chunk_id,
        )
        allowed.add(_citation_key(citation))
    for memory in payload.input_context.retrieved_memories:
        citation = memory.source_ref_json
        allowed.add(_citation_key(citation))
        if citation.document_id is not None:
            allowed.add(
                _citation_key(
                    SourceReference(
                        document_id=citation.document_id,
                        excerpt_ref=citation.excerpt_ref,
                    )
                )
            )
    return allowed


def _validate_citations(
    citations: Iterable[SourceReference],
    allowed: set[tuple[str, str, str, str]],
) -> list[SourceReference]:
    unique: dict[tuple[str, str, str, str], SourceReference] = {}
    for citation in citations:
        key = _citation_key(citation)
        if key not in allowed:
            raise ReportCitationError("report cited evidence absent from its input")
        unique.setdefault(key, citation)
    if not unique:
        raise ReportCitationError("report statement requires a citation")
    return list(unique.values())


def _citation_key(citation: SourceReference) -> tuple[str, str, str, str]:
    return (
        citation.document_id or "",
        citation.excerpt_ref or "",
        citation.provider or "",
        citation.source_url or "",
    )


def _result_uncertainties(result: AgentExecutionResult) -> list[str]:
    missing = [f"Missing data: {item}." for item in result.missing_data]
    return _unique([*result.uncertainties, *missing])


def _section_citations(
    sections: Sequence[StandardReportSection],
) -> list[SourceReference]:
    citations = [
        citation for section in sections for citation in _statements_citations(section)
    ]
    return _deduplicate_citations(citations)


def _statements_citations(
    section: StandardReportSection,
) -> list[SourceReference]:
    citations = [
        citation
        for statements in (
            section.facts,
            section.inferences,
            section.risk_warnings,
        )
        for statement in statements
        for citation in statement.citations
    ]
    return _deduplicate_citations(citations)


def _deduplicate_citations(
    citations: Iterable[SourceReference],
) -> list[SourceReference]:
    unique: dict[tuple[str, str, str, str], SourceReference] = {}
    for citation in citations:
        unique.setdefault(_citation_key(citation), citation)
    return list(unique.values())


def _render_report_markdown(
    title: str,
    sections: Sequence[StandardReportSection],
) -> str:
    rendered = [f"# {title}"]
    rendered.extend(_render_section_markdown(section) for section in sections)
    return "\n\n".join(rendered)


def _render_section_markdown(section: StandardReportSection) -> str:
    rendered = [f"## {section.title}"]
    for title, statements in (
        ("Facts", section.facts),
        ("Inferences", section.inferences),
        ("Risk Warnings", section.risk_warnings),
    ):
        block = _render_statements(title, statements)
        if block is not None:
            rendered.append(block)
    if section.uncertainties:
        rendered.append(
            "\n".join(
                [
                    "### Uncertainties",
                    *(f"- {item}" for item in section.uncertainties),
                ]
            )
        )
    return "\n\n".join(rendered)


def _render_statements(
    title: str,
    statements: Sequence[ReportStatement],
) -> str | None:
    if not statements:
        return None
    return "\n".join(
        [
            f"### {title}",
            *(
                f"- {statement.text} {_render_citations(statement.citations)}"
                for statement in statements
            ),
        ]
    )


def _render_citations(citations: Sequence[SourceReference]) -> str:
    labels: list[str] = []
    for citation in citations:
        if citation.document_id:
            label = citation.document_id
            if citation.excerpt_ref:
                label = f"{label}#{citation.excerpt_ref}"
        elif citation.provider:
            label = citation.provider
        else:
            label = citation.source_url or "source"
        labels.append(label)
    return f"[Sources: {', '.join(labels)}]"


def _final_recommendation(
    summary_points: Sequence[str],
    risk_score: float,
) -> str:
    summary = summary_points[0]
    return (
        f"Research synthesis: {summary} "
        f"Narrative risk score: {risk_score:.2f}. "
        "This conclusion is research analysis only."
    )


def _join_statements(statements: Sequence[str]) -> str | None:
    return " ".join(statements) if statements else None


def _reject_trading_text(text: str) -> None:
    normalized = text.casefold()
    forbidden_phrases = (
        "price target",
        "target price",
        "position size",
        "place an order",
        "execute an order",
        "买入",
        "卖出",
        "目标价",
        "仓位",
        "下单",
    )
    if re.search(
        r"\b(?:buy|sell)\s+(?:the\s+)?"
        r"(?:shares?|stocks?|securit(?:y|ies)|position)\b",
        normalized,
    ) is not None or any(phrase in normalized for phrase in forbidden_phrases):
        raise ReportAssemblyError("report content contained a trading instruction")


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))
