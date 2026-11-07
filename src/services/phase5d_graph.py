"""Real Phase5D resolver returning the sole frozen shared JSON envelopes.

W2 owns shared Python bindings. This boundary accepts their schema-valid JSON and
resolved immutable Plan/State registrations; it does not invent a parallel model.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Protocol

from src.schemas.phase5d_authority import authority
from src.schemas.phase5d_evidence import PitEvidenceInput
from src.schemas.research_data_quality import quality_hash
from src.services.phase5d_evidence import evaluate_pit


class CanonicalReferenceResolver(Protocol):
    """Orchestration supplies its registered immutable exact Plan/State store."""

    def resolve(self, reference: dict[str, Any]) -> dict[str, Any]:
        """Resolve actual immutable bytes, rejecting stale or unknown revisions."""
        ...


def reference(
    namespace: str, object_id: str, version: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Use the frozen Reference wire shape and actual resolved JSON digest."""
    result = dict(
        namespace=namespace, id=object_id, version=version, sha256=quality_hash(payload)
    )
    validate_shared(result, "Reference")
    return result


def validate_shared(value: Any, name: str) -> None:
    """Validate the closed frozen JSON subset without a new runtime dependency."""
    shared, contracts = authority("shared"), authority("contracts")

    def check(v: Any, schema: dict[str, Any], root: dict[str, Any]) -> None:
        if "$ref" in schema:
            ref = schema["$ref"]
            owner = contracts if ref.startswith("contracts.json") else root
            check(v, owner["$defs"][ref.rsplit("/", 1)[-1]], owner)
            return
        for key in ("oneOf", "anyOf"):
            if key in schema:
                successes = 0
                for branch in schema[key]:
                    try:
                        check(v, branch, root)
                        successes += 1
                    except ValueError:
                        continue
                if successes == 0 or (key == "oneOf" and successes != 1):
                    raise ValueError("SHARED_UNION")
                return
        if "const" in schema and v != schema["const"]:
            raise ValueError("SHARED_CONST")
        if "enum" in schema and v not in schema["enum"]:
            raise ValueError("SHARED_ENUM")
        kind = schema.get("type")
        if isinstance(kind, list):
            if v is None and "null" in kind:
                return
            kind = next(t for t in kind if t != "null")
        if kind == "null" and v is not None:
            raise ValueError("SHARED_NULL")
        if kind == "object":
            if (
                not isinstance(v, dict)
                or not set(schema.get("required", ())) <= v.keys()
                or (
                    schema.get("additionalProperties") is False
                    and not v.keys() <= schema["properties"].keys()
                )
            ):
                raise ValueError("SHARED_OBJECT_FIELDS")
            for k, x in v.items():
                if k in schema.get("properties", {}):
                    check(x, schema["properties"][k], root)
        if kind == "string":
            if (
                not isinstance(v, str)
                or len(v) < schema.get("minLength", 0)
                or ("pattern" in schema and not re.search(schema["pattern"], v))
            ):
                raise ValueError("SHARED_STRING")
            if schema.get("format") == "date-time":
                clock = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if clock.tzinfo is None:
                    raise ValueError("SHARED_AWARE_CLOCK")
        if kind == "integer" and (type(v) is not int or v < schema.get("minimum", 0)):
            raise ValueError("SHARED_INTEGER")
        if kind == "boolean" and type(v) is not bool:
            raise ValueError("SHARED_BOOLEAN")
        if kind == "array":
            if not isinstance(v, list):
                raise ValueError("SHARED_ARRAY")
            if schema.get("uniqueItems") and len(
                {json.dumps(x, sort_keys=True) for x in v}
            ) != len(v):
                raise ValueError("SHARED_DUPLICATE_ITEMS")
            for x in v:
                check(x, schema["items"], root)

    root = shared if name in shared["$defs"] else contracts
    check(value, root["$defs"][name], root)


