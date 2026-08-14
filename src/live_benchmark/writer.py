"""Credential-free filesystem artifacts for live Agent Benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path

from src.schemas.live_benchmark import (
    LiveBenchmarkComparison,
    LiveBenchmarkRunResult,
    MaterializedLiveScenario,
)

_FORBIDDEN_KEYS = {
    "api_key",
    "api_secret",
    "credential",
    "password",
    "secret",
    "token",
}


class LiveBenchmarkArtifactError(ValueError):
    """Raised when an artifact could expose a credential-shaped field."""


class LiveBenchmarkWriter:
    """Write stable JSON/Markdown artifacts beneath one explicit run root."""

    def write(
        self,
        result: LiveBenchmarkRunResult,
        scenarios: list[MaterializedLiveScenario],
        output_root: Path,
    ) -> Path:
        """Atomically persist one complete result and all case artifacts."""

        run_root = output_root / result.run_id
        run_root.mkdir(parents=True, exist_ok=False)
        by_case = {item.case_id: item for item in result.cases}
        scenario_by_case = {item.case_id: item for item in scenarios}
        _write_json(run_root / "run_manifest.json", _manifest(result))
        _write_json(run_root / "summary.json", result.model_dump(mode="json"))
        for case_id, case in by_case.items():
            case_root = run_root / "cases" / case_id
            case_root.mkdir(parents=True)
            scenario = scenario_by_case[case_id]
            _write_json(case_root / "input.json", scenario.model_dump(mode="json"))
            _write_json(
                case_root / "agents.json",
                {
                    "agent_statuses": {
                        key.value: value for key, value in case.agent_statuses.items()
                    },
                    "input_fingerprint": case.input_fingerprint,
                    "result": case.agent_result,
                },
            )
            if case.report is not None:
                _write_json(
                    case_root / "report.json", case.report.model_dump(mode="json")
                )
                (case_root / "report.md").write_text(
                    case.report.report_markdown,
                    encoding="utf-8",
                )
            if case.evaluation is not None:
                _write_json(
                    case_root / "evaluation.json",
                    case.evaluation.model_dump(mode="json"),
                )
        return run_root

    @staticmethod
    def write_comparison(
        comparison: LiveBenchmarkComparison,
        path: Path,
    ) -> None:
        """Write one neutral A/B comparison."""

        _write_json(path, comparison.model_dump(mode="json"))


def _manifest(result: LiveBenchmarkRunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "dataset_version": result.dataset_version,
        "snapshot_id": result.snapshot_id,
        "snapshot_sha256": result.snapshot_sha256,
        "market_coverage": [item.value for item in result.market_coverage],
        "coverage_limitations": result.coverage_limitations,
        "provider": result.config.provider,
        "provider_real": result.config.provider_real,
        "judge_real": result.config.judge_real,
        "model_name": result.config.model_name,
        "prompt_versions": {
            key.value: value for key, value in result.config.prompt_versions.items()
        },
        "prompt_sha256": {
            key.value: value for key, value in result.config.prompt_sha256.items()
        },
        "inference_parameters": result.config.inference_parameters,
        "evaluation_ruleset_version": result.config.evaluation_ruleset_version,
        "generated_at": result.config.generated_at.isoformat(),
        "case_input_fingerprints": result.case_input_fingerprints,
    }


def _write_json(path: Path, value: object) -> None:
    _reject_secret_fields(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _reject_secret_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_KEYS or normalized.endswith(
                ("api_key", "secret_key")
            ):
                raise LiveBenchmarkArtifactError(
                    "live Benchmark artifacts cannot contain credential fields"
                )
            _reject_secret_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_fields(item)
