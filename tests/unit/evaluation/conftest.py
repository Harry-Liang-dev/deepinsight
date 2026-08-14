"""Shared deterministic report-evaluation fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.evaluation import EvaluationRuleLoader
from src.reports import ReportAssembler
from src.schemas.evaluation import EvaluationEvidenceItem, EvaluationInput
from tests.fixtures.report_data import make_report_input


@pytest.fixture
def rule_loader() -> EvaluationRuleLoader:
    """Load the repository's first versioned quality rule set."""

    return EvaluationRuleLoader(Path("config/evaluation"))


@pytest.fixture
def evaluation_input() -> EvaluationInput:
    """Return an attributable standard report and its exact source text."""

    report = ReportAssembler().assemble(make_report_input())
    return EvaluationInput(
        report=report,
        evidence_items=[
            EvaluationEvidenceItem(
                evidence_id="doc-1:chunk-1",
                source_ref=report.source_trace[0],
                text=(
                    "Revenue increased while valuation remained elevated. "
                    "Policy conditions remained restrictive."
                ),
                published_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        ],
        ruleset_version="report_quality_v1",
    )
