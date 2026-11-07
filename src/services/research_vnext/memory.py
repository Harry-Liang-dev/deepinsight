"""Agent-side G84 adaptation only; no W6 methods, tables or store mutations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from src.memory.contracts import ResearchContextBundle
from src.memory.vnext import (
    MemoryAccessContext,
    content_sha256,
    read_set_from_bundle,
    validate_write_proposal,
)
from src.memory.vnext_contracts import (
    Action,
    ArtifactRef,
    MemoryReadSet,
    MemoryWriteProposal,
    RecordKind,
    Scope,
)
from src.schemas.agents import AgentContext
from src.schemas.memory import MemoryWriteRequest


def agent_reads(
    bundle: ResearchContextBundle,
    *,
    bundle_ref: ArtifactRef,
    memory_refs: Mapping[str, ArtifactRef],
    access: MemoryAccessContext,
    scope: Scope,
    agent_run_id: str,
    created_at: datetime,
) -> MemoryReadSet:
    """Record actual supplied Memory, not inferred attention or fact authority."""
    return read_set_from_bundle(
        bundle,
        bundle_ref=bundle_ref,
        memory_refs=memory_refs,
        access=access,
        scope=scope,
        agent_run_id=agent_run_id,
        record_id="reads:" + agent_run_id,
        created_at=created_at,
    )


def propose_increment(
    payload: MemoryWriteRequest,
    *,
    reads: MemoryReadSet,
    access: MemoryAccessContext,
    action: Action,
    kind: RecordKind,
    created_at: datetime,
) -> MemoryWriteProposal:
    """Return pending existing-write payload for W6 intake; never persist it."""
    from src.services.research_vnext.contracts import artifact

    reads = MemoryReadSet.model_validate_json(reads.model_dump_json())
    if reads.owner != access.owner or reads.agent_role != access.role:
        raise ValueError("ROLE_READSET_OWNER_MISMATCH")
    access.require("READ_HISTORY", reads.scope)
    payload_ref = ArtifactRef(
        artifact_id="payload:" + content_sha256(payload),
        sha256_digest=content_sha256(payload),
        version="memory_write_request",
        owner=access.owner,
        available_at=created_at,
        observed_at=created_at,
        ingested_at=created_at,
    )
    proposal = MemoryWriteProposal(
        owner=access.owner,
        record_id="increment:" + payload_ref.sha256,
        revision=1,
        created_at=created_at,
        research_as_of=reads.research_as_of,
        scope=reads.scope,
        source_refs=reads.source_refs,
        agent_role=access.role,
        agent_run_id=reads.agent_run_id,
        action=action,
        record_kind=kind,
        payload=payload_ref,
        read_set=artifact(reads),
    )
    return validate_write_proposal(proposal, payload, access=access)


def legacy_context_with_reads(
    context: AgentContext,
    bundle: ResearchContextBundle,
    reads: MemoryReadSet,
    *,
    access: MemoryAccessContext,
) -> AgentContext:
    """Carry actual G84 context/read-set to any original role, not as new facts.

    W1 calls this before its existing dispatcher. Source Evidence and original
    role manifests remain authoritative; structured context is not fact admission.
    """
    from src.schemas.agents import AgentContext

    actual = agent_reads(
        bundle,
        bundle_ref=reads.bundle_ref,
        memory_refs={r.artifact_id: r for r in reads.memory_refs},
        access=access,
        scope=reads.scope,
        agent_run_id=reads.agent_run_id,
        created_at=reads.created_at,
    )
    if actual.sha256 != reads.sha256:
        raise ValueError("MEMORY_CONTEXT_READSET_MISMATCH")
    return AgentContext.model_validate(
        {
            **context.model_dump(mode="python"),
            "structured_features": {
                **context.structured_features,
                "g84_memory_read_set": reads.model_dump(mode="json"),
                "g84_memory_context": bundle.model_dump(mode="json"),
                "g84_memory_authority": "CONTEXT_ONLY_NOT_FACT_ADMISSION",
            },
        }
    )
