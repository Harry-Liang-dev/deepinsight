"""G85 retained-source adapters; W3 owns materiality and Agent scheduling."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from src.memory.vnext_contracts import ArtifactRef, Frozen, MemoryDelta, Scope, Text
from src.models.enums import MemoryLevel
from src.schemas.research_v2_shared import Clock, Reference, Revision, digest


class SourceSnapshot(Frozen):
    """One provider-native identity after temporal normalization, never a summary."""

    schema_version: Literal["g85_source_snapshot_v1"] = "g85_source_snapshot_v1"
    source: ArtifactRef
    scope: Scope
    subject: Text
    fact_identity: Text
    memory_level: MemoryLevel
    change_kind: Literal["MARKET_SNAPSHOT", "EVENT", "FILING", "CORRECTION", "RESEARCH"]
    effective_at: Clock
    published_at: Clock
    expires_at: Clock | None = None
    status: Literal["ACTIVE", "INVALIDATED"] = "ACTIVE"
    evidence: tuple[Reference, ...] = Field(min_length=1)

    @property
    def key(self) -> str:
        """Keep providers and subjects distinct even when event IDs collide."""
        return digest(
            (self.source.owner, self.source.artifact_id, self.subject, self.scope)
        )


class MemoryChange(Frozen):
    """Missing sources retain their old identity without fabricating an after."""

    key: Text
    status: Literal[
        "NEW", "UPDATED", "REVISED", "UNCHANGED", "EXPIRED", "INVALIDATED", "MISSING"
    ]
    before: SourceSnapshot | None
    after: SourceSnapshot | None
    delta: MemoryDelta | None
    catalyst_identity: Text


class MemoryChangeSet(Frozen):
    """Complete checked population, including no-op and missing dependencies."""

    schema_version: Literal["g85_memory_changeset_v1"] = "g85_memory_changeset_v1"
    as_of: Clock
    created_at: Clock
    previous_population: str
    checked_population: tuple[SourceSnapshot, ...]
    changes: tuple[MemoryChange, ...]


def detect_changes(
    previous: tuple[SourceSnapshot, ...],
    current: tuple[SourceSnapshot, ...],
    *,
    as_of: datetime,
    created_at: datetime,
    resolve: Callable[[ArtifactRef], bytes],
    detector: ArtifactRef,
    policy: ArtifactRef,
    materiality: Callable[[SourceSnapshot | None, SourceSnapshot], bool],
) -> MemoryChangeSet:
    """Compare verified retained bytes/versions; no acquisition or LLM calls.

    The composition root supplies a frozen W3 policy and its implementation.
    Missing/expired/invalid sources block reuse even without a material delta.
    """
    as_of, created_at = ArtifactRef.utc(as_of), ArtifactRef.utc(created_at)
    if created_at < as_of:
        raise ValueError("CREATION_PRECEDES_CUTOFF")
    for ref in (detector, policy):
        ref.require_recorded_by(created_at)
        if hashlib.sha256(resolve(ref)).hexdigest() != ref.sha256_digest:
            raise ValueError("DETECTOR_POLICY_BYTES")
    previous = tuple(
        SourceSnapshot.model_validate_json(s.model_dump_json()) for s in previous
    )
    current = tuple(
        SourceSnapshot.model_validate_json(s.model_dump_json()) for s in current
    )
    populations = []
    for population in (previous, current):
        index = {s.key: s for s in population}
        if len(index) != len(population):
            raise ValueError("DUPLICATE_SOURCE_SUBJECT")
        for s in population:
            s.source.require_recorded_by(as_of)
            if s.published_at > as_of:
                raise ValueError("FUTURE_PUBLICATION")
            if hashlib.sha256(resolve(s.source)).hexdigest() != s.source.sha256_digest:
                raise ValueError("SOURCE_BYTES_MISMATCH")
        populations.append(index)
    old, new = populations
    changes = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        delta = None
        status: Literal[
            "NEW",
            "UPDATED",
            "REVISED",
            "UNCHANGED",
            "EXPIRED",
            "INVALIDATED",
            "MISSING",
        ]
        if after is None:
            status = "MISSING"
        elif after.status == "INVALIDATED":
            status = "INVALIDATED"
        elif after.expires_at is not None and after.expires_at <= as_of:
            status = "EXPIRED"
        elif before is None:
            status = "NEW"
        elif before == after or (
            before.source.owner == after.source.owner
            and before.source.version == after.source.version
            and before.source.sha256_digest == after.source.sha256_digest
            and before.model_dump(exclude={"source"})
            == after.model_dump(exclude={"source"})
        ):
            status = "UNCHANGED"
            # Keep the first acquisition identity; delta audits the new observation.
            new[key] = before
        elif before.source.sha256_digest == after.source.sha256_digest:
            # Version/clock changes still affect reuse, never imply materiality.
            status = "UPDATED"
        elif before.effective_at == after.effective_at:
            status = "REVISED"
        else:
            status = "UPDATED"
        if after is not None:
            same_bytes = (
                before is not None
                and before.source.sha256_digest == after.source.sha256_digest
            )
            refs = tuple(
                dict.fromkeys((*((before.source,) if before else ()), after.source))
            )
            delta = MemoryDelta(
                owner="g85_retained_detector",
                record_id="delta:" + digest((key, before, after, as_of)),
                revision=1,
                created_at=created_at,
                research_as_of=as_of,
                scope=after.scope,
                source_refs=refs,
                memory_level=after.memory_level,
                change_kind=after.change_kind,
                before=before.source if before else None,
                after=after.source,
                change_detector=detector,
                materiality_rule=policy,
                material=(
                    False
                    if same_bytes or status in ("EXPIRED", "INVALIDATED")
                    else materiality(before, after)
                ),
            )
        item = after or before
        assert item is not None
        changes.append(
            MemoryChange(
                key=key,
                status=status,
                before=before,
                after=after,
                delta=delta,
                catalyst_identity=digest((item.subject, item.fact_identity)),
            )
        )
    return MemoryChangeSet(
        as_of=as_of,
        created_at=created_at,
        previous_population=digest(previous),
        checked_population=tuple(new[k] for k in sorted(new)),
        changes=tuple(changes),
    )


class ResearchDependency(Frozen):
    """Exact existing artifact dependency, including sourced directed relations."""

    artifact: Reference
    scope: Scope
    source_keys: tuple[str, ...]
    upstream: tuple[Reference, ...]
    relationship_evidence: tuple[ArtifactRef, ...] = ()
    valid_from: Clock
    valid_until: Clock


class ImpactResolution(Frozen):
    """W3 input only: affected artifacts and mechanisms, never issuer returns."""

    changeset_sha256: str
    invalidated: tuple[Reference, ...]
    scopes: tuple[Scope, ...]
    relation_sources: tuple[ArtifactRef, ...]
    disposition: Literal["DEPENDENCY_REVIEW_ONLY"] = "DEPENDENCY_REVIEW_ONLY"


def resolve_impact(
    changes: MemoryChangeSet,
    dependencies: tuple[ResearchDependency, ...],
    resolve: Callable[[ArtifactRef], bytes],
) -> ImpactResolution:
    """Close actual dependency edges; unrelated stocks never enter the closure."""
    keys = {c.key for c in changes.changes if c.status != "UNCHANGED"}
    index = {d.artifact: d for d in dependencies}
    if len(index) != len(dependencies):
        raise ValueError("DUPLICATE_DEPENDENCY_ARTIFACT")
    selected: set[Reference] = set()
    relations: set[ArtifactRef] = set()
    active = []
    for d in dependencies:
        if not d.valid_from <= changes.as_of < d.valid_until:
            continue
        for ref in d.relationship_evidence:
            ref.require_recorded_by(changes.as_of)
            if hashlib.sha256(resolve(ref)).hexdigest() != ref.sha256_digest:
                raise ValueError("RELATION_SOURCE_MISMATCH")
        for parent in d.upstream:
            if parent not in index:
                raise ValueError("UNRESOLVED_DEPENDENCY")
            if index[parent].scope != d.scope and not d.relationship_evidence:
                raise ValueError("UNSOURCED_CROSS_SCOPE_EDGE")
        active.append(d)
    changed = True
    while changed:
        changed = False
        for d in active:
            if d.artifact not in selected and (
                keys.intersection(d.source_keys) or selected.intersection(d.upstream)
            ):
                selected.add(d.artifact)
                relations.update(d.relationship_evidence)
                changed = True
    return ImpactResolution(
        changeset_sha256=changes.sha256,
        invalidated=tuple(
            sorted(selected, key=lambda r: (r.namespace, r.id, r.sha256))
        ),
        scopes=tuple(
            sorted({index[r].scope for r in selected}, key=lambda s: s.scope_id)
        ),
        relation_sources=tuple(sorted(relations, key=lambda r: r.sha256)),
    )


class ReuseInputs(Frozen):
    """Resolver-owned complete dependency fingerprint, not report existence."""

    scope: Scope
    task: Text
    revision: Revision
    sources: tuple[SourceSnapshot, ...] = Field(min_length=1)
    claims: tuple[Reference, ...]
    memories: tuple[ArtifactRef, ...]
    agent_version: Text
    prompt_version: Text
    validator_version: Text
    strategy_version: Text
    source_policy_version: Text
    scientific_status: Literal["VALIDATED", "UNVALIDATED", "INVALIDATED"]
    valid_from: Clock
    valid_until: Clock

    @model_validator(mode="after")
    def interval(self) -> Self:
        """Require a nonempty validity interval."""
        if self.valid_until <= self.valid_from:
            raise ValueError("INVALID_REUSE_INTERVAL")
        return self


class ReuseProof(Frozen):
    """Persistable actual resolver comparisons at an explicit cutoff."""

    previous_sha256: str
    current_sha256: str
    changeset_sha256: str
    revision: Revision
    as_of: Clock
    disposition: Literal["REUSED", "BLOCKED_REUSE"]
    reasons: tuple[str, ...]


def qualify_reuse(
    previous: ReuseInputs,
    current: ReuseInputs,
    changes: MemoryChangeSet,
    impact: ImpactResolution,
    validate_claim: Callable[[Reference], None],
    validate_revision: Callable[[Revision], None],
) -> ReuseProof:
    """Revalidate Claims and freshness even when all retained bytes match."""
    validate_revision(current.revision)
    reasons = []
    if previous != current:
        reasons.append("DEPENDENCY_OR_VERSION_CHANGED")
    if current.scientific_status != "VALIDATED":
        reasons.append("SCIENTIFIC_STATUS")
    if not current.valid_from <= changes.as_of < current.valid_until:
        reasons.append("EXPIRED_OR_FUTURE")
    if impact.changeset_sha256 != changes.sha256:
        raise ValueError("IMPACT_CHANGESET_MISMATCH")
    if current.revision.state in impact.invalidated or set(current.claims).intersection(
        impact.invalidated
    ):
        reasons.append("INVALIDATED")
    checked = {s.key: s for s in changes.checked_population}
    for s in current.sources:
        if (
            checked.get(s.key) != s
            or s.status != "ACTIVE"
            or (s.expires_at and s.expires_at <= changes.as_of)
        ):
            reasons.append("SOURCE_MISSING_CHANGED_OR_EXPIRED")
    for ref in current.memories:
        ref.require_recorded_by(changes.as_of)
    for claim in current.claims:
        validate_claim(claim)
    return ReuseProof(
        previous_sha256=previous.sha256,
        current_sha256=current.sha256,
        changeset_sha256=changes.sha256,
        revision=current.revision,
        as_of=changes.as_of,
        disposition="BLOCKED_REUSE" if reasons else "REUSED",
        reasons=tuple(dict.fromkeys(reasons)),
    )
