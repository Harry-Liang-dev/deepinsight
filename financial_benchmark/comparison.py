"""Paired comparisons and transparent populations; no single reward ranking."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from .evaluator import METRICS
from .gold import confusion
from .models import ArchivedTrace, ScoreResult

SEMANTIC_KEYS = METRICS[3:14]


def aggregate(
    scores: list[ScoreResult],
    traces: list[ArchivedTrace],
    approved_golds: list[str | None] | None = None,
) -> dict[str, Any]:
    """Keep completed, failed and unexecuted slots in separate denominators."""
    if len(scores) != len(traces) or {r.trace_id for r in scores} != {
        t.trace_id for t in traces
    }:
        raise ValueError("PLANNED_TRACE_DENOMINATOR_MISMATCH")
    labels: list[str | None] = (
        approved_golds if approved_golds is not None else [None] * len(traces)
    )
    if len(labels) != len(traces):
        raise ValueError("GOLD_DENOMINATOR_MISMATCH")
    gold_metrics = confusion(labels, [r.native_prediction for r in scores])
    states = Counter(t.execution_state for t in traces)
    failures = Counter(k for r in scores for k in r.failure_clusters)
    counts = {k: dict(Counter(r.metrics[k].status for r in scores)) for k in METRICS}
    us = [t.usage for t in traces if t.usage]
    native_preds: Counter[str | None] = Counter(r.native_prediction for r in scores)
    return dict(
        planned_slots=len(traces),
        distinct_research_cases=len({t.case_id for t in traces}),
        execution_states=dict(states),
        actual_provider_responses=states["COMPLETED"],
        metrics=counts,
        failure_clusters=dict(failures),
        valid_native_predictions=sum(
            native_preds[v] for v in ("SUPPORTED", "UNSUPPORTED", "UNDETERMINED")
        ),
        native_abstentions=native_preds["UNDETERMINED"],
        abstention_is_not_success=True,
        independent_gold_cases=len(
            {t.case_id for t, g in zip(traces, labels, strict=True) if g is not None}
        ),
        formal_accuracy=gold_metrics.get("accuracy_over_labeled_planned", "UNKNOWN"),
        formal_false_acceptance=gold_metrics["false_acceptance"],
        formal_false_rejection=gold_metrics["false_rejection"],
        Gold_population=gold_metrics,
        scientific_effect="NOT_DEMONSTRATED",
        scientific_admission=False,
        usage={
            "observed_records": len(us),
            "input_tokens": sum(u["input_tokens"] for u in us),
            "output_tokens": sum(u["output_tokens"] for u in us),
            "cached_input_tokens_observed": sum(
                u.get("input_tokens_details", {}).get("cached_tokens") or 0 for u in us
            ),
            "cached_unknown_records": sum(
                u.get("input_tokens_details", {}).get("cached_tokens") is None
                for u in us
            ),
            "conditional_reference_cost_cny_sum": str(
                sum(
                    (
                        Decimal(t.reference_cost_cny)
                        for t in traces
                        if t.reference_cost_cny is not None
                    ),
                    Decimal(0),
                )
            ),
            "actual_bill": "UNKNOWN",
        },
        complete_research_pass="UNKNOWN_NO_INDEPENDENT_FULL_TASK_REVIEW",
        model_calls_this_evaluation=0,
    )


def compare(
    baseline: list[tuple[ArchivedTrace, ScoreResult]],
    candidate: list[tuple[ArchivedTrace, ScoreResult]],
) -> dict[str, Any]:
    """Compare exact paired populations; UNKNOWN prevents invented dominance."""

    def index(
        rows: list[tuple[ArchivedTrace, ScoreResult]],
    ) -> dict[str, tuple[ArchivedTrace, ScoreResult]]:
        out = {t.case_id: (t, s) for t, s in rows}
        if len(out) != len(rows):
            raise ValueError("REPLICATES_REQUIRE_EXPLICIT_PAIR_ID")
        return out

    a = index(baseline)
    b = index(candidate)
    rows: list[dict[str, Any]] = []
    for case in sorted(set(a) | set(b)):
        if case not in a or case not in b:
            rows.append(
                dict(
                    case_id=case, status="MISSING_PAIRED_RESULT", pareto="INDETERMINATE"
                )
            )
            continue
        at, ar = a[case]
        bt, br = b[case]
        controls = (
            "task_identity",
            "case_version",
            "source_context_fingerprint",
            "research_as_of",
            "rights_fingerprint",
        )
        if (
            any(getattr(at, k) != getattr(bt, k) for k in controls)
            or ar.protocol_sha256 != br.protocol_sha256
        ):
            rows.append(
                dict(case_id=case, status="CONTRAST_INVALID", pareto="NOT_COMPARABLE")
            )
            continue
        changes = {
            k: {"baseline": ar.metrics[k].status, "candidate": br.metrics[k].status}
            for k in METRICS
            if ar.metrics[k].status != br.metrics[k].status
        }
        gains = [
            k
            for k in SEMANTIC_KEYS
            if ar.metrics[k].status == "FAIL" and br.metrics[k].status == "PASS"
        ]
        losses = [
            k
            for k in SEMANTIC_KEYS
            if ar.metrics[k].status == "PASS" and br.metrics[k].status == "FAIL"
        ]
        uncertain = [
            k
            for k in SEMANTIC_KEYS
            if "UNKNOWN" in (ar.metrics[k].status, br.metrics[k].status)
        ]
        eng_gain = (
            ar.metrics["schema_validity"].status == "FAIL"
            and br.metrics["schema_validity"].status == "PASS"
        )
        eng_financial = eng_gain and (bool(losses) or bool(br.serious_errors))
        au = at.usage or {}
        bu = bt.usage or {}
        delta_input = (
            au.get("input_tokens", 0) - bu.get("input_tokens", 0)
            if "input_tokens" in au and "input_tokens" in bu
            else None
        )
        quality_keys = (*METRICS[:3], *SEMANTIC_KEYS)
        optional = {"tool_selection_accuracy", "report_quality"}
        complete = (
            all(
                (ar.metrics[k].status == br.metrics[k].status == "PASS")
                or (
                    k in optional
                    and ar.metrics[k].status == br.metrics[k].status == "NOT_APPLICABLE"
                )
                for k in quality_keys
            )
            and ar.original_native_result.get("valid") is True
            and br.original_native_result.get("valid") is True
            and not ar.serious_errors
            and not br.serious_errors
        )
        dominates = (
            bool(gains) and not losses and not uncertain and not br.serious_errors
        )
        rows.append(
            dict(
                case_id=case,
                status="PAIRED",
                changes=changes,
                semantic_improvements=gains,
                semantic_regressions=losses,
                unknown_semantic_dimensions=uncertain,
                new_serious_errors=[
                    x for x in br.serious_errors if x not in ar.serious_errors
                ],
                engineering_gain_with_financial_harm=eng_financial,
                abstention_change=(br.native_prediction == "UNDETERMINED")
                - (ar.native_prediction == "UNDETERMINED"),
                unnecessary_abstention="UNKNOWN_WITHOUT_GOLD",
                input_reduction=delta_input,
                output_reduction=(
                    (au["output_tokens"] - bu["output_tokens"])
                    if "output_tokens" in au and "output_tokens" in bu
                    else None
                ),
                baseline_cache_tokens=au.get("input_tokens_details", {}).get(
                    "cached_tokens"
                ),
                candidate_cache_tokens=bu.get("input_tokens_details", {}).get(
                    "cached_tokens"
                ),
                conditional_reference_cost_reduction=(
                    str(Decimal(at.reference_cost_cny) - Decimal(bt.reference_cost_cny))
                    if at.reference_cost_cny is not None
                    and bt.reference_cost_cny is not None
                    else "UNKNOWN"
                ),
                latency_reduction_seconds=(
                    at.latency_seconds - bt.latency_seconds
                    if at.latency_seconds is not None and bt.latency_seconds is not None
                    else None
                ),
                actual_provider_bill="UNKNOWN",
                required_counterevidence_lost=(
                    ar.metrics["counterevidence_coverage"].status == "PASS"
                    and br.metrics["counterevidence_coverage"].status
                    in ("FAIL", "UNKNOWN")
                ),
                candidate_declared_support_with_unsupported_causal_diagnostic=(
                    br.diagnostic_prediction == "SUPPORTED"
                    and br.metrics["causal_support_correctness"].status == "FAIL"
                ),
                coverage_preserving_token_reduction=bool(
                    complete and delta_input is not None and delta_input > 0
                ),
                pareto=(
                    "CANDIDATE_DOMINATES_ON_KNOWN_COMPLETE_DIMENSIONS"
                    if dominates
                    else "INDETERMINATE" if uncertain else "TRADEOFF_OR_NO_DOMINANCE"
                ),
            )
        )
    return dict(
        scope="DEVELOPMENT_COMPARISON_NOT_CAUSAL_OR_OOS",
        rows=rows,
        formal_scientific_accuracy="UNKNOWN",
        weighted_reward=None,
        selection_rule="Pareto dimensions and serious safety flags; no style-based reward. Unknown Gold is never an improvement.",
        planned_union=len(rows),
    )
