"""Fixed corpus fixtures for Benchmark integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmark import BenchmarkCaseLoader
from src.schemas.benchmark import BenchmarkManifest, ResearchBenchmarkCase


@pytest.fixture(scope="session")
def benchmark_loader() -> BenchmarkCaseLoader:
    """Return the repository's explicit offline corpus loader."""

    return BenchmarkCaseLoader(Path("benchmarks"))


@pytest.fixture(scope="session")
def benchmark_manifest(
    benchmark_loader: BenchmarkCaseLoader,
) -> BenchmarkManifest:
    """Return the versioned corpus manifest."""

    return benchmark_loader.load_manifest()


@pytest.fixture(scope="session")
def benchmark_cases(
    benchmark_loader: BenchmarkCaseLoader,
) -> list[ResearchBenchmarkCase]:
    """Return all validated version-one cases."""

    return benchmark_loader.load_all()
