"""Stable live Benchmark input fingerprints."""

from __future__ import annotations

import hashlib
import json

from src.schemas.live_benchmark import LiveBenchmarkConfig, MaterializedLiveScenario


def live_case_fingerprint(
    scenario: MaterializedLiveScenario,
    config: LiveBenchmarkConfig,
    snapshot_sha256: str,
) -> str:
    """Hash every inference-affecting input without credentials or prompt text."""

    canonical = json.dumps(
        {
            "config": {
                "provider": config.provider,
                "model_name": config.model_name,
                "prompt_versions": {
                    key.value: value for key, value in config.prompt_versions.items()
                },
                "prompt_sha256": {
                    key.value: value for key, value in config.prompt_sha256.items()
                },
                "inference_parameters": config.inference_parameters,
                "evaluation_ruleset_version": config.evaluation_ruleset_version,
            },
            "scenario": scenario.model_dump(mode="json"),
            "snapshot_sha256": snapshot_sha256,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
