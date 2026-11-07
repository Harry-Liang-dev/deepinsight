"""Explicit engineering lifecycle fixture; never counted as a real source revision."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.memory.temporal_delta import ContentNode, TemporalSource
from src.memory.temporal_versions import (
    VersionEvent,
    append_version_event,
    qualified_delivery,
    qualified_relations,
    version_snapshot,
    version_status,
)
from src.services.native_preservation import blob_hash
from tools.g111_r1_msft import MSFTMemory, save
from tools.g113_temporal_reuse import changes_and_impact, historical_read, process


def run(root: Path, output: Path, storage: Path) -> dict[str, Any]:
    """Retain a synthetic relation supplement/withdrawal and context withdrawal."""
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(storage, output / "storage")
    memory = MSFTMemory(root, output)
    before = memory.population()
    first = memory.retrieve("fixture-before")
    old_at = memory.at
    target = next(
        ContentNode.model_validate_json(b).memory_id
        for _, b in memory.journal.entries("g111-nodes")
        if "MSFT:REPORTING_REGIME" in b
    )
    rid = memory.journal.entries("g111-r1-relations")[0][0]
    raws: dict[str, bytes] = {}

    def validate(event: VersionEvent) -> None:
        raw = raws[event.source.raw_sha256]
        value = json.loads(raw)
        if (
            event.source.origin != "SYNTHETIC_ENGINEERING_FIXTURE"
            or event.quote != raw.decode()
            or value["target"] != event.target_id
            or value["action"] != event.action
        ):
            raise ValueError("FIXTURE_ACTION_NOT_SUPPORTED")

    receipts = []
    for kind, target_id, action in (
        ("RELATION", rid, "ADDITIONAL_EVIDENCE"),
        ("RELATION", rid, "RETRACTED"),
        ("MEMORY", target, "RETRACTED"),
    ):
        delivery = memory.retrieve("fixture-" + kind + action)
        raw = json.dumps(
            dict(
                origin="SYNTHETIC_ENGINEERING_FIXTURE",
                target=target_id,
                action=action,
                not_a_financial_statement=True,
            ),
            sort_keys=True,
        ).encode()
        sha = blob_hash(raw)
        raws[sha] = raw
        (output / (sha + ".fixture.txt")).write_bytes(raw)
        source = TemporalSource(
            source_id="fixture:" + sha,
            raw_sha256=sha,
            subject="US:MSFT",
            scope_ids=("ASSET:US:MSFT",),
            event_at=None,
            available_at=memory.at,
            observed_at=memory.at,
            ingested_at=memory.at,
            origin="SYNTHETIC_ENGINEERING_FIXTURE",
        )
        event = VersionEvent.model_validate(
            dict(
                command_id="fixture:" + sha,
                target_type=kind,
                target_id=target_id,
                action=action,
                source=source,
                source_locator="RAW_UTF8:0:" + str(len(raw)),
                quote=raw.decode(),
                reason="ENGINEERING_FIXTURE_NO_REAL_REVISION_EVIDENCE",
                recorded_at=memory.at,
                research_as_of=memory.at,
                uncertainty="Synthetic test; no real source correction established",
            )
        )
        prior = version_snapshot(memory.journal)
        persisted = append_version_event(
            memory.journal,
            event,
            raw=raw,
            delivery=delivery,
            access=memory.access,
            expected_snapshot=prior,
            validate_revision_support=validate,
        )
        assert (
            append_version_event(
                memory.journal,
                event,
                raw=raw,
                delivery=delivery,
                access=memory.access,
                expected_snapshot=prior,
                validate_revision_support=validate,
            )
            == persisted
        )
        q = qualified_delivery(memory.journal, delivery, memory.access)
        relations = qualified_relations(
            memory.journal,
            q,
            access=memory.access,
            validate_support=memory.validate_support,
            validate_revision_support=validate,
        )
        impact = changes_and_impact(
            memory, [], [{"relation_id": target_id, "kind": "RELATION_UPDATE"}]
        )
        receipts.append(
            dict(
                event=event.model_dump(mode="json"),
                readset=q,
                relations=relations,
                impact=impact,
            )
        )
    historical = historical_read(memory, old_at, "fixture-old-cutoff")
    reopened = MSFTMemory(root, output)
    delivery = reopened.retrieve("fixture-reopened")
    current = qualified_delivery(reopened.journal, delivery, reopened.access)
    assert len(historical["accepted"]) == 11 and len(current["accepted"]) == 10
    assert memory.population() == before
    try:
        process(reopened, "G105-GET-05", "fixture-must-block-hash-skip")
    except ValueError as exc:
        blocked = str(exc)
    else:
        raise AssertionError("INACTIVE_DEPENDENCY_NOT_BLOCKED")
    result = dict(
        origin="SYNTHETIC_ENGINEERING_FIXTURE",
        real_source_revision_pass=False,
        receipts=receipts,
        historical_readset=historical,
        reopened_readset=current,
        historical_status=version_status(
            memory.journal, target, knowledge_as_of=old_at
        ),
        current_status=version_status(
            memory.journal, target, knowledge_as_of=reopened.at
        ),
        hash_reuse_rejected=blocked,
        raw_memory_rows_unchanged=True,
        version_events=len(memory.journal.entries("g113-version-events")),
        original_delivery=first.read_set.model_dump(mode="json"),
        future_boundary=version_status(
            memory.journal, target, knowledge_as_of=old_at - timedelta(microseconds=1)
        ),
    )
    save(output / "RESULT.json", result)
    save(
        output / "VERSION_EVENTS.json",
        [json.loads(b) for _, b in memory.journal.entries("g113-version-events")],
    )
    return result


def run_supersession(root: Path, output: Path) -> dict[str, Any]:
    """Write two nonfinancial synthetic versions through original G100 MemoryService."""
    from src.memory.hybrid_sources import RegisteredNarrativeSource
    from src.memory.temporal_delta import ObservedContent, run_temporal_cycle
    from src.memory.temporal_versions import classify_cycle
    from src.schemas.common import SourceReference
    from src.services.native_preservation import NativePreserver
    from tools.g111_temporal_memory import ReplayMemory

    output.mkdir(parents=True, exist_ok=False)
    memory = ReplayMemory(root, output, "US:TEST")
    cycles = []
    sources = []
    for value in ("alpha", "beta"):
        sid = "ENGINEERING_FIXTURE:" + value
        text = (
            "ENGINEERING_FIXTURE nonfinancial status: alpha."
            if value == "alpha"
            else "ENGINEERING_FIXTURE nonfinancial status: beta replaces alpha."
        )
        url = "https://fixture.invalid/" + value
        native = NativePreserver(
            output / "native" / value,
            provider="SYNTHETIC_ENGINEERING_FIXTURE",
            owner="US:TEST",
            run_id="g113-nonfinancial-fixture",
            retention_authority="ENGINEERING_ONLY",
            allowed_endpoints=(url,),
            normalization_version="UTF8_V1",
            clock=lambda: memory.at,
        )
        identity = native.preserve(
            url, text.encode(), status=200, headers={"content-type": "text/plain"}
        )
        memory.sources[sid] = RegisteredNarrativeSource(
            native,
            identity,
            SourceReference(
                document_id=sid,
                provider="SYNTHETIC_ENGINEERING_FIXTURE",
                source_url=url,
            ),
            blob_hash(text.encode()),
            "US:TEST",
            "Engineering Fixture",
            "EVENT",
            "UTF8_TEXT",
            None,
            None,
            None,
            "SYNTHETIC_ENGINEERING_FIXTURE",
        )
        memory.locators[value] = (0, len(text.encode()))
        source = TemporalSource(
            source_id=sid,
            raw_sha256=blob_hash(text.encode()),
            subject="US:TEST",
            scope_ids=("ASSET:US:TEST",),
            event_at=None,
            available_at=memory.at,
            observed_at=memory.at,
            ingested_at=memory.at,
            origin="SYNTHETIC_ENGINEERING_FIXTURE",
        )
        content = ObservedContent(
            subject="US:TEST",
            concept="NONFINANCIAL_FIXTURE_STATUS",
            period="ENGINEERING_ONLY",
            unit="NATURAL_LANGUAGE",
            basis="FIXTURE",
            value_literal=value,
            locator=sid + "#" + value,
            quote=text,
            source_id=sid,
            raw_sha256=source.raw_sha256,
            event_at=None,
        )
        cycles.append(
            run_temporal_cycle(
                memory.journal,
                source,
                raw=text.encode(),
                as_of=memory.at,
                created_at=memory.at,
                extract=lambda: (content,),
                admit=memory.admit,
                extractor_identity="g113-nonfinancial-engineering-fixture-v1",
            )
        )
        sources.append((source, text.encode()))
    delivery = memory.retrieve("fixture-both-versions")
    access = memory.access.model_copy(
        update={"scopes": (memory.scope, delivery.read_set.scope)}
    )
    first, second = (c.nodes[0] for c in cycles)
    source, raw = sources[-1]
    event = VersionEvent(
        command_id="fixture-explicit-supersession",
        target_type="MEMORY",
        target_id=first.memory_id,
        action="SUPERSEDED",
        successor_memory_id=second.memory_id,
        source=source,
        source_locator="RAW_UTF8:0:" + str(len(raw)),
        quote=raw.decode(),
        reason="ENGINEERING_FIXTURE_EXPLICIT_REPLACEMENT",
        recorded_at=memory.at,
        research_as_of=memory.at,
        uncertainty="No real financial correction demonstrated",
    )

    def validate(e: VersionEvent) -> None:
        if (
            e.source.origin != "SYNTHETIC_ENGINEERING_FIXTURE"
            or e.quote != raw.decode()
            or e.successor_memory_id != second.memory_id
            or e.target_id != first.memory_id
            or e.action != "SUPERSEDED"
        ):
            raise ValueError("FIXTURE_SUPERSESSION_SEMANTICS")

    before = version_snapshot(memory.journal)
    append_version_event(
        memory.journal,
        event,
        raw=raw,
        delivery=delivery,
        access=access,
        expected_snapshot=before,
        validate_revision_support=validate,
    )
    append_version_event(
        memory.journal,
        event,
        raw=raw,
        delivery=delivery,
        access=access,
        expected_snapshot=before,
        validate_revision_support=validate,
    )
    q = qualified_delivery(memory.journal, delivery, access)
    assert [r["artifact_id"] for r in q["accepted"]] == [second.memory_id]
    assert len(memory.journal.entries("g111-nodes")) == 2
    result = dict(
        origin="SYNTHETIC_ENGINEERING_FIXTURE",
        real_source_revision_pass=False,
        cycles=[c.model_dump(mode="json") for c in cycles],
        classifications=[classify_cycle(c) for c in cycles],
        event=event.model_dump(mode="json"),
        old_memory_id=first.memory_id,
        new_memory_id=second.memory_id,
        qualified_readset=q,
        old_version_preserved=True,
        scientific_memory_writes=0,
        old_status_at_creation=version_status(
            memory.journal, first.memory_id, knowledge_as_of=first.created_at
        ),
        original_memoryservice_admissions=2,
    )
    save(output / "RESULT.json", result)
    return result
