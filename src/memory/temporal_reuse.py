"""G113 AgentResult eligibility reuses G85 and the original reference validator."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.memory.hybrid import HybridRead
from src.memory.incremental import (
    ImpactResolution,
    MemoryChangeSet,
    ReuseInputs,
    qualify_reuse,
)
from src.memory.temporal_versions import (
    qualified_delivery,
    version_snapshot,
    version_status,
)
from src.memory.vnext import MemoryAccessContext
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_collaboration import AnalystResult
from src.schemas.research_v2_shared import Reference, Revision, digest
from src.services.research_v2_collaboration.validation import ReferenceValidator


def qualify_agent_result(
    journal: MemoryJournalRepository,
    *,
    result_ref: Reference | None,
    acceptance_ref: Reference | None,
    previous: ReuseInputs | None,
    current: ReuseInputs | None,
    changes: MemoryChangeSet,
    impact: ImpactResolution,
    validator: ReferenceValidator | None,
    access: MemoryAccessContext,
    validate_revision: Callable[[Revision], None],
    relation_ids: tuple[str, ...] = (),
    current_validator: ReferenceValidator | None = None,
    delivery: HybridRead | None = None,
) -> dict[str, Any]:
    """Fail closed on missing original result and scientific acceptance.

    Resolver and original scientific authority must be injected by trusted W1
    composition, not by an Agent's proposal. No State or accepted Claim is written.
    """
    reasons: list[str] = []
    proof = None
    if current is not None:
        access.require("READ_HISTORY", current.scope)
    elif not access.enabled:
        raise ValueError("G113_REUSE_DISABLED")
    status = "NOT_EVALUABLE"
    if result_ref is None:
        reasons.append("NO_QUALIFIED_HISTORICAL_AGENTRESULT")
    elif any(
        x is None
        for x in (
            acceptance_ref,
            previous,
            current,
            validator,
            current_validator,
            delivery,
        )
    ):
        status = "BLOCKED_REUSE"
        reasons.append("MISSING_ORIGINAL_ACCEPTANCE_OR_DEPENDENCIES")
    else:
        assert previous is not None and current is not None and validator is not None
        assert acceptance_ref is not None and current_validator is not None
        assert delivery is not None
        status = "BLOCKED_REUSE"
        try:
            if current_validator.binding.research_as_of != changes.as_of:
                raise ValueError("CURRENT_VALIDATOR_CUTOFF")
            if delivery.read_set.research_as_of != changes.as_of:
                raise ValueError("CURRENT_MEMORY_READSET_CUTOFF")
            qualified = qualified_delivery(journal, delivery, access)
            delivered = {r["artifact_id"]: r for r in qualified["accepted"]}
            if any(
                delivered.get(r.artifact_id) != r.model_dump(mode="json")
                for r in current.memories
            ):
                raise ValueError("CURRENT_MEMORY_NOT_QUALIFIED")
            result_ref.require("RECEIPT")
            result = AnalystResult.model_validate_json(validator.artifact(result_ref))
            if result.reference != result_ref:
                raise ValueError("RESULT_IDENTITY")
            if (
                result.generated_at > changes.as_of
                or result.research_as_of != validator.binding.research_as_of
                or result.scope_id != current.scope.scope_id
                or result.read_state != previous.revision.state
                or set(result.claims) != set(previous.claims)
            ):
                raise ValueError("RESULT_CLOCK_SCOPE_OR_DEPENDENCIES")
            if (
                result.prompt.version != previous.prompt_version
                or result.producer_build.version != previous.agent_version
            ):
                raise ValueError("RESULT_VERSION")
            validator.analyst(result, previous.revision)
            validator.receipt(acceptance_ref, previous.revision)
            acceptance = json.loads(validator.artifact(acceptance_ref))
            if (
                acceptance.get("result") != result_ref.model_dump(mode="json")
                or acceptance.get("status") != "ACCEPTED"
                or acceptance.get("reuse_inputs_sha256") != previous.sha256
                or acceptance.get("role") != access.role
                or acceptance.get("task") != current.task
            ):
                raise ValueError("UNBOUND_OR_UNACCEPTED_ORIGINAL_RESULT")

            def validate_claim(ref: Reference) -> None:
                current_validator.claim(ref, current.revision, current.scope.scope_id)

            proof = qualify_reuse(
                previous,
                current,
                changes,
                impact,
                validate_claim,
                validate_revision,
            )
            reasons.extend(proof.reasons)
            for ref in current.memories:
                if (
                    version_status(
                        journal, ref.artifact_id, knowledge_as_of=changes.as_of
                    )
                    != "ACTIVE"
                ):
                    reasons.append("MEMORY_VERSION_INVALIDATED")
            known_relations = {k for k, _ in journal.entries("g111-r1-relations")}
            for rid in relation_ids:
                if (
                    rid not in known_relations
                    or version_status(journal, rid, knowledge_as_of=changes.as_of)
                    != "ACTIVE"
                ):
                    reasons.append("RELATION_MISSING_OR_INVALIDATED")
            if not reasons:
                status = "QUALIFIED_REUSE"
        except (ValueError, KeyError, OSError) as exc:
            reasons.append(type(exc).__name__ + ":" + str(exc))
    row = dict(
        schema_version="g113_agent_result_qualification_v1",
        disposition=status,
        result_ref=result_ref.model_dump(mode="json") if result_ref else None,
        acceptance_ref=(
            acceptance_ref.model_dump(mode="json") if acceptance_ref else None
        ),
        reasons=list(dict.fromkeys(reasons)),
        as_of=changes.as_of.isoformat(),
        changeset_sha256=changes.sha256,
        version_snapshot=version_snapshot(journal),
        proof=proof.model_dump(mode="json") if proof else None,
        actually_consumed=False,
        scientific_admission=False,
    )
    with journal.serialized():
        journal.append(
            "g113-agent-reuse",
            digest(row),
            json.dumps(row, sort_keys=True),
            len(journal.entries("g113-agent-reuse")),
        )
    return row
