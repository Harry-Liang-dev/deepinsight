"""Command-line entry point for the deterministic offline Benchmark."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from src.benchmark import BenchmarkCaseLoader, ResearchBenchmarkRunner
from src.evaluation import EvaluationRuleLoader, FakeReportJudge
from src.models.enums import BenchmarkRunMode


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicit offline corpus and write its JSON summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--rules-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    loader = BenchmarkCaseLoader(arguments.benchmark_root)
    manifest = loader.load_manifest()
    runner = ResearchBenchmarkRunner(
        manifest,
        EvaluationRuleLoader(arguments.rules_root),
        FakeReportJudge(),
        mode=BenchmarkRunMode.DEFAULT,
        clock=lambda: manifest.default_generated_at,
    )
    result = runner.run(loader.load_all())
    runner.write(result, arguments.output)
    print(
        json.dumps(
            {
                "benchmark_version": result.benchmark_version,
                "failed_cases": result.failed_cases,
                "output": str(arguments.output),
                "passed_cases": result.passed_cases,
                "status": "ok" if result.failed_cases == 0 else "failed",
                "total_cases": result.total_cases,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.failed_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
