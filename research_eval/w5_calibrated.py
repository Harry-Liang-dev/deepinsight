"""Forward-only W5 calibration adoption; original benchmark pins remain unchanged."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from research_eval.evaluation import ExperimentComparator
from research_eval.models import (
    DatasetCase,
    EvaluationResult,
    FrozenExperiment,
    Metric,
    identity,
)
from research_eval.source_text import verify_source_text
from research_eval.w5_adapter import W5Benchmark, sha

ROOT = Path(
    os.environ.get(
        "DEEPINSIGHT_W5_CALIBRATION_ROOT",
        str(Path.home() / ".local/share/deepinsight/calibration-v1"),
    )
)
DELIVERY = "6721d94462554dfa50c62bac32f7e22cbab809c2"
MANIFEST = "340e3d97bb4c64eb0112ad6f8675789aaa98db4ec6ea134e0873275f0b0de261"
PROFILE = "financial-calibration-1.1.0"
PROTOCOL = "f200e86f841055cfeb47948ba1b215244d0d1320cf1e8703b4ef641cd609ab29"
CASES = tuple(f"HIST-AB-EV2-AB-DEV-C{n:03}" for n in range(2, 6))


class CalibratedBenchmark(W5Benchmark):
    """Pin the separately published evaluator, never reinterpret an old campaign."""

    pinned_delivery = DELIVERY
    pinned_manifest = MANIFEST
    calibration_profile = PROFILE

    def __init__(self, root: Path = ROOT) -> None:
        super().__init__(root)
        self.population = json.loads(
            self.read("FOUR_CASE_FIRST_CAMPAIGN_EVALUATION_FREEZE.json")
        )
        if (
            self.protocol_sha256 != PROTOCOL
            or tuple(self.population["case_ids"]) != CASES
        ):
            raise ValueError("CALIBRATION_PROTOCOL_OR_POPULATION_DRIFT")
        for row in self.population["cases"]:
            own = self.cases[row["case_id"]]
            if (
                row["task_identity"] != self.io.task_fingerprint(own)
                or row["case_version"] != own.case_version
                or row["original_complete_claim"] != own.original_complete_claim
                or row["ResearchAsOf"] != own.research_as_of
                or row["rights_fingerprint"]
                != sha(self.io.canonical(own.rights_and_access_profile))
                or row["source_context_fingerprint"] != self.io.case_fingerprint(own)
            ):
                raise ValueError("CALIBRATION_CASE_BINDING")

    def project(self, case_id: str) -> DatasetCase:
        """Reuse export; bind published normalized snapshots to exact raw entities."""
        case = super().project(case_id)
        own = self.cases[case_id]
        registry_path = "HISTORICAL_REGRESSION_DATASET.jsonl"
        registry = self.read(registry_path)
        bindings = {}
        for source in case.sources:
            refs = [
                r
                for r in own.source_snapshot_refs
                if r.kind == "HISTORICAL_SOURCE:" + source.source_id
                and r.sha256 != source.sha256
            ]
            if len(refs) != 1:
                raise ValueError("SOURCE_NORMALIZATION_AMBIGUITY")
            ref = refs[0]
            normalized = self.read(ref.path)
            raw = Path(source.path).read_bytes()
            bindings[source.source_id] = dict(
                version="W5_PUBLISHED_RAW_NORMALIZED_BINDING_V1",
                raw_sha256=source.sha256,
                raw_content_encoding=(
                    "gzip" if raw.startswith(b"\x1f\x8b") else "identity"
                ),
                text_encoding="utf-8",
                normalized_path=str(self.root / ref.path),
                normalized_sha256=sha(normalized),
                registry_path=str(self.root / registry_path),
                registry_sha256=sha(registry),
                case_id=case_id,
                provenance=(
                    "Exact W5 EvaluationCase snapshot pair and canonical raw map; "
                    "not a new extraction or live grant"
                ),
            )
        visible = {**case.visible_input, "source_read_bindings": bindings}
        projected = case.model_copy(update={"visible_input": visible})
        for source in projected.sources:
            verify_source_text(source, bindings[source.source_id])
        return projected


class CalibratedComparator(ExperimentComparator):
    """Preserve calibrated axes and full paired denominators; no total score."""

    def compare(
        self, frozen: FrozenExperiment, results: list[EvaluationResult]
    ) -> dict[str, Any]:
        summary = super().compare(frozen, results)
        by_id = {r.run_id: r for r in results}
        axes = sorted({k for r in results for k in r.metrics if k.startswith("w5cal_")})
        pairs = []
        for v in frozen.variants:
            members = [
                by_id[r.run_id] for r in frozen.requests if r.variant_id == v.variant_id
            ]
            for axis in axes:
                summary["variants"][v.variant_id][axis] = dict(
                    denominator=len(members),
                    counts=dict(
                        Counter(
                            r.metrics.get(axis, Metric(status="UNKNOWN")).status
                            for r in members
                        )
                    ),
                )
        for case in frozen.dataset.cases:
            cells = {}
            for request in frozen.requests:
                if request.case_id == case.case_id:
                    result = by_id[request.run_id]
                    cells[request.variant_id] = dict(
                        request_sha256=request.request_sha256,
                        assistant_sha256=result.trace_sha256,
                        evaluation_result_sha256=identity(result),
                        axes={
                            k: result.metrics.get(
                                k, Metric(status="UNKNOWN")
                            ).model_dump(mode="json")
                            for k in axes
                        },
                    )
            pairs.append(dict(case_id=case.case_id, cells=cells))
        summary.update(
            version="W1_W5CAL_PAIRED_COMPARISON_V1",
            calibration_profile=PROFILE,
            calibration_axes=axes,
            pairs=pairs,
            independent_gold=0,
            origin="NEW_MOCK_EXECUTION_OR_EXPLICITLY_SEPARATE_LIVE_ARCHIVE",
        )
        return summary
