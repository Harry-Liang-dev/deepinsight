"""Presentation-only vNext review; never creates ResearchState or Quant output."""

from __future__ import annotations

from src.reports.assembler import _render_report_markdown
from src.reports.contracts import StandardReportSection
from src.services.research_vnext.contracts import ReviewProduct, TraderProduct


def render_review(trader: TraderProduct, review: ReviewProduct) -> str:
    """Reuse existing renderer with explicit non-executing research boundaries."""
    sections = [
        StandardReportSection(
            section_name="boundary",
            title="Research only",
            section_order=0,
            uncertainties=[
                (
                    "DEVELOPMENT_ONLY_OPT_IN; NOT_PRODUCTION; NOT_FOR"
                    "MAL_PIT; NOT_QUANT_ADMITTED; NOT_TRADING"
                )
            ],
        ),
        StandardReportSection(
            section_name="proposal",
            title=trader.action,
            section_order=1,
            uncertainties=[
                trader.proposal.thesis,
                *trader.proposal.invalidation_conditions,
                *trader.uncertainties,
            ],
        ),
        StandardReportSection(
            section_name="review",
            title=review.decision,
            section_order=2,
            uncertainties=list(review.review.reasons),
        ),
    ]
    return _render_report_markdown("Research vNext — non-executing review", sections)
