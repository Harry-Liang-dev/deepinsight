"""Explicit synthetic edge cases; real replay is separately retained by CLI."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.memory.temporal_delta import (
    ObservedContent,
    TemporalCycle,
    TemporalSource,
    eligible_nodes,
    invalidate_observation,
    run_temporal_cycle,
    selective_impact,
)
from src.repositories import DuckDBDatabase
from src.repositories.memory_journal import MemoryJournalRepository
from src.services.native_preservation import blob_hash

AT = datetime(2026, 10, 30, 20, tzinfo=UTC)


def source(raw: bytes, sid: str = "fixture") -> TemporalSource:
    return TemporalSource(
        source_id=sid,
        raw_sha256=blob_hash(raw),
        subject="US:TEST",
        scope_ids=("ASSET:US:TEST",),
        event_at=None,
        available_at=AT,
        observed_at=AT,
        ingested_at=AT,
        origin="SYNTHETIC_ENGINEERING_FIXTURE",
    )


def content(s: TemporalSource, value: str = "10", month: int = 9) -> ObservedContent:
    return ObservedContent(
        subject=s.subject,
        concept="fixture_disclosure",
        period=str(month),
        unit="USD",
        basis="TEST_ONLY",
        value_literal=value,
        locator="fixture-span",
        quote="fixture",
        source_id=s.source_id,
        raw_sha256=s.raw_sha256,
        event_at=None,
        period_end=AT.replace(month=month).date(),
    )


@pytest.fixture
def journal(tmp_path: Path) -> MemoryJournalRepository:
    db = DuckDBDatabase(tmp_path / "memory.duckdb")
    db.bootstrap()
    j = MemoryJournalRepository(db)
    j.bootstrap()
    return j


def test_skip_and_semantic_relations(journal: MemoryJournalRepository) -> None:
    calls: list[str] = []

    def admit(c: ObservedContent) -> str:
        calls.append(c.content_id)
        return "mem:" + c.content_id

    def cycle(raw: bytes, sid: str, value: str, month: int) -> TemporalCycle:
        s = source(raw, sid)
        return run_temporal_cycle(
            journal,
            s,
            raw=raw,
            as_of=AT,
            created_at=AT,
            extract=lambda: (content(s, value, month),),
            admit=admit,
        )

    a = cycle(b"a", "one", "10", 9)
    assert a.deltas[0].semantic_ids == (a.nodes[0].content.semantic_id,)
    b = cycle(b"a", "one", "10", 9)
    assert b.duplicate_research_skipped and b.extractor_calls == b.admission_calls == 0
    assert a.after_snapshot == b.after_snapshot
    c = cycle(b"other publisher", "two", "10", 9)
    assert c.deltas[0].kind == "NEW_RELATION" and not c.nodes
    repeated_corroboration = cycle(b"other publisher", "two", "10", 9)
    assert repeated_corroboration.duplicate_research_skipped
    assert repeated_corroboration.deltas[0].old_memory_ids == (a.nodes[0].memory_id,)
    assert repeated_corroboration.deltas[0].semantic_ids == a.deltas[0].semantic_ids
    d = cycle(b"correction", "one", "11", 9)
    assert d.deltas[0].kind == "CORRECTION"
    assert d.relations[0].status == "HYPOTHESIZED_RELATION"
    e = cycle(b"old", "three", "8", 6)
    assert e.deltas[0].kind == "HISTORICAL_BACKFILL"
    f = cycle(b"new", "four", "12", 10)
    assert f.deltas[0].kind == "FACT_UPDATE"
    assert len(calls) == 4
    assert selective_impact(f)[0]["disposition"] == "SELECTIVE_EXECUTION"
    assert len(journal.entries("g111-nodes")) == 4
    old = journal.entries("g111-nodes")
    invalid = invalidate_observation(
        journal,
        a.nodes[0].content.content_id,
        source(b"review"),
        raw=b"review",
        as_of=AT,
        reason="synthetic contradiction",
    )
    assert invalid.kind == "INVALIDATION" and journal.entries("g111-nodes") == old
    assert a.nodes[0] not in eligible_nodes(journal, AT)
    assert not eligible_nodes(journal, AT - timedelta(seconds=1))


@pytest.mark.parametrize("attack", ["future", "unknown", "bytes"])
def test_pit_and_identity_deny_before_processing(
    journal: MemoryJournalRepository, attack: str
) -> None:
    s = source(b"a")
    if attack == "future":
        s = s.model_copy(update={"ingested_at": AT + timedelta(seconds=1)})
    if attack == "unknown":
        s = s.model_copy(update={"available_at": None})

    def forbidden() -> tuple[ObservedContent, ...]:
        raise AssertionError("must not process")

    with pytest.raises(ValueError):
        run_temporal_cycle(
            journal,
            s,
            raw=b"wrong" if attack == "bytes" else b"a",
            as_of=AT,
            created_at=AT,
            extract=forbidden,
            admit=lambda c: "bad",
        )
    assert not journal.entries("g111-nodes")


def test_new_extractor_version_cannot_hide_new_information(
    journal: MemoryJournalRepository,
) -> None:
    s = source(b"same raw")
    first = content(s)
    second = first.model_copy(update={"concept": "newly_supported_concept"})
    one = run_temporal_cycle(
        journal,
        s,
        raw=b"same raw",
        as_of=AT,
        created_at=AT,
        extract=lambda: (first,),
        admit=lambda c: "mem:" + c.content_id,
        extractor_identity="v1",
    )
    two = run_temporal_cycle(
        journal,
        s,
        raw=b"same raw",
        as_of=AT,
        created_at=AT,
        extract=lambda: (first, second),
        admit=lambda c: "mem:" + c.content_id,
        extractor_identity="v2",
    )
    assert not two.duplicate_research_skipped
    assert two.admission_calls == 1 and len(journal.entries("g111-nodes")) == 2
    assert one.nodes[0].memory_id != two.nodes[0].memory_id


def test_concurrent_duplicate_cycle_serializes_processing(
    journal: MemoryJournalRepository,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    s = source(b"one retained document")
    calls = []

    def run(_: int) -> TemporalCycle:
        def extract() -> tuple[ObservedContent, ...]:
            calls.append("processed")
            return (content(s),)

        return run_temporal_cycle(
            journal,
            s,
            raw=b"one retained document",
            as_of=AT,
            created_at=AT,
            extract=extract,
            admit=lambda c: "mem:" + c.content_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert len(calls) == 1
    assert sum(c.duplicate_research_skipped for c in results) == 1
    assert len(journal.entries("g111-nodes")) == 1


def test_old_cutoff_cannot_diff_against_future_memory(
    journal: MemoryJournalRepository,
) -> None:
    s = source(b"retained")
    run_temporal_cycle(
        journal,
        s,
        raw=b"retained",
        as_of=AT,
        created_at=AT,
        extract=lambda: (content(s),),
        admit=lambda c: "mem:" + c.content_id,
    )
    past = AT - timedelta(days=1)
    historical = s.model_copy(
        update={"available_at": past, "ingested_at": past, "observed_at": past}
    )
    with pytest.raises(ValueError, match="G111_FUTURE_MEMORY_SNAPSHOT"):
        run_temporal_cycle(
            journal,
            historical,
            raw=b"retained",
            as_of=past,
            created_at=AT,
            extract=lambda: (),
            admit=lambda c: "must-not-run",
        )
    assert len(journal.entries("g111-cycles")) == 1
