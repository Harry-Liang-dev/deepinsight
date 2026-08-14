"""Explicit real-provider execution of all fixed live Agent scenarios."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import live_agent_benchmark

_PROVIDER = os.getenv("DEEPINSIGHT_LLM_PROVIDER")
_HAS_PROVIDER = (
    _PROVIDER == "qwen"
    and bool(os.getenv("QWEN_API_KEY"))
    and bool(os.getenv("QWEN_MODEL_NAME"))
) or (_PROVIDER == "openai" and bool(os.getenv("OPENAI_API_KEY")))


@pytest.mark.live
@pytest.mark.skipif(
    not _HAS_PROVIDER,
    reason="Real live Agent Benchmark provider is not configured",
)
def test_fixed_live_agent_benchmark(tmp_path: Path) -> None:
    """Run six fixed inputs through real Agents, reports, and real Judge."""

    assert (
        live_agent_benchmark.main(
            [
                "--output-root",
                str(tmp_path),
            ]
        )
        == 0
    )
