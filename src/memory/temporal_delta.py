"""G111 development temporal diff over the existing Memory journal and G100 lane."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from src.memory.vnext_contracts import Frozen
from src.repositories.locking import duckdb_file_lock
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_shared import Clock, digest


class TemporalSource(Frozen):
    """Retained identity; local observation never proves remote immutability."""

    schema_version: Literal["g111_temporal_source_v1"] = "g111_temporal_source_v1"
    availability_basis: Literal["CONSERVATIVE_LOCAL_OBSERVATION_NOT_PUBLICATION"] = (
        "CONSERVATIVE_LOCAL_OBSERVATION_NOT_PUBLICATION"
    )
    source_id: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject: str
    scope_ids: tuple[str, ...]
    event_at: Clock | None
    available_at: Clock | None
    observed_at: Clock | None
    ingested_at: Clock | None
    origin: Literal["REAL_RETAINED_SOURCE", "SYNTHETIC_ENGINEERING_FIXTURE"]


class ObservedContent(Frozen):
    """Source-bound identity assigned by a versioned extractor, not prose similarity."""

    subject: str
    concept: str
    period: str
    unit: str
    basis: str
    value_literal: str
    locator: str
    quote: str
    source_id: str
    raw_sha256: str
    event_at: Clock | None
    period_end: date | None = None

    @property
    def semantic_id(self) -> str:
        """Keep issuer, period, unit and basis in the stable proposition identity."""
        return digest((self.subject, self.concept, self.period, self.unit, self.basis))

    @property
    def content_id(self) -> str:
        """Different reported values remain immutable versions of one proposition."""
        return digest((self.semantic_id, self.value_literal))


class TemporalRelation(Frozen):
    """Directed evidence relationship; never correlation promoted to causation."""

    relation_type: Literal[
        "CORROBORATES",
        "PERIOD_SUCCESSOR",
        "HISTORICAL_CONTEXT",
        "CHALLENGES",
        "SUPERSEDES",
    ]
    from_content: str
    to_content: str
    at: Clock
    source_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    status: Literal["SOURCE_SUPPORTED_RELATION", "HYPOTHESIZED_RELATION"]
    uncertainty: str
    valid_from: Clock
    valid_until: Clock | None = None


class ContentNode(Frozen):
    """A source observation in development Memory, not an accepted world fact."""

    content: ObservedContent
    memory_id: str
    created_at: Clock
    scientific_admitted: Literal[False] = False


class TemporalDelta(Frozen):
    """Actual source/read population and unknown clocks survive every delta."""

    schema_version: Literal["g111_temporal_delta_v1"] = "g111_temporal_delta_v1"
    kind: Literal[
        "UNCHANGED",
        "NEW_FACT",
        "FACT_UPDATE",
        "CORRECTION",
        "NEW_RELATION",
        "INVALIDATION",
        "HISTORICAL_BACKFILL",
    ]
    source: TemporalSource
    content_ids: tuple[str, ...]
    semantic_ids: tuple[str, ...]
    old_memory_ids: tuple[str, ...]
    memory_snapshot_id: str
    research_as_of: Clock
    memory_created_at: Clock
    source_readset: tuple[str, ...]
    memory_readset: tuple[str, ...]
    reason: str


class TemporalCycle(Frozen):
    """No paid-model or external-GET savings are inferred from a cache hit."""

    schema_version: Literal["g111_temporal_cycle_v1"] = "g111_temporal_cycle_v1"
    extractor_identity: str
    before_snapshot: str
    after_snapshot: str
    deltas: tuple[TemporalDelta, ...]
    relations: tuple[TemporalRelation, ...]
    nodes: tuple[ContentNode, ...]
    selected_memory_ids: tuple[str, ...]
    selected_content_ids: tuple[str, ...]
    duplicate_research_skipped: bool
    extractor_calls: int
    admission_calls: int
    remote_unchanged_verified: Literal[False] = False


def visible(source: TemporalSource, as_of: datetime) -> bool:
    """Unknown acquisition or availability cannot pass historical eligibility."""
    clocks = (source.available_at, source.observed_at, source.ingested_at)
    return all(c is not None and c <= as_of for c in clocks)


def run_temporal_cycle(
    journal: MemoryJournalRepository,
    source: TemporalSource,
    *,
    raw: bytes,
    as_of: datetime,
    created_at: datetime,
    extract: Callable[[], tuple[ObservedContent, ...]],
    admit: Callable[[ObservedContent], str],
    extractor_identity: str = "g111-semantic-extractor-v1",
) -> TemporalCycle:
    """Serialize the whole development cycle without altering existing State CAS.

    This trusted composition interface is not an Agent permission surface.
    The admission callback must use the original checked Memory service.
    """
    with duckdb_file_lock(journal.database_path.with_suffix(".g111-cycle")):
        return _run_temporal_cycle(
            journal,
            source,
            raw=raw,
            as_of=as_of,
            created_at=created_at,
            extract=extract,
            admit=admit,
            extractor_identity=extractor_identity,
        )


def _run_temporal_cycle(
    journal: MemoryJournalRepository,
    source: TemporalSource,
    *,
    raw: bytes,
    as_of: datetime,
    created_at: datetime,
    extract: Callable[[], tuple[ObservedContent, ...]],
    admit: Callable[[ObservedContent], str],
    extractor_identity: str = "g111-semantic-extractor-v1",
) -> TemporalCycle:
    """Skip extraction/embedding/admission before work; append immutable provenance.

    Run in the serialized composition worker used by the existing Memory service.
    Exact G100 admission remains idempotent across interrupted journal writes.
    The extractor's bounded scope must be disclosed; this is not an NLP oracle.
    """
    import hashlib

    source = TemporalSource.model_validate_json(source.model_dump_json())
    if hashlib.sha256(raw).hexdigest() != source.raw_sha256:
        raise ValueError("G111_SOURCE_BYTES_MISMATCH")
    if created_at < as_of or not visible(source, as_of):
        raise ValueError("G111_FUTURE_OR_UNKNOWN_SOURCE_TIME")
    if not extractor_identity.strip():
        raise ValueError("G111_EXTRACTOR_VERSION_REQUIRED")
    rows = journal.entries("g111-nodes")
    nodes = tuple(ContentNode.model_validate_json(body) for _, body in rows)
    if any(n.created_at > as_of for n in nodes) or any(
        d.memory_created_at > as_of
        for _, body in journal.entries("g111-cycles")
        for d in TemporalCycle.model_validate_json(body).deltas
    ):
        raise ValueError("G111_FUTURE_MEMORY_SNAPSHOT")
    before = memory_snapshot(journal)
    source_key = digest((source.subject, source.raw_sha256, extractor_identity))
    archived = journal.entries("g111-sources")
    duplicate = any(k == source_key for k, _ in archived)
    deltas: list[TemporalDelta] = []
    relations: list[TemporalRelation] = []
    new_nodes: list[ContentNode] = []
    selected: set[str] = set()

    def delta(
        kind: str, ids: tuple[str, ...], old: tuple[str, ...], reason: str
    ) -> None:
        deltas.append(
            TemporalDelta.model_validate(
                dict(
                    kind=kind,
                    source=source,
                    content_ids=ids,
                    semantic_ids=tuple(
                        sorted(
                            {
                                n.content.semantic_id
                                for n in (*nodes, *new_nodes)
                                if n.content.content_id in ids
                            }
                        )
                    ),
                    old_memory_ids=old,
                    memory_snapshot_id=before,
                    research_as_of=as_of,
                    memory_created_at=created_at,
                    source_readset=(source.source_id + ":" + source.raw_sha256,),
                    memory_readset=old,
                    reason=reason,
                )
            )
        )

    if duplicate:
        mapping = next(
            json.loads(body)
            for key, body in journal.entries("g111-source-contents")
            if key == source_key
        )
        prior = [n for n in nodes if n.content.content_id in mapping["content_ids"]]
        delta(
            "UNCHANGED",
            tuple(n.content.content_id for n in prior),
            tuple(n.memory_id for n in prior),
            "IDENTICAL_RETAINED_BYTES_NOT_REMOTE_VERIFICATION",
        )
    else:
        contents = extract()
        if len({c.content_id for c in contents}) != len(contents):
            raise ValueError("G111_DUPLICATE_EXTRACTOR_IDENTITY")
        for c in contents:
            if (c.subject, c.source_id, c.raw_sha256) != (
                source.subject,
                source.source_id,
                source.raw_sha256,
            ):
                raise ValueError("G111_EXTRACTOR_SOURCE_BINDING")
            same = next(
                (n for n in nodes if n.content.content_id == c.content_id), None
            )
            if same:
                relations.append(
                    TemporalRelation(
                        relation_type=(
                            "SUPERSEDES"
                            if same.content.source_id == c.source_id
                            else "CORROBORATES"
                        ),
                        from_content=c.content_id,
                        to_content=same.content.content_id,
                        at=created_at,
                        source_ids=(c.source_id, same.content.source_id),
                        evidence_locators=(c.locator, same.content.locator),
                        status="SOURCE_SUPPORTED_RELATION",
                        uncertainty="URL does not prove independent publisher",
                        valid_from=created_at,
                    )
                )
                delta(
                    "NEW_RELATION",
                    (c.content_id,),
                    (same.memory_id,),
                    (
                        "SOURCE_VERSION_ATTESTS_SAME_PROPOSITION"
                        if same.content.source_id == c.source_id
                        else "ADDITIONAL_SOURCE_ATTRIBUTION_NO_DUPLICATE_FACT_NODE"
                    ),
                )
                selected.add(same.memory_id)
                continue
            previous = [
                n
                for n in nodes
                if n.content.subject == c.subject
                and n.content.concept == c.concept
                and n.content.unit == c.unit
                and n.content.basis == c.basis
            ]
            same_period = next(
                (n for n in previous if n.content.semantic_id == c.semantic_id), None
            )
            latest = max(
                previous,
                key=lambda n: n.content.period_end or date.min,
                default=None,
            )
            backfill = (
                latest is not None
                and c.period_end is not None
                and latest.content.period_end is not None
                and c.period_end < latest.content.period_end
            )
            kind = (
                "CORRECTION"
                if same_period
                else (
                    "HISTORICAL_BACKFILL"
                    if backfill
                    else "FACT_UPDATE" if previous else "NEW_FACT"
                )
            )
            parent = same_period or latest
            mid = admit(c)
            node = ContentNode(content=c, memory_id=mid, created_at=created_at)
            new_nodes.append(node)
            delta(
                kind,
                (c.content_id,),
                (parent.memory_id,) if parent else (),
                "SOURCE_ATTRIBUTED_OBSERVATION_NOT_SCIENTIFIC_FACT",
            )
            if parent:
                selected.add(parent.memory_id)
                relation_type: Literal[
                    "CHALLENGES", "HISTORICAL_CONTEXT", "PERIOD_SUCCESSOR"
                ] = (
                    "CHALLENGES"
                    if same_period
                    else "HISTORICAL_CONTEXT" if backfill else "PERIOD_SUCCESSOR"
                )
                relations.append(
                    TemporalRelation(
                        relation_type=relation_type,
                        from_content=c.content_id,
                        to_content=parent.content.content_id,
                        at=created_at,
                        source_ids=(c.source_id, parent.content.source_id),
                        evidence_locators=(c.locator, parent.content.locator),
                        status=(
                            "HYPOTHESIZED_RELATION"
                            if same_period
                            else "SOURCE_SUPPORTED_RELATION"
                        ),
                        uncertainty=(
                            "Conflicting values: review required"
                            if same_period
                            else "Period ordering only; no causal claim"
                        ),
                        valid_from=created_at,
                    )
                )
        with journal.serialized():
            for n in new_nodes:
                journal.append(
                    "g111-nodes",
                    n.content.content_id,
                    n.model_dump_json(),
                    len(journal.entries("g111-nodes")),
                )
            for r in relations:
                journal.append(
                    "g111-relations",
                    r.sha256,
                    r.model_dump_json(),
                    len(journal.entries("g111-relations")),
                )
            journal.append(
                "g111-source-contents",
                source_key,
                json.dumps(
                    {"content_ids": [c.content_id for c in contents]}, sort_keys=True
                ),
                len(journal.entries("g111-source-contents")),
            )
            journal.append(
                "g111-sources", source_key, source.model_dump_json(), len(archived)
            )
    after = memory_snapshot(journal)
    result = TemporalCycle(
        extractor_identity=extractor_identity,
        before_snapshot=before,
        after_snapshot=after,
        deltas=tuple(deltas),
        relations=tuple(relations),
        nodes=tuple(new_nodes),
        selected_memory_ids=tuple(sorted(selected)),
        selected_content_ids=tuple(n.content.content_id for n in new_nodes),
        duplicate_research_skipped=duplicate,
        extractor_calls=0 if duplicate else 1,
        admission_calls=len(new_nodes),
    )
    with journal.serialized():
        journal.append(
            "g111-cycles",
            result.sha256,
            result.model_dump_json(),
            len(journal.entries("g111-cycles")),
        )
    return result


def selective_impact(cycle: TemporalCycle) -> tuple[dict[str, object], ...]:
    """Reuse G84 closure as development routing input; never dispatch an Agent."""
    from datetime import timedelta

    from src.memory.vnext import ImpactRule, plan_impact
    from src.memory.vnext_contracts import (
        ROLE_STAGES,
        ArtifactRef,
        MemoryDelta,
        ResearchMandate,
        Scope,
    )
    from src.models.enums import AgentName, MemoryLevel, ResearchScopeType

    results = []
    for d in cycle.deltas:
        s = d.source
        assert s.available_at and s.observed_at and s.ingested_at
        scope = Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:" + s.subject)
        source_ref = ArtifactRef(
            artifact_id=s.source_id,
            sha256_digest=s.raw_sha256,
            version="retained-native-bytes",
            owner=s.subject,
            available_at=s.available_at,
            observed_at=s.observed_at,
            ingested_at=s.ingested_at,
        )
        policy = ArtifactRef(
            artifact_id="g111-development-routing",
            sha256_digest=digest("fundamental_then_existing_G84_downstream"),
            version="1",
            owner="W6-development",
            available_at=d.research_as_of,
            observed_at=d.research_as_of,
            ingested_at=d.research_as_of,
        )
        delta = MemoryDelta(
            owner="g111",
            record_id=d.sha256,
            revision=1,
            created_at=d.memory_created_at,
            research_as_of=d.research_as_of,
            scope=scope,
            source_refs=(source_ref,),
            memory_level=MemoryLevel.L2,
            change_kind="FILING",
            before=None,
            after=source_ref,
            change_detector=policy,
            materiality_rule=policy,
            material=d.kind != "UNCHANGED",
        )
        mandate = ResearchMandate(
            owner="g111-explicit-offline-cli",
            record_id="development-selection:" + d.sha256,
            revision=1,
            created_at=d.research_as_of,
            research_as_of=d.research_as_of,
            scope=scope,
            source_refs=(source_ref, policy),
            opportunity=source_ref,
            authorization=policy,
            selection="HUMAN_SELECTION",
            allowed_scopes=(scope,),
            allowed_roles=tuple(r for stage in ROLE_STAGES for r in stage),
            expires_at=d.research_as_of + timedelta(hours=1),
        )
        plan = plan_impact(
            delta,
            mandate,
            policy=ImpactRule(
                owner="W6-development",
                scope=scope,
                change_kind="FILING",
                direct_roles=(AgentName.FUNDAMENTAL_ANALYST,),
                rationale="Development routing only; W3 owns policy and dispatch",
            ),
            enabled=True,
        )
        results.append(plan.model_dump(mode="json"))
    return tuple(results)


def invalidate_observation(
    journal: MemoryJournalRepository,
    content_id: str,
    source: TemporalSource,
    *,
    raw: bytes,
    as_of: datetime,
    reason: str,
) -> TemporalDelta:
    """Record an explicit development review invalidation; preserve old content."""
    import hashlib

    if (
        not reason.strip()
        or not visible(source, as_of)
        or hashlib.sha256(raw).hexdigest() != source.raw_sha256
    ):
        raise ValueError("G111_INVALIDATION_EVIDENCE")
    rows = journal.entries("g111-nodes")
    node = next(
        (ContentNode.model_validate_json(b) for k, b in rows if k == content_id), None
    )
    if node is None:
        raise ValueError("G111_UNKNOWN_INVALIDATION_ENDPOINT")
    d = TemporalDelta(
        kind="INVALIDATION",
        source=source,
        content_ids=(content_id,),
        semantic_ids=(node.content.semantic_id,),
        old_memory_ids=(node.memory_id,),
        memory_snapshot_id=memory_snapshot(journal),
        research_as_of=as_of,
        memory_created_at=as_of,
        source_readset=(source.source_id + ":" + source.raw_sha256,),
        memory_readset=(node.memory_id,),
        reason="DEVELOPMENT_REVIEW_REQUIRED:" + reason,
    )
    with journal.serialized():
        journal.append(
            "g111-invalidations",
            d.sha256,
            d.model_dump_json(),
            len(journal.entries("g111-invalidations")),
        )
    return d


def memory_snapshot(journal: MemoryJournalRepository) -> str:
    """Bind content, provenance, relation and invalidation populations together."""
    return digest(
        {
            name: journal.entries(name)
            for name in (
                "g111-nodes",
                "g111-sources",
                "g111-source-contents",
                "g111-relations",
                "g111-invalidations",
            )
        }
    )


def eligible_nodes(
    journal: MemoryJournalRepository, as_of: datetime
) -> tuple[ContentNode, ...]:
    """Reject future or explicitly invalidated development context at read time."""
    invalid = {
        cid
        for _, body in journal.entries("g111-invalidations")
        for d in (TemporalDelta.model_validate_json(body),)
        if d.research_as_of <= as_of
        for cid in d.content_ids
    }
    return tuple(
        n
        for _, body in journal.entries("g111-nodes")
        for n in (ContentNode.model_validate_json(body),)
        if n.created_at <= as_of and n.content.content_id not in invalid
    )
