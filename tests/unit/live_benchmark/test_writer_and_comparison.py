"""Offline artifact and A/B tests for the live Agent Benchmark."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.agents import ResearchTaskResult
from src.live_benchmark import (
    LiveBenchmarkArtifactError,
    LiveBenchmarkComparator,
    LiveBenchmarkComparisonError,
    LiveBenchmarkWriter,
    LiveSnapshotLoader,
    materialize_scenarios,
)
from src.models.enums import AgentName, AgentStatus
from src.schemas.live_benchmark import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunResult,
    LiveCaseResult,
)

ROOT = Path(__file__).resolve().parents[3]


def _run(run_id: str, *, snapshot_hash: str | None = None) -> LiveBenchmarkRunResult:
    loaded = LiveSnapshotLoader(
        ROOT / "benchmarks/live_agent/v1/snapshot.yaml",
        ROOT / "benchmarks/live_agent/v1/snapshot.sha256",
    ).load()
    scenario = materialize_scenarios(loaded)[0]
    config = LiveBenchmarkConfig(
        run_id=run_id,
        provider="qwen",
        provider_real=True,
        judge_real=True,
        model_name="qwen3.7-flash",
        prompt_versions={name: "v1" for name in AgentName},
        prompt_sha256={name: "a" * 64 for name in AgentName},
        inference_parameters={"max_retries": 1},
        evaluation_ruleset_version="report_quality_v1",
        generated_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    agent_result = ResearchTaskResult(
        task_id=f"task:{run_id}",
        status=AgentStatus.ERROR,
        analyst_results={},
    )
    case = LiveCaseResult(
        case_id=scenario.case_id,
        scenario=scenario.scenario,
        input_fingerprint="a" * 64,
        status="failed",
        agent_statuses={name: "not_run" for name in AgentName},
        agent_success_rate=0.0,
        agent_result=agent_result.model_dump(mode="json"),
        error_code="agent_pipeline_failed",
    )
    return LiveBenchmarkRunResult(
        run_id=run_id,
        dataset_version=loaded.snapshot.dataset_version,
        snapshot_id=loaded.snapshot.snapshot_id,
        snapshot_sha256=snapshot_hash or loaded.sha256,
        market_coverage=loaded.snapshot.market_coverage,
        coverage_limitations=loaded.snapshot.coverage_limitations,
        config=config,
        case_input_fingerprints={scenario.case_id: case.input_fingerprint},
        cases=[case],
        completed_cases=0,
        failed_cases=1,
    )


def test_writer_saves_case_input_and_agent_output(tmp_path: Path) -> None:
    """Every case retains its input identity and full Agent result."""

    loaded = LiveSnapshotLoader(
        ROOT / "benchmarks/live_agent/v1/snapshot.yaml",
        ROOT / "benchmarks/live_agent/v1/snapshot.sha256",
    ).load()
    scenario = materialize_scenarios(loaded)[0]

    output = LiveBenchmarkWriter().write(_run("run-a"), [scenario], tmp_path)

    assert (output / "run_manifest.json").is_file()
    assert (output / "summary.json").is_file()
    assert (output / "cases" / scenario.case_id / "input.json").is_file()
    agents = (output / "cases" / scenario.case_id / "agents.json").read_text()
    assert "agent_pipeline_failed" not in agents
    assert "task:run-a" in agents


def test_writer_rejects_credential_shaped_fields(tmp_path: Path) -> None:
    """Even runtime metadata cannot introduce credential fields into artifacts."""

    result = _run("run-secret")
    result.config.inference_parameters = {"api_key": "forbidden"}
    loaded = LiveSnapshotLoader(
        ROOT / "benchmarks/live_agent/v1/snapshot.yaml",
        ROOT / "benchmarks/live_agent/v1/snapshot.sha256",
    ).load()

    with pytest.raises(LiveBenchmarkArtifactError, match="credential"):
        LiveBenchmarkWriter().write(
            result,
            [materialize_scenarios(loaded)[0]],
            tmp_path,
        )


def test_comparison_requires_same_snapshot_and_reports_neutral_delta() -> None:
    """A/B comparison rejects drift and does not label improvement."""

    comparison = LiveBenchmarkComparator().compare(
        _run("baseline"),
        _run("candidate"),
    )

    assert comparison.baseline_run_id == "baseline"
    assert comparison.candidate_run_id == "candidate"
    assert comparison.case_deltas[0].overall_score_delta is None
    assert comparison.case_deltas[0].agent_success_rate_delta == 0.0

    with pytest.raises(LiveBenchmarkComparisonError, match="not comparable"):
        LiveBenchmarkComparator().compare(
            _run("baseline"),
            _run("candidate-drift", snapshot_hash="b" * 64),
        )
