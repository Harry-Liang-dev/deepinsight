"""G111-R1 source-context edges in the existing journal; no fact authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from src.memory.hybrid import HybridRead
from src.memory.temporal_delta import eligible_nodes
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Frozen
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_shared import Clock, digest


class BoundMemoryRelation(Frozen):
    """Real persisted endpoints with source support and original effective precision."""

    schema_version: Literal["g111_r1_bound_relation_v1"] = "g111_r1_bound_relation_v1"
    relation_id: str
    from_memory_id: str
    to_memory_id: str
    relation_type: Literal["SAME_ISSUER_REPORTING_CONTEXT", "ADDITIONAL_SOURCE_SUPPORT"]
    source_support: tuple[dict[str, Any], ...]
    effective_time: dict[str, Any]
    research_as_of: Clock
    created_at: Clock
    uncertainty: str
    status: Literal["SOURCE_SUPPORTED_CONTEXT_NOT_WORLD_FACT"] = (
        "SOURCE_SUPPORTED_CONTEXT_NOT_WORLD_FACT"
    )
    world_fact_authority: Literal[False] = False
    scope: Literal["ASSET:US:MSFT"] = "ASSET:US:MSFT"


def require_delivered(
    delivery: HybridRead, journal: MemoryJournalRepository, access: MemoryAccessContext
) -> set[str]:
    """Require actual G100 delivery and current permission, not arbitrary IDs."""
    access.require("READ_HISTORY", delivery.read_set.scope)
    if (delivery.sha256, delivery.model_dump_json()) not in journal.entries(
        "g100-deliveries"
    ):
        raise ValueError("G111_R1_UNRECORDED_DELIVERY")
    if (
        delivery.read_set.owner != access.owner
        or delivery.read_set.agent_role != access.role
    ):
        raise ValueError("G111_R1_DELIVERY_OWNER")
    eligible = {
        n.memory_id for n in eligible_nodes(journal, delivery.read_set.research_as_of)
    }
    return {r.artifact_id for r in delivery.read_set.memory_refs} & eligible


def bind_relation(
    journal: MemoryJournalRepository,
    proposal: dict[str, Any],
    *,
    facts: dict[str, dict[str, Any]],
    seeds: dict[str, dict[str, Any]],
    actual_ids: dict[str, str],
    delivery: HybridRead,
    access: MemoryAccessContext,
    validate_support: Callable[[dict[str, Any]], None],
    at: datetime,
) -> BoundMemoryRelation:
    """Check frozen semantic support and both real endpoints before appending."""
    allowed = require_delivered(delivery, journal, access)
    allowed &= {n.memory_id for n in eligible_nodes(journal, at)}
    access.require("APPEND_EVENT", delivery.read_set.scope)
    f = facts[proposal["NewFactID"]]
    h = seeds[proposal["RelatedHistoricalMemoryID"]]
    kind = proposal["RelationType"]
    if (
        f["issuer"] != "US:MSFT"
        or h["issuer"] != f["issuer"]
        or proposal["cross_asset"]
        or proposal["world_fact_authority"]
        or not proposal["Uncertainty"]
    ):
        raise ValueError("G111_R1_RELATION_SCOPE_AUTHORITY")
    evidence = proposal["EvidenceSupport"]
    supplied = {digest(e) for e in (*f["evidence"], *h["evidence"])}
    if not evidence or any(digest(e) not in supplied for e in evidence):
        raise ValueError("G111_R1_UNBOUND_SUPPORT")
    if kind == "SAME_ISSUER_REPORTING_CONTEXT":
        bound = {digest(e) for e in evidence}
        if (
            h["series"] != "MSFT:REPORTING_REGIME"
            or not bound.intersection(digest(e) for e in f["evidence"])
            or not bound.intersection(digest(e) for e in h["evidence"])
        ):
            raise ValueError("G111_R1_BOTH_ENDPOINTS_REQUIRED")
    elif kind != "ADDITIONAL_SOURCE_SUPPORT" or f["id"] != h["fact_id"]:
        raise ValueError("G111_R1_UNSUPPORTED_RELATION")
    for e in evidence:
        validate_support(e)
    start, end = actual_ids[f["id"]], actual_ids[h["fact_id"]]
    if not {start, end} <= allowed or at < delivery.read_set.created_at:
        raise ValueError("G111_R1_ENDPOINT_NOT_CURRENTLY_ELIGIBLE")
    identity = digest((start, end, kind, evidence, proposal["EffectiveTime"]))
    relation = BoundMemoryRelation(
        relation_id=identity,
        from_memory_id=start,
        to_memory_id=end,
        relation_type=kind,
        source_support=tuple(evidence),
        effective_time=proposal["EffectiveTime"],
        research_as_of=at,
        created_at=at,
        uncertainty=proposal["Uncertainty"]
        + (
            " Source12 corroborates Azure membership only;"
            " no independent-publisher or causal claim."
        ),
    )
    with journal.serialized():
        for key, body in journal.entries("g111-r1-relations"):
            if key == identity:
                return BoundMemoryRelation.model_validate_json(body)
        journal.append(
            "g111-r1-relations",
            identity,
            relation.model_dump_json(),
            len(journal.entries("g111-r1-relations")),
        )
    return relation


def read_relations(
    journal: MemoryJournalRepository,
    delivery: HybridRead,
    access: MemoryAccessContext,
    validate_support: Callable[[dict[str, Any]], None],
) -> tuple[BoundMemoryRelation, ...]:
    """Return only currently delivered endpoints and revalidated source edges."""
    allowed = require_delivered(delivery, journal, access)
    result = []
    for _, body in journal.entries("g111-r1-relations"):
        relation = BoundMemoryRelation.model_validate_json(body)
        if (
            relation.created_at > delivery.read_set.research_as_of
            or not {relation.from_memory_id, relation.to_memory_id} <= allowed
        ):
            continue
        for evidence in relation.source_support:
            validate_support(evidence)
        result.append(relation)
    return tuple(result)
