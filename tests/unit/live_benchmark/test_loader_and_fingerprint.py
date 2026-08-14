"""Offline contracts for the fixed live Agent Benchmark snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.live_benchmark import (
    LiveSnapshotError,
    LiveSnapshotLoader,
    live_case_fingerprint,
    materialize_scenarios,
)
from src.models.enums import AgentName
from src.schemas.live_benchmark import LiveBenchmarkConfig

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "benchmarks/live_agent/v1/snapshot.yaml"
CHECKSUM = ROOT / "benchmarks/live_agent/v1/snapshot.sha256"


def _config(*, model: str = "qwen3.7-flash") -> LiveBenchmarkConfig:
    return LiveBenchmarkConfig(
        run_id="live-test-run",
        provider="qwen",
        provider_real=True,
        judge_real=True,
        model_name=model,
        prompt_versions={name: "test-v1" for name in AgentName},
        prompt_sha256={name: "a" * 64 for name in AgentName},
        inference_parameters={"enable_thinking": False, "max_retries": 1},
        evaluation_ruleset_version="report_quality_v1",
        generated_at=datetime(2026, 8, 8, tzinfo=UTC),
    )


def test_snapshot_checksum_and_six_us_scenarios_are_fixed() -> None:
    """The live corpus must be immutable, real-source US-only input."""

    loaded = LiveSnapshotLoader(SNAPSHOT, CHECKSUM).load()
    scenarios = materialize_scenarios(loaded)

    assert loaded.snapshot.dataset_version == "live_agent_benchmark_v1"
    assert len(scenarios) == 6
    assert {item.scenario for item in scenarios} == {
        "normal_fundamentals",
        "missing_data",
        "conflicting_evidence",
        "material_event",
        "high_volatility",
        "incomplete_memory",
    }
    assert {source.provider for source in loaded.snapshot.sources} == {
        "sec_edgar",
        "alpaca_market_data",
    }
    assert all(str(item.context.asset_id).startswith("US:") for item in scenarios)


def test_snapshot_byte_drift_fails_before_materialization(tmp_path: Path) -> None:
    """A changed snapshot cannot silently enter a live comparison."""

    changed = tmp_path / "snapshot.yaml"
    changed.write_bytes(SNAPSHOT.read_bytes() + b"\n")

    with pytest.raises(LiveSnapshotError, match="checksum"):
        LiveSnapshotLoader(changed, CHECKSUM).load()


def test_fingerprint_is_stable_and_sensitive_to_model() -> None:
    """Canonical input identity changes when an inference input changes."""

    loaded = LiveSnapshotLoader(SNAPSHOT, CHECKSUM).load()
    scenario = materialize_scenarios(loaded)[0]

    first = live_case_fingerprint(scenario, _config(), loaded.sha256)
    repeated = live_case_fingerprint(scenario, _config(), loaded.sha256)
    candidate = live_case_fingerprint(
        scenario,
        _config(model="candidate-model"),
        loaded.sha256,
    )

    assert first == repeated
    assert first != candidate


def test_live_config_rejects_fake_provider_or_judge() -> None:
    """Evaluation metadata cannot claim a live run with a fake component."""

    data = _config().model_dump()
    data["provider_real"] = False

    with pytest.raises(ValueError, match="real LLM and Judge"):
        LiveBenchmarkConfig.model_validate(data)
