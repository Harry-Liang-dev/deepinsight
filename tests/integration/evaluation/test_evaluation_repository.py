"""Integration tests for immutable evaluation-result persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    FakeReportJudge,
    ReportEvaluationService,
)
from src.reports import ReportAssembler
from src.repositories import (
    DuckDBDatabase,
    EvaluationRepository,
    RepositoryError,
)
from src.schemas.evaluation import EvaluationEvidenceItem, EvaluationInput
from tests.fixtures.report_data import make_report_input


def test_evaluation_repository_round_trip_and_duplicate_protection(
    tmp_path: Path,
) -> None:
    """Complete audit JSON round-trips and an existing ID is immutable."""

    database = DuckDBDatabase(tmp_path / "evaluation.duckdb")
    database.bootstrap()
    repository = EvaluationRepository(database)
    report = ReportAssembler().assemble(make_report_input())
    payload = EvaluationInput(
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
    result = ReportEvaluationService(
        EvaluationRuleLoader(Path("config/evaluation")),
        DeterministicReportEvaluator(),
        FakeReportJudge(),
        repository,
        evaluation_id_factory=lambda: "evaluation-persisted",
        clock=lambda: datetime(2026, 8, 7, tzinfo=UTC),
    ).evaluate(payload)

    assert repository.get("evaluation-persisted") == result
    assert repository.get("absent") is None
    with pytest.raises(RepositoryError, match="failed to save"):
        repository.save(result)

    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE report_evaluations
            SET overall_score = 0.0
            WHERE evaluation_id = ?
            """,
            ("evaluation-persisted",),
        )
    with pytest.raises(RepositoryError, match="inconsistent"):
        repository.get("evaluation-persisted")
