"""Offline command line pipeline. Runner integration consumes the same library API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .comparison import aggregate, compare
from .evaluator import Evaluator
from .gold import confusion, load_gold
from .io import case_fingerprint, load_cases, strict_json
from .models import ArchivedTrace, EvaluationCase, ScoreResult


def dump(path: Path, value: Any) -> None:
    """Write only explicitly selected evaluation result paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def replay(root: Path) -> dict[str, Any]:
    """Load → validate → evaluate originals → aggregate → failure report."""
    cases = load_cases(root)
    indexed = {c.case_id: c for c in cases}
    traces = [
        ArchivedTrace.model_validate(x)
        for x in strict_json(
            (root / "benchmark_data/ARCHIVED_TRACES.json").read_bytes()
        )
    ]
    if len({t.trace_id for t in traces}) != len(traces):
        raise ValueError("DUPLICATE_TRACE")
    evaluator = Evaluator(root)
    scores = [evaluator.evaluate(indexed[t.case_id], t) for t in traces]
    policy = strict_json(
        (root / "benchmark_data/GOLD_AUTHORITY_POLICY.json").read_bytes()
    )
    golds = [load_gold(root, indexed[t.case_id], policy) for t in traces]
    summary = aggregate(scores, traces, golds)
    by_variant = {
        v: aggregate(
            [s for s in scores if s.variant_id == v],
            [t for t in traces if t.variant_id == v],
        )
        for v in sorted({t.variant_id for t in traces})
    }
    data = dict(
        scope="POSTHOC_DIAGNOSTIC_ONLY_NOT_NATIVE_RESCORING",
        dataset_version="1.0.0",
        evaluator_protocol_sha256=evaluator.protocol_sha256,
        registry_cases=len(cases),
        historical_regression_cases=sum(c.dataset_split == "REGRESSION" for c in cases),
        unexecuted_new_development_obligations=sum(
            c.dataset_split == "DEVELOPMENT" for c in cases
        ),
        summary=summary,
        by_variant=by_variant,
        independent_gold_confusion=confusion(
            golds, [s.native_prediction for s in scores]
        ),
        scores=[s.model_dump() for s in scores],
    )
    dump(root / "HISTORICAL_REPLAY_EVALUATION.json", data)
    a = [(t, s) for t, s in zip(traces, scores, strict=True) if t.variant_id == "AB_A"]
    b = [(t, s) for t, s in zip(traces, scores, strict=True) if t.variant_id == "AB_B"]
    comparison = compare(a, b)
    dump(root / "benchmark_data/AB_BASELINE_CANDIDATE_COMPARISON.json", comparison)
    failures = [
        dict(
            trace_id=s.trace_id,
            case_id=s.case_id,
            clusters=s.failure_clusters,
            serious=s.serious_errors,
            failed_metrics={
                k: m.model_dump() for k, m in s.metrics.items() if m.status == "FAIL"
            },
            unknown_metrics=[k for k, m in s.metrics.items() if m.status == "UNKNOWN"],
        )
        for s in scores
    ]
    dump(
        root / "benchmark_data/FAILURE_REPORT.json",
        dict(planned_slots=len(traces), rows=failures),
    )
    return dict(
        registry_cases=len(cases),
        historical_regression_cases=data["historical_regression_cases"],
        planned_slots=len(traces),
        actual_responses=summary["actual_provider_responses"],
        independent_gold_cases=summary["independent_gold_cases"],
        formal_accuracy="UNKNOWN",
        new_model_calls=0,
        new_provider_calls=0,
    )


def developer_export(root: Path, case: EvaluationCase) -> dict[str, Any]:
    """Whitelist task/source material; never include archived answers, labels or adjudications."""
    if case.dataset_split not in ("DEVELOPMENT", "REGRESSION"):
        raise PermissionError("HOLDOUT_PROSPECTIVE_PENDING_ACCESS_DENIED")
    fields = (
        "case_id",
        "case_version",
        "task_family",
        "issuer",
        "security",
        "original_complete_claim",
        "research_question",
        "source_snapshot_refs",
        "evidence_catalog_ref",
        "research_as_of",
        "clocks",
        "rights_and_access_profile",
        "expected_task_behavior",
        "known_counterevidence",
        "allowed_tools",
    )
    record = {k: case.model_dump()[k] for k in fields}
    record["purpose"] = "DEVELOPMENT_TASK_SOURCE_EXPORT_NOT_SDK_REQUEST_OR_RELEASE"
    record["source_context_fingerprint"] = case_fingerprint(case)
    # Original inputs are not automatically re-embedded: W1 builds new candidates from the whitelist.
    record["archived_model_outputs_included"] = False
    return record


def main() -> None:
    """Run pure local evaluation; no Provider import or network option exists."""
    p = argparse.ArgumentParser()
    p.add_argument(
        "command", choices=["validate", "replay", "developer-export", "compare"]
    )
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--case-id")
    p.add_argument("--output", type=Path)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--candidate", type=Path)
    args = p.parse_args()
    if args.command == "replay":
        print(json.dumps(replay(args.root)))
    elif args.command == "validate":
        print(json.dumps(dict(valid_cases=len(load_cases(args.root)), status="PASS")))
    elif args.command == "developer-export":
        c = next(c for c in load_cases(args.root) if c.case_id == args.case_id)
        value = developer_export(args.root, c)
        if args.output:
            dump(args.output, value)
        else:
            print(json.dumps(value, ensure_ascii=False))
    else:
        if not args.baseline or not args.candidate:
            raise ValueError("BOTH_RUN_RESULT_FILES_REQUIRED")

        def rows(path: Path) -> list[tuple[ArchivedTrace, ScoreResult]]:
            return [
                (
                    ArchivedTrace.model_validate(x["trace"]),
                    ScoreResult.model_validate(x["score"]),
                )
                for x in strict_json(path.read_bytes())
            ]

        value = compare(rows(args.baseline), rows(args.candidate))
        if args.output:
            dump(args.output, value)
        else:
            print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