class Phase5DEvidenceResolver:
    """Resolve all canonical evidence, with no builder-declared validity shortcut."""

    def __init__(
        self,
        envelope: PitEvidenceInput,
        *,
        run_binding: dict[str, Any],
        state_revision: dict[str, Any],
        registrations: CanonicalReferenceResolver,
    ) -> None:
        """Require actual registered immutable Plan/State/Episode and exact binding."""
        self.envelope = PitEvidenceInput.model_validate_json(envelope.model_dump_json())
        validate_shared(run_binding, "RunBinding")
        validate_shared(state_revision, "Revision")
        binding = envelope.closure.binding
        if (
            run_binding["run_id"] != binding.source_run_id
            or run_binding["capture_id"] != binding.capture_id
            or datetime.fromisoformat(
                run_binding["research_as_of"].replace("Z", "+00:00")
            )
            != envelope.original_input.data_bundle.as_of
        ):
            raise ValueError("SHARED_RUN_CAPTURE_CUTOFF_BINDING")
        if (
            state_revision["sequence"] == 0
            and state_revision["parent"] is not None
            or state_revision["sequence"] > 0
            and state_revision["parent"] is None
        ):
            raise ValueError("SHARED_REVISION_PARENT")
        for ref, namespace in (
            (run_binding["plan"], "PLAN"),
            (run_binding["episode"], "EPISODE"),
            (state_revision["state"], "STATE"),
        ):
            if ref["namespace"] != namespace:
                raise ValueError("SHARED_NAMESPACE")
            payload = registrations.resolve(ref)
            raw_resolver = getattr(registrations, "resolve_plan_bytes", None)
            if namespace == "PLAN" and raw_resolver is not None:
                raw = raw_resolver(ref)
                if (
                    not isinstance(raw, bytes)
                    or hashlib.sha256(raw).hexdigest() != ref["sha256"]
                    or json.loads(raw) != payload
                ):
                    raise ValueError("SHARED_REGISTERED_PLAN_BYTES")
            elif quality_hash(payload) != ref["sha256"]:
                raise ValueError("SHARED_REGISTERED_CONTENT_HASH")
            if namespace == "EPISODE" and payload != (
                self.envelope.original_input.research_episode.model_dump(mode="json")
            ):
                raise ValueError("REGISTERED_EPISODE_CONTENT_BINDING")
            if namespace == "STATE" and (
                ref["id"] != binding.research_state_id
                or payload
                != self.envelope.original_input.research_state.model_dump(mode="json")
            ):
                raise ValueError("REGISTERED_STATE_CONTENT_BINDING")
        # The registered Plan must match the producer's pre-acquisition plan pin.
        if run_binding["plan"]["sha256"] != binding.plan_sha256:
            raise ValueError("REGISTERED_PLAN_IDENTITY")
        if run_binding["episode"]["id"] != binding.episode_id:
            raise ValueError("REGISTERED_EPISODE_IDENTITY")
        if state_revision["parent"] is not None:
            parent = registrations.resolve(state_revision["parent"])
            if (
                state_revision["parent"]["namespace"] != "STATE"
                or quality_hash(parent) != state_revision["parent"]["sha256"]
            ):
                raise ValueError("REGISTERED_PARENT_STATE")
        self.binding = json.loads(json.dumps(run_binding))
        self.revision = json.loads(json.dumps(state_revision))
        self._read_state_bytes = json.dumps(
            [self.binding, self.revision], sort_keys=True
        )
        self.evaluation = evaluate_pit(self.envelope)
        self._input_bytes = self.envelope.model_dump_json()
        self.receipts: dict[str, dict[str, Any]] = {}
        self.nodes = {n.canonical_id: n for n in self.envelope.closure.nodes}
        self.claims = {
            str(r.claim.claim_id): r
            for r in self.envelope.original_input.accepted_claims
        }

    def evidence_reference(self, key: str) -> dict[str, Any]:
        """Expose canonical object bytes without changing their hash convention."""
        node = self.nodes[key]
        payload = node.structured_payload or node.document_payload
        assert payload is not None
        return reference(
            "EVIDENCE",
            key,
            (
                "ResearchEvidenceItem/1.0"
                if node.structured_payload
                else "DocumentChunkProof/2.0"
            ),
            payload.model_dump(mode="json"),
        )

    def claim_reference(self, key: str) -> dict[str, Any]:
        """Bind the complete canonical accepted Claim producer/usage record."""
        return reference(
            "CLAIM",
            key,
            "ResearchStateClaimInput/1.0",
            self.claims[key].model_dump(mode="json"),
        )

    def _receipt(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        ref = reference("RECEIPT", key, "phase5d_validation_receipt_v1", payload)
        self.receipts[ref["sha256"]] = json.loads(json.dumps(payload))
        return ref

    def _binding(
        self, run_binding: dict[str, Any], state_revision: dict[str, Any]
    ) -> None:
        if self.envelope.model_dump_json() != self._input_bytes:
            raise ValueError("MUTATED_RESOLVER_INPUT")
        if (
            json.dumps([self.binding, self.revision], sort_keys=True)
            != self._read_state_bytes
        ):
            raise ValueError("MUTATED_RESOLVER_READ_STATE")
        if run_binding != self.binding or state_revision != self.revision:
            raise ValueError("STALE_OR_WRONG_READ_STATE")

    def resolve_evidence(
        self,
        ref: dict[str, Any],
        run_binding: dict[str, Any],
        state_revision: dict[str, Any],
    ) -> dict[str, Any]:
        """Return independently validated participation and exact reason receipt."""
        self._binding(run_binding, state_revision)
        validate_shared(ref, "Reference")
        if ref["id"] not in self.nodes or ref != self.evidence_reference(ref["id"]):
            raise ValueError("CANONICAL_EVIDENCE_REFERENCE")
        key = ref["id"]
        decision = next(r for r in self.evaluation.evidence if r.evidence_id == key)
        node = self.nodes[key]
        proof = next(
            (p for p in self.envelope.authorities if p.evidence_id == key), None
        )
        receipt = self._receipt(
            key,
            {
                "binding": self.binding,
                "state_revision": self.revision,
                "input_identity": self.envelope.content_identity,
                "decision": decision.model_dump(mode="json"),
            },
        )
        temporal = (
            self._receipt("temporal:" + key, proof.model_dump(mode="json"))
            if proof
            else None
        )
        source = self._receipt(
            "source:" + key,
            (
                proof.acquisition.model_dump(mode="json")
                if proof and proof.acquisition
                else node.source_identity.model_dump(mode="json")
            ),
        )
        usage = (
            "ACCEPTED_FACT_SUPPORT"
            if decision.required_slot_satisfied
            else (
                "ATTRIBUTED_DIAGNOSTIC_CONTEXT"
                if decision.participation == "DIAGNOSTIC_EVIDENCE"
                else (
                    "HYPOTHESIS_CONTEXT"
                    if decision.participation == "DEPENDENCY_WITNESS"
                    else "QUARANTINED"
                )
            )
        )
        result = dict(
            binding=self.binding,
            state_revision=self.revision,
            evidence=ref,
            canonical_namespace=node.namespace,
            owner_asset_id=node.owner_subject,
            source=source,
            participation=decision.participation,
            research_usage=usage,
            independently_valid=decision.independently_valid,
            temporal_authority=temporal,
            validation_receipt=receipt,
            reason_codes=list(decision.reason_codes),
            required_slot_satisfied=decision.required_slot_satisfied,
        )
        validate_shared(result, "EvidenceDecision")
        return result

    def resolve_claim(
        self,
        ref: dict[str, Any],
        run_binding: dict[str, Any],
        state_revision: dict[str, Any],
    ) -> dict[str, Any]:
        """Reject any invalid required citation; never filter a surviving subset."""
        self._binding(run_binding, state_revision)
        validate_shared(ref, "Reference")
        if ref["id"] not in self.claims or ref != self.claim_reference(ref["id"]):
            raise ValueError("CANONICAL_CLAIM_REFERENCE")
        decision = next(r for r in self.evaluation.claims if r.claim_id == ref["id"])
        receipt = self._receipt(
            ref["id"],
            {
                "binding": self.binding,
                "state_revision": self.revision,
                "input_identity": self.envelope.content_identity,
                "decision": decision.model_dump(mode="json"),
            },
        )
        result = dict(
            binding=self.binding,
            state_revision=self.revision,
            claim=ref,
            owner_asset_id=str(self.envelope.original_input.data_bundle.asset_id),
            required_evidence=[
                self.evidence_reference(k) for k in decision.required_evidence
            ],
            eligible_for_pit_count=decision.eligible_for_pit_count,
            validation_receipt=receipt,
            reason_codes=list(decision.reason_codes),
        )
        validate_shared(result, "ClaimDecision")
        return result
