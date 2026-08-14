"""Neutral candidate-versus-baseline live Benchmark comparisons."""

from __future__ import annotations

from src.models.enums import EvaluationDimension
from src.schemas.live_benchmark import (
    LiveBenchmarkComparison,
    LiveBenchmarkRunResult,
    LiveCaseDelta,
)


class LiveBenchmarkComparisonError(ValueError):
    """Raised when two runs did not use the same measurement input."""


class LiveBenchmarkComparator:
    """Compare measurements without deciding that one Prompt is better."""

    def compare(
        self,
        baseline: LiveBenchmarkRunResult,
        candidate: LiveBenchmarkRunResult,
    ) -> LiveBenchmarkComparison:
        """Return candidate-minus-baseline deltas for compatible real runs."""

        if (
            baseline.dataset_version != candidate.dataset_version
            or baseline.snapshot_sha256 != candidate.snapshot_sha256
            or baseline.config.evaluation_ruleset_version
            != candidate.config.evaluation_ruleset_version
            or set(baseline.case_input_fingerprints)
            != set(candidate.case_input_fingerprints)
        ):
            raise LiveBenchmarkComparisonError("live Benchmark runs are not comparable")
        baseline_cases = {item.case_id: item for item in baseline.cases}
        deltas: list[LiveCaseDelta] = []
        for candidate_case in sorted(candidate.cases, key=lambda item: item.case_id):
            baseline_case = baseline_cases[candidate_case.case_id]
            overall_delta = None
            dimensions: dict[EvaluationDimension, float] = {}
            if baseline_case.evaluation and candidate_case.evaluation:
                overall_delta = (
                    candidate_case.evaluation.overall_score
                    - baseline_case.evaluation.overall_score
                )
                baseline_dimensions = {
                    item.dimension: item.score
                    for item in baseline_case.evaluation.dimensions
                }
                dimensions = {
                    item.dimension: item.score - baseline_dimensions[item.dimension]
                    for item in candidate_case.evaluation.dimensions
                }
            deltas.append(
                LiveCaseDelta(
                    case_id=candidate_case.case_id,
                    overall_score_delta=overall_delta,
                    agent_success_rate_delta=(
                        candidate_case.agent_success_rate
                        - baseline_case.agent_success_rate
                    ),
                    dimension_deltas=dimensions,
                )
            )
        return LiveBenchmarkComparison(
            baseline_run_id=baseline.run_id,
            candidate_run_id=candidate.run_id,
            dataset_version=baseline.dataset_version,
            snapshot_sha256=baseline.snapshot_sha256,
            case_deltas=deltas,
        )
