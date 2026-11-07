"""Evaluation-only W1 Scorer Port bridge. Never authorizes or invokes a Runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .evaluator import Evaluator
from .io import (
    canonical,
    case_fingerprint,
    clock,
    load_cases,
    sha,
    strict_json,
)
from .models import ArchivedTrace


class W1ScorerPort:
    """Bridge known archived responses to W1's typed transport envelope."""

    evaluator_id = "w5-financial-benchmark-v1-port"

    def __init__(self, root: Path, *, calibration_profile: str | None = None) -> None:
        self.root = root
        self.engine = Evaluator(root)
        self.protocol_sha256 = self.engine.protocol_sha256
        self.calibration = None
        if calibration_profile is not None:
            if calibration_profile != "financial-calibration-1.1.0":
                raise ValueError("UNKNOWN_CALIBRATION_PROFILE")
            from .calibration import CalibrationScorer

            self.calibration = CalibrationScorer(root)
            self.protocol_sha256 = self.calibration.protocol_sha256
            self.evaluator_id = self.calibration.evaluator_id
        self.cases = {c.case_id: c for c in load_cases(root)}
        self.traces = [
            ArchivedTrace.model_validate(x)
            for x in strict_json(
                (root / "benchmark_data/ARCHIVED_TRACES.json").read_bytes()
            )
        ]

    def evaluate(self, case: Any, assistant: bytes, mechanical: Any) -> Any:
        """Preserve mechanical evidence; unknown new responses cannot inherit old judgements."""
        if (
            mechanical.protocol_sha256 != self.protocol_sha256
            or mechanical.trace_sha256 != sha(assistant)
        ):
            raise ValueError("W1_SCORER_RESPONSE_OR_PROTOCOL_DRIFT")
        own = self.cases.get(case.case_id)
        if (
            own is None
            or case.full_claim != own.original_complete_claim
            or clock(case.research_as_of.isoformat()) != clock(own.research_as_of)
        ):
            raise ValueError("W1_CASE_SCOPE_DRIFT")
        expected_sources = own.provenance.get("source_document_hashes", {})
        if {s.source_id: s.sha256 for s in case.sources} != expected_sources:
            raise ValueError("W1_SOURCE_UNIVERSE_DRIFT")
        for source in case.sources:
            if sha(Path(source.path).read_bytes()) != source.sha256:
                raise ValueError("W1_RAW_SOURCE_DRIFT")
        if case.visible_input.get("w5_source_context_fingerprint") != case_fingerprint(
            own
        ) or case.visible_input.get("w5_rights_fingerprint") != sha(
            canonical(own.rights_and_access_profile)
        ):
            raise ValueError("W1_SCOPE_PROJECTION_DRIFT")
        if self.calibration is not None:
            from .io import task_fingerprint

            version = case.visible_input.get(
                "w5_case_version",
                case.visible_input.get("task", {}).get("case_version"),
            )
            if version != own.case_version or case.visible_input.get(
                "w5_task_identity"
            ) != task_fingerprint(own):
                raise ValueError("W1_CALIBRATION_TASK_VERSION_DRIFT")
            scored = self.calibration.evaluate(
                own.case_id, assistant, task_kind=case.task_kind
            )
            metrics = {
                k: v.model_dump(mode="json") for k, v in mechanical.metrics.items()
            }
            for k, v in scored["metrics"].items():
                metrics["w5cal_" + k] = {
                    "status": v["status"],
                    "value": None,
                    "evidence": [
                        __import__("json").dumps(v, ensure_ascii=False, sort_keys=True)
                    ],
                }
            data = mechanical.model_dump(mode="json")
            data.update(
                evaluator_id=self.evaluator_id,
                provenance="INTERNAL_PRECHECK",
                gold_status="NONE",
                metrics=metrics,
                scientific_admission=False,
            )
            return type(mechanical).model_validate(data)
        matches = [
            t
            for t in self.traces
            if t.case_id == own.case_id
            and t.assistant
            and t.assistant.sha256 == sha(assistant)
        ]
        # W1 transport has no independent evaluator ReleasePin yet. Do not claim it.
        metrics = {k: v.model_dump(mode="json") for k, v in mechanical.metrics.items()}
        if matches:
            score = self.engine.evaluate(own, matches[0])
            for k, m in score.metrics.items():
                metrics["w5_" + k] = {
                    "status": m.status,
                    "value": None,
                    "evidence": [m.basis, m.explanation],
                }
        else:
            metrics["w5_semantic_review"] = {
                "status": "UNKNOWN",
                "value": None,
                "evidence": [
                    "New response requires its own frozen Trace/Source binding and independent evaluation; no inherited historical adjudication."
                ],
            }
        data = mechanical.model_dump(mode="json")
        data.update(
            evaluator_id=self.evaluator_id,
            provenance="INTERNAL_PRECHECK",
            gold_status="NONE",
            metrics=metrics,
            scientific_admission=False,
        )
        return type(mechanical).model_validate(data)
