"""Content-bound adapter from Phase5D canonical context to shared v2 revisions.

Canonical v1 State/Episode are Evidence context, never aliases for a v2 revision.
Every shared decision retains both contexts and the independent Phase5D receipt.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.agents.evidence import numeric_literals
from src.agents.numeric_grounding import (
    NativeNumericBinding,
    validate_numeric_grounding,
)
from src.schemas.agents import RoleEvidenceManifestEntry, ValidatedClaim
from src.schemas.research_v2_collaboration import ResearchPlan
from src.schemas.research_v2_shared import (
    ClaimDecision,
    EvidenceDecision,
    Reference,
    Revision,
    RunBinding,
    canonical,
    digest,
    reference,
)
from src.services.phase5d_graph import Phase5DEvidenceResolver

from .state import StateSnapshot


class Phase5DCollaborationResolver:
    """Use independent canonical validation, with explicit synthetic scope mapping."""

    def __init__(
        self,
        authority: Phase5DEvidenceResolver,
        plan: ResearchPlan,
        values: dict[Reference, bytes],
        scope: str,
        canonical_owner: str,
        *,
        retained_readonly: bool = False,
        fresh_source_registration: Reference | None = None,
        native_numeric: NativeNumericBinding | None = None,
    ) -> None:
        """Freeze exact input and scope; no ticker inference or default VALID path."""
        self.native_numeric = native_numeric
        self.retained_readonly = retained_readonly
        self.fresh_source_registration = fresh_source_registration
        if retained_readonly:
            if (
                authority.binding["mode"] != "RETAINED_READONLY"
                or scope != canonical_owner
                or plan.requested_assets != (scope,)
                or str(authority.envelope.original_input.data_bundle.asset_id) != scope
                or authority.envelope.original_input.data_bundle.as_of
                > plan.research_as_of
            ):
                raise ValueError("RETAINED_SCOPE_OR_CUTOFF_BINDING")
        elif (
            authority.binding["mode"] != "SYNTHETIC_OFFLINE"
            or not scope.startswith("SYNTHETIC:")
            or scope not in plan.requested_assets
            or str(authority.envelope.original_input.data_bundle.asset_id)
            != canonical_owner
            or authority.binding["run_id"] != plan.run_id
            or authority.binding["plan"]["sha256"] != plan.reference.sha256
            or authority.envelope.original_input.data_bundle.as_of
            != plan.research_as_of
        ):
            raise ValueError("PHASE5D_INTEGRATION_REGISTRATION")
        self.authority = authority
        self._evaluation_identity = digest(authority.evaluation)
        self.plan = plan
        self.values = dict(values)
        scope_id = (
            "retained-canonical-scope-binding"
            if retained_readonly
            else "synthetic-canonical-scope-binding"
        )
        scope_refs = [
            r
            for r in plan.input_snapshots
            if r.id == scope_id and r.namespace == "DEFINITION" and r.version == "1.0.0"
        ]
        if len(scope_refs) != 1:
            raise ValueError("MISSING_SCOPE_REGISTRATION")
        scope_payload = json.loads(self.artifact(scope_refs[0]))
        if retained_readonly and fresh_source_registration is not None:
            if fresh_source_registration not in plan.source_permissions:
                raise ValueError("FRESH_SOURCE_PERMISSION_REQUIRED")
            registration = json.loads(self.artifact(fresh_source_registration))
            if (
                registration.get("schema") != "G90_NATIVE_SOURCE_REGISTRATION_V1"
                or registration.get("owner") != canonical_owner
                or scope_payload
                != {
                    "mode": "G90_FRESH_RUN_RETAINED_NATIVE_SOURCE",
                    "registration": fresh_source_registration.model_dump(mode="json"),
                    "bindings": {scope: canonical_owner},
                    "consumer_run_id": plan.run_id,
                }
            ):
                raise ValueError("FRESH_SOURCE_SCOPE_BINDING")
            registered = registration["evidence"]
            for node in authority.nodes.values():
                if authority.evidence_reference(node.canonical_id) not in registered:
                    raise ValueError("FRESH_SOURCE_NOT_REGISTERED")
        elif retained_readonly:
            if scope_payload != {
                "mode": "RETAINED_READONLY_NOT_NEW_SOURCE_HISTORY",
                "canonical_input_identity": authority.envelope.content_identity,
                "bindings": {scope: canonical_owner},
                "consumer_run_id": plan.run_id,
            }:
                raise ValueError("WRONG_RETAINED_SCOPE_REGISTRATION")
        elif (
            scope_payload.get("mode") != "INVENTED_ONLY_NOT_LISTING_AUTHORITY"
            or scope_payload.get("bindings", {}).get(scope) != canonical_owner
            or set(scope_payload["bindings"]) != set(plan.requested_assets)
            or len(set(scope_payload["bindings"].values()))
            != len(plan.requested_assets)
        ):
            raise ValueError("WRONG_SCOPE_REGISTRATION")
        self.input_reference = reference(
            "RECEIPT", "phase5d-full-input", "pit_evidence_input_v1", authority.envelope
        )
        self.values[self.input_reference] = canonical(authority.envelope)
        self.scope = scope
        self.canonical_owner = canonical_owner
        self.snapshot: Callable[[Reference], StateSnapshot] | None = None
        self._receipts: dict[Reference, tuple[RunBinding, Revision]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self._claims: dict[Reference, dict[str, Any]] = {}
        for key, row in authority.claims.items():
            claim = ValidatedClaim.model_validate(row.claim.model_dump())
            ref = reference("CLAIM", key, "validated_claim_v1", claim)
            self.values[ref] = canonical(claim)
            self._claims[ref] = authority.claim_reference(key)
        self.evidence = tuple(
            Reference.model_validate_json(
                canonical(authority.evidence_reference(p.evidence_id))
            )
            for p in authority.envelope.authorities
        )
        if retained_readonly:
            self.evidence = tuple(
                Reference.model_validate_json(
                    canonical(authority.evidence_reference(k))
                )
                for k, node in authority.nodes.items()
                if node.owner_subject == canonical_owner
            )
        for ref in self.evidence:
            node = authority.nodes[ref.id]
            self.values[ref] = canonical(
                node.structured_payload or node.document_payload
            )

    @property
    def claim(self) -> Reference:
        """Expose an existing Claim only; empty pre-dispatch context has none."""
        if not self._claims:
            raise ValueError("NO_CANONICAL_CLAIMS_REGISTERED")
        return next(iter(self._claims))

    def artifact(self, ref: Reference) -> bytes:
        """Resolve exact immutable bytes and reject modified or unknown references."""
        raw = self.values.get(ref)
        if raw is None or digest(json.loads(raw)) != ref.sha256:
            raise ValueError("PHASE5D_ARTIFACT_IDENTITY")
        return raw

    def _check(self, binding: RunBinding, revision: Revision) -> None:
        if digest(self.authority.evaluation) != self._evaluation_identity:
            raise ValueError("MUTATED_PHASE5D_EVALUATION")
        if (
            binding.mode
            != ("RETAINED_READONLY" if self.retained_readonly else "SYNTHETIC_OFFLINE")
            or binding.capture_id is not None
            or binding.plan != self.plan.reference
            or binding.episode != self.plan.episode
            or binding.run_id != self.plan.run_id
            or binding.research_as_of != self.plan.research_as_of
            or self.snapshot is None
        ):
            raise ValueError("PHASE5D_COLLABORATION_BINDING")
        state = self.snapshot(revision.state)
        if state.revision != revision or state.binding != binding:
            raise ValueError("PHASE5D_STATE_REVISION_BINDING")
        self.values[revision.state] = canonical(state)

    def _proof(
        self, kind: str, payload: object, binding: RunBinding, revision: Revision
    ) -> Reference:
        body = dict(
            kind=kind,
            binding=binding,
            state_revision=revision,
            phase5d_input=self.authority.envelope.content_identity,
            input_reference=self.input_reference,
            canonical_binding=self.authority.binding,
            canonical_revision=self.authority.revision,
            scope_binding={
                "scope": self.scope,
                "canonical_owner": self.canonical_owner,
                "mode": (
                    "RETAINED_READONLY_NOT_NEW_SOURCE_HISTORY"
                    if self.retained_readonly
                    else "INVENTED_ONLY_NOT_LISTING_AUTHORITY"
                ),
            },
            payload=payload,
        )
        ref = reference("RECEIPT", kind, "phase5d_collaboration_receipt_v1", body)
        self.values[ref] = canonical(body)
        self._receipts[ref] = (binding, revision)
        return ref

    def validate_receipt(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> None:
        """Only independently generated receipts for this exact read revision pass."""
        self._check(binding, revision)
        self.artifact(ref)
        if self._receipts.get(ref) != (binding, revision):
            raise ValueError("PHASE5D_UNREGISTERED_VALIDATION_RECEIPT")
        # Revalidate the original independently bound input, including drift checks.
        self.authority._binding(self.authority.binding, self.authority.revision)

    def resolve_evidence(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> EvidenceDecision:
        """Rebind Phase5D decisions without changing participation or validity."""
        self._check(binding, revision)
        raw = self.authority.resolve_evidence(
            ref.model_dump(mode="json"), self.authority.binding, self.authority.revision
        )
        if raw["owner_asset_id"] != self.canonical_owner:
            raise ValueError("PHASE5D_OWNER_BINDING")
        proof = self._proof("evidence:" + ref.id, raw, binding, revision)
        temporal = raw["temporal_authority"]
        temporal_ref = (
            self._proof(
                "temporal:" + ref.id,
                self.authority.receipts[temporal["sha256"]],
                binding,
                revision,
            )
            if temporal
            else None
        )
        source = self.input_reference
        decision = EvidenceDecision.model_validate_json(
            canonical(
                {
                    **raw,
                    "binding": binding,
                    "state_revision": revision,
                    "owner_asset_id": self.scope,
                    "validation_receipt": proof,
                    "source": source,
                    "temporal_authority": temporal_ref,
                }
            )
        )
        self.decisions[digest(decision)] = decision.model_dump(mode="json")
        return decision

    def resolve_claim(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> ClaimDecision:
        """Validate full canonical Claim closure and the existing literal grounder."""
        self._check(binding, revision)
        if ref not in self._claims:
            raise ValueError("PHASE5D_CANONICAL_CLAIM")
        claim = ValidatedClaim.model_validate_json(self.artifact(ref))
        raw = self.authority.resolve_claim(
            self._claims[ref], self.authority.binding, self.authority.revision
        )
        if raw["owner_asset_id"] != self.canonical_owner:
            raise ValueError("PHASE5D_OWNER_BINDING")
        entries = []
        for required in raw["required_evidence"]:
            node = self.authority.nodes[required["id"]]
            item = node.structured_payload
            if item is None:
                doc = node.document_payload
                if doc is None:
                    raise ValueError("CANONICAL_DOCUMENT_REQUIRED")
                entries.append(
                    RoleEvidenceManifestEntry(
                        evidence_id=doc.canonical_id,
                        evidence_type="document",
                        source=doc.exact_citation_reference,
                        short_description=doc.chunk_text,
                        numeric_tokens=numeric_literals(doc.chunk_text),
                    )
                )
                continue
            entries.append(
                RoleEvidenceManifestEntry(
                    evidence_id=item.evidence_id,
                    evidence_type="structured_direct",
                    source=item.to_source_reference(),
                    as_of=item.effective_at,
                    short_description=str(item.value),
                    numeric_tokens=numeric_literals(str(item.value)),
                )
            )
        grounded = validate_numeric_grounding(
            claim.claim_text, tuple(entries), native_binding=self.native_numeric
        )
        if (
            grounded.ungrounded_literals
            or grounded.numeric_literals != claim.numeric_literals
        ):
            raise ValueError("INVALID_CANONICAL_CLAIM_GROUNDING")
        proof = self._proof("claim:" + ref.id, raw, binding, revision)
        decision = ClaimDecision.model_validate_json(
            canonical(
                {
                    **raw,
                    "binding": binding,
                    "state_revision": revision,
                    "claim": ref,
                    "owner_asset_id": self.scope,
                    "validation_receipt": proof,
                }
            )
        )
        self.decisions[digest(decision)] = decision.model_dump(mode="json")
        return decision
