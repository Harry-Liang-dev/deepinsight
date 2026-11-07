"""Actual Agent-run binding for the existing controlled Memory admission API.

This adapter supplies lineage, never source authority. All scientific decisions
remain with ReferenceValidator and the existing Phase5D resolver.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from src.memory import MemoryService
    from src.memory.contracts import ResearchContextBundle, ResearchContextRequest

from src.agents.contracts import AgentExecutionResult, AgentInvocation
from src.memory.controlled import (
    ControlledRetrieval,
    MemoryAdmission,
    RetrievalAudit,
    record_usage,
)
from src.memory.vnext import MemoryAccessContext, content_sha256
from src.memory.vnext_contracts import (
    ArtifactRef,
    Frozen,
    MemoryReadSet,
    MemoryWriteProposal,
    RecordKind,
    Scope,
)
from src.models.enums import AgentStatus, MemoryLevel, ResearchScopeType
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.repositories import AgentRunRepository, LLMCacheRepository
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.common import SourceReference
from src.schemas.memory import (
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    MemoryWriteRequest,
    SemanticMemoryLifecycleStatus,
)
from src.schemas.research_v2_collaboration import AnalystResult
from src.schemas.research_v2_shared import (
    Clock,
    Reference,
    Revision,
    RunBinding,
    digest,
)
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind, utc_from_storage
from src.services.research_v2_collaboration.state import StateReducer
from src.services.research_vnext.contracts import artifact


class AgentMemoryExecution(Frozen):
    """Exact execution plus independently accepted v2 result, not self-attestation."""

    schema_version: Literal["g88_agent_memory_execution_v1"] = (
        "g88_agent_memory_execution_v1"
    )
    binding: RunBinding
    revision: Revision
    accepted: AnalystResult
    result: AgentExecutionResult
    reads: MemoryReadSet
    raw_response: JsonObject
    input_sha256: str
    recorded_at: Clock


def _check_execution(
    value: AgentMemoryExecution, reducer: StateReducer, journal: MemoryJournalRepository
) -> None:
    result = value.result
    if value.binding != reducer.binding or value.revision != reducer.head.revision:
        raise ValueError("MEMORY_EXECUTION_RUN_OR_REVISION")
    if (
        result.status != AgentStatus.OK
        or result.rejected_claims
        or result.output is None
    ):
        raise ValueError("MEMORY_EXECUTION_NOT_ACCEPTED")
    if (
        value.accepted not in reducer.head.analyst_results
        or value.accepted.reference in reducer.head.invalidated
    ):
        raise ValueError("MEMORY_V2_RESULT_NOT_ACCEPTED")
    if (
        value.accepted.participant != result.agent_name.value
        or value.accepted.run_id != value.binding.run_id
    ):
        raise ValueError("MEMORY_EXECUTION_ROLE_OR_RUN")
    from src.services.research_v2_collaboration.phase5d import (
        Phase5DCollaborationResolver,
    )

    resolver = reducer.validator.resolver
    if not isinstance(resolver, Phase5DCollaborationResolver):
        raise ValueError("CANONICAL_PHASE5D_SOURCE_AUTHORITY_REQUIRED")
    reads = value.reads
    if (
        reads.agent_run_id != result.run_id
        or reads.agent_role != result.agent_name
        or reads.research_as_of != value.binding.research_as_of
    ):
        raise ValueError("MEMORY_EXECUTION_READSET")
    if (reads.sha256, reads.model_dump_json()) not in journal.entries("readsets"):
        raise ValueError("MEMORY_EXECUTION_UNDELIVERED_READSET")
    record = AgentRunRepository(journal._database).get(result.run_id)
    metadata = result.llm_run_metadata
    if (
        record is None
        or metadata is None
        or record.agent_name != result.agent_name
        or record.status != "ok"
        or record.output_payload != result.output
        or digest(record.input_payload) != value.input_sha256
    ):
        raise ValueError("MEMORY_ORIGINAL_AGENT_RECORD")
    invocation = AgentInvocation.model_validate(record.input_payload)
    input_context = invocation.input_payload.get("input_context")
    if (
        not isinstance(input_context, dict)
        or input_context.get("asset_id") != resolver.canonical_owner
    ):
        raise ValueError("MEMORY_ACTUAL_INPUT_ISSUER_MISMATCH")
    if not _contains(
        record.input_payload,
        {
            "g88_canonical_owner": resolver.canonical_owner,
            "g88_v2_scope": resolver.scope,
        },
    ):
        raise ValueError("MEMORY_ACTUAL_INPUT_SOURCE_OWNER")
    for evidence in value.accepted.evidence_refs:
        if not _contains(record.input_payload, evidence.model_dump(mode="json")):
            raise ValueError("MEMORY_SOURCE_NOT_IN_ACTUAL_AGENT_INPUT")
    if not _contains(record.input_payload, reads.model_dump(mode="json")):
        raise ValueError("MEMORY_READSET_NOT_IN_ACTUAL_AGENT_INPUT")
    if (
        record.finished_at is None
        or utc_from_storage(record.finished_at) > value.recorded_at
    ):
        raise ValueError("MEMORY_EXECUTION_CLOCK")
    if value.accepted.generated_at > value.recorded_at:
        raise ValueError("FUTURE_V2_RESULT")
    if value.accepted.generated_at < utc_from_storage(record.finished_at):
        raise ValueError("V2_RESULT_PREDATES_AGENT_RESPONSE")
    cache = LLMCacheRepository(journal._database).get(metadata.request_fingerprint)
    if (
        cache is None
        or cache.response != value.raw_response
        or cache.provider != metadata.provider
        or cache.model_name != record.model_name
    ):
        raise ValueError("MEMORY_ORIGINAL_RESPONSE_MISSING_OR_CHANGED")
    old = reducer.snapshot(value.accepted.read_state)
    reducer.validator.analyst(value.accepted, old.revision)


def retain_execution(
    *,
    result: AgentExecutionResult,
    reads: MemoryReadSet,
    accepted: AnalystResult,
    reducer: StateReducer,
    journal: MemoryJournalRepository,
    at: datetime,
) -> AgentMemoryExecution:
    """Read original run/cache records and retain one verified execution lineage."""
    record = AgentRunRepository(journal._database).get(result.run_id)
    metadata = result.llm_run_metadata
    if record is None or metadata is None:
        raise ValueError("MEMORY_ORIGINAL_AGENT_RECORD")
    cache = LLMCacheRepository(journal._database).get(metadata.request_fingerprint)
    if cache is None:
        raise ValueError("MEMORY_ORIGINAL_RESPONSE_MISSING_OR_CHANGED")
    value = AgentMemoryExecution(
        binding=reducer.binding,
        revision=reducer.head.revision,
        accepted=accepted,
        result=result,
        reads=reads,
        raw_response=cache.response,
        input_sha256=digest(record.input_payload),
        recorded_at=at,
    )
    _check_execution(value, reducer, journal)
    for _, body in journal.entries("g88-executions"):
        old = AgentMemoryExecution.model_validate_json(body)
        if (
            old.binding.run_id == value.binding.run_id
            and old.result.run_id == result.run_id
        ):
            if old.model_copy(update={"recorded_at": at}) != value:
                raise ValueError("AGENT_RUN_EXECUTION_CONFLICT")
            return old
    journal.append(
        "g88-executions",
        value.sha256,
        value.model_dump_json(),
        len(journal.entries("g88-executions")),
    )
    return value


def _strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(_strings(v) for v in value))
    return set()


def propose_from_execution(
    execution: AgentMemoryExecution,
    *,
    statement_id: str,
    scope: Scope,
    owner: str,
    subject_owner: str,
    sources: Mapping[Reference, ArtifactRef],
    at: datetime,
    journal: MemoryJournalRepository,
) -> MemoryAdmission:
    """Select exact accepted output; do not repair text or manufacture a v2 proof."""
    if (execution.sha256, execution.model_dump_json()) not in journal.entries(
        "g88-executions"
    ):
        raise ValueError("UNRETAINED_EXECUTION")
    if execution.reads.scope != scope or execution.reads.owner != owner:
        raise ValueError("MEMORY_EXECUTION_SCOPE_OWNER")
    accepted = execution.accepted
    statements = [
        s
        for s in (*accepted.findings, *accepted.hypotheses, *accepted.uncertainties)
        if s.id == statement_id
    ]
    questions = [q for q in accepted.open_questions if q.id == statement_id]
    if len(statements) + len(questions) != 1:
        raise ValueError("MEMORY_EXACT_ACCEPTED_ITEM_REQUIRED")
    item = (statements or questions)[0]
    text = item.text
    if text not in _strings(execution.raw_response) or text not in _strings(
        execution.result.output
    ):
        raise ValueError("MEMORY_TEXT_NOT_ORIGINAL_AGENT_OUTPUT")
    kind = (
        "RESEARCH_QUESTION"
        if questions
        else {"ANALYTICAL_INFERENCE": "INFERENCE", "UNCERTAINTY": "HYPOTHESIS"}.get(
            statements[0].kind, statements[0].kind
        )
    )
    refs = tuple(sources[e] for e in accepted.evidence_refs)
    for e, ref in zip(accepted.evidence_refs, refs, strict=True):
        if (e.id, e.sha256, e.version) != (
            ref.artifact_id,
            ref.sha256_digest,
            ref.version,
        ):
            raise ValueError("MEMORY_SOURCE_IDENTITY")
        ref.require_recorded_by(execution.binding.research_as_of)
    if at < execution.recorded_at:
        raise ValueError("MEMORY_WRITE_BEFORE_EXECUTION")
    payload = MemoryWriteRequest(
        asset_id=(
            AssetId(subject_owner)
            if scope.scope_type == ResearchScopeType.ASSET
            else None
        ),
        memory_level=MemoryLevel.L3,
        namespace_key=scope.scope_id,
        effective_ts=execution.binding.research_as_of,
        summary_text=text,
        created_by=owner,
        source_ref_json=SourceReference(document_id=accepted.evidence_refs[0].id),
        metadata=LearningMemoryMetadata(
            memory_version="g88_research_memory_v1",
            research_reference="agent-execution:" + execution.sha256,
            usage_class=LearningMemoryUsageClass.SEMANTIC,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            parent_scope_id="GLOBAL:RESEARCH",
            semantic_status=SemanticMemoryLifecycleStatus.CANDIDATE,
            source_claim_ids=tuple(
                r.id for r in getattr(item, "support", ()) if r.namespace == "CLAIM"
            ),
            temporal=TemporalMetadata(
                source_kind=TemporalSourceKind.MEMORY, available_at=at, ingested_at=at
            ),
        ),
    )
    payload_ref = ArtifactRef(
        artifact_id="payload:" + content_sha256(payload),
        sha256_digest=content_sha256(payload),
        version="memory_write_request",
        owner=owner,
        available_at=at,
        observed_at=at,
        ingested_at=at,
    )
    proposal = MemoryWriteProposal(
        owner=owner,
        record_id="g88-write:" + digest((execution.sha256, statement_id)),
        revision=1,
        created_at=at,
        research_as_of=at,
        scope=scope,
        source_refs=refs,
        agent_role=execution.result.agent_name,
        agent_run_id=execution.result.run_id,
        action="CITE_VALIDATED_FACT" if kind == "FACT" else "PROPOSE_HYPOTHESIS",
        record_kind=cast(RecordKind, kind),
        payload=payload_ref,
        read_set=artifact(execution.reads),
    )
    request = MemoryAdmission(
        proposal=proposal,
        payload=payload,
        read_set=execution.reads,
        revision=execution.revision,
        subject_owner=subject_owner,
        statement=statements[0] if statements else None,
        question=questions[0] if questions else None,
        evidence=accepted.evidence_refs,
    )
    body = json.dumps(
        {
            "admission": request.model_dump(mode="json"),
            "execution": execution.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    journal.append(
        "g88-proposals", request.sha256, body, len(journal.entries("g88-proposals"))
    )
    return request


def execution_for_admission(
    request: MemoryAdmission, reducer: StateReducer, journal: MemoryJournalRepository
) -> AgentMemoryExecution | None:
    """Consume the actual durable proposal binding; no caller PASS flag."""
    rows = [
        body for key, body in journal.entries("g88-proposals") if key == request.sha256
    ]
    if not rows:
        if request.proposal.record_id.startswith("g88-write:"):
            raise ValueError("MISSING_EXECUTION_BINDING")
        return None
    body = json.loads(rows[0])
    value = AgentMemoryExecution.model_validate_json(json.dumps(body["execution"]))
    if body["admission"] != request.model_dump(mode="json") or not any(
        key == value.sha256 and AgentMemoryExecution.model_validate_json(raw) == value
        for key, raw in journal.entries("g88-executions")
    ):
        raise ValueError("MEMORY_EXECUTION_BODY_CHANGED")
    _check_execution(value, reducer, journal)
    if (
        request.read_set != value.reads
        or request.proposal.agent_run_id != value.result.run_id
        or request.subject_owner != value.accepted.scope_id
    ):
        raise ValueError("MEMORY_EXECUTION_ADMISSION_BINDING")
    if (
        request.statement
        not in (
            *value.accepted.findings,
            *value.accepted.hypotheses,
            *value.accepted.uncertainties,
        )
        and request.question not in value.accepted.open_questions
    ):
        raise ValueError("MEMORY_ITEM_NOT_ACCEPTED")
    if (
        request.evidence != value.accepted.evidence_refs
        or request.revision != value.revision
    ):
        raise ValueError("MEMORY_EXECUTION_SOURCE_REVISION")
    if (
        request.proposal.created_at < value.recorded_at
        or request.proposal.research_as_of != request.proposal.created_at
    ):
        raise ValueError("MEMORY_EXECUTION_WRITE_CLOCK")
    return value


def _contains(value: object, target: object) -> bool:
    if value == target:
        return True
    if isinstance(value, dict):
        return any(_contains(v, target) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains(v, target) for v in value)
    return False


def project_context(
    service: MemoryService,
    query: ResearchContextRequest,
    retrieval: ControlledRetrieval,
    *,
    access: MemoryAccessContext,
    journal: MemoryJournalRepository,
) -> tuple[ResearchContextBundle, MemoryReadSet]:
    """Filter actual service retrieval through controlled eligibility."""
    from src.memory.contracts import (
        ResearchContextBundle,
        ResearchContextSection,
        RetrievalStatus,
    )
    from src.services.research_vnext.memory import agent_reads

    if (
        query.as_of != retrieval.read_set.research_as_of
        or access.owner != retrieval.read_set.owner
    ):
        raise ValueError("MEMORY_PROJECTION_CUTOFF_OWNER")
    if (retrieval.sha256, retrieval.model_dump_json()) not in journal.entries(
        "retrieval-audit"
    ):
        raise ValueError("UNKNOWN_RETRIEVAL")
    bundle = service.retrieve_context(query)
    allowed = {r.artifact_id: r for r in retrieval.read_set.memory_refs}
    sections = {
        s.value: [i for i in bundle.items_for_section(s) if i.memory_id in allowed]
        for s in ResearchContextSection
    }
    payloads = dict(zip(allowed, retrieval.payloads, strict=True))
    for items in sections.values():
        for item in items:
            expected = payloads[item.memory_id]
            if (
                item.summary_text,
                item.namespace_key,
                item.memory_level,
                item.asset_id,
                item.effective_ts,
                item.source,
                item.created_by,
                item.metadata,
            ) != (
                expected.summary_text,
                expected.namespace_key,
                expected.memory_level,
                expected.asset_id,
                expected.effective_ts,
                expected.source_ref_json,
                expected.created_by,
                expected.metadata,
            ):
                raise ValueError("PERSISTED_MEMORY_ADMISSION_MISMATCH")
    count = sum(len(items) for items in sections.values())
    metadata = bundle.retrieval_metadata.model_copy(
        update={
            "result_count": count,
            "section_counts": {
                s: len(sections[s.value]) for s in ResearchContextSection
            },
            "status": RetrievalStatus.PARTIAL if count else RetrievalStatus.EMPTY,
            "no_relevant_memory": not count,
        }
    )
    bundle = ResearchContextBundle.model_validate(
        {**bundle.model_dump(), **sections, "retrieval_metadata": metadata}
    )
    refs = {
        i.memory_id: allowed[i.memory_id].model_copy(
            update={
                "sha256_digest": content_sha256(i),
                "version": "research_context_memory_v1",
                "available_at": i.available_at,
                # Project the payload's actual recorded clock, not the later
                # admission receipt clock. Controlled retrieval already checks
                # that the receipt itself exists by the Episode cutoff.
                "observed_at": (
                    i.metadata.temporal.ingested_at
                    if i.metadata and i.metadata.temporal.ingested_at
                    else allowed[i.memory_id].observed_at
                ),
                "ingested_at": (
                    i.metadata.temporal.ingested_at
                    if i.metadata and i.metadata.temporal.ingested_at
                    else allowed[i.memory_id].ingested_at
                ),
            }
        )
        for s in ResearchContextSection
        for i in bundle.items_for_section(s)
    }
    b = retrieval.read_set.bundle_ref.model_copy(
        update={
            "artifact_id": "projected:" + content_sha256(bundle),
            "sha256_digest": content_sha256(bundle),
            "version": bundle.schema_version,
        }
    )
    reads = agent_reads(
        bundle,
        bundle_ref=b,
        memory_refs=refs,
        access=access,
        scope=retrieval.read_set.scope,
        agent_run_id=retrieval.read_set.agent_run_id,
        created_at=retrieval.read_set.created_at,
    )
    journal.append(
        "readsets",
        reads.sha256,
        reads.model_dump_json(),
        len(journal.entries("readsets")),
    )
    journal.append(
        "g88-projections",
        reads.sha256,
        json.dumps(
            {"retrieval": retrieval.sha256, "bundle": bundle.model_dump(mode="json")},
            sort_keys=True,
        ),
        len(journal.entries("g88-projections")),
    )
    return bundle, reads


def record_agent_citations(
    result: AgentExecutionResult,
    reads: MemoryReadSet,
    retrieval: ControlledRetrieval,
    *,
    journal: MemoryJournalRepository,
) -> tuple[RetrievalAudit, ...]:
    """Count accepted explicit citations from an actual retained Agent execution."""
    if (
        result.status != AgentStatus.OK
        or result.rejected_claims
        or result.run_id != reads.agent_run_id
    ):
        raise ValueError("MEMORY_CITATION_AGENT_NOT_ACCEPTED")
    record = AgentRunRepository(journal._database).get(result.run_id)
    if (
        record is None
        or record.output_payload != result.output
        or not _contains(record.input_payload, reads.model_dump(mode="json"))
    ):
        raise ValueError("MEMORY_CITATION_INPUT_OUTPUT_BINDING")
    rows = [
        json.loads(body)
        for key, body in journal.entries("g88-projections")
        if key == reads.sha256
    ]
    if len(rows) != 1 or rows[0]["retrieval"] != retrieval.sha256:
        raise ValueError("MEMORY_CITATION_PROJECTION_BINDING")
    from src.memory.controlled import AdmissionReceipt

    receipts = {
        r.result.memory_id: r
        for _, body in journal.entries("memory-catalog")
        for r in (AdmissionReceipt.model_validate_json(body),)
    }
    from src.agents.coordinator import _validated_claims

    if not _contains(record.input_payload, rows[0]["bundle"]):
        raise ValueError("MEMORY_BUNDLE_NOT_IN_ACTUAL_AGENT_INPUT")
    if (
        record.finished_at is None
        or utc_from_storage(record.finished_at) < reads.research_as_of
    ):
        raise ValueError("MEMORY_CONSUMPTION_CLOCK")
    from src.memory.controlled import retrieve_memory

    if not reads.memory_refs:
        return ()
    if not retrieval.audit:
        raise ValueError("MEMORY_CITATION_MISSING_RETRIEVAL_AUDIT")
    current = retrieve_memory(
        journal=journal,
        access=MemoryAccessContext(
            owner=reads.owner,
            role=reads.agent_role,
            scopes=(reads.scope,),
            enabled=True,
        ),
        scope=reads.scope,
        as_of=reads.research_as_of,
        created_at=reads.created_at,
        run_id=reads.agent_run_id,
        revision=retrieval.audit[0].revision,
    )
    usable = {r.artifact_id for r in current.read_set.memory_refs}
    uses = []
    for ref in reads.memory_refs:
        claims = tuple(
            c for c in _validated_claims(result) if ref.artifact_id in c.evidence_ids
        )
        if not claims:
            continue
        if ref.artifact_id not in usable:
            raise ValueError("MEMORY_INVALIDATED_BEFORE_CONSUMPTION")
        if receipts[ref.artifact_id].validation_status != "VALIDATED_CITATION":
            raise ValueError("UNVERIFIED_MEMORY_NOT_FACT_AUTHORITY")
        source_id = receipts[
            ref.artifact_id
        ].admission.payload.source_ref_json.document_id
        if any(
            not any(s.document_id == source_id for s in c.source_references)
            for c in claims
        ):
            raise ValueError("MEMORY_CITATION_SOURCE_MISMATCH")
        uses.append(
            record_usage(
                journal,
                retrieval,
                ref.artifact_id,
                tuple(c.claim_id or c.claim_path for c in claims),
            )
        )
    return tuple(uses)
