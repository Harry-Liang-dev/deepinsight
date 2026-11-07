"""Local reference-only SFT/preference/RL schemas; no trainer or uploads."""

import hashlib
from pathlib import Path
from typing import Any, Literal

from research_eval.models import EvaluationResult, FrozenExperiment, Record, identity


class ExperienceRecord(Record):
    """Observed behavior references only, with explicit missing-label states."""

    version: Literal["experience-reference-v1"] = "experience-reference-v1"
    run_id: str
    format: Literal["SFT", "PREFERENCE", "RL"]
    task_identity: str
    prompt_identity: str
    source_permissions: list[dict[str, Any]]
    model_configuration: dict[str, Any]
    frozen_request_sha256: str
    request_path: str
    visible_observation_identity: str
    authority_receipt_path: str
    frozen_experiment_path: str
    raw_trace_path: str
    raw_trace_sha256: str
    evaluation: dict[str, Any] | None
    training_eligible: Literal[False] = False
    chosen: None = None
    rejected: None = None
    reward: None = None
    inaccessible_internal_reasoning: None = None
    tool_calls: tuple[()] = ()
    business_writes: Literal[0] = 0


class ExperienceExporter:
    """Export actual local references, never fabricate rewards or preference pairs."""

    def export(
        self,
        frozen: FrozenExperiment,
        archive: Path,
        results: list[EvaluationResult],
        kind: Literal["SFT", "PREFERENCE", "RL"],
    ) -> list[ExperienceRecord]:
        """Require case-level local export license and matching observed trace."""
        by_id = {r.run_id: r for r in results}
        cases = {c.case_id: c for c in frozen.dataset.cases}
        rows = []
        for request in frozen.requests:
            case = cases[request.case_id]
            if not case.local_export_allowed:
                raise ValueError("DATA_LICENSE_FORBIDS_EXPERIENCE_EXPORT")
            path = archive / request.run_id / "assistant.txt"
            if not path.exists():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            evaluated = by_id.get(request.run_id)
            if evaluated is not None and (
                evaluated.trace_sha256 != digest
                or evaluated.protocol_sha256
                != frozen.campaign.evaluator_protocol_sha256
            ):
                raise ValueError("EXPORT_EVALUATION_DRIFT")
            rows.append(
                ExperienceRecord(
                    run_id=request.run_id,
                    format=kind,
                    task_identity=identity(case),
                    prompt_identity=request.prompt_identity,
                    source_permissions=[
                        s.model_dump(mode="json") for s in case.sources
                    ],
                    model_configuration=dict(
                        model=frozen.campaign.model,
                        provider=frozen.campaign.provider,
                        endpoint=frozen.campaign.endpoint,
                        output_cap=frozen.campaign.output_cap,
                        origin=frozen.spec.mode,
                    ),
                    frozen_request_sha256=request.request_sha256,
                    request_path=str(archive / request.run_id / "request.raw"),
                    visible_observation_identity=identity(request.input_payload),
                    authority_receipt_path=str(
                        archive / request.run_id / "authority.json"
                    ),
                    frozen_experiment_path=str(archive / "freeze.json"),
                    raw_trace_path=str(path),
                    raw_trace_sha256=digest,
                    evaluation=evaluated.model_dump(mode="json") if evaluated else None,
                )
            )
        return rows
