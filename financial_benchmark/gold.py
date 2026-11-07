"""Independent Gold eligibility requires an owner-pinned registry, never candidate self-report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .io import artifact, case_fingerprint, strict_json, task_fingerprint
from .models import ArtifactRef, EvaluationCase

STATES = ("SUPPORTED", "UNSUPPORTED", "UNDETERMINED")


def load_gold(root: Path, case: EvaluationCase, policy: dict[str, Any]) -> str | None:
    """Return no Gold unless independently approved artifact and reviewer roster exist."""
    approved = set(policy.get("approved_independent_reviewers", []))
    for entry in policy.get("approved_gold_manifests", []):
        ref = ArtifactRef.model_validate(entry)
        record = strict_json(artifact(root, ref))
        if record["case_id"] != case.case_id:
            continue
        if (
            record.get("task_identity") != task_fingerprint(case)
            or record.get("case_version") != case.case_version
        ):
            raise ValueError("GOLD_TASK_CLAIM_DRIFT")
        if record["source_context_fingerprint"] != case_fingerprint(case):
            raise ValueError("GOLD_SOURCE_DRIFT")
        reviewers = record.get("independent_reviews", [])
        ids = {r["reviewer_id"] for r in reviewers}
        if len(reviewers) != 2 or len(ids) != 2 or not ids.issubset(approved):
            raise ValueError("UNAPPROVED_REVIEWERS")
        if any(
            r.get("blind_to_candidate_predictions") is not True
            or r.get("conflict_declared") != "NONE"
            or r.get("independent") is not True
            for r in reviewers
        ):
            raise ValueError("GOLD_NOT_INDEPENDENT")
        labels = {r["label"] for r in reviewers}
        if not labels.issubset(STATES):
            raise ValueError("UNKNOWN_GOLD_LABEL")
        if len(labels) == 1:
            return cast(str, labels.pop())
        adjud = record.get("adjudication", {})
        if (
            adjud.get("reviewer_id") in ids
            or adjud.get("reviewer_id") not in approved
            or adjud.get("label") not in STATES
        ):
            raise ValueError("PENDING_INDEPENDENT_ADJUDICATION")
        return cast(str, adjud["label"])
    return None


def confusion(golds: list[str | None], predictions: list[str | None]) -> dict[str, Any]:
    """Full three-state plus no-prediction population; never score missing Gold."""
    if len(golds) != len(predictions):
        raise ValueError("DENOMINATOR_MISMATCH")
    matrix = {g: {p: 0 for p in (*STATES, "NO_PREDICTION")} for g in STATES}
    unknown = 0
    for g, p in zip(golds, predictions, strict=True):
        if g is None:
            unknown += 1
            continue
        if g not in STATES or p not in (*STATES, None):
            raise ValueError("INVALID_THREE_STATE_VALUE")
        matrix[g][p if p else "NO_PREDICTION"] += 1
    count = len(golds) - unknown
    if not count:
        return dict(
            matrix=matrix,
            labeled=0,
            unlabeled=unknown,
            formal_accuracy="UNKNOWN",
            false_acceptance="UNKNOWN",
            false_rejection="UNKNOWN",
            supported_retention="UNKNOWN",
        )

    def rate(n: int, d: int) -> float | str:
        return n / d if d else "UNDEFINED"

    decided = sum(matrix[g][p] for g in STATES for p in STATES)
    s = sum(matrix["SUPPORTED"].values())
    u = sum(matrix["UNSUPPORTED"].values())
    d = sum(matrix["UNDETERMINED"].values())
    return dict(
        matrix=matrix,
        labeled=count,
        unlabeled=unknown,
        accuracy_over_labeled_planned=rate(sum(matrix[g][g] for g in STATES), count),
        conditional_accuracy_over_predictions=rate(
            sum(matrix[g][g] for g in STATES), decided
        ),
        false_acceptance=rate(matrix["UNSUPPORTED"]["SUPPORTED"], u),
        false_rejection=rate(matrix["SUPPORTED"]["UNSUPPORTED"], s),
        supported_abstention=rate(matrix["SUPPORTED"]["UNDETERMINED"], s),
        undetermined_upgrade=rate(matrix["UNDETERMINED"]["SUPPORTED"], d),
        supported_retention=rate(matrix["SUPPORTED"]["SUPPORTED"], s),
        decision_coverage=rate(
            sum(matrix[g][p] for g in STATES for p in ("SUPPORTED", "UNSUPPORTED")),
            count,
        ),
        no_prediction=sum(matrix[g]["NO_PREDICTION"] for g in STATES),
        undetermined_rate=rate(sum(matrix[g]["UNDETERMINED"] for g in STATES), count),
    )
