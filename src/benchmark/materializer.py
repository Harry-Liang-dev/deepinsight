"""Deterministic materialization of fixed Benchmark report semantics."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time
from typing import cast

from src.agents.evidence import numeric_literals
from src.models.enums import (
    BenchmarkExpectedOutcome,
    ClaimIntent,
    ReportType,
    TaskStatus,
)
from src.models.types import JsonObject, JsonValue
from src.reports.contracts import (
    STANDARD_SECTION_NAMES,
    ReportStatement,
    StandardReportSection,
)
from src.schemas.benchmark import BenchmarkClaim, ResearchBenchmarkCase
from src.schemas.common import SourceReference
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


class BenchmarkReportMaterializer:
    """Turn fixed case content into the current standard report contract."""

    def build(self, case: ResearchBenchmarkCase) -> ResearchReport:
        """Build one report without Agent, Provider, Memory, or network access."""

        if (
            case.expected_outcome is not BenchmarkExpectedOutcome.REPORT
            or case.report is None
        ):
            raise ValueError("only report Benchmark cases can be materialized")
        sources = {
            source.evidence_id: SourceReference(
                document_id=source.document_id,
                excerpt_ref=source.excerpt_ref,
                provider=source.provider,
            )
            for source in case.sources
        }
        sections = [
            StandardReportSection(
                section_name=name,
                title=_SECTION_TITLES[name],
                section_order=index,
                facts=[_statement(case.report.facts, index, "fact", sources)],
                inferences=[
                    _statement(case.report.inferences, index, "inference", sources)
                ],
                risk_warnings=[_statement(case.report.risks, index, "risk", sources)],
                uncertainties=[
                    case.report.uncertainties[index % len(case.report.uncertainties)]
                ],
            )
            for index, name in enumerate(STANDARD_SECTION_NAMES)
        ]
        report_id = f"benchmark-{case.case_id}-{case.case_version}"
        report_json: JsonObject = {
            section.section_name: cast(
                JsonValue,
                section.model_dump(mode="json"),
            )
            for section in sections
        }
        report_sections = [
            ReportSection(
                report_id=report_id,
                section_name=section.section_name,
                section_order=section.section_order,
                section_markdown=_render_section(section),
                citations=_section_citations(section),
            )
            for section in sections
        ]
        source_trace = _deduplicate_sources(
            citation for section in sections for citation in _section_citations(section)
        )
        return ResearchReport(
            report_id=report_id,
            report_date=case.report_date,
            market_scope=case.market,
            report_type=ReportType.SINGLE_ASSET,
            asset_id=case.asset_id,
            title=case.report.title,
            thesis_bull_summary=case.report.bull_summary,
            thesis_bear_summary=case.report.bear_summary,
            risk_summary=case.report.risk_summary,
            final_recommendation=case.report.final_recommendation,
            report_markdown=_render_report(case.report.title, sections),
            report_json=report_json,
            source_trace=source_trace,
            sections=report_sections,
            status=TaskStatus.COMPLETED,
            created_at=datetime.combine(case.report_date, time.min, tzinfo=UTC),
        )


def _statement(
    claims: list[BenchmarkClaim],
    index: int,
    claim_type: str,
    sources: dict[str, SourceReference],
) -> ReportStatement:
    claim = claims[index % len(claims)]
    return ReportStatement(
        text=claim.text,
        citations=[sources[evidence_id] for evidence_id in claim.evidence_ids],
        claim_id=f"benchmark:{claim_type}:{index}",
        claim_intent=(
            ClaimIntent.FACT
            if claim_type == "fact"
            else ClaimIntent.ANALYTICAL_INFERENCE
        ),
        numeric_literals=numeric_literals(claim.text),
    )


def _render_report(
    title: str,
    sections: list[StandardReportSection],
) -> str:
    return "\n\n".join([f"# {title}", *(_render_section(item) for item in sections)])


def _render_section(section: StandardReportSection) -> str:
    blocks = [f"## {section.title}"]
    for heading, statements in (
        ("Facts", section.facts),
        ("Inferences", section.inferences),
        ("Risk Warnings", section.risk_warnings),
    ):
        blocks.append(f"### {heading}")
        blocks.extend(f"- {statement.text}" for statement in statements)
    blocks.append("### Uncertainties")
    blocks.extend(f"- {item}" for item in section.uncertainties)
    return "\n".join(blocks)


def _section_citations(
    section: StandardReportSection,
) -> list[SourceReference]:
    return _deduplicate_sources(
        citation
        for statements in (
            section.facts,
            section.inferences,
            section.risk_warnings,
        )
        for statement in statements
        for citation in statement.citations
    )


def _deduplicate_sources(
    citations: Iterable[SourceReference],
) -> list[SourceReference]:
    unique: dict[tuple[str, str, str, str], SourceReference] = {}
    for citation in citations:
        key = (
            citation.document_id or "",
            citation.excerpt_ref or "",
            citation.provider or "",
            citation.source_url or "",
        )
        unique.setdefault(key, citation)
    return list(unique.values())
