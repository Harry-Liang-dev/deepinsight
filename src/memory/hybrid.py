"""Opt-in source observation admission using the original MemoryService and journal.

This is NOT G85/G88 scientific Memory admission. No Agent result is manufactured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextRequest,
    ResearchContextSection,
    RetrievalStatus,
)
from src.memory.controlled import _write_or_recover
from src.memory.hybrid_contracts import (
    NarrativeProposal,
    NarrativeRecord,
    SemanticReviewFixture,
)
from src.memory.hybrid_sources import NativeLocatorResolver
from src.memory.service import MemoryService
from src.memory.vnext import MemoryAccessContext, content_sha256, read_set_from_bundle
from src.memory.vnext_contracts import ArtifactRef, Frozen, MemoryReadSet, Scope
from src.models.enums import MemoryLevel, ResearchScopeType
from src.models.identifiers import AssetId
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_v2_shared import Clock
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind


class SourceAdmission(Frozen):
    """Observation receipt; persistence is not a scientific or Agent acceptance."""

    record: NarrativeRecord
    payload: MemoryWriteRequest
    result: MemoryWriteResult
    persisted_at: Clock
    source_assertion_admitted: bool
    research_result_accepted: Literal[False] = False
    scientific_memory_admitted: Literal[False] = False


class HybridRead(Frozen):
    """Original bundle and G84 ReadSet with exact non-factual authority sidecars."""

    episode_id: str
    bundle: ResearchContextBundle
    read_set: MemoryReadSet
    retrieved_ids: tuple[str, ...]
    supplied_records: tuple[SourceAdmission, ...]
    excluded_ids: tuple[str, ...]


def _same_store(service: MemoryService, journal: MemoryJournalRepository) -> None:
    if service._duckdb_repo._database.path.resolve() != journal.database_path:
        raise ValueError("G100_SECOND_DATABASE_FORBIDDEN")


def admit_source_observation(
    service: MemoryService,
    p: NarrativeProposal,
    *,
    resolver: NativeLocatorResolver,
    access: MemoryAccessContext,
    journal: MemoryJournalRepository,
    episode: ResearchEpisode,
    enabled: bool = False,
    review_fixture: SemanticReviewFixture | None = None,
) -> SourceAdmission:
    """Append a source observation via existing ACL/transaction/recovery machinery."""
    if not enabled:
        raise ValueError("G100_DISABLED")
    p = NarrativeProposal.model_validate_json(p.model_dump_json())
    access.require("APPEND_EVENT", p.scope)
    _same_store(service, journal)
    if (
        p.owner != access.owner
        or p.scope.scope_type != ResearchScopeType.RESEARCH_EPISODE
        or p.scope.scope_id != "EPISODE:" + episode.episode_id
        or p.episode_id != episode.episode_id
        or p.research_state_id != episode.research_state_id
        or p.subject != str(episode.asset_id)
        or p.research_as_of != episode.research_as_of
        or p.created_at < episode.created_at
    ):
        raise ValueError("G100_OWNER_SCOPE_EPISODE")
    record = resolver.validate(p, review_fixture)
    now = service._clock()
    if not p.created_at <= now < record.review_due_at:
        raise ValueError("G100_CREATION_OR_RETENTION")
    stream = "g100-observations:" + p.owner + ":" + p.scope.scope_id + ":" + p.record_id
    with journal.serialized():
        rows = journal.entries(stream)
        for identity, body in rows:
            old = SourceAdmission.model_validate_json(body)
            if old.record.proposal.revision == p.revision:
                if old.record != record:
                    raise ValueError("G100_REVISION_CONFLICT")
                journal.append(
                    "g100-source-catalog",
                    old.record.sha256,
                    old.model_dump_json(),
                    len(journal.entries("g100-source-catalog")),
                )
                return old
        previous = SourceAdmission.model_validate_json(rows[-1][1]) if rows else None
        if p.revision != len(rows) + 1 or p.supersedes_memory_id != (
            previous.result.memory_id if previous else None
        ):
            raise ValueError("G100_STALE_REVISION")
        # An immutable intent enables recovery after Memory succeeds but journal fails.
        intents = journal.entries("g100-write-intents")
        intent = next((body for key, body in intents if key == record.sha256), None)
        if intent is None:
            payload = MemoryWriteRequest(
                memory_level=(
                    MemoryLevel.L3
                    if p.kind == "RESEARCH_HYPOTHESIS"
                    else MemoryLevel.L2
                ),
                namespace_key=p.scope.scope_id,
                effective_ts=now,
                summary_text=record.model_dump_json(),
                asset_id=AssetId(p.subject),
                memory_type="g100_source_observation_not_claim",
                created_by=p.owner,
                source_ref_json=p.source_ref,
                metadata=LearningMemoryMetadata(
                    memory_version="g100_source_observation_v1",
                    usage_class=LearningMemoryUsageClass.EPISODIC,
                    scope_type=p.scope.scope_type,
                    scope_id=p.scope.scope_id,
                    parent_scope_id="ASSET:" + p.subject,
                    episode_id=p.episode_id,
                    research_state_id=p.research_state_id,
                    source_claim_ids=(),
                    source_event_ids=(record.sha256,),
                    content_kind=EpisodicMemoryContentKind.IMPORTANT_EVENT,
                    temporal=TemporalMetadata(
                        source_kind=TemporalSourceKind.MEMORY,
                        available_at=now,
                        ingested_at=now,
                        effective_from=now,
                        effective_to=record.review_due_at,
                    ),
                ),
            )
            journal.append(
                "g100-write-intents",
                record.sha256,
                payload.model_dump_json(),
                len(intents),
            )
        else:
            payload = MemoryWriteRequest.model_validate_json(intent)
        result = _write_or_recover(service, payload)
        receipt = SourceAdmission(
            record=record,
            payload=payload,
            result=result,
            persisted_at=service._clock(),
            source_assertion_admitted=record.fact_authority
            == "SOURCE_ATTRIBUTED_STATEMENT",
        )
        journal.append(stream, record.sha256, receipt.model_dump_json(), len(rows))
        # Separate catalog prevents new records from masquerading as G85 admissions.
        journal.append(
            "g100-source-catalog",
            record.sha256,
            receipt.model_dump_json(),
            len(journal.entries("g100-source-catalog")),
        )
        return receipt


def retrieve_observations(
    service: MemoryService,
    *,
    resolver: NativeLocatorResolver,
    access: MemoryAccessContext,
    journal: MemoryJournalRepository,
    request: ResearchContextRequest,
    episode: ResearchEpisode,
    run_id: str,
    as_created: datetime,
    lane: Literal["ATTRIBUTED_SOURCES", "ISOLATED_LEADS"],
) -> HybridRead:
    """Retrieve existing persisted Memory; filter source authority before supplying."""
    _same_store(service, journal)
    receiving = Scope(
        scope_type=ResearchScopeType.RESEARCH_EPISODE,
        scope_id="EPISODE:" + episode.episode_id,
    )
    access.require("READ_HISTORY", receiving)
    if episode.research_as_of != request.as_of or episode.created_at > as_created:
        raise ValueError("G100_RECEIVING_EPISODE_CLOCK")
    if as_created < request.as_of or service._clock() < as_created:
        raise ValueError("G100_RETRIEVAL_CLOCK")
    for namespace in request.namespace_keys:
        scope = next((s for s in access.scopes if s.scope_id == namespace), None)
        if scope is None:
            raise ValueError("G100_SCOPE_DENIED")
        access.require("READ_HISTORY", scope)
    raw = service.retrieve_context(request)
    catalog = [
        SourceAdmission.model_validate_json(body)
        for _, body in journal.entries("g100-source-catalog")
    ]
    receipts = {r.result.memory_id: r for r in catalog}
    superseded = {
        r.record.proposal.supersedes_memory_id
        for r in catalog
        if r.persisted_at <= request.as_of
    }
    selected = []
    excluded = []
    retrieved = []
    updates = {}
    for section in ResearchContextSection:
        keep = []
        for item in raw.items_for_section(section):
            retrieved.append(item.memory_id)
            r = receipts.get(item.memory_id)
            eligible = r is not None
            if r is not None:
                try:
                    # No reviewer fixture can be replayed as live semantic authority.
                    checked = resolver.validate(r.record.proposal)
                    eligible = (
                        r.persisted_at <= request.as_of < r.record.review_due_at
                        and item.asset_id == episode.asset_id
                        and item.memory_id not in superseded
                        and item.summary_text == r.payload.summary_text
                        and item.metadata == r.payload.metadata
                        and item.source == r.payload.source_ref_json
                        and checked.source_receipt_identity
                        == r.record.source_receipt_identity
                    )
                    eligible = eligible and r.source_assertion_admitted == (
                        checked.fact_authority == "SOURCE_ATTRIBUTED_STATEMENT"
                    )
                    if lane == "ATTRIBUTED_SOURCES":
                        eligible = eligible and r.source_assertion_admitted
                    else:
                        eligible = eligible and not r.source_assertion_admitted
                except (ValueError, KeyError, OSError):
                    eligible = False
            if eligible:
                assert r is not None
                selected.append(r)
                keep.append(item)
            else:
                excluded.append(item.memory_id)
        updates[section.value] = keep
    meta = raw.retrieval_metadata.model_copy(
        update={
            "result_count": len(selected),
            "empty_valid": not selected,
            "section_counts": {
                s: len(updates[s.value]) for s in ResearchContextSection
            },
            "status": RetrievalStatus.PARTIAL if selected else RetrievalStatus.EMPTY,
            "no_relevant_memory": not selected,
        }
    )
    missing = [
        MissingContext(
            section=section,
            reason=MissingContextReason.NO_RELEVANT_MEMORY,
            detail="No eligible G100 authority in this section/lane",
            requested_levels=request.memory_levels,
        )
        for section in ResearchContextSection
        if not updates[section.value]
    ]
    bundle = ResearchContextBundle.model_validate(
        {
            **raw.model_dump(),
            **updates,
            "missing_context": missing,
            "retrieval_metadata": meta,
        }
    )
    bref = ArtifactRef(
        artifact_id="g100-bundle:" + content_sha256(bundle),
        sha256_digest=content_sha256(bundle),
        version=bundle.schema_version,
        owner=access.owner,
        available_at=as_created,
        observed_at=as_created,
        ingested_at=as_created,
    )
    refs = {}
    for section in ResearchContextSection:
        for item in bundle.items_for_section(section):
            assert item.metadata is not None and item.available_at is not None
            refs[item.memory_id] = ArtifactRef(
                artifact_id=item.memory_id,
                sha256_digest=content_sha256(item),
                version="g100_source_observation_v1",
                owner=item.created_by,
                available_at=item.available_at,
                observed_at=item.available_at,
                ingested_at=item.metadata.temporal.ingested_at or item.available_at,
            )
    reads = read_set_from_bundle(
        bundle,
        bundle_ref=bref,
        memory_refs=refs,
        access=access,
        scope=receiving,
        agent_run_id=run_id,
        record_id=run_id + ":" + lane,
        created_at=as_created,
    )
    result = HybridRead(
        episode_id=episode.episode_id,
        bundle=bundle,
        read_set=reads,
        retrieved_ids=tuple(retrieved),
        supplied_records=tuple(selected),
        excluded_ids=tuple(excluded),
    )
    with journal.serialized():
        journal.append(
            "g100-deliveries",
            result.sha256,
            result.model_dump_json(),
            len(journal.entries("g100-deliveries")),
        )
    return result


def consume_observation(
    delivery: HybridRead,
    *,
    memory_id: str,
    model_text: str,
    use: Literal["ATTRIBUTED_SOURCE", "LEAD", "WORLD_FACT"],
    access: MemoryAccessContext,
    journal: MemoryJournalRepository,
    at: datetime,
    resolver: NativeLocatorResolver,
) -> dict[str, str | bool]:
    """Record citations without rewriting output or granting world-fact rights."""
    access.require("READ_HISTORY", delivery.read_set.scope)
    if (
        access.owner != delivery.read_set.owner
        or access.role != delivery.read_set.agent_role
        or (delivery.sha256, delivery.model_dump_json())
        not in journal.entries("g100-deliveries")
    ):
        raise ValueError("G100_UNDELIVERED_MEMORY")
    receipt = next(
        (r for r in delivery.supplied_records if r.result.memory_id == memory_id), None
    )
    if (
        receipt is None
        or at < delivery.read_set.created_at
        or at >= receipt.record.review_due_at
    ):
        raise ValueError("G100_UNSUPPLIED_OR_EXPIRED")
    checked = resolver.validate(receipt.record.proposal)
    if receipt.source_assertion_admitted != (
        checked.fact_authority == "SOURCE_ATTRIBUTED_STATEMENT"
    ):
        raise ValueError("G100_AUTHORITY_CHANGED")
    for _, body in journal.entries("g100-source-catalog"):
        newer = SourceAdmission.model_validate_json(body)
        if (
            newer.persisted_at <= at
            and newer.record.proposal.supersedes_memory_id == memory_id
        ):
            raise ValueError("G100_SUPERSEDED_BEFORE_CONSUMPTION")
    if use == "WORLD_FACT":
        raise ValueError("G100_STRICT_STRUCTURED_VALIDATION_REQUIRED")
    cited = "[memory:" + memory_id + "]" in model_text
    expected = (
        receipt.record.publisher
        + " stated: "
        + receipt.record.proposal.statement
        + " [memory:"
        + memory_id
        + "]"
    )
    valid = (
        cited
        and use == "ATTRIBUTED_SOURCE"
        and receipt.source_assertion_admitted
        and model_text == expected
    )
    row: dict[str, str | bool] = {
        "memory_id": memory_id,
        "retrieved": True,
        "supplied": True,
        "cited": cited,
        "validly_consumed": valid,
        "world_fact_authority": False,
        "use": use,
        "original_model_text": model_text,
    }
    from src.schemas.research_v2_shared import canonical, digest

    with journal.serialized():
        journal.append(
            "g100-consumption",
            digest(row),
            canonical(row).decode(),
            len(journal.entries("g100-consumption")),
        )
    return row
