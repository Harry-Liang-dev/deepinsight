"""End-to-end offline Benchmark execution and failure diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmark import ResearchBenchmarkRunner
from src.evaluation import EvaluationRuleLoader, FakeReportJudge, LLMReportJudge
from src.models.enums import BenchmarkRunMode
from src.models.types import JsonObject
from src.schemas.benchmark import (
    BenchmarkManifest,
    BenchmarkRunResult,
    ResearchBenchmarkCase,
)
from src.schemas.evaluation import JudgeResponse


class _NoopGateway:
    """Gateway that would fail if a boundary test accidentally invoked it."""

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[JudgeResponse] | None = None,
    ) -> JsonObject:
        del (
            model,
            system_prompt,
            input_payload,
            prompt_version,
            schema_version,
            response_model,
        )
        raise AssertionError("default Benchmark attempted an LLM call")


def _runner(manifest: BenchmarkManifest) -> ResearchBenchmarkRunner:
    return ResearchBenchmarkRunner(
        manifest,
        EvaluationRuleLoader(Path("config/evaluation")),
        FakeReportJudge(),
        mode=BenchmarkRunMode.DEFAULT,
        clock=lambda: manifest.default_generated_at,
    )


def test_default_benchmark_passes_all_cases_without_network(
    benchmark_manifest: BenchmarkManifest,
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """The checked-in corpus runs entirely through deterministic offline gates."""

    result = _runner(benchmark_manifest).run(benchmark_cases)

    assert result.total_cases == 7
    assert result.passed_cases == 7
    assert result.failed_cases == 0
    assert all(case.passed for case in result.cases)
    assert (
        next(
            case for case in result.cases if case.scenario == "analyst_failure"
        ).evaluation
        is None
    )
    assert all(
        case.evaluation is not None
        for case in result.cases
        if case.scenario != "analyst_failure"
    )


def test_default_result_is_reproducible_and_json_round_trips(
    tmp_path: Path,
    benchmark_manifest: BenchmarkManifest,
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """Fixed cases, rules, Fake Judge, and time produce identical JSON."""

    runner = _runner(benchmark_manifest)
    first = runner.run(benchmark_cases)
    second = runner.run(reversed(benchmark_cases))
    output = tmp_path / "benchmark.json"
    runner.write(first, output)
    loaded = BenchmarkRunResult.model_validate_json(output.read_text(encoding="utf-8"))

    assert first == second
    assert loaded == first


def test_missing_expected_fact_fails_despite_perfect_fake_judge(
    benchmark_manifest: BenchmarkManifest,
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """Fake semantic scores cannot hide a missing fixed expected fact."""

    case = next(item for item in benchmark_cases if item.scenario == "complete_company")
    expected = case.expected.model_copy(
        update={
            "required_facts": [
                *case.expected.required_facts,
                "This required fact is absent.",
            ]
        }
    )
    degraded = case.model_copy(update={"expected": expected})

    result = _runner(benchmark_manifest).run([degraded]).cases[0]

    assert not result.passed
    assert result.evaluation is not None
    assert result.evaluation.judge_score == 1.0
    failure = next(
        item for item in result.failures if item.metric == "expected_fact_coverage"
    )
    assert failure.actual < failure.threshold


def test_forbidden_conclusion_and_deterministic_threshold_name_failures(
    benchmark_manifest: BenchmarkManifest,
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """Failures identify the exact compliance or deterministic metric."""

    case = next(item for item in benchmark_cases if item.scenario == "complete_company")
    assert case.report is not None
    report = case.report.model_copy(update={"final_recommendation": "Buy the stock."})
    source = case.sources[0].model_copy(
        update={"published_at": case.sources[0].published_at.replace(year=2027)}
    )
    degraded = case.model_copy(update={"report": report, "sources": [source]})

    result = _runner(benchmark_manifest).run([degraded]).cases[0]
    metrics = {failure.metric for failure in result.failures}

    assert not result.passed
    assert "forbidden_conclusion_compliance" in metrics
    assert "check:temporal_validity" in metrics
    assert "deterministic_score" in metrics


def test_default_and_live_judge_boundaries_are_enforced(
    benchmark_manifest: BenchmarkManifest,
) -> None:
    """Default cannot use a live Judge and live cannot use the Fake Judge."""

    live_judge = LLMReportJudge(_NoopGateway(), "live-model")
    with pytest.raises(ValueError, match="default Benchmark"):
        ResearchBenchmarkRunner(
            benchmark_manifest,
            EvaluationRuleLoader(Path("config/evaluation")),
            live_judge,
            mode=BenchmarkRunMode.DEFAULT,
            clock=lambda: benchmark_manifest.default_generated_at,
        )
    with pytest.raises(ValueError, match="live Benchmark"):
        ResearchBenchmarkRunner(
            benchmark_manifest,
            EvaluationRuleLoader(Path("config/evaluation")),
            FakeReportJudge(),
            mode=BenchmarkRunMode.LIVE,
            clock=lambda: benchmark_manifest.default_generated_at,
        )
