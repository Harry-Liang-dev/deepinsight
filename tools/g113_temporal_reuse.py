"""Offline G113 longitudinal development replay; G111/G112 originals are read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.memory.contracts import ResearchContextRequest
from src.memory.hybrid import retrieve_observations
from src.memory.incremental import (
    MemoryChange,
    MemoryChangeSet,
    ResearchDependency,
    resolve_impact,
)
from src.memory.temporal_delta import TemporalCycle
from src.memory.temporal_reuse import qualify_agent_result
from src.memory.temporal_versions import (
    VersionEvent,
    classify_cycle,
    qualified_delivery,
    qualified_relations,
    version_snapshot,
)
from src.memory.vnext_contracts import Scope
from src.models.enums import Market, MemoryLevel, ResearchScopeType
from src.schemas.research_v2_shared import digest, reference
from tools.g111_r1_msft import (
    SOURCE_IDS,
    MSFTMemory,
    census,
    relation_bindings,
    research_inputs,
    save,
)
from tools.g111_temporal_memory import episode, read


def reject_revision(event: VersionEvent) -> None:
    """No real source in this frozen case establishes a retraction/supersession."""
    raise ValueError("G113_NO_REAL_REVISION_AUTHORITY:" + event.command_id)


def get_read(memory: MSFTMemory, label: str) -> dict[str, Any]:
    """Persist version-qualified context after actual service retrieval."""
    delivery = memory.retrieve(label)
    result = qualified_delivery(memory.journal, delivery, memory.access)
    relations = qualified_relations(
        memory.journal,
        result,
        access=memory.access,
        validate_revision_support=reject_revision,
        validate_support=memory.validate_support,
    )
    return {"readset": result, "relations": relations}


def historical_read(memory: MSFTMemory, as_of: datetime, label: str) -> dict[str, Any]:
    """Retrieve actual historical versions without backdating Memory creation."""
    created = datetime.now(UTC)
    if as_of > created:
        raise ValueError("G113_FUTURE_READ")
    ep = episode(as_of, label, "US:MSFT").model_copy(update={"created_at": created})
    memory.at = created
    receiving = Scope(
        scope_type=ResearchScopeType.RESEARCH_EPISODE,
        scope_id="EPISODE:" + ep.episode_id,
    )
    for scope in memory.history_scopes:
        memory.access.require("READ_HISTORY", scope)
    access = memory.access.model_copy(
        update={"scopes": (*memory.history_scopes, receiving)}
    )
    delivery = retrieve_observations(
        memory.service(),
        resolver=memory.resolver,
        access=access,
        journal=memory.journal,
        request=ResearchContextRequest(
            query_text="g111 retained context",
            as_of=as_of,
            market=Market.US,
            namespace_keys=[s.scope_id for s in memory.history_scopes],
            memory_levels=[MemoryLevel.L2],
            top_k_per_section=100,
        ),
        episode=ep,
        run_id=label,
        as_created=created,
        lane="ATTRIBUTED_SOURCES",
    )
    return qualified_delivery(memory.journal, delivery, access)


def process(memory: MSFTMemory, sid: str, label: str) -> dict[str, Any]:
    """Check current permission and validity before retained-byte skip."""
    current = get_read(memory, label + "-qualification")
    relevant = {
        memory.id_map()[f["id"]]
        for f in memory.facts
        if f["id"] in memory.id_map()
        and any(e["source_id"] == sid for e in f["evidence"])
    }
    accepted = {r["artifact_id"] for r in current["readset"]["accepted"]}
    if not relevant <= accepted:
        raise ValueError("G113_INACTIVE_DEPENDENCY_CANNOT_HASH_REUSE")
    result = memory.process(sid, label)
    cycle = TemporalCycle.model_validate(result["temporal_cycle"])
    result["g113_delta"] = classify_cycle(cycle)
    source_metadata = memory.source_catalog[sid]
    for d in result["g113_delta"]:
        d["reported_filing_acceptance"] = source_metadata.get("published_at")
        d["publication_basis"] = "RETAINED_METADATA_NOT_INDEPENDENT_FIRST_PUBLIC_PROOF"
        # The annual source is already independently identified in the frozen case.
        d["temporal_context"] = (
            "HISTORICAL_BACKFILL"
            if source_metadata["plan"]["form"] == "10-K"
            else "RETAINED_REPORT_PERIOD_NOT_CURRENT_BUSINESS_EVENT"
        )
    with memory.journal.serialized():
        memory.journal.append(
            "g113-cycles",
            digest(result),
            json.dumps(result, sort_keys=True),
            len(memory.journal.entries("g113-cycles")),
        )
    return result


def changes_and_impact(
    memory: MSFTMemory,
    rows: list[dict[str, Any]],
    relation_delta: list[dict[str, Any]],
) -> dict[str, Any]:
    """Adapt changed IDs to G85; W3 retains task and materiality authority."""
    changed = {r["memory_id"] for r in rows if r["kind"] != "UNCHANGED"}
    changed.update(r["relation_id"] for r in relation_delta if r["kind"] != "UNCHANGED")
    changes = MemoryChangeSet(
        as_of=memory.at,
        created_at=memory.at,
        previous_population=digest(rows),
        checked_population=(),
        changes=tuple(
            MemoryChange(
                key=key,
                status="UPDATED",
                before=None,
                after=None,
                delta=None,
                catalyst_identity=key,
            )
            for key in sorted(changed)
        ),
    )
    # These are frozen W3 candidate tasks, not newly invented Agent results/Claims.
    scope = Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:US:MSFT")
    deps = tuple(
        ResearchDependency(
            artifact=reference(
                "QUESTION",
                role,
                "g113_frozen_w3_task_v1",
                read(memory.case / "model-inputs" / (role + ".TASK_TEMPLATE.json")),
            ),
            scope=scope,
            source_keys=tuple(
                sorted(
                    set(memory.id_map().values())
                    | {k for k, _ in memory.journal.entries("g111-r1-relations")}
                )
            ),
            upstream=(),
            valid_from=memory.at,
            valid_until=memory.at + timedelta(hours=1),
        )
        for role in ("fundamental_analyst", "news_event_analyst")
    )
    impact = resolve_impact(changes, deps, lambda _: b"")
    reuse = qualify_agent_result(
        memory.journal,
        result_ref=None,
        acceptance_ref=None,
        previous=None,
        current=None,
        changes=changes,
        impact=impact,
        validator=None,
        access=memory.access,
        validate_revision=lambda _: None,
    )
    return dict(
        changeset=changes.model_dump(mode="json"),
        impact=impact.model_dump(mode="json"),
        dependencies=[d.model_dump(mode="json") for d in deps],
        affected_tasks=[r.id for r in impact.invalidated],
        agent_result_reuse=reuse,
        dispatch_authorized=False,
        policy_owner="W3",
        real_cross_company="NOT_DEMONSTRATED",
    )


def observation_census(
    memory: MSFTMemory, before: dict[str, str], supports: set[str]
) -> list[dict[str, Any]]:
    """Measure changes with separate reporting-period and arrival axes."""
    rows = census(memory, before, supports)
    for row in rows:
        row["g111_kind"] = row["kind"]
        row["kind"] = {
            "NEW_FACT": "NEW_OBSERVATION",
            "NEW_EVIDENCE_FOR_EXISTING_FACT": "ADDITIONAL_EVIDENCE",
            "UNCHANGED": "UNCHANGED",
        }[row["kind"]]
        row["late_historical_source_ids"] = [
            e["source_id"]
            for e in row["added_evidence"]
            if memory.source_catalog[e["source_id"]]["plan"]["form"] == "10-K"
        ]
        row["event_at"] = None
        row["operating_period"] = row["observation"]["period"]
        row["version_effective_at"] = None
        row["classification_authority"] = (
            "FROZEN_SOURCE_OBSERVATION_NOT_SCIENTIFIC_FACT"
        )
    return rows


def bind_view_candidates(memory: MSFTMemory, inputs: dict[str, Any]) -> dict[str, Any]:
    """Bind excerpt IDs and retain all support and counterevidence views."""
    for packet in inputs.values():
        views = packet["required_source_excerpt_views"]
        catalog = {}
        for view in views:
            identity = "g113-view:" + digest(
                {
                    k: view[k]
                    for k in (
                        "source_id",
                        "source_sha256",
                        "native_manifest_identity",
                        "locator",
                        "returned_text",
                    )
                }
            )
            catalog[identity] = view
        packet["evidence_view_catalog"] = catalog
        packet["evidence_view_catalog_id"] = digest(catalog)
        packet["lazy_view_interface"] = (
            "tools.g113_temporal_reuse.resolve_view(memory, catalog_id, view_id)"
        )
        packet["reference_instructions"] = (
            "Reference exact view IDs. W1 resolves original source coordinates; "
            "the original validator determines Claim authority. Do not invent hashes."
        )
        packet["source_period_warning"] = (
            "Historical annual backfill is not a new daily operating event."
        )
        packet["qualified_agent_result_reuse"] = "NOT_EVALUABLE"
        packet["g113_version_snapshot"] = version_snapshot(memory.journal)
        with memory.journal.serialized():
            memory.journal.append(
                "g113-view-catalogs",
                digest(catalog),
                json.dumps(catalog, sort_keys=True),
                len(memory.journal.entries("g113-view-catalogs")),
            )
    return inputs


def resolve_view(memory: MSFTMemory, catalog_id: str, view_id: str) -> dict[str, Any]:
    """Refetch exact catalog views through the original source validator."""
    catalogs = dict(memory.journal.entries("g113-view-catalogs"))
    view = json.loads(catalogs[catalog_id])[view_id]
    return memory.fetch_evidence(
        dict(
            source_id=view["source_id"],
            raw_sha256=view["source_sha256"],
            native_manifest_identity=view["native_manifest_identity"],
            locator=view["locator"],
            quote=view["returned_text"],
        )
    )


def run_case(
    root: Path, output: Path, storage: Path, *, controlled: bool
) -> dict[str, Any]:
    """Append to a copy; reopen actual DB/index and measure no-change processing."""
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(storage, output / "storage")
    memory = MSFTMemory(root, output)
    before = memory.population()
    save(output / "BEFORE_SNAPSHOT.json", memory.snapshot())
    t0 = process(memory, SOURCE_IDS[0], output.name + "-T0")
    ids = memory.id_map()
    support_ids = {k for k, _ in memory.journal.entries("g111-r1-support")}
    previous_relations = {k for k, _ in memory.journal.entries("g111-r1-relations")}
    cycles = [
        process(memory, sid, output.name + "-T1-" + sid) for sid in SOURCE_IDS[1:]
    ]
    delivery = memory.retrieve(output.name + "-T1-read")
    bindings = relation_bindings(memory, delivery)
    relations = [
        {
            "relation_id": r["relation_id"],
            "kind": (
                "UNCHANGED"
                if r["relation_id"] in previous_relations
                else "RELATION_UPDATE"
            ),
            "change": "SOURCE_SUPPORTED_CONTEXT_EDGE",
            "relation": r,
        }
        for r in bindings
    ]
    rows = observation_census(memory, ids, support_ids)
    impact = changes_and_impact(memory, rows, relations)
    original_rows = census(memory, ids, support_ids)
    inputs = bind_view_candidates(
        memory, research_inputs(memory, delivery, original_rows, bindings)
    )
    for packet in inputs.values():
        packet["delta_census"] = rows
        packet["relation_delta"] = relations
        packet["affected_tasks"] = impact["affected_tasks"]
    stable = memory.population()
    stable_snapshot = version_snapshot(memory.journal)
    repeat = [
        process(memory, sid, output.name + "-repeat-" + sid) for sid in SOURCE_IDS
    ]
    assert memory.population() == stable
    assert version_snapshot(memory.journal) == stable_snapshot
    assert all(r["temporal_cycle"]["duplicate_research_skipped"] for r in repeat)
    reopened = MSFTMemory(root, output)
    next_read = get_read(reopened, output.name + "-reopened")
    assert set(reopened.id_map().values()) <= {
        r["artifact_id"] for r in next_read["readset"]["accepted"]
    }
    assert all(reopened.population().get(k) == v for k, v in before.items())
    repeat_rows = observation_census(
        reopened,
        reopened.id_map(),
        {k for k, _ in reopened.journal.entries("g111-r1-support")},
    )
    repeat_impact = changes_and_impact(reopened, repeat_rows, [])
    result = dict(
        mode=(
            "CONTROLLED_SOURCE_REPLAY" if controlled else "ACTUAL_EXISTING_MEMORY_DIFF"
        ),
        initial_population=len(before),
        final_population=len(stable),
        original_rows_preserved=True,
        actual_ids=reopened.id_map(),
        t0=t0,
        t1=cycles,
        delta_census=rows,
        counts=dict(Counter(r["kind"] for r in rows)),
        relation_delta=relations,
        impact_plan=impact,
        repeat=repeat,
        repeat_impact=repeat_impact,
        next_cycle=next_read,
        source_revision_real_case="NOT_DEMONSTRATED",
        metrics=dict(
            repeated_sources_skipped=3,
            extractor_calls_prevented=sum(
                1 - r["temporal_cycle"]["extractor_calls"] for r in repeat
            ),
            repeat_admission_calls=sum(
                r["temporal_cycle"]["admission_calls"] for r in repeat
            ),
            duplicate_memory_writes=0,
            duplicate_relations=0,
            repeat_affected_tasks=len(repeat_impact["affected_tasks"]),
            actual_model_calls_saved="NOT_MEASURED",
            actual_external_gets_saved="UNKNOWN",
            measured_coverage_preserving_context_reduction="UNKNOWN",
            new_model_calls=0,
            new_provider_calls=0,
        ),
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
    )
    save(output / "RESULT.json", result)
    save(output / "W1_INPUT.json", inputs)
    save(output / "AFTER_SNAPSHOT.json", reopened.snapshot())
    for stream in (
        "g113-cycles",
        "g113-readsets",
        "g113-agent-reuse",
        "g113-view-catalogs",
    ):
        save(
            output / (stream + ".json"),
            [json.loads(v) for _, v in reopened.journal.entries(stream)],
        )
    return result


def main() -> int:
    """Replay frozen local bytes only; never mutate an original directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("G113_OUTPUT_MUST_BE_NEW")
    root = Path(__file__).resolve().parents[1]

    def denied(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("G113_NO_NETWORK")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.create_connection = denied
    code_paths = (
        "src/memory/temporal_versions.py",
        "src/memory/temporal_reuse.py",
        "tools/g113_temporal_reuse.py",
        "tools/g113_version_fixture.py",
    )
    code_hashes = {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code_paths
    }
    started = datetime.now(UTC).isoformat()
    original = root / "artifacts/g111-r1/delivery/actual/storage"
    before = hashlib.sha256((original / "memory.duckdb").read_bytes()).hexdigest()
    actual = run_case(root, args.output / "actual", original, controlled=False)
    controlled = run_case(
        root,
        args.output / "controlled",
        root / "artifacts/g111/run/storage",
        controlled=True,
    )
    from tools.g113_version_fixture import run as lifecycle_fixture
    from tools.g113_version_fixture import run_supersession

    lifecycle = lifecycle_fixture(root, args.output / "lifecycle-fixture", original)
    supersession = run_supersession(root, args.output / "supersession-fixture")
    assert code_hashes == {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code_paths
    }
    assert (
        hashlib.sha256((original / "memory.duckdb").read_bytes()).hexdigest() == before
    )
    save(
        args.output / "SUMMARY.json",
        dict(
            started_at=started,
            finished_at=datetime.now(UTC).isoformat(),
            executed_source_files=code_hashes,
            source_stable_during_execution=True,
            lifecycle_fixture_events=lifecycle["version_events"],
            supersession_fixture_admissions=supersession[
                "original_memoryservice_admissions"
            ],
            real_source_revision="NOT_DEMONSTRATED",
            actual=actual["counts"],
            controlled=controlled["counts"],
            original_database_sha256=before,
            original_unchanged=True,
            model_calls=0,
            provider_calls=0,
            historical_agent_result_reuse="NOT_EVALUABLE",
            real_cross_company="NOT_DEMONSTRATED",
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
