"""Tests for evaluation orchestration, aggregation, and audit metadata."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    FakeReportJudge,
    ReportEvaluationService,
)
from src.schemas.evaluation import EvaluationInput, EvaluationResult


class _Store:
    """Capture persisted results through the repository boundary."""

    def __init__(self) -> None:
        self.saved: list[EvaluationResult] = []

    def save(self, result: EvaluationResult) -> None:
        self.saved.append(result)


def _service(
    loader: EvaluationRuleLoader,
    store: _Store,
) -> ReportEvaluationService:
    return ReportEvaluationService(
        loader,
        DeterministicReportEvaluator(),
        FakeReportJudge({"readability": 0.5}),
        store,
        evaluation_id_factory=lambda: "evaluation-1",
        clock=lambda: datetime(2026, 8, 7, tzinfo=UTC),
    )


def test_service_persists_complete_separated_versioned_result(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """One call produces all dimensions with check-level reasons and evidence."""

    store = _Store()
    result = _service(rule_loader, store).evaluate(evaluation_input)

    assert store.saved == [result]
    assert result.evaluation_id == "evaluation-1"
    assert result.ruleset_version == "report_quality_v1"
    assert result.judge_model == "fake-report-judge"
    assert len(result.deterministic_checks) == 8
    assert len(result.judge_checks) == 6
    assert len(result.dimensions) == 12
    assert result.deterministic_score == 1.0
    assert result.judge_score == pytest.approx(4.7 / 5.2)
    assert result.overall_score == pytest.approx(11.5 / 12)
    assert all(item.reason and item.evidence for item in result.dimensions)


def test_input_fingerprint_is_stable_for_unordered_disclosures(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Equivalent set-like input order does not change the audit fingerprint."""

    first = evaluation_input.model_copy(
        update={"known_missing_data": ["beta", "alpha"]}
    )
    second = evaluation_input.model_copy(
        update={"known_missing_data": ["alpha", "beta"]}
    )

    result_one = _service(rule_loader, _Store()).evaluate(first)
    result_two = _service(rule_loader, _Store()).evaluate(second)

    assert result_one.input_fingerprint == result_two.input_fingerprint
