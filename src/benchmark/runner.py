"""Threshold-based execution of fixed research Benchmark cases."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from src.benchmark.materializer import BenchmarkReportMaterializer
from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    FakeReportJudge,
    ReportEvaluationService,
    ReportJudge,
)
from src.models.enums import (
    BenchmarkExpectedOutcome,
    BenchmarkRunMode,
)
from src.schemas.benchmark import (
    BenchmarkCaseResult,
    BenchmarkManifest,
    BenchmarkMetricFailure,
    BenchmarkRunResult,
    BenchmarkSource,
    ResearchBenchmarkCase,
)
from src.schemas.common import SourceReference
from src.schemas.evaluation import (
    EvaluationEvidenceItem,
    EvaluationInput,
    EvaluationResult,
)


class _EvaluationCollector:
    """Capture one EvaluationResult without adding Benchmark persistence."""

    def __init__(self) -> None:
        self.result: EvaluationResult | None = None

    def save(self, result: EvaluationResult) -> None:
        self.result = result


class ResearchBenchmarkRunner:
    """Run deterministic default gates and optional live semantic gates."""

    def __init__(
        self,
        manifest: BenchmarkManifest,
        rule_loader: EvaluationRuleLoader,
        judge: ReportJudge,
        *,
        mode: BenchmarkRunMode,
        clock: Callable[[], datetime],
        materializer: BenchmarkReportMaterializer | None = None,
    ) -> None:
        """Bind explicit data, evaluation, Judge, mode, and time dependencies."""

        is_fake = isinstance(judge, FakeReportJudge)
        if mode is BenchmarkRunMode.DEFAULT and not is_fake:
            raise ValueError("default Benchmark requires the offline Fake Judge")
        if mode is BenchmarkRunMode.LIVE and is_fake:
            raise ValueError("live Benchmark cannot use the Fake Judge")
        self._manifest = manifest
        self._rule_loader = rule_loader
        self._judge = judge
        self._mode = mode
        self._clock = clock
        self._materializer = materializer or BenchmarkReportMaterializer()

    def run(
        self,
        cases: Iterable[ResearchBenchmarkCase],
    ) -> BenchmarkRunResult:
        """Evaluate sorted cases and return a machine-readable summary."""

        results = [self._run_case(case) for case in sorted(cases, key=_case_key)]
        passed = sum(item.passed for item in results)
        return BenchmarkRunResult(
            benchmark_version=self._manifest.benchmark_version,
            mode=self._mode,
            evaluation_ruleset_version=self._manifest.evaluation_ruleset_version,
            judge_model=self._judge.model_name,
            generated_at=self._clock(),
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=len(results) - passed,
            cases=results,
        )

    @staticmethod
    def write(result: BenchmarkRunResult, path: Path) -> None:
        """Atomically write stable pretty JSON for CI and audit tools."""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _run_case(self, case: ResearchBenchmarkCase) -> BenchmarkCaseResult:
        if case.expected_outcome is BenchmarkExpectedOutcome.EXPECTED_FAILURE:
            lifecycle = float(
                case.observed_failure_code == case.expected.expected_failure_code
                and case.report is None
            )
            fact_coverage = _source_fact_coverage(
                case.expected.required_facts,
                [source.text for source in case.sources],
            )
            failures = [
                *_minimum_failure(
                    "lifecycle_compliance",
                    lifecycle,
                    case.thresholds.lifecycle_compliance_min,
                ),
                *_minimum_failure(
                    "expected_fact_coverage",
                    fact_coverage,
                    case.thresholds.expected_fact_coverage_min,
                ),
            ]
            return BenchmarkCaseResult(
                case_id=case.case_id,
                case_version=case.case_version,
                scenario=case.scenario,
                market=case.market,
                asset_id=case.asset_id,
                passed=not failures,
                lifecycle_compliance=lifecycle,
                expected_fact_coverage=fact_coverage,
                forbidden_conclusion_compliance=1.0,
                observed_failure_code=case.observed_failure_code,
                failures=failures,
            )

        report = self._materializer.build(case)
        collector = _EvaluationCollector()
        service = ReportEvaluationService(
            self._rule_loader,
            DeterministicReportEvaluator(),
            self._judge,
            collector,
            evaluation_id_factory=(
                lambda: f"benchmark-evaluation-{case.case_id}-{case.case_version}"
            ),
            clock=self._clock,
        )
        evaluation = service.evaluate(
            EvaluationInput(
                report=report,
                evidence_items=[
                    EvaluationEvidenceItem(
                        evidence_id=source.evidence_id,
                        source_ref=report_source(source),
                        text=source.text,
                        published_at=source.published_at,
                    )
                    for source in case.sources
                ],
                known_missing_data=case.known_missing_data,
                ruleset_version=self._manifest.evaluation_ruleset_version,
            )
        )
        check_scores = {
            check.check_id: check.score for check in evaluation.deterministic_checks
        }
        dimension_scores = {
            dimension.dimension: dimension.score for dimension in evaluation.dimensions
        }
        fact_coverage = _fact_coverage(
            case.expected.required_facts,
            report.report_markdown,
            [source.text for source in case.sources],
        )
        forbidden_compliance = _forbidden_compliance(
            case.expected.forbidden_conclusions,
            " ".join(
                item
                for item in (
                    report.report_markdown,
                    report.thesis_bull_summary,
                    report.thesis_bear_summary,
                    report.risk_summary,
                    report.final_recommendation,
                )
                if item is not None
            ),
        )
        failures = [
            *_minimum_failure(
                "lifecycle_compliance",
                1.0,
                case.thresholds.lifecycle_compliance_min,
            ),
            *_minimum_failure(
                "deterministic_score",
                evaluation.deterministic_score,
                case.thresholds.deterministic_score_min or 0.0,
            ),
            *_minimum_failure(
                "expected_fact_coverage",
                fact_coverage,
                case.thresholds.expected_fact_coverage_min,
            ),
            *_minimum_failure(
                "forbidden_conclusion_compliance",
                forbidden_compliance,
                case.thresholds.forbidden_conclusion_compliance_min,
            ),
        ]
        for check_id, minimum in case.thresholds.check_minimums.items():
            failures.extend(
                _minimum_failure(
                    f"check:{check_id}",
                    check_scores[check_id],
                    minimum,
                )
            )
        if self._mode is BenchmarkRunMode.LIVE:
            for dimension, minimum in case.thresholds.live_dimension_minimums.items():
                failures.extend(
                    _minimum_failure(
                        f"dimension:{dimension.value}",
                        dimension_scores[dimension],
                        minimum,
                    )
                )
        return BenchmarkCaseResult(
            case_id=case.case_id,
            case_version=case.case_version,
            scenario=case.scenario,
            market=case.market,
            asset_id=case.asset_id,
            passed=not failures,
            lifecycle_compliance=1.0,
            expected_fact_coverage=fact_coverage,
            forbidden_conclusion_compliance=forbidden_compliance,
            evaluation=evaluation,
            check_scores=check_scores,
            dimension_scores=dimension_scores,
            failures=failures,
        )


def report_source(source: BenchmarkSource) -> SourceReference:
    """Build a SourceReference without exposing YAML models to evaluation."""

    return SourceReference(
        document_id=source.document_id,
        excerpt_ref=source.excerpt_ref,
        provider=source.provider,
    )


def _fact_coverage(
    expected: list[str],
    report_text: str,
    evidence_texts: list[str],
) -> float:
    if not expected:
        return 1.0
    report = _normalize(report_text)
    evidence = _normalize(" ".join(evidence_texts))
    covered = sum(
        _normalize(fact) in report and _normalize(fact) in evidence for fact in expected
    )
    return covered / len(expected)


def _source_fact_coverage(
    expected: list[str],
    evidence_texts: list[str],
) -> float:
    if not expected:
        return 1.0
    evidence = _normalize(" ".join(evidence_texts))
    covered = sum(_normalize(fact) in evidence for fact in expected)
    return covered / len(expected)


def _forbidden_compliance(forbidden: list[str], report_text: str) -> float:
    normalized = _normalize(report_text)
    violations = sum(_normalize(item) in normalized for item in forbidden)
    return 1.0 - (violations / len(forbidden))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _minimum_failure(
    metric: str,
    actual: float,
    threshold: float,
) -> list[BenchmarkMetricFailure]:
    if actual >= threshold:
        return []
    return [
        BenchmarkMetricFailure(
            metric=metric,
            actual=actual,
            threshold=threshold,
            reason=f"{metric} scored {actual:.6f}, below {threshold:.6f}.",
        )
    ]


def _case_key(case: ResearchBenchmarkCase) -> str:
    return case.case_id
