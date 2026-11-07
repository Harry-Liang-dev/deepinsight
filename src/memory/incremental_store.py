"""Durable G85 receipts over the original DuckDB and StateReducer contracts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from src.memory.incremental import (
    ImpactResolution,
    MemoryChangeSet,
    ResearchDependency,
    ReuseProof,
    SourceSnapshot,
    detect_changes,
    resolve_impact,
)
from src.memory.vnext_contracts import ArtifactRef
from src.repositories.memory_journal import (
    MemoryJournalRepository,
    OrderedJournalSnapshot,
    require_contiguous_history,
)
from src.schemas.research_v2_shared import digest
from src.services.research_v2_collaboration.state import (
    StateEvent,
    StateReducer,
    StateSnapshot,
)
from src.services.research_v2_collaboration.validation import ReferenceValidator


def retain_changes(
    journal: MemoryJournalRepository,
    changes: MemoryChangeSet,
    impact: ImpactResolution,
    *,
    expected: int,
) -> None:
    """Append the complete checked population and derived invalidation proof."""
    if impact.changeset_sha256 != changes.sha256:
        raise ValueError("IMPACT_CHANGESET_MISMATCH")
    with journal.serialized():
        journal.append(
            "changesets", changes.sha256, changes.model_dump_json(), expected
        )
        journal.append(
            "impacts",
            impact.sha256,
            impact.model_dump_json(),
            len(journal.entries("impacts")),
        )


def retain_reuse(journal: MemoryJournalRepository, proof: ReuseProof) -> None:
    """Retain actual reuse/blocked comparisons, with exact State revision."""
    if not any(k == proof.changeset_sha256 for k, _ in journal.entries("changesets")):
        raise ValueError("UNCHECKED_SOURCE_POPULATION")
    with journal.serialized():
        journal.append(
            "reuse",
            proof.sha256,
            proof.model_dump_json(),
            len(journal.entries("reuse")),
        )


def read_state_event_history(
    journal: MemoryJournalRepository, stream: str
) -> tuple[OrderedJournalSnapshot, tuple[StateEvent, ...]]:
    """Read and validate the same full State history for append and restore."""
    snapshot = journal.entries_with_sequence(stream)
    require_contiguous_history(snapshot)
    events = []
    for _, identity, body in snapshot:
        event = StateEvent.model_validate_json(body)
        if digest(event) != identity:
            raise ValueError("G102_EVENT_JOURNAL_IDENTITY")
        events.append(event)
    return snapshot, tuple(events)


def apply_state_event(
    journal: MemoryJournalRepository,
    reducer: StateReducer,
    event: StateEvent,
    *,
    authority: Callable[[StateEvent, StateReducer], ReferenceValidator] | None = None,
) -> StateSnapshot:
    """Replay original reducer checks before durable append; never fork State logic.

    The supplied reducer must be reconstructed from its plan and retained events
    after restart. Validation is done on a replay clone so a DB failure cannot
    advance the caller's head. This adapter grants no new writer roles.
    """
    stream = "state-events:" + reducer.binding.run_id
    with journal.serialized():
        snapshot, _ = read_state_event_history(journal, stream)
        rows = tuple((identity, body) for _, identity, body in snapshot)
        if tuple(body for _, body in rows) != tuple(
            e.model_dump_json() for e in reducer.events
        ):
            raise ValueError("DURABLE_STATE_HEAD_MISMATCH")
        clone = StateReducer(reducer.plan, reducer.validator)
        for old in reducer.events:
            if authority is not None:
                clone.validator = authority(old, clone)
            clone.apply(old)
        if authority is not None:
            # Exact duplicates are validated in their original position above.
            duplicate = next((old for old in reducer.events if old == event), None)
            if duplicate is not None:
                journal.append(
                    stream,
                    digest(event),
                    event.model_dump_json(),
                    len(rows),
                    expected_entries=rows,
                    expected_snapshot=snapshot,
                )
                return clone.apply(event)
            clone.validator = authority(event, clone)
        result = clone.apply(event)
        # Bind the checked snapshot again inside the INSERT transaction. The
        # existing journal lock spans validation; the DB lock spans check/commit.
        journal.append(
            stream,
            digest(event),
            event.model_dump_json(),
            len(rows),
            expected_entries=rows,
            expected_snapshot=snapshot,
        )
        if authority is None:
            reducer.apply(event)
        else:
            # Publish only the original reducer clone that already passed all
            # checks, AFTER durable CAS succeeds. No fallible second validation
            # occurs after commit; DB failure leaves the caller untouched.
            reducer._events = list(clone._events)
            reducer._snapshots = list(clone._snapshots)
            reducer._keys = dict(clone._keys)
            reducer.validator = clone.validator
        return result


def process_sources(
    journal: MemoryJournalRepository,
    population_id: str,
    current: tuple[SourceSnapshot, ...],
    *,
    as_of: datetime,
    created_at: datetime,
    resolve: Callable[[ArtifactRef], bytes],
    detector: ArtifactRef,
    policy: ArtifactRef,
    materiality: Callable[[SourceSnapshot | None, SourceSnapshot], bool],
    dependencies: tuple[ResearchDependency, ...],
) -> tuple[MemoryChangeSet, ImpactResolution]:
    """Execute retained snapshot → actual delta → impact and durably retain inputs.

    Population IDs identify complete acquisition scopes, not individual events.
    A missing member remains MISSING. No fallback acquisition or Agent scheduling
    occurs here. W3 consumes the returned G84 deltas and exact impacted references.
    """
    if not population_id.strip():
        raise ValueError("POPULATION_ID_REQUIRED")
    with journal.serialized():
        stream = "source-population:" + population_id
        history = journal.entries(stream)
        previous: tuple[SourceSnapshot, ...] = ()
        if history:
            prior = MemoryChangeSet.model_validate_json(history[-1][1])
            if as_of < prior.as_of or created_at < prior.created_at:
                raise ValueError("SOURCE_POPULATION_CLOCK_REGRESSION")
            previous = prior.checked_population
        changes = detect_changes(
            previous,
            current,
            as_of=as_of,
            created_at=created_at,
            resolve=resolve,
            detector=detector,
            policy=policy,
            materiality=materiality,
        )
        impact = resolve_impact(changes, dependencies, resolve)
        journal.append(
            "changesets",
            changes.sha256,
            changes.model_dump_json(),
            len(journal.entries("changesets")),
        )
        journal.append(
            "impacts",
            impact.sha256,
            impact.model_dump_json(),
            len(journal.entries("impacts")),
        )
        journal.append(stream, changes.sha256, changes.model_dump_json(), len(history))
        return changes, impact
