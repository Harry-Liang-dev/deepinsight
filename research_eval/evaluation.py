"""Layered deterministic diagnostics and a separately versioned W5 scorer port."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from research_eval.models import (
    DatasetCase,
    EvaluationResult,
    Failure,
    FailureKind,
    FrozenExperiment,
    Metric,
    encoded,
    identity,
)
from research_eval.source_text import verify_source_text
from research_eval.storage import TraceRecorder
from src.agents.evidence import numeric_literals
from src.agents.numeric_grounding import validate_numeric_grounding
from tools.g107_matrix import strict_object
from tools.g113_r9_integrity import prose_errors

METRICS = (
    "json",
    "schema",
    "local_guard",
    "source_selection",
    "source_coverage",
    "numeric_consistency",
    "full_claim_preserved",
    "verdict_reasoning_consistency",
    "premise_identification",
    "counterevidence_coverage",
    "grounded_abstention",
    "false_support_risk",
    "task_completion",
    "cost_latency",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "latency_seconds",
)


class ProposalShape(BaseModel):
    """Only structural constraints; local task semantics are a separate stage."""

    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED"]
    evidence_handles: list[str]
    reasoning: str
    missing_premises: list[str]
    counterevidence_handles: list[str]
    uncertainty: str


class Evaluator(Protocol):
    """W5 implements this interface; private Gold never enters request compilation."""

    evaluator_id: str
    protocol_sha256: str

    def evaluate(
        self, case: DatasetCase, assistant: bytes, mechanical: EvaluationResult
    ) -> EvaluationResult:
        """Return independently attributable metrics without mutating raw content."""
        ...


@dataclass
class NumericEntry:
    """Read-only projection for the existing deterministic Numeric Grounder."""

    evidence_id: str
    short_description: str
    numeric_tokens: tuple[str, ...]


class MechanicalEvaluator:
    """Exact shape/reference checks do not prove economic entailment."""

    evaluator_id = "w1-layered-mechanical-v1"

    def __init__(self, protocol_sha256: str) -> None:
        self.protocol_sha256 = protocol_sha256

    def evaluate(self, case: DatasetCase, raw: bytes, run_id: str) -> EvaluationResult:
        """Report all independently decidable failures and exact JSON Pointers."""
        metrics = {k: Metric(status="UNKNOWN") for k in METRICS}
        failures: list[Failure] = []

        def issue(kind: FailureKind, pointer: str, rule: str) -> None:
            failures.append(Failure(kind=kind, pointer=pointer, rule=rule))

        def finish() -> EvaluationResult:
            return EvaluationResult(
                run_id=run_id,
                evaluator_id=self.evaluator_id,
                protocol_sha256=self.protocol_sha256,
                trace_sha256=hashlib.sha256(raw).hexdigest(),
                provenance="MECHANICAL",
                gold_status="NONE",
                metrics=metrics,
                failures=tuple(failures),
            )

        try:
            obj = strict_object(raw.decode("utf-8", errors="strict"))
            metrics["json"] = Metric(status="PASS")
        except (ValueError, UnicodeError):
            metrics["json"] = Metric(status="FAIL")
            issue(FailureKind.PROTOCOL_FAILURE, "", "ONE_STRICT_JSON_OBJECT_NO_REPAIR")
            return finish()
        try:
            proposal = ProposalShape.model_validate(obj)
            metrics["schema"] = Metric(status="PASS")
        except ValidationError as exc:
            metrics["schema"] = Metric(status="FAIL")
            for e in exc.errors(include_url=False):
                pointer = "/" + "/".join(
                    str(x).replace("~", "~0").replace("/", "~1") for x in e["loc"]
                )
                issue(FailureKind.SCHEMA_FAILURE, pointer, str(e["type"]))
            return finish()
        local_count = len(failures)
        for field in ("reasoning", "uncertainty"):
            value = getattr(proposal, field)
            # Future technical task contract permits no actual uncertainty.
            if not value.strip() and (
                field == "reasoning" or case.task_kind == "financial"
            ):
                issue(
                    FailureKind.LOCAL_GUARD_FAILURE,
                    "/" + field,
                    "NONEMPTY_FINANCIAL_UNCERTAINTY_OR_REASONING",
                )
        for field in (
            "evidence_handles",
            "counterevidence_handles",
            "missing_premises",
        ):
            items = getattr(proposal, field)
            for i, item in enumerate(items):
                if not item.strip() or item in items[:i]:
                    issue(
                        FailureKind.LOCAL_GUARD_FAILURE,
                        f"/{field}/{i}",
                        "NONEMPTY_UNIQUE_ITEM",
                    )
        metrics["local_guard"] = Metric(
            status="PASS" if len(failures) == local_count else "FAIL"
        )
        handles = proposal.evidence_handles + proposal.counterevidence_handles
        bad = False
        for field in ("evidence_handles", "counterevidence_handles"):
            for i, h in enumerate(getattr(proposal, field)):
                if h not in case.handles:
                    issue(
                        FailureKind.EVIDENCE_RESOLUTION_FAILURE,
                        f"/{field}/{i}",
                        "EXACT_OFFERED_HANDLE",
                    )
                    bad = True
        metrics["source_selection"] = Metric(
            status="FAIL" if bad else ("PASS" if handles else "NOT_APPLICABLE")
        )
        absent = set(case.required_handles) - set(handles)
        if absent:
            issue(
                FailureKind.DATA_COVERAGE_FAILURE,
                "/evidence_handles",
                "MISSING_REQUIRED_HANDLES:" + ",".join(sorted(absent)),
            )
        metrics["source_coverage"] = Metric(status="FAIL" if absent else "PASS")
        # Literal grounding is narrow mechanical evidence, not a causal truth score.
        selected_ids = {case.handles[h] for h in handles if h in case.handles}
        entries = []
        for source in case.sources:
            if source.source_id in selected_ids:
                raw_source = Path(source.path).read_bytes()
                if hashlib.sha256(raw_source).hexdigest() != source.sha256:
                    issue(
                        FailureKind.SOURCE_AUTHORITY_FAILURE,
                        "/sources",
                        "RAW_SOURCE_HASH_DRIFT",
                    )
                    metrics["source_selection"] = Metric(status="FAIL")
                    return finish()
                try:
                    binding = case.visible_input.get("source_read_bindings", {}).get(
                        source.source_id
                    )
                    text = (
                        verify_source_text(source, binding)
                        if binding is not None
                        else (
                            gzip.decompress(raw_source)
                            if raw_source.startswith(b"\x1f\x8b")
                            else raw_source
                        ).decode("utf-8")
                    )
                except (OSError, UnicodeError, EOFError):
                    issue(
                        FailureKind.UNKNOWN_OR_NOT_EVALUATED,
                        "/sources",
                        "SOURCE_TEXT_DECODING_NOT_SUPPORTED",
                    )
                    return finish()
                except (ValueError, KeyError):
                    issue(
                        FailureKind.SOURCE_AUTHORITY_FAILURE,
                        "/sources",
                        "SOURCE_NORMALIZATION_BINDING_DRIFT",
                    )
                    metrics["source_selection"] = Metric(status="FAIL")
                    return finish()
                entries.append(
                    NumericEntry(source.source_id, text, tuple(numeric_literals(text)))
                )
        prose = (
            proposal.reasoning
            + " "
            + proposal.uncertainty
            + " "
            + " ".join(proposal.missing_premises)
        )
        grounded = validate_numeric_grounding(prose, entries)
        unit_errors = prose_errors(proposal.model_dump())
        if grounded.ungrounded_literals or unit_errors:
            issue(
                FailureKind.NUMERIC_GROUNDING_FAILURE,
                "/reasoning",
                "SELECTED_SOURCE_GROUNDING_OR_UNIT_CONFLICT",
            )
        metrics["numeric_consistency"] = Metric(
            status=(
                "FAIL"
                if grounded.ungrounded_literals or unit_errors
                else ("PASS" if grounded.numeric_literals else "NOT_APPLICABLE")
            ),
            evidence=(
                "EXACT_LITERAL_OR_DETERMINISTIC_GROUNDING_NOT_FINANCIAL_SEMANTICS",
            ),
        )
        if (
            case.task_kind == "financial"
            and proposal.verdict == "SUPPORTED"
            and (not proposal.evidence_handles or proposal.missing_premises)
        ):
            issue(
                FailureKind.UNSUPPORTED_CAUSAL_ACCEPTANCE,
                "/verdict",
                "DECLARED_SUPPORT_WITHOUT_EVIDENCE_OR_WITH_MISSING_PREMISE_NOT_FULL_SEMANTIC_GOLD",
            )
        # Full claim was supplied but whether model understood it requires W5.
        return finish()


def evaluate_archive(
    frozen: FrozenExperiment, archive: Path, *, evaluator: Evaluator | None = None
) -> list[EvaluationResult]:
    """Read only original traces, retaining missing samples in the denominator."""
    if encoded(frozen) != (archive / "freeze.json").read_bytes():
        raise ValueError("EVALUATION_FREEZE_MISMATCH")
    cases = {c.case_id: c for c in frozen.dataset.cases}
    census = json.loads((archive / "census.json").read_bytes())
    rows = {r["run_id"]: r for r in census["rows"]}
    mechanical = MechanicalEvaluator(frozen.campaign.evaluator_protocol_sha256)
    results = []
    for request in frozen.requests:
        path = archive / request.run_id / "assistant.txt"
        if not path.exists():
            failure_path = archive / request.run_id / "authority_failure.json"
            authority_failure = (
                json.loads(failure_path.read_bytes()) if failure_path.exists() else None
            )
            r = EvaluationResult(
                run_id=request.run_id,
                evaluator_id=mechanical.evaluator_id,
                protocol_sha256=mechanical.protocol_sha256,
                trace_sha256=identity(rows[request.run_id]),
                provenance="MECHANICAL",
                gold_status="NONE",
                metrics={k: Metric(status="UNKNOWN") for k in METRICS},
                failures=(
                    Failure(
                        kind=(
                            FailureKind.SOURCE_AUTHORITY_FAILURE
                            if authority_failure
                            else FailureKind.UNKNOWN_OR_NOT_EVALUATED
                        ),
                        pointer="/current_authority" if authority_failure else "",
                        rule=(
                            authority_failure["rule"]
                            if authority_failure
                            else rows[request.run_id]["status"]
                        ),
                    ),
                ),
            )
        else:
            raw = path.read_bytes()
            # The raw capture hash must agree before a worker can contribute a score.
            response = archive / request.run_id / "response.raw"
            http = json.loads((archive / request.run_id / "http.json").read_bytes())
            if (
                hashlib.sha256(response.read_bytes()).hexdigest()
                != http["response_sha256"]
            ):
                raise ValueError("EVALUATION_RAW_RESPONSE_DRIFT")
            envelope = json.loads(response.read_bytes())
            extracted = "".join(
                p["text"]
                for o in envelope.get("output", [])
                if o.get("type") == "message"
                for p in o.get("content", [])
                if p.get("type") == "output_text"
            ).encode()
            if raw != extracted:
                raise ValueError("EVALUATION_ASSISTANT_DRIFT")
            r = mechanical.evaluate(cases[request.case_id], raw, request.run_id)
            metrics = dict(r.metrics)
            usage_path = archive / request.run_id / "usage.json"
            if usage_path.exists():
                usage = json.loads(usage_path.read_bytes())
                origin = (
                    "SIMULATED_USAGE"
                    if census["origin"] == "ENGINEERING_MOCK_SDK"
                    else "PROVIDER_USAGE"
                )
                for key in ("input_tokens", "output_tokens", "cached_tokens"):
                    value = usage.get(key)
                    metrics[key] = Metric(
                        status="PASS" if isinstance(value, int) else "UNKNOWN",
                        value=value if isinstance(value, int) else None,
                        evidence=(origin,),
                    )
                invocation = json.loads(
                    (archive / request.run_id / "invocation.json").read_bytes()
                )
                elapsed = (
                    datetime.fromisoformat(http["ActualResponseAt"])
                    - datetime.fromisoformat(invocation["ActualInvocationAt"])
                ).total_seconds()
                metrics["latency_seconds"] = Metric(
                    status="PASS", value=elapsed, evidence=("LOCAL_CAPTURE_CLOCK",)
                )
                r = r.model_copy(update={"metrics": metrics})
            if evaluator is not None:
                if (
                    evaluator.protocol_sha256
                    != frozen.campaign.evaluator_protocol_sha256
                ):
                    raise ValueError("EVALUATOR_PROTOCOL_MISMATCH")
                scored = EvaluationResult.model_validate_json(
                    encoded(evaluator.evaluate(cases[request.case_id], raw, r))
                )
                if (
                    scored.run_id != r.run_id
                    or scored.trace_sha256 != r.trace_sha256
                    or scored.protocol_sha256 != r.protocol_sha256
                    or scored.evaluator_id != evaluator.evaluator_id
                ):
                    raise ValueError("EVALUATOR_BINDING_MISMATCH")
                if scored.provenance == "W5_INDEPENDENT":
                    raise ValueError("INDEPENDENT_EVALUATOR_ISSUANCE_NOT_INSTALLED")
                r = scored
        results.append(r)
    return results


class ExperimentComparator:
    """Compare complete paired populations, never only successful survivors."""

    def compare(
        self, frozen: FrozenExperiment, results: list[EvaluationResult]
    ) -> dict[str, Any]:
        """Aggregate known statuses; no invented composite scientific score."""
        by_id = {r.run_id: r for r in results}
        if len(by_id) != len(results) or set(by_id) != {
            r.run_id for r in frozen.requests
        }:
            raise ValueError("EVALUATION_POPULATION_MISSING_OR_DUPLICATE")
        groups: dict[str, Any] = {}
        for variant in frozen.variants:
            members = [
                by_id[r.run_id]
                for r in frozen.requests
                if r.variant_id == variant.variant_id
            ]
            groups[variant.variant_id] = {
                k: dict(
                    denominator=len(members),
                    counts=dict(
                        Counter(
                            r.metrics.get(k, Metric(status="UNKNOWN")).status
                            for r in members
                        )
                    ),
                )
                for k in METRICS
            }
        return dict(
            paired_cases=len(frozen.dataset.cases),
            planned=len(frozen.requests),
            variants=groups,
            scientific_score=None,
            scientific_effect="NOT_DEMONSTRATED",
            fixture_results_are_not_model_predictions=True,
        )


class FailureClusterer:
    """Group precise mechanical or independently supplied semantic rule failures."""

    def report(self, results: list[EvaluationResult]) -> dict[str, Any]:
        """Count by taxonomy and rule, not a generic content-failure bucket."""
        return dict(
            total_cases=len(results),
            clusters=dict(
                Counter(
                    f.kind.value + ":" + f.rule for r in results for f in r.failures
                )
            ),
            details=[
                dict(
                    run_id=r.run_id,
                    failures=[f.model_dump(mode="json") for f in r.failures],
                )
                for r in results
            ],
        )


def collect_results(
    frozen: FrozenExperiment, archive: Path, files: list[Path]
) -> list[EvaluationResult]:
    """Ingest isolated worker artifacts; deduplicate and reject stale trace/protocol."""
    references = {r.run_id: r for r in evaluate_archive(frozen, archive)}
    found: dict[str, EvaluationResult] = {}
    for path in files:
        result = EvaluationResult.model_validate_json(path.read_bytes())
        expected = references.get(result.run_id)
        if (
            expected is None
            or result.trace_sha256 != expected.trace_sha256
            or result.protocol_sha256 != expected.protocol_sha256
        ):
            raise ValueError("WORKER_RESULT_IDENTITY")
        # File provenance alone is never independent authority.
        if result.provenance == "W5_INDEPENDENT":
            raise ValueError("INDEPENDENT_EVALUATOR_ISSUANCE_NOT_INSTALLED")
        if result.run_id in found and encoded(found[result.run_id]) != encoded(result):
            raise ValueError("CONFLICTING_WORKER_RESULT")
        found[result.run_id] = result
    return list(found.values())


def write_evaluations(output: Path, results: list[EvaluationResult]) -> None:
    """Write versioned result files for separate worker collection."""
    recorder = TraceRecorder(output)
    for r in results:
        recorder.record(r.run_id + ".json", r)
