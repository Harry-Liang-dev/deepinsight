"""Offline evaluation of the tracked Phase One real-report acceptance artifact."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from pathlib import Path
from typing import cast

from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    FakeReportJudge,
    ReportEvaluationService,
)
from src.models.enums import EvaluationDimension
from src.models.types import JsonObject
from src.schemas.evaluation import (
    EvaluationEvidenceItem,
    EvaluationInput,
    EvaluationResult,
)
from src.schemas.reports import ResearchReport

_ARTIFACT_ROOT = Path("data/live_acceptance/20260806T150000Z")
_REPORT_PATH = _ARTIFACT_ROOT / "reports" / "rep_4d16218e5bb14bfbb2548de4263b99f1.json"
_RAW_PATH = (
    _ARTIFACT_ROOT
    / "raw"
    / "source_9a77456fa49e"
    / "e52ff61e03854d3fa60570213028fc45a0ce18e9c7ee080e73495370a2065575.txt"
)


class _Store:
    """Capture the historical evaluation without touching its live database."""

    def __init__(self) -> None:
        self.result: EvaluationResult | None = None

    def save(self, result: EvaluationResult) -> None:
        self.result = result


def test_tracked_legacy_report_does_not_masquerade_as_claim_v2() -> None:
    """A historical prose-only report remains readable but is not Claim-v2 valid."""

    report = ResearchReport.model_validate(
        cast(
            JsonObject,
            json.loads(_REPORT_PATH.read_text(encoding="utf-8")),
        )
    )
    source_text = _RAW_PATH.read_text(encoding="utf-8")
    published_at = datetime.combine(report.report_date, time.min, tzinfo=UTC)
    payload = EvaluationInput(
        report=report,
        evidence_items=[
            EvaluationEvidenceItem(
                evidence_id=f"historical-source-{index}",
                source_ref=source_ref,
                text=source_text,
                published_at=published_at,
            )
            for index, source_ref in enumerate(report.source_trace)
        ],
        known_missing_data=[
            "structured_features.pe_ttm",
            "retrieved_memories",
        ],
        ruleset_version="report_quality_v1",
    )
    store = _Store()
    result = ReportEvaluationService(
        EvaluationRuleLoader(Path("config/evaluation")),
        DeterministicReportEvaluator(),
        FakeReportJudge(),
        store,
        evaluation_id_factory=lambda: "evaluation-historical-live-report",
        clock=lambda: datetime(2026, 8, 7, tzinfo=UTC),
    ).evaluate(payload)
    dimensions = {item.dimension: item for item in result.dimensions}
    numeric = next(
        item
        for item in result.deterministic_checks
        if item.check_id == "numeric_grounding"
    )

    assert store.result == result
    assert dimensions[EvaluationDimension.STRUCTURE_COMPLETENESS].score < 1.0
    assert dimensions[EvaluationDimension.CITATION_COVERAGE].score == 1.0
    assert dimensions[EvaluationDimension.CITATION_TRACEABILITY].score == 1.0
    assert dimensions[EvaluationDimension.MISSING_DATA_DISCLOSURE].score == 1.0
    assert numeric.score == 1.0
    assert "no numeric textual claims" in numeric.reason
