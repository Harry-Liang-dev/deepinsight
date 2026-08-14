"""Strict loading for versioned fixed Benchmark cases."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from src.schemas.benchmark import BenchmarkManifest, ResearchBenchmarkCase


class BenchmarkCaseLoadError(RuntimeError):
    """Raised when the Benchmark corpus cannot be validated."""


class BenchmarkCaseLoader:
    """Load one manifest and its exact case version directory."""

    def __init__(self, benchmark_root: Path) -> None:
        """Bind an explicit Benchmark root without process-global paths."""

        self._root = benchmark_root

    def load_manifest(self) -> BenchmarkManifest:
        """Load the corpus manifest."""

        return _load_model(
            self._root / "manifest.yaml",
            BenchmarkManifest,
            "Benchmark manifest",
        )

    def load_all(self) -> list[ResearchBenchmarkCase]:
        """Return validated cases ordered by case ID."""

        manifest = self.load_manifest()
        case_root = self._root / "cases" / manifest.case_directory
        paths = sorted(case_root.glob("*.yaml"))
        if not paths:
            raise BenchmarkCaseLoadError("Benchmark case directory is empty")
        cases = [
            _load_model(path, ResearchBenchmarkCase, f"Benchmark case {path.name}")
            for path in paths
        ]
        identifiers = [case.case_id for case in cases]
        if len(identifiers) != len(set(identifiers)):
            raise BenchmarkCaseLoadError("Benchmark case IDs must be unique")
        if any(case.benchmark_version != manifest.benchmark_version for case in cases):
            raise BenchmarkCaseLoadError(
                "Benchmark case version does not match manifest"
            )
        return sorted(cases, key=lambda case: case.case_id)


def _load_model[ModelT: BaseModel](
    path: Path,
    model_type: type[ModelT],
    label: str,
) -> ModelT:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return model_type.model_validate(raw)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
        raise BenchmarkCaseLoadError(f"{label} is unavailable or invalid") from exc
