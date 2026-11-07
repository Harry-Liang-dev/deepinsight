"""Explainable multidimensional scorer. No LLM judge and no business admission."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

from .io import (
    artifact,
    canonical,
    case_fingerprint,
    clock,
    sha,
    strict_json,
    task_fingerprint,
)
from .models import ArchivedTrace, EvaluationCase, MetricResult, ScoreResult

METRICS = (
    "schema_validity",
    "evidence_link_validity",
    "source_scope_correctness",
    "numeric_consistency",
    "time_and_asof_correctness",
    "parent_claim_preservation",
    "premise_coverage",
    "counterevidence_coverage",
    "causal_support_correctness",
    "verdict_reasoning_consistency",
    "uncertainty_calibration",
    "useful_research_coverage",
    "tool_selection_accuracy",
    "report_quality",
    "token_cost_latency",
)
SEMANTIC_METRICS = METRICS[3:14]
VERDICTS = {"SUPPORTED", "UNSUPPORTED", "UNDETERMINED"}


def result(status: str, basis: str, why: str, **values: Any) -> MetricResult:
    """Construct a scoped metric with raw explanations and evidence."""
    return MetricResult.model_validate(
        dict(status=status, basis=basis, explanation=why, **values)
    )


def pointer(obj: Any, path: str) -> Any:
    """Read an original JSON Pointer without recovering malformed JSON."""
    for token in path.strip("/").split("/") if path else []:
        key = token.replace("~1", "/").replace("~0", "~")
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def numeric_checks(
    assertions: list[dict[str, Any]], references: list[dict[str, Any]]
) -> MetricResult:
    """Compare registered Decimal references, scope, period and unit; no new fact grounding."""
    if not assertions:
        return result(
            "UNKNOWN",
            "NO_STRUCTURED_ASSERTIONS",
            "No reliable numeric projection; prose requires source-based review, not silent extraction.",
        )
    expected = {r["metric_id"]: r for r in references}
    rows: list[dict[str, Any]] = []
    for a in assertions:
        e = expected.get(a.get("metric_id"))
        if not e:
            rows.append(
                dict(
                    metric_id=a.get("metric_id"),
                    status="UNKNOWN",
                    reason="UNREGISTERED_REFERENCE",
                )
            )
            continue
        scope_ok = all(a.get(k) == e.get(k) for k in ("unit", "period", "scope"))
        try:
            actual = Decimal(str(a["value"]))
            target = Decimal(e["value"])
            tolerance = Decimal(e.get("tolerance", "0"))
            valid = (
                actual.is_finite()
                and target.is_finite()
                and tolerance.is_finite()
                and tolerance >= 0
            )
            match = valid and abs(actual - target) <= tolerance
        except (InvalidOperation, KeyError):
            match = False
        rows.append(
            dict(
                metric_id=a.get("metric_id"),
                status="PASS" if scope_ok and match else "FAIL",
                source_ref=e.get("source_ref"),
                scope_correct=scope_ok,
            )
        )
    statuses = {r["status"] for r in rows}
    return result(
        (
            "FAIL"
            if "FAIL" in statuses
            else ("UNKNOWN" if "UNKNOWN" in statuses else "PASS")
        ),
        "DETERMINISTIC_REGISTERED_REFERENCE",
        "Evaluation-only comparison to existing source/calculation references. No unit inference, new Canonical Evidence or Numeric Grounder permission.",
        measurements={"checks": rows},
    )


def citation_checks(obj: Any, catalog: list[dict[str, Any]], mode: str) -> MetricResult:
    """Resolve only actual offered IDs; exact-quote history stays exact."""
    if not isinstance(obj, dict):
        return result("UNKNOWN", "NO_OBJECT", "No strict original object.")
    indexed = {r.get("handle", r.get("fragment_id")): r for r in catalog}
    rows: list[dict[str, Any]] = []
    citations = obj.get("evidence", []) if mode == "EXACT_QUOTE" else []
    if mode == "HANDLE":
        for field in ("evidence_handles", "counterevidence_handles"):
            citations += (
                [dict(handle=h) for h in obj.get(field, []) if isinstance(h, str)]
                if isinstance(obj.get(field, []), list)
                else []
            )
    for c in citations if isinstance(citations, list) else []:
        if not isinstance(c, dict):
            rows.append({"status": "FAIL", "reason": "CITATION_TYPE"})
            continue
        key = c.get("handle", c.get("fragment_id"))
        e = indexed.get(key)
        if not e:
            rows.append(dict(id=key, status="FAIL", reason="UNAVAILABLE_ID"))
            continue
        quote = c.get("quote")
        if mode == "EXACT_QUOTE":
            count = e["text"].count(quote) if isinstance(quote, str) and quote else 0
            rows.append(
                dict(
                    id=key,
                    status="PASS" if count == 1 else "FAIL",
                    reason=(
                        "EXACT_UNIQUE" if count == 1 else "QUOTE_NOT_EXACT_AND_UNIQUE"
                    ),
                    matches=count,
                )
            )
        else:
            rows.append(
                dict(id=key, status="PASS", reason="OFFERED_HANDLE_ONLY_NOT_ENTAILMENT")
            )
    if not rows:
        return result(
            "UNKNOWN",
            "NO_NATIVE_CITATIONS",
            "No eligible citation records; flat diagnostic fields do not become native candidates.",
        )
    return result(
        "FAIL" if any(r["status"] == "FAIL" for r in rows) else "PASS",
        "DETERMINISTIC_CITATION_IDENTITY",
        "Exact original citation population; valid identity does not establish economic support.",
        measurements={"citations": rows},
    )


class Evaluator:
    """Evaluate immutable traces using a separately pinned W5 protocol."""

    def __init__(
        self, root: Path, protocol_path: str = "benchmark_data/EVALUATOR_PROTOCOL.json"
    ) -> None:
        self.root = root
        self.protocol_bytes = (root / protocol_path).read_bytes()
        self.protocol = strict_json(self.protocol_bytes)
        self.protocol_sha256 = sha(self.protocol_bytes)
        if tuple(self.protocol["metrics"]) != METRICS:
            raise ValueError("UNKNOWN_METRIC_VERSION")
        review_bytes = (
            root / "benchmark_data/APPROVED_DIAGNOSTIC_REVIEWS.json"
        ).read_bytes()
        if sha(review_bytes) != self.protocol["review_registry_sha256"]:
            raise ValueError("W5_REVIEW_REGISTRY_DRIFT")
        self.approved_reviews = set(strict_json(review_bytes)["approved_sha256"])
        if (
            sha((root / "benchmark_data/GOLD_AUTHORITY_POLICY.json").read_bytes())
            != self.protocol["gold_policy_sha256"]
        ):
            raise ValueError("GOLD_AUTHORITY_POLICY_DRIFT")

    def evaluate(self, case: EvaluationCase, trace: ArchivedTrace) -> ScoreResult:
        """Keep all planned slots. Missing evidence yields UNKNOWN, never success."""
        if trace.task_identity != task_fingerprint(case):
            raise ValueError("TASK_CLAIM_STRENGTH_DRIFT")
        if trace.case_id != case.case_id or trace.case_version != case.case_version:
            raise ValueError("CASE_IDENTITY_DRIFT")
        if (
            trace.source_context_fingerprint != case_fingerprint(case)
            or trace.research_as_of != case.research_as_of
        ):
            raise ValueError("SOURCE_ASOF_DRIFT")
        if trace.rights_fingerprint != sha(canonical(case.rights_and_access_profile)):
            raise ValueError("RIGHTS_DRIFT")
        metrics = {
            k: result(
                "UNKNOWN", "NOT_EVALUATED", "No applicable verified evidence/review."
            )
            for k in METRICS
        }
        clusters: list[str] = []
        serious: list[dict[str, Any]] = []
        parsed = None
        native_prediction = None
        diagnostic_prediction = None
        ref = (
            strict_json(artifact(self.root, case.evaluation_reference))
            if case.evaluation_reference
            else {}
        )
        for r in [trace.request, trace.response, trace.assistant, trace.native_schema]:
            if r:
                artifact(self.root, r)
        if trace.execution_state == "COMPLETED":
            if not trace.response or not trace.assistant:
                raise ValueError("COMPLETE_TRACE_MISSING_RAW_RESPONSE")
            envelope = strict_json(artifact(self.root, trace.response))
            extracted = "".join(
                part["text"]
                for item in envelope.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            ).encode()
            if extracted != artifact(self.root, trace.assistant):
                raise ValueError("RAW_PROVIDER_ASSISTANT_DRIFT")
            if envelope.get("usage") != trace.usage:
                raise ValueError("RAW_PROVIDER_USAGE_DRIFT")
            if (
                envelope.get("model") != trace.model
                or envelope.get("status") != "completed"
            ):
                raise ValueError("RAW_PROVIDER_MODEL_COMPLETION_DRIFT")
        if trace.execution_state != "COMPLETED":
            clusters.append(trace.execution_state)
            metrics["schema_validity"] = result(
                "UNKNOWN",
                "NO_COMPLETE_RESPONSE",
                "Unexecuted/unknown/system-failed is retained in planned denominator, not proven model scientific failure.",
            )
        elif trace.assistant:
            raw = artifact(self.root, trace.assistant)
            try:
                parsed = strict_json(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("ROOT_NOT_OBJECT")
                schema = (
                    strict_json(artifact(self.root, trace.native_schema))
                    if trace.native_schema
                    else None
                )
                errors = (
                    list(Draft202012Validator(schema).iter_errors(parsed))
                    if schema
                    else []
                )
                details = [
                    dict(
                        pointer="/" + "/".join(str(x) for x in e.absolute_path),
                        validator=e.validator,
                        message=e.message,
                    )
                    for e in errors
                ]
                local = []
                if ref.get("local_nonempty_fields"):
                    local = [
                        k
                        for k in ref["local_nonempty_fields"]
                        if not isinstance(parsed.get(k), str) or not parsed[k].strip()
                    ]
                metrics["schema_validity"] = result(
                    "FAIL" if errors or local else ("PASS" if schema else "UNKNOWN"),
                    "ORIGINAL_STRICT_JSON_AND_FROZEN_SCHEMA",
                    "Independent decomposition; original native result is immutable.",
                    measurements={
                        "strict_json": True,
                        "json_schema_valid": not errors if schema else None,
                        "schema_errors": details,
                        "local_guard_missing_or_empty": local,
                    },
                )
                if errors:
                    clusters.append("SCHEMA_CONTRACT")
                if local:
                    clusters.append("EMPTY_REQUIRED_SEMANTIC_FIELD")
                root_verdict = parsed.get(
                    "verdict", parsed.get("support_status", parsed.get("status"))
                )
                diagnostic_prediction = (
                    root_verdict if isinstance(root_verdict, str) else None
                )
                if (
                    trace.original_native_result.get("valid") is True
                    and root_verdict in VERDICTS
                ):
                    native_prediction = root_verdict
                elif (
                    trace.original_native_result.get("prediction") in VERDICTS
                    and trace.original_native_result.get("valid") is True
                ):
                    native_prediction = trace.original_native_result["prediction"]
                metrics["evidence_link_validity"] = citation_checks(
                    parsed,
                    strict_json(artifact(self.root, case.evidence_catalog_ref)),
                    ref.get("citation_mode", "NONE"),
                )
            except (ValueError, UnicodeError) as exc:
                parsed = None
                clusters.append("STRICT_JSON")
                metrics["schema_validity"] = result(
                    "FAIL",
                    "ORIGINAL_STRICT_PARSER",
                    str(exc),
                    measurements={"strict_json": False, "json_schema_valid": None},
                )
        if not case.allowed_tools and not trace.proposed_actions:
            metrics["tool_selection_accuracy"] = result(
                "NOT_APPLICABLE",
                "TASK_FAMILY",
                "Original task has no tool-planning obligation.",
            )
        if case.task_family != "RESEARCH_REPORT_VALUE":
            metrics["report_quality"] = result(
                "NOT_APPLICABLE",
                "TASK_FAMILY",
                "Claim verification is not a complete research-report task.",
            )
        # Artifact source clocks are not a proof that the model reasoned temporally.
        boundary = []
        for source_id, c in case.clocks.items():
            arrivals = [
                v
                for k in ("published_at", "available_at")
                if isinstance((v := c.get(k)), str)
            ]
            boundary.append(
                dict(
                    source_id=source_id,
                    eligible=all(
                        clock(v) <= clock(case.research_as_of) for v in arrivals
                    ),
                    known=bool(arrivals),
                )
            )
        metrics["time_and_asof_correctness"] = result(
            "UNKNOWN",
            "SYSTEM_CLOCK_BOUNDARY_ONLY",
            "Model temporal application requires trace-specific review; historical metadata cannot certify current ACL/TTL or AgentResult reuse.",
            measurements={"source_boundaries": boundary},
        )
        if any(x["known"] and not x["eligible"] for x in boundary):
            metrics["source_scope_correctness"] = result(
                "FAIL",
                "ASOF_SOURCE_ELIGIBILITY",
                "Selected source universe contains a post-cutoff arrival/publication.",
                measurements={"source_boundaries": boundary},
            )
            clusters.append("SOURCE_TIME")
        elif metrics["evidence_link_validity"].status == "FAIL":
            metrics["source_scope_correctness"] = result(
                "FAIL",
                "ID_BINDING_ONLY",
                "An offered/source citation failed identity checks; economic support remains separate.",
            )
        for assertion in trace.numeric_assertions:
            span = assertion.get("model_span")
            if not span or parsed is None:
                raise ValueError("NUMERIC_PROJECTION_REQUIRES_ORIGINAL_SPAN")
            leaf = pointer(parsed, span["pointer"])
            if (
                not isinstance(leaf, str)
                or leaf[span["start"] : span["end"]] != span["excerpt"]
            ):
                raise ValueError("NUMERIC_MODEL_SPAN_DRIFT")
            if Decimal(span["excerpt"].replace(",", "")) != Decimal(
                str(assertion["value"])
            ):
                raise ValueError("NUMERIC_LITERAL_PROJECTION_DRIFT")
        metrics["numeric_consistency"] = numeric_checks(
            trace.numeric_assertions, ref.get("numeric_references", [])
        )
        if trace.proposed_actions:
            unavailable = [
                a
                for a in trace.proposed_actions
                if a.get("tool") not in case.allowed_tools
                or a.get("requests_business_write") is True
            ]
            metrics["tool_selection_accuracy"] = result(
                "FAIL" if unavailable else "UNKNOWN",
                "ACTION_SPACE_ONLY",
                "Allowed tool selection is not proven useful planning; frozen task/expert rubric must evaluate purpose, evidence target, stop and unknowns.",
                measurements={"unauthorized_actions": unavailable},
            )
        if trace.diagnostic_review_ref:
            if trace.diagnostic_review_ref.sha256 not in self.approved_reviews:
                raise ValueError("UNAPPROVED_DIAGNOSTIC_REVIEW")
            review = strict_json(artifact(self.root, trace.diagnostic_review_ref))
            if (
                not trace.assistant
                or review["assistant_sha256"] != trace.assistant.sha256
            ):
                raise ValueError("REVIEW_FOR_DIFFERENT_RESPONSE")
            if (
                review["scope"] != "POSTHOC_DIAGNOSTIC_ONLY"
                or review.get("independent_gold") is not False
            ):
                raise ValueError("UNAPPROVED_GOLD_UPGRADE")
            for observation in review.get("observations", []):
                metric = observation["metric"]
                if metric not in SEMANTIC_METRICS:
                    raise ValueError("UNAPPROVED_REVIEW_METRIC")
                spans = observation.get("model_spans", [])
                for span in spans:
                    if parsed is None:
                        raise ValueError("NO_RELIABLE_REVIEW_STRUCTURE")
                    value = pointer(parsed, span["pointer"])
                    if (
                        not isinstance(value, str)
                        or value[span["start"] : span["end"]] != span["excerpt"]
                    ):
                        raise ValueError("REVIEW_SPAN_MISMATCH")
                if not spans:
                    raise ValueError("SEMANTIC_REVIEW_REQUIRES_MODEL_SPAN")
                metrics[metric] = result(
                    observation["status"],
                    "POSTHOC_DEVELOPMENT_ADJUDICATION",
                    observation["reason"],
                    evidence=spans + observation.get("source_evidence", []),
                )
            serious.extend(review.get("serious_errors", []))
            clusters.extend(review.get("failure_clusters", []))
        # No arbitrary weighted score. Unknown semantic dimensions remain unknown.
        if trace.usage:
            u = trace.usage
            mandatory = [
                u.get("input_tokens"),
                u.get("output_tokens"),
                u.get("total_tokens"),
            ]
            known = all(type(v) is int and v >= 0 for v in mandatory)
            consistent = (
                known and u["input_tokens"] + u["output_tokens"] == u["total_tokens"]
            )
            cached = u.get("input_tokens_details", {}).get("cached_tokens")
            consistent = consistent and (
                cached is None
                or (type(cached) is int and 0 <= cached <= u["input_tokens"])
            )
            metrics["token_cost_latency"] = result(
                "PASS" if consistent else "FAIL",
                "PROVIDER_USAGE_ONLY",
                "Cost is conditional reference, actual bill UNKNOWN; neither lower cost nor cache hits prove research quality.",
                measurements={
                    "input_tokens": u.get("input_tokens"),
                    "output_tokens": u.get("output_tokens"),
                    "cached_tokens": cached,
                    "latency_seconds": trace.latency_seconds,
                    "reference_cost_cny": trace.reference_cost_cny,
                    "actual_bill": "UNKNOWN",
                },
            )
        scope: Literal["OFFLINE_MOCK_INTERFACE_ONLY", "POSTHOC_DIAGNOSTIC_ONLY"] = (
            "OFFLINE_MOCK_INTERFACE_ONLY"
            if trace.run_id.startswith("MOCK")
            else "POSTHOC_DIAGNOSTIC_ONLY"
        )
        return ScoreResult(
            protocol_sha256=self.protocol_sha256,
            trace_id=trace.trace_id,
            case_id=case.case_id,
            variant_id=trace.variant_id,
            execution_state=trace.execution_state,
            original_native_result=trace.original_native_result,
            native_prediction=native_prediction,
            diagnostic_prediction=diagnostic_prediction,
            metrics=metrics,
            serious_errors=serious,
            failure_clusters=sorted(set(clusters)),
            diagnostic_scope=scope,
        )
