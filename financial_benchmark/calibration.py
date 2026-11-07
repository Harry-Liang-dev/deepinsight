"""Financial calibration 1.1: source/computation checks, never an automatic expert Gold."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .io import artifact, load_cases, sha, strict_json


class CalibrationScorer:
    """Evaluate new six-field submissions under separately frozen calibration rules."""

    evaluator_id = "w5-financial-calibration-1.1.0"

    def __init__(self, root: Path) -> None:
        self.root = root
        raw = (root / "calibration_data/SCORER_PROTOCOL.json").read_bytes()
        self.protocol_sha256 = sha(raw)
        self.protocol = strict_json(raw)
        for relative, expected in self.protocol.get(
            "implementation_hashes", {}
        ).items():
            if sha((root / relative).read_bytes()) != expected:
                raise ValueError("CALIBRATION_IMPLEMENTATION_DRIFT")
        if self.protocol.get("implementation_hashes", {}).get(
            "financial_benchmark/calibration.py"
        ) != sha(Path(__file__).read_bytes()):
            raise ValueError("LOADED_CALIBRATION_IMPLEMENTATION_DRIFT")
        ledger = (root / "DETERMINISTIC_REFERENCE_LEDGER.json").read_bytes()
        packs = (root / "HIGH_VALUE_FINANCIAL_EVAL_CASES.jsonl").read_bytes()
        if (
            sha(ledger) != self.protocol["reference_ledger_sha256"]
            or sha(packs) != self.protocol["high_value_cases_sha256"]
        ):
            raise ValueError("CALIBRATION_REFERENCE_DRIFT")
        self.packs = {
            p["case_id"]: p
            for p in (strict_json(line) for line in packs.splitlines() if line)
        }
        self.references = {p["case_id"]: p for p in strict_json(ledger)["rows"]}
        # Actual original six-field shape is reused. This is not a new model carrier.
        traces = strict_json(
            (root / "benchmark_data/ARCHIVED_TRACES.json").read_bytes()
        )
        ref = next(
            t["native_schema"] for t in traces if t["trace_id"] == "MINIMAL2-PROBE-01"
        )
        body = (root / ref["path"]).read_bytes()
        if sha(body) != ref["sha256"]:
            raise ValueError("CALIBRATION_SCHEMA_DRIFT")
        self.schema = strict_json(body)
        self.cases = {c.case_id: c for c in load_cases(root)}

    def numeric_check(self, case_id: str, answer: dict[str, Any]) -> dict[str, Any]:
        """Check registered financial values with source, unit, period and accounting scope."""
        if case_id not in self.packs:
            raise ValueError("UNKNOWN_CALIBRATION_CASE")
        refs: dict[str, dict[str, Any]] = {
            r["metric_id"]: r
            for r in self.references[case_id].get("numeric_reference_rows", [])
        }
        target = refs.get(str(answer.get("metric_id")))
        if target is None:
            return dict(
                status="UNKNOWN",
                reason="NO_REGISTERED_REFERENCE_NOT_GROUNDED",
                grounded_pass=False,
            )
        offered = {s["handle"]: s for s in self.packs[case_id]["source_spans"]}
        if (
            answer.get("handle") != target["handle"]
            or answer.get("handle") not in offered
        ):
            return dict(
                status="FAIL", reason="MISSING_OR_WRONG_SOURCE", grounded_pass=False
            )
        if any(answer.get(k) != target[k] for k in ("period", "scope")):
            return dict(
                status="FAIL",
                reason="PERIOD_OR_ACCOUNTING_SCOPE_MISMATCH",
                grounded_pass=False,
            )
        unit_rule = target.get("equivalent_units", {}).get(answer.get("unit"))
        if unit_rule is None:
            return dict(
                status="UNKNOWN",
                reason="UNREGISTERED_UNIT_REQUIRES_NARRATIVE_OR_EXPERT_REVIEW",
                grounded_pass=False,
            )
        if any(
            k in answer and k in unit_rule and answer[k] != unit_rule[k]
            for k in ("currency", "scale")
        ):
            return dict(
                status="FAIL",
                reason="EXPLICIT_CURRENCY_OR_SCALE_CONFLICT",
                grounded_pass=False,
            )
        try:
            actual = Decimal(str(answer["value"])) * Decimal(unit_rule["factor"])
            expected = Decimal(target["value"])
            if target.get("comparison_quantum"):
                actual = actual.quantize(
                    Decimal(target["comparison_quantum"]), rounding=ROUND_HALF_UP
                )
            ok = actual.is_finite() and actual == expected
        except (InvalidOperation, KeyError):
            ok = False
        return dict(
            status="PASS" if ok else "FAIL",
            reason=(
                "REGISTERED_SOURCE_OR_HALF_UP_REFERENCE"
                if ok
                else "NUMERIC_VALUE_MISMATCH"
            ),
            grounded_pass=ok,
            source_id=offered[target["handle"]]["source_id"],
            source_locator=offered[target["handle"]]["locator"],
            reference_type="DETERMINISTIC_REFERENCE_NOT_INDEPENDENT_CLAIM_GOLD",
        )

    def evaluate(
        self,
        case_id: str,
        raw: bytes,
        *,
        task_kind: str = "financial",
        numeric_projection: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Do not infer financial reasoning from length, keywords, similarity or valid IDs."""
        pack = self.packs.get(case_id)
        if pack is None and task_kind != "technical":
            raise ValueError("UNKNOWN_CALIBRATION_CASE")
        metrics: dict[str, Any] = {
            k: dict(
                status="UNKNOWN",
                basis="NO_APPROVED_INDEPENDENT_GOLD_OR_TRACE_SPECIFIC_EXPERT_REVIEW",
            )
            for k in (
                "economic_judgment_correctness",
                "evidence_sufficiency",
                "research_value",
                "full_causal_parent_support",
                "uncertainty_calibration",
            )
        }
        failures = []
        obj = None
        intent = None
        try:
            obj = strict_json(raw)
            if not isinstance(obj, dict):
                raise ValueError("ROOT_NOT_OBJECT")
            errors = list(Draft202012Validator(self.schema).iter_errors(obj))
            metrics["strict_json"] = dict(status="PASS")
            metrics["native_schema"] = dict(
                status="FAIL" if errors else "PASS",
                errors=[
                    dict(
                        pointer="/" + ("/".join(str(t) for t in e.absolute_path)),
                        rule=e.message,
                    )
                    for e in errors
                ],
            )
            intent = obj.get("verdict")
            if errors:
                failures.append("SCHEMA")
            empty = [
                f
                for f in ("reasoning", "uncertainty")
                if not isinstance(obj.get(f), str)
                or (
                    not obj[f].strip()
                    and (f == "reasoning" or task_kind == "financial")
                )
            ]
            duplicates = [
                f
                for f in (
                    "evidence_handles",
                    "counterevidence_handles",
                    "missing_premises",
                )
                if isinstance(obj.get(f), list)
                and (
                    any(not isinstance(x, str) or not x.strip() for x in obj[f])
                    or len(set(str(x) for x in obj[f])) != len(obj[f])
                )
            ]
            metrics["local_guard"] = dict(
                status="FAIL" if empty or duplicates else "PASS",
                empty_fields=empty,
                duplicate_or_empty_items=duplicates,
                rule="New technical tasks may have no uncertainty; no historical MINIMAL2 native result is changed.",
            )
            if empty or duplicates:
                failures.append("LOCAL_GUARD")
        except (ValueError, UnicodeError) as exc:
            metrics["strict_json"] = dict(status="FAIL", error=str(exc))
            metrics["native_schema"] = dict(status="UNKNOWN")
            metrics["local_guard"] = dict(status="UNKNOWN")
            failures.append("STRICT_JSON")
        linked = []
        unoffered = []
        if obj is not None and not failures:
            catalog = (
                strict_json(
                    artifact(self.root, self.cases[case_id].evidence_catalog_ref)
                )
                if pack
                else []
            )
            offered = {e.get("handle", e.get("fragment_id")) for e in catalog}
            selected = obj["evidence_handles"] + obj["counterevidence_handles"]
            linked = [h for h in selected if h in offered]
            unoffered = [h for h in selected if h not in offered]
            metrics["evidence_link_validity"] = dict(
                status=(
                    "FAIL" if unoffered else ("PASS" if selected else "NOT_APPLICABLE")
                ),
                resolved=linked,
                unoffered=unoffered,
                not_economic_entailment=True,
            )
            if unoffered:
                failures.append("EVIDENCE_IDENTITY")
            if (
                task_kind == "financial"
                and intent == "SUPPORTED"
                and (not obj["evidence_handles"] or obj["missing_premises"])
            ):
                metrics["declared_premise_verdict_consistency"] = dict(
                    status="FAIL",
                    basis="MODEL_DECLARED_SUPPORT_WITH_NO_CITATION_OR_WITH_MISSING_PREMISE_FIELD",
                    expert_must_decide_premise_necessity=True,
                )
                if not obj["evidence_handles"]:
                    metrics["evidence_sufficiency"] = dict(
                        status="FAIL",
                        basis="NO_ATTRIBUTABLE_SUPPORTING_EVIDENCE_SUBMITTED_NOT_A_WORLD_FACT_REFUTATION",
                    )
                else:
                    metrics["evidence_sufficiency"] = dict(
                        status="UNKNOWN",
                        basis="Declared premise may be necessary or irrelevant to a conditional Claim; needs expert review, no keyword inference.",
                    )
                failures.append("DECLARED_UNSUPPORTED_PARENT_RISK")
            # These are exact registered counterexamples, not a free-text semantics model.
            blocked = (
                [
                    r
                    for r in self.references[case_id].get(
                        "required_claim_conditions", []
                    )
                    if r["required_for_complete_claim"] is True and r["value"] is False
                ]
                if pack
                else []
            )
            if intent == "SUPPORTED" and blocked:
                metrics["deterministic_reference_consistency"] = dict(
                    status="FAIL",
                    basis="DECLARED_COMPLETE_SUPPORT_CONFLICTS_REGISTERED_REQUIRED_CONDITION",
                    reference=blocked,
                )
                metrics["economic_judgment_correctness"] = dict(
                    status="FAIL",
                    basis="DETERMINISTIC_REGISTERED_NECESSARY_CONDITION_FALSE",
                    reference_class="DETERMINISTIC_REFERENCE",
                    scope="This exact complete source-bound Claim; not an approved independent Gold accuracy label.",
                )
                metrics["full_causal_parent_support"] = dict(
                    status="FAIL",
                    basis="COMPLETE_CLAIM_REQUIRES_A_CONDITION_CONTRADICTED_BY_REGISTERED_REFERENCE",
                )
                failures.append("SUPPORTED_CONTRADICTS_REGISTERED_REFERENCE")
            else:
                metrics["deterministic_reference_consistency"] = dict(
                    status="UNKNOWN",
                    basis="No automatic full-Claim label from expert candidate or wording.",
                )

        else:
            metrics["evidence_link_validity"] = dict(
                status="UNKNOWN", basis="NO_ELIGIBLE_NATIVE_OBJECT"
            )
        numeric = [self.numeric_check(case_id, a) for a in (numeric_projection or [])]
        metrics["numeric_consistency"] = dict(
            status=(
                "FAIL"
                if any(r["status"] == "FAIL" for r in numeric)
                else (
                    "PASS"
                    if numeric and all(r["status"] == "PASS" for r in numeric)
                    else "UNKNOWN"
                )
            ),
            checks=numeric,
            scope="Explicit registered numeric projections only, never all prose.",
        )
        mechanical_failure_codes = {
            "STRICT_JSON",
            "SCHEMA",
            "LOCAL_GUARD",
            "EVIDENCE_IDENTITY",
        }
        valid = not any(f in mechanical_failure_codes for f in failures)
        if task_kind == "technical":
            for field in (
                "economic_judgment_correctness",
                "research_value",
                "full_causal_parent_support",
                "uncertainty_calibration",
            ):
                metrics[field] = dict(
                    status="NOT_APPLICABLE", basis="NONFINANCIAL_TASK"
                )
        return dict(
            evaluator_id=self.evaluator_id,
            protocol_sha256=self.protocol_sha256,
            assistant_sha256=sha(raw),
            case_id=case_id,
            task_kind=task_kind,
            six_field_carrier_compliance=valid,
            declared_verdict=intent,
            candidate_prediction=intent if valid else None,
            metrics=metrics,
            failures=failures,
            abstention=intent == "UNDETERMINED",
            decision_coverage=int(intent in ("SUPPORTED", "UNSUPPORTED") and valid),
            full_research_score=None,
            approved_independent_gold=False,
            formal_accuracy="UNKNOWN",
            scientific_admission=False,
            scope="DETERMINISTIC_CALIBRATION_PLUS_EXPERT_REVIEW_REQUIRED_NOT_MODEL_RESEARCH_EFFECT",
        )
