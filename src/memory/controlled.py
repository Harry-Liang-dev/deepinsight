"""G85 checked adapters for the original MemoryService and v2 validators."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from src.memory.incremental import ImpactResolution, MemoryChangeSet
from src.memory.vnext import (
    MemoryAccessContext,
    content_sha256,
    validate_write_proposal,
)
from src.memory.vnext_contracts import (
    ArtifactRef,
    Frozen,
    MemoryReadSet,
    MemoryWriteProposal,
    Scope,
)
from src.models.enums import MemoryLevel
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryUsageClass,
    MemoryWriteRequest,
    MemoryWriteResult,
    SemanticMemoryLifecycleStatus,
)
from src.schemas.research_v2_collaboration import Question, Statement
from src.schemas.research_v2_shared import Clock, Reference, Revision
from src.services.research_v2_collaboration.state import StateReducer

if TYPE_CHECKING:
    from src.memory.hybrid import SourceAdmission
    from src.memory.hybrid_contracts import NarrativeProposal, SemanticReviewFixture
    from src.memory.hybrid_sources import NativeLocatorResolver
    from src.memory.service import MemoryService
    from src.schemas.research_episode import ResearchEpisode


class MemoryAdmission(Frozen):
    """Versioned extension binding G84 to an exact original v2 revision."""

    schema_version: Literal["g85_memory_admission_v1"] = "g85_memory_admission_v1"
    proposal: MemoryWriteProposal
    payload: MemoryWriteRequest
    read_set: MemoryReadSet
    revision: Revision
    subject_owner: str
    statement: Statement | None = None
    question: Question | None = None
    evidence: tuple[Reference, ...] = Field(min_length=1)


class AdmissionReceipt(Frozen):
    """Content-bound persisted result; hypotheses remain unverified context."""

    admission: MemoryAdmission
    result: MemoryWriteResult
    validation_status: Literal["VALIDATED_CITATION", "UNVERIFIED_RESEARCH"]
    created_at: Clock


def admit_memory(
    service: MemoryService,
    request: MemoryAdmission,
    *,
    access: MemoryAccessContext,
    reducer: StateReducer,
    journal: MemoryJournalRepository,
    scope_owners: Mapping[Scope, str],
    source_identities: Mapping[Reference, ArtifactRef],
) -> AdmissionReceipt:
    """Resolve source/Claim authority before an idempotent original-service write."""
    if journal.database_path != service._duckdb_repo._database.path.resolve():
        raise ValueError("SECOND_MEMORY_DATABASE_FORBIDDEN")
    request = MemoryAdmission.model_validate_json(request.model_dump_json())
    p, payload, reads = request.proposal, request.payload, request.read_set
    from src.memory.feedback import execution_for_admission

    execution = execution_for_admission(request, reducer, journal)
    validate_write_proposal(p, payload, access=access)
    if scope_owners.get(p.scope) != request.subject_owner:
        raise ValueError("SUBJECT_SCOPE_BINDING")
    if (
        reads.owner != access.owner
        or reads.agent_role != access.role
        or reads.agent_run_id != p.agent_run_id
        or reads.scope != p.scope
        or reads.research_as_of
        != (execution.binding.research_as_of if execution else p.research_as_of)
        or p.read_set.sha256_digest != reads.sha256
        or p.read_set.artifact_id != reads.record_id
        or p.read_set.version != reads.schema_version
        or p.read_set.owner != reads.owner
    ):
        raise ValueError("READ_SET_BINDING")
    if execution is None and (
        reducer.binding.research_as_of != p.research_as_of
        or reducer.binding.run_id != p.agent_run_id
    ):
        raise ValueError("RUN_BINDING")
    if request.revision != reducer.head.revision:
        raise ValueError("STALE_REVISION")
    reducer.snapshot(request.revision.state)
    if reducer.head.completed:
        raise ValueError("COMPLETED_STATE_IMMUTABLE")
    # A reference hash supplied by an Agent is insufficient: require actual delivery.
    retained = journal.entries("readsets")
    if (reads.sha256, reads.model_dump_json()) not in retained:
        raise ValueError("UNDELIVERED_READ_SET")
    if payload.memory_level != MemoryLevel.L3:
        raise ValueError("AGENT_RESEARCH_LEVEL_REQUIRED")
    metadata = payload.metadata
    assert metadata is not None
    if (
        metadata.usage_class is LearningMemoryUsageClass.PERFORMANCE
        or p.record_kind == "OUTCOME"
        or metadata.outcome_id is not None
    ):
        # Existing G84/bridge supplies no mature outcome admission authority.
        raise ValueError("MATURE_OUTCOME_AUTHORITY_UNAVAILABLE")
    if p.action in ("UPDATE_WORKING_STATE", "REVIEW_FINAL_STATE"):
        raise ValueError("USE_ORIGINAL_STATE_REDUCER")
    if metadata.semantic_status is SemanticMemoryLifecycleStatus.VALIDATED:
        raise ValueError("SEMANTIC_PROMOTION_REQUIRES_EXISTING_AUTHORITY")
    if (
        metadata.content_kind is EpisodicMemoryContentKind.VALIDATED_CLAIM
        and p.record_kind != "FACT"
    ):
        raise ValueError("HYPOTHESIS_CANNOT_DECLARE_VALIDATED_CLAIM")
    claim_refs = (
        ()
        if request.statement is None
        else tuple(r for r in request.statement.support if r.namespace == "CLAIM")
    )
    if set(metadata.source_claim_ids) - {r.id for r in claim_refs}:
        raise ValueError("UNBOUND_METADATA_CLAIMS")
    validator = reducer.validator
    for evidence in request.evidence:
        if source_identities.get(evidence) not in p.source_refs:
            raise ValueError("UNBOUND_SOURCE_IDENTITY")
        validator.evidence(
            evidence,
            request.revision,
            request.subject_owner,
            factual=p.record_kind == "FACT",
        )
    source_pairs = {(r.artifact_id, r.sha256_digest, r.version) for r in p.source_refs}
    if not {(r.id, r.sha256, r.version) for r in request.evidence} <= source_pairs:
        raise ValueError("UNBOUND_SOURCE_IDENTITY")
    if payload.source_ref_json.document_id not in {r.id for r in request.evidence}:
        raise ValueError("PAYLOAD_SOURCE_MISMATCH")
    if request.statement is not None and request.question is None:
        s = request.statement
        if {"ANALYTICAL_INFERENCE": "INFERENCE", "UNCERTAINTY": "HYPOTHESIS"}.get(
            s.kind, s.kind
        ) != p.record_kind or s.text != payload.summary_text:
            raise ValueError("STATEMENT_PAYLOAD_MISMATCH")
        validator.statement(s, request.revision, request.subject_owner)
    elif request.question is not None and request.statement is None:
        if (
            p.record_kind != "RESEARCH_QUESTION"
            or request.question.text != payload.summary_text
        ):
            raise ValueError("QUESTION_PAYLOAD_MISMATCH")
        validator.question(request.question, request.revision)
    else:
        raise ValueError("EXACT_RESEARCH_PAYLOAD_REQUIRED")
    if service._clock() < p.created_at:
        raise ValueError("ADMISSION_CLOCK_REGRESSION")
    stream = "admissions:" + access.owner
    with journal.serialized():
        rows = journal.entries(stream)
        for identity, body in rows:
            receipt = AdmissionReceipt.model_validate_json(body)
            if receipt.admission.proposal.record_id == p.record_id:
                if identity != request.sha256:
                    raise ValueError("PROPOSAL_IDEMPOTENCY_CONFLICT")
                journal.append(
                    "memory-catalog",
                    request.sha256,
                    body,
                    len(journal.entries("memory-catalog")),
                )
                return receipt
        result = _write_or_recover(service, payload)
        receipt = AdmissionReceipt(
            admission=request,
            result=result,
            validation_status=(
                "VALIDATED_CITATION"
                if p.record_kind == "FACT"
                else "UNVERIFIED_RESEARCH"
            ),
            created_at=service._clock(),
        )
        journal.append(stream, request.sha256, receipt.model_dump_json(), len(rows))
        journal.append(
            "memory-catalog",
            request.sha256,
            receipt.model_dump_json(),
            len(journal.entries("memory-catalog")),
        )
        return receipt


class RetrievalAudit(Frozen):
    """Delivery versus actual citation, with exact revision and rejection reasons."""

    memory_id: str
    revision: Revision
    agent_run_id: str
    agent_role: str
    accepted: bool
    reason: str
    provided: bool
    referenced_ids: tuple[str, ...] = ()


class ControlledRetrieval(Frozen):
    """Bounded structured context; no vector hit can certify a factual claim."""

    read_set: MemoryReadSet
    payloads: tuple[MemoryWriteRequest, ...]
    audit: tuple[RetrievalAudit, ...]
    consumed_budget: int


def retrieve_memory(
    *,
    journal: MemoryJournalRepository,
    access: MemoryAccessContext,
    scope: Scope,
    as_of: datetime,
    created_at: datetime,
    run_id: str,
    revision: Revision,
    top_k: int = 8,
    token_budget: int = 2048,
    invalidated: tuple[str, ...] = (),
    source_ids: tuple[str, ...] | None = None,
) -> ControlledRetrieval:
    """Filter exact retained identities before optional semantics; structured fallback.

    UTF-8 bytes conservatively bound tokens without loading an external tokenizer.
    Legacy records without complete lineage cannot enter this opt-in path.
    """
    access.require("READ_HISTORY", scope)
    as_of, created_at = ArtifactRef.utc(as_of), ArtifactRef.utc(created_at)
    if not 0 < top_k <= 100 or not 0 < token_budget <= 32768:
        raise ValueError("RETRIEVAL_BUDGET")
    # Scope grants originate at the trusted root; enumerate retained receipts.
    receipts = [
        AdmissionReceipt.model_validate_json(body)
        for _, body in journal.entries("memory-catalog")
    ]
    changed_at = {
        key: MemoryChangeSet.model_validate_json(body).as_of
        for key, body in journal.entries("changesets")
    }
    invalid_refs: set[Reference] = set()
    for _, body in journal.entries("impacts"):
        impact = ImpactResolution.model_validate_json(body)
        if impact.changeset_sha256 not in changed_at:
            raise ValueError("ORPHAN_IMPACT")
        if changed_at[impact.changeset_sha256] <= as_of:
            invalid_refs.update(impact.invalidated)
    receipts.sort(
        key=lambda r: (
            -r.admission.payload.importance_score,
            -r.created_at.timestamp(),
            r.result.memory_id,
        )
    )
    selected: list[MemoryWriteRequest] = []
    refs: list[ArtifactRef] = []
    audit: list[RetrievalAudit] = []
    consumed = 0
    seen: set[str] = set()
    for r in receipts:
        a, memory_id = r.admission, r.result.memory_id
        p = a.proposal
        if memory_id in seen:
            continue
        seen.add(memory_id)
        reason = "ACCEPTED_CONTEXT_ONLY"
        if p.scope != scope or p.scope not in access.scopes:
            reason = "SCOPE_DENIED"
        elif (
            max(
                r.created_at,
                p.research_as_of,
                *(
                    max(s.available_at, s.observed_at, s.ingested_at)
                    for s in p.source_refs
                ),
            )
            > as_of
        ):
            reason = "FUTURE_MEMORY_OR_SOURCE"
        elif (
            memory_id in invalidated
            or a.revision.state in invalid_refs
            or set(a.evidence).intersection(invalid_refs)
            or (
                a.statement is not None
                and set(a.statement.support).intersection(invalid_refs)
            )
        ):
            reason = "INVALIDATED"
        if reason == "ACCEPTED_CONTEXT_ONLY" and a.payload.metadata is not None:
            from src.schemas.temporal import temporal_access_decision

            if not temporal_access_decision(a.payload.metadata.temporal, as_of).usable:
                reason = "TEMPORAL_STATUS"
        if (
            reason == "ACCEPTED_CONTEXT_ONLY"
            and source_ids is not None
            and not set(source_ids).intersection(r.artifact_id for r in p.source_refs)
        ):
            reason = "SOURCE_FILTER"
        cost = len(a.payload.summary_text.encode("utf-8"))
        if reason == "ACCEPTED_CONTEXT_ONLY" and (
            len(selected) >= top_k or consumed + cost > token_budget
        ):
            reason = "BUDGET"
        accepted = reason == "ACCEPTED_CONTEXT_ONLY"
        audit.append(
            RetrievalAudit(
                memory_id=memory_id,
                revision=revision,
                agent_run_id=run_id,
                agent_role=str(access.role),
                accepted=accepted,
                reason=reason,
                provided=accepted,
            )
        )
        if accepted:
            selected.append(a.payload)
            consumed += cost
            refs.append(
                ArtifactRef(
                    artifact_id=memory_id,
                    sha256_digest=content_sha256(a.payload),
                    version="g85_memory_admission_v1",
                    owner=p.owner,
                    available_at=r.created_at,
                    observed_at=r.created_at,
                    ingested_at=r.created_at,
                )
            )
    bundle_bytes = json.dumps(
        [p.model_dump(mode="json") for p in selected],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    bundle = ArtifactRef(
        artifact_id="bundle:" + hashlib.sha256(bundle_bytes).hexdigest(),
        sha256_digest=hashlib.sha256(bundle_bytes).hexdigest(),
        version="g85_structured_bundle_v1",
        owner=access.owner,
        available_at=created_at,
        observed_at=created_at,
        ingested_at=created_at,
    )
    reads = MemoryReadSet(
        owner=access.owner,
        record_id=bundle.artifact_id,
        revision=1,
        created_at=created_at,
        research_as_of=as_of,
        scope=scope,
        source_refs=tuple(refs),
        bundle_ref=bundle,
        bundle_sha256=bundle.sha256_digest,
        agent_role=access.role,
        agent_run_id=run_id,
        retrieval_query_id=bundle.artifact_id,
        memory_refs=tuple(refs),
    )
    result = ControlledRetrieval(
        read_set=reads,
        payloads=tuple(selected),
        audit=tuple(audit),
        consumed_budget=consumed,
    )
    with journal.serialized():
        journal.append(
            "readsets",
            reads.sha256,
            reads.model_dump_json(),
            len(journal.entries("readsets")),
        )
        journal.append(
            "retrieval-audit",
            result.sha256,
            result.model_dump_json(),
            len(journal.entries("retrieval-audit")),
        )
    return result


def record_usage(
    journal: MemoryJournalRepository,
    retrieval: ControlledRetrieval,
    memory_id: str,
    referenced_ids: tuple[str, ...],
) -> RetrievalAudit:
    """Record explicit downstream citations separately from supplied context."""
    if not referenced_ids or not all(referenced_ids):
        raise ValueError("USAGE_REFERENCES_REQUIRED")
    if (retrieval.sha256, retrieval.model_dump_json()) not in journal.entries(
        "retrieval-audit"
    ):
        raise ValueError("UNKNOWN_RETRIEVAL")
    delivered = next(
        (a for a in retrieval.audit if a.memory_id == memory_id and a.provided), None
    )
    if delivered is None:
        raise ValueError("MEMORY_NOT_PROVIDED")
    usage = RetrievalAudit.model_validate(
        {**delivered.model_dump(), "referenced_ids": referenced_ids}
    )
    with journal.serialized():
        journal.append(
            "usage",
            usage.sha256,
            usage.model_dump_json(),
            len(journal.entries("usage")),
        )
    return usage


def _write_or_recover(
    service: MemoryService, payload: MemoryWriteRequest
) -> MemoryWriteResult:
    # Exact payload identity permits recovery after Memory write / receipt interruption.
    # Serialize through the G85 journal operation lock; original MemoryService writes.
    from src.schemas.temporal import utc_from_storage

    for old in service._duckdb_repo.list_namespace(
        service.namespace_for_level(payload.memory_level)
    ):
        if old.source_ref is None:
            continue
        restored = MemoryWriteRequest(
            memory_level=old.memory_level,
            namespace_key=old.namespace_key,
            effective_ts=utc_from_storage(old.effective_ts),
            summary_text=old.summary_text,
            asset_id=old.asset_id,
            memory_type=old.memory_type,
            importance_score=old.importance_score,
            source_ref_json=old.source_ref,
            created_by=old.created_by,
            metadata=old.metadata,
        )
        if restored == payload:
            return MemoryWriteResult(
                memory_id=old.memory_id,
                faiss_namespace=old.faiss_namespace,
                faiss_vector_id=old.faiss_vector_id,
            )
    return service.write(payload)


def admit_source_assertion(
    service: MemoryService,
    proposal: NarrativeProposal,
    *,
    resolver: NativeLocatorResolver,
    access: MemoryAccessContext,
    journal: MemoryJournalRepository,
    episode: ResearchEpisode,
    enabled: bool = False,
    review_fixture: SemanticReviewFixture | None = None,
) -> SourceAdmission:
    """G100 opt-in source observations; never replace v2 scientific admission.

    Uses the existing ACL, journal, MemoryService and crash-recovery writer.
    The G84 Claim/AgentRun proposal cannot express this new limited authority.
    """
    from src.memory.hybrid import admit_source_observation

    return admit_source_observation(
        service,
        proposal,
        resolver=resolver,
        access=access,
        journal=journal,
        episode=episode,
        enabled=enabled,
        review_fixture=review_fixture,
    )
