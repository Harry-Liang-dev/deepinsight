"""Original-condition validation; a reply is never itself a resolution proof."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from src.schemas.research_v2_collaboration import CollaborationMessage, ResearchPlan
from src.schemas.research_v2_shared import (
    Frozen,
    Reference,
    Revision,
    RunBinding,
    Text,
    canonical,
    reference,
)

from .validation import ReferenceValidator


class ResolutionCondition(Frozen):
    """Prospectively registered condition, read from immutable plan inputs."""

    condition_id: Text
    owner_asset_id: Text
    required_claims: tuple[Reference, ...]
    required_evidence: tuple[Reference, ...]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """An original condition cannot disguise Evidence as an accepted Claim."""
        for item in self.required_claims:
            item.require("CLAIM")
        for item in self.required_evidence:
            item.require("EVIDENCE")
        return self

    @property
    def reference(self) -> Reference:
        """Bind the complete requirement, not its display name."""
        return reference(
            "DEFINITION", self.condition_id, "resolution_condition_v1", self
        )


class ResolutionProof(Frozen):
    """Runtime receipt retaining exact original conditions and validator decisions."""

    binding: RunBinding
    revision: Revision
    request: Reference
    validator_build: Reference
    conditions: tuple[Reference, ...]
    evidence: tuple[Reference, ...]
    validator_receipts: tuple[Reference, ...]
    satisfied: bool
    reason_codes: tuple[Text, ...]

    @property
    def reference(self) -> Reference:
        """Resolution receipt is independently reproducible from immutable inputs."""
        return reference(
            "RECEIPT", "resolution-" + self.request.id, "resolution_proof_v1", self
        )


def assess_resolution(
    plan: ResearchPlan,
    validator: ReferenceValidator,
    revision: Revision,
    request: CollaborationMessage,
    evidence: tuple[Reference, ...],
) -> ResolutionProof:
    """Verify all siblings and the original, prospectively bound acceptance rules."""
    conditions = []
    receipts = []
    reasons = []
    rules = {
        r.id: r
        for r in plan.input_snapshots
        if r.namespace == "DEFINITION" and r.version == "resolution_condition_v1"
    }
    owners: dict[Reference, str] = {}
    # Validate every sibling even when the request has unknown acceptance rules.
    for supplied in evidence:
        validator.artifact(supplied)
        if supplied.namespace == "CLAIM":
            claim_decision = validator.resolver.resolve_claim(
                supplied, validator.binding, revision
            )
            owner = claim_decision.owner_asset_id
            validator.claim(supplied, revision, owner)
            receipts.append(claim_decision.validation_receipt)
        elif supplied.namespace == "EVIDENCE":
            evidence_decision = validator.resolver.resolve_evidence(
                supplied, validator.binding, revision
            )
            owner = evidence_decision.owner_asset_id
            validator.evidence(supplied, revision, owner)
            receipts.append(evidence_decision.validation_receipt)
        else:
            raise ValueError("RESOLUTION_REFERENCE_KIND")
        if owner not in plan.requested_assets:
            raise ValueError("RESOLUTION_ASSET_OUTSIDE_PLAN")
        owners[supplied] = owner
    for name in request.acceptance_conditions:
        ref = rules.get(name)
        if ref is None:
            reasons.append("UNREGISTERED_ACCEPTANCE_CONDITION")
            continue
        condition = ResolutionCondition.model_validate_json(validator.artifact(ref))
        if (
            condition.reference != ref
            or not condition.required_claims
            and not condition.required_evidence
        ):
            raise ValueError("INVALID_RESOLUTION_CONDITION")
        conditions.append(ref)
        required = (*condition.required_claims, *condition.required_evidence)
        if not set(required) <= set(evidence):
            reasons.append("ORIGINAL_CONDITION_NOT_SATISFIED")
        if any(owner != condition.owner_asset_id for owner in owners.values()):
            raise ValueError("RESOLUTION_CONDITION_OWNER")
    return ResolutionProof(
        binding=validator.binding,
        revision=revision,
        request=request.reference,
        validator_build=plan.producer_build,
        conditions=tuple(conditions),
        evidence=evidence,
        validator_receipts=tuple(dict.fromkeys(receipts)),
        satisfied=not reasons and bool(conditions),
        reason_codes=tuple(dict.fromkeys(reasons))
        or ("ORIGINAL_CONDITIONS_VALIDATED",),
    )


def validate_resolution(
    plan: ResearchPlan,
    validator: ReferenceValidator,
    revision: Revision,
    request: CollaborationMessage,
    response: CollaborationMessage,
) -> None:
    """Recompute receipt meaning before RESOLVED; reject forged self-attestation."""
    if (
        response.causal_requests != (request.reference,)
        or response.sender != request.recipient
        or response.recipient != request.sender
        or response.acceptance_conditions != request.acceptance_conditions
    ):
        raise ValueError("RESOLUTION_ORIGINAL_REQUEST_BINDING")
    if response.resolution_status == "RESOLVED":
        proof = assess_resolution(
            plan, validator, revision, request, response.resolution_evidence
        )
        if not proof.satisfied or response.validation_receipt != proof.reference:
            raise ValueError("RESOLUTION_ORIGINAL_CONDITIONS")
        if validator.artifact(proof.reference) != canonical(proof):
            raise ValueError("RESOLUTION_PROOF_BYTES")
    elif response.validation_receipt is not None:
        proof = assess_resolution(
            plan, validator, revision, request, response.resolution_evidence
        )
        if proof.reference != response.validation_receipt or proof.satisfied:
            raise ValueError("UNRESOLVED_RECEIPT_CONTRADICTION")
        validator.artifact(proof.reference)
