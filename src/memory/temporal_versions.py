"""G113 versioned receipts over G111 Memory; no new store or factual authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from src.memory.hybrid import HybridRead
from src.memory.temporal_delta import (
    ContentNode,
    TemporalCycle,
    TemporalSource,
    visible,
)
from src.memory.temporal_relations import BoundMemoryRelation, require_delivered
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Frozen, Scope
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_shared import Clock, digest

Kind = Literal[
    "NEW_OBSERVATION",
    "ADDITIONAL_EVIDENCE",
    "FACT_UPDATE",
    "RELATION_UPDATE",
    "HISTORICAL_BACKFILL",
    "UNCHANGED",
    "SUPERSEDED",
    "RETRACTED",
]
STREAM = "g113-version-events"


class VersionEvent(Frozen):
    """Evidence-bound development validity, with separate knowledge/effective time."""

    schema_version: Literal["g113_version_event_v1"] = "g113_version_event_v1"
    command_id: str = Field(min_length=1)
    target_type: Literal["MEMORY", "RELATION"]
    target_id: str = Field(min_length=1)
    action: Literal["SUPERSEDED", "RETRACTED", "ADDITIONAL_EVIDENCE"]
    successor_memory_id: str | None = None
    source: TemporalSource
    source_published_at: Clock | None = None
    source_locator: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    effective_at: Clock | None = None
    recorded_at: Clock
    research_as_of: Clock
    uncertainty: str = Field(min_length=1)
    authority: Literal["DEVELOPMENT_SOURCE_CONTEXT_ONLY"] = (
        "DEVELOPMENT_SOURCE_CONTEXT_ONLY"
    )


def authorized_delivery(
    journal: MemoryJournalRepository,
    delivery: HybridRead,
    access: MemoryAccessContext,
) -> set[str]:
    """Recheck original record scopes after retrieval, not just receiving Episode."""
    allowed = require_delivered(delivery, journal, access)
    for receipt in delivery.supplied_records:
        access.require("READ_HISTORY", receipt.record.proposal.scope)
    return allowed


def version_snapshot(journal: MemoryJournalRepository) -> str:
    """Bind ordered source, support, validity and relation revisions, not summaries."""
    return digest(
        {
            s: journal.entries_with_sequence(s)
            for s in (
                "g111-nodes",
                "g111-sources",
                "g111-source-contents",
                "g111-relations",
                "g111-invalidations",
                "g111-r1-support",
                "g111-r1-relations",
                STREAM,
            )
        }
    )


def version_status(
    journal: MemoryJournalRepository,
    target_id: str,
    *,
    knowledge_as_of: datetime,
    valid_at: datetime | None = None,
) -> str:
    """Never let a later correction change what was known at an old cutoff."""
    valid_at = valid_at or knowledge_as_of
    status = "ACTIVE"
    for _, body in journal.entries(STREAM):
        e = VersionEvent.model_validate_json(body)
        if (
            e.target_id == target_id
            and e.recorded_at <= knowledge_as_of
            and (e.effective_at or e.recorded_at) <= valid_at
            and e.action != "ADDITIONAL_EVIDENCE"
        ):
            status = e.action
    return status


def append_version_event(
    journal: MemoryJournalRepository,
    event: VersionEvent,
    *,
    raw: bytes,
    delivery: HybridRead,
    access: MemoryAccessContext,
    expected_snapshot: str,
    validate_revision_support: Callable[[VersionEvent], None],
) -> VersionEvent:
    """Require trusted semantic/source validation and actual delivered endpoints.

    The callback must establish that the exact retained statement supports the
    requested lifecycle action. A matching SHA or quote alone is insufficient.
    """
    event = VersionEvent.model_validate_json(event.model_dump_json())
    access.require("APPEND_EVENT", delivery.read_set.scope)
    allowed = authorized_delivery(journal, delivery, access)
    if (
        event.recorded_at < event.research_as_of
        or delivery.read_set.research_as_of != event.research_as_of
        or delivery.read_set.created_at > event.recorded_at
        or not visible(event.source, event.research_as_of)
        or hashlib.sha256(raw).hexdigest() != event.source.raw_sha256
        or (
            event.source_published_at is not None
            and event.source_published_at > event.research_as_of
        )
    ):
        raise ValueError("G113_SOURCE_OR_DELIVERY_CLOCK")
    nodes = {
        n.memory_id: n
        for _, b in journal.entries("g111-nodes")
        for n in (ContentNode.model_validate_json(b),)
    }
    relations = {
        r.relation_id: r
        for _, b in journal.entries("g111-r1-relations")
        for r in (BoundMemoryRelation.model_validate_json(b),)
    }
    if event.target_type == "MEMORY":
        endpoints = {event.target_id}
    else:
        r = relations.get(event.target_id)
        if r is None or r.created_at > event.research_as_of:
            raise ValueError("G113_UNKNOWN_RELATION")
        endpoints = {r.from_memory_id, r.to_memory_id}
    if event.successor_memory_id:
        if event.action != "SUPERSEDED" or event.target_type != "MEMORY":
            raise ValueError("G113_UNEXPECTED_SUCCESSOR")
        endpoints.add(event.successor_memory_id)
    elif event.action == "SUPERSEDED":
        raise ValueError("G113_SUCCESSOR_REQUIRED")
    if not endpoints <= allowed or not endpoints <= nodes.keys():
        raise ValueError("G113_ENDPOINT_NOT_DELIVERED")
    if any(nodes[i].content.subject != event.source.subject for i in endpoints):
        raise ValueError("G113_UNSUPPORTED_CROSS_ISSUER_REVISION")
    if event.successor_memory_id and (
        event.target_id == event.successor_memory_id
        or nodes[event.target_id].content.semantic_id
        != nodes[event.successor_memory_id].content.semantic_id
    ):
        raise ValueError("G113_SUCCESSOR_SEMANTIC_IDENTITY")
    validate_revision_support(event)
    with journal.serialized():
        previous = journal.entries(STREAM)
        for key, body in previous:
            if key == event.command_id:
                old = VersionEvent.model_validate_json(body)
                if old != event:
                    raise ValueError("G113_COMMAND_CONFLICT")
                return old
        if version_snapshot(journal) != expected_snapshot:
            raise ValueError("G113_STALE_SNAPSHOT")
        if any(
            version_status(journal, i, knowledge_as_of=event.research_as_of) != "ACTIVE"
            for i in {*endpoints, event.target_id}
        ):
            raise ValueError("G113_ENDPOINT_INACTIVE")
        journal.append(
            STREAM,
            event.command_id,
            event.model_dump_json(),
            len(previous),
            expected_entries=previous,
        )
    return event


def qualified_delivery(
    journal: MemoryJournalRepository,
    delivery: HybridRead,
    access: MemoryAccessContext,
    *,
    valid_at: datetime | None = None,
) -> dict[str, Any]:
    """Filter actual G100 retrieval by G111 eligibility and G113 validity before use."""
    allowed = authorized_delivery(journal, delivery, access)
    at = delivery.read_set.research_as_of
    accepted, rejected = [], []
    for ref in delivery.read_set.memory_refs:
        status = version_status(
            journal, ref.artifact_id, knowledge_as_of=at, valid_at=valid_at
        )
        reason = "NOT_G111_ELIGIBLE" if ref.artifact_id not in allowed else status
        if reason == "ACTIVE":
            accepted.append(ref.model_dump(mode="json"))
        else:
            rejected.append({"memory_id": ref.artifact_id, "reason": reason})
    row = dict(
        schema_version="g113_qualified_readset_v1",
        upstream_g84_readset=delivery.read_set.model_dump(mode="json"),
        upstream_delivery_sha256=delivery.sha256,
        version_snapshot_id=version_snapshot(journal),
        research_as_of=at.isoformat(),
        valid_at=(valid_at or at).isoformat(),
        accepted=accepted,
        rejected=rejected,
        provided_memory_ids=[],
        actually_consumed_memory_ids=[],
        consumer_role=access.role,
        consumer_owner=access.owner,
    )
    with journal.serialized():
        journal.append(
            "g113-readsets",
            digest(row),
            json.dumps(row, sort_keys=True),
            len(journal.entries("g113-readsets")),
        )
    return row


def qualified_relations(
    journal: MemoryJournalRepository,
    readset: dict[str, Any],
    *,
    access: MemoryAccessContext,
    validate_revision_support: Callable[[VersionEvent], None],
    validate_support: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    """Resolve edges only through a persisted qualified readset and valid endpoints."""
    if (digest(readset), json.dumps(readset, sort_keys=True)) not in journal.entries(
        "g113-readsets"
    ):
        raise ValueError("G113_UNRECORDED_READSET")
    access.require(
        "READ_HISTORY", Scope.model_validate(readset["upstream_g84_readset"]["scope"])
    )
    if (
        access.owner != readset["consumer_owner"]
        or access.role != readset["consumer_role"]
    ):
        raise ValueError("G113_READSET_OWNER")
    deliveries = dict(journal.entries("g100-deliveries"))
    original = HybridRead.model_validate_json(
        deliveries[readset["upstream_delivery_sha256"]]
    )
    authorized_delivery(journal, original, access)
    at = datetime.fromisoformat(readset["research_as_of"])
    valid_at = datetime.fromisoformat(readset["valid_at"])
    allowed = {r["artifact_id"] for r in readset["accepted"]}
    result = []
    for _, body in journal.entries("g111-r1-relations"):
        r = BoundMemoryRelation.model_validate_json(body)
        if (
            r.created_at > at
            or not {r.from_memory_id, r.to_memory_id} <= allowed
            or version_status(
                journal, r.relation_id, knowledge_as_of=at, valid_at=valid_at
            )
            != "ACTIVE"
        ):
            continue
        for e in r.source_support:
            validate_support(e)
        supplements = [
            e.model_dump(mode="json")
            for _, b in journal.entries(STREAM)
            for e in (VersionEvent.model_validate_json(b),)
            if e.target_id == r.relation_id
            and e.action == "ADDITIONAL_EVIDENCE"
            and e.recorded_at <= at
            and (e.effective_at or e.recorded_at) <= valid_at
        ]
        for supplement in supplements:
            validate_revision_support(VersionEvent.model_validate(supplement))
        result.append({**r.model_dump(mode="json"), "additional_support": supplements})
    return result


def classify_cycle(cycle: TemporalCycle) -> list[dict[str, Any]]:
    """Keep a conflicting value distinct from an established correction."""
    names: dict[str, Kind] = {
        "NEW_FACT": "NEW_OBSERVATION",
        "NEW_RELATION": "ADDITIONAL_EVIDENCE",
        "CORRECTION": "FACT_UPDATE",
        "INVALIDATION": "FACT_UPDATE",
        "FACT_UPDATE": "FACT_UPDATE",
        "HISTORICAL_BACKFILL": "HISTORICAL_BACKFILL",
        "UNCHANGED": "UNCHANGED",
    }
    return [
        dict(
            schema_version="g113_content_delta_v1",
            kind=names[d.kind],
            prior_g111_kind=d.kind,
            requires_review=d.kind in ("CORRECTION", "INVALIDATION"),
            version_disposition=(
                "CONFLICT_REVIEW_REQUIRED"
                if d.kind in ("CORRECTION", "INVALIDATION")
                else "SOURCE_OBSERVATION_ONLY"
            ),
            content_ids=d.content_ids,
            semantic_ids=d.semantic_ids,
            old_memory_ids=d.old_memory_ids,
            source=d.source.model_dump(mode="json"),
            source_published_at=None,
            research_as_of=d.research_as_of.isoformat(),
            memory_created_at=d.memory_created_at.isoformat(),
            source_readset=d.source_readset,
            memory_readset=d.memory_readset,
            memory_snapshot_id=d.memory_snapshot_id,
            business_event_at=(
                d.source.event_at.isoformat() if d.source.event_at else None
            ),
            operating_periods=[
                n.content.period
                for n in cycle.nodes
                if n.content.content_id in d.content_ids
            ],
            new_memory_ids=[
                n.memory_id
                for n in cycle.nodes
                if n.content.content_id in d.content_ids
            ],
            version_effective_at=None,
            reason=d.reason,
            remote_unchanged_verified=False,
        )
        for d in cycle.deltas
    ]
