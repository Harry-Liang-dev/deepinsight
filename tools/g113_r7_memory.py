"""Current read-only R7 receivers in the existing authorized development replay.

This composition creates no source, financial fact, production permission or
model invocation. It uses original MemoryService, W6 delivery and ACL/CAS gates.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.delivery import MemoryDelivery
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_v2_shared import canonical, digest
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT
from tools.g113_r1_prepare import no_change
from tools.g113_r2_freeze import read
from tools.g113_r2_memory import ReceivingMemory, bind_current, recheck

VERSION = "G113_R7_CURRENT_MEMORY_AUTHORITY_V1"
ORDER = ("A1", "B1", "B2", "A2", "A3", "B3", "B4", "A4")
CUTOFF = "2026-10-30T18:40:22.704289+00:00"


def population_contract(release_contract: str) -> tuple[tuple[str, ...], str, str]:
    """Code-owned exact populations; no caller-selected role/count expansion."""
    if release_contract == "G113_R7_EIGHT_SLOT_V1":
        return ORDER, "G113-R7-", VERSION
    if release_contract == "G113_R8_FOUR_SLOT_V1":
        return (
            ("B1", "B2", "B3", "B4"),
            "G113-R8-",
            "G113_R8_CURRENT_MEMORY_AUTHORITY_V1",
        )
    if release_contract == "G113_R9_FOUR_SLOT_V1":
        return (
            ("B1", "B2", "B3", "B4"),
            "G113-R9-",
            "G113_R9_CURRENT_MEMORY_AUTHORITY_V1",
        )
    if release_contract == "H2_FIXED12_DEVELOPMENT_V1":
        return (
            tuple(f"H2-C{i:03}" for i in range(1, 13)),
            "H2-LIVE-FREEZE-",
            "H2_CURRENT_MEMORY_AUTHORITY_V1",
        )
    raise ValueError("UNREGISTERED_MEMORY_POPULATION_CONTRACT")


def install_runtime(
    instance: Path, *, release_contract: str = "G113_R7_EIGHT_SLOT_V1"
) -> dict[str, Any]:
    """Install a new retained-data instance; existing paths are never overwritten."""
    _, prefix, version = population_contract(release_contract)
    record = dev.install(
        instance,
        authorization=(
            dev.H2_AUTHORIZATION
            if release_contract == "H2_FIXED12_DEVELOPMENT_V1"
            else dev.AUTHORIZATION
        ),
    )
    installation = blob_hash((instance / "INSTANCE.json").read_bytes())
    rt = dev.DevelopmentRuntime(instance, installation)
    rt.receiver(
        "fundamental_analyst",
        datetime.fromisoformat(CUTOFF),
        "G113-R5-NOCHANGE",
        record["instance_id"] + ":" + prefix + "nochange-audit",
        datetime.now(UTC),
    )
    return dict(
        version=version,
        root=str(instance.resolve()),
        instance_id=record["instance_id"],
        installation_sha256=installation,
        purpose=prefix + "AUTHORIZED_DEVELOPMENT_HISTORICAL_REPLAY",
        authority="CURRENT_USER_G113_DEVELOPMENT_AUTHORIZATION",
        source_commit=record["source_commit"],
        source_manifest_sha256=record["source_manifest_sha256"],
        scientific_memory=False,
        production_access=False,
        model_execution_authorized=False,
    )


def ordinary_control(rt: dev.DevelopmentRuntime) -> dict[str, Any]:
    """Execute the real unchanged-population controller, never dispatch a model."""
    controls = [
        read_grant
        for _, raw in rt.journal.entries(dev.GRANTS)
        if (read_grant := json.loads(raw))["task"] == "G113-R5-NOCHANGE"
    ]
    if len(controls) != 1:
        raise ValueError("R7_NOCHANGE_CONTROL_IDENTITY")
    control = controls[0]
    memory = dev.NoChangeMemory(ROOT, rt.path)
    memory.bind_receiver(
        ResearchEpisode.model_validate(control["episode"]),
        dev.NoChangeAuditAccess.model_validate(control["access"]),
        control["invocation"],
    )
    result = no_change(memory)
    if result["new_research_tasks"] != 0 or result["model_calls"] != 0:
        raise ValueError("R7_NOCHANGE_MODEL_DISPATCH")
    return result


def population_receipt(rt: dev.DevelopmentRuntime) -> dict[str, Any]:
    """Record exact original business population, support and relationship IDs."""
    memory = ReceivingMemory(ROOT, rt.path)
    population = memory.population()
    supports = memory.journal.entries_with_sequence("g111-r1-support")
    relations = memory.journal.entries_with_sequence("g111-r1-relations")
    if (
        len(population) != 27
        or len(memory.id_map()) != 11
        or len(supports) != 13
        or len(relations) != 4
        or digest(population) != rt.record["original_business_population_sha256"]
        or memory.id_map() != rt.record["original_msft_ids"]
    ):
        raise ValueError("R7_ORIGINAL_BUSINESS_POPULATION_CHANGED")
    return dict(
        memory_count=27,
        msft_observation_count=11,
        source_support_count=13,
        relation_count=4,
        population_sha256=digest(population),
        observation_memory_ids=memory.id_map(),
        source_support_identity=digest(supports),
        relation_identity=digest(relations),
        relation_ids=[r[1] for r in relations],
        scientific_writes=0,
    )


def bind_receivers(
    instance: Path,
    installation_sha256: str,
    rows: list[dict[str, Any]],
    catalog_loader: Callable[[dict[str, Any]], TaskCatalog],
    output: Path,
    *,
    operation_id: str,
    created: datetime,
    release_contract: str = "G113_R7_EIGHT_SLOT_V1",
) -> dict[str, Any]:
    """Install exact versioned current receivers without changing SDK content."""
    order, prefix, version = population_contract(release_contract)
    if (
        tuple(row["sample_id"] for row in rows) != order
        or not operation_id.startswith(prefix)
        or created.tzinfo is None
    ):
        raise ValueError("R7_MEMORY_POPULATION_OR_OPERATION")
    rt = dev.DevelopmentRuntime(instance, installation_sha256)
    before_grants = rt.journal.entries(dev.GRANTS)
    before = population_receipt(rt)
    control = ordinary_control(rt)
    durable(output / "NOCHANGE_CONTROL.json", canonical(control))
    template = MemoryDelivery.model_validate(read(dev.TEMPLATE))
    slots, proofs = [], []
    for original in rows:
        catalog = catalog_loader(original)
        if (
            catalog.identity != original["semantic_task_identity"]
            or catalog.data()["role"] != original["role"]
            or catalog.data()["research_as_of"] != CUTOFF
        ):
            raise ValueError("R7_MEMORY_TASK_CATALOG_IDENTITY")
        name = original["slot"]
        folder = output / name
        folder.mkdir(parents=True, exist_ok=True)
        task = operation_id + ":task:" + original["sample_id"]
        invocation = operation_id + ":invocation:" + original["sample_id"]
        memory = rt.receiver(
            original["role"],
            datetime.fromisoformat(CUTOFF),
            task,
            invocation,
            created,
        )
        candidate, binding = bind_current(memory, catalog, template)
        access = digest(memory.access)
        checked = recheck(memory, candidate, catalog, access)
        records = {
            "CURRENT_BINDING.json": binding,
            "W6_DELIVERY.json": candidate.model_dump(mode="json"),
            "PRESEND_OFFLINE_CHECK.json": checked,
            "RECEIVING_EPISODE_CANDIDATE.json": memory.ep.model_dump(mode="json"),
            "ACCESS_CONTEXT.json": memory.access.model_dump(mode="json"),
        }
        for name, value in records.items():
            durable(folder / name, canonical(value))
        row = dict(
            original,
            operational_task_id=task,
            invocation_candidate_id=invocation,
            episode_candidate_id=memory.ep.episode_id,
            access_identity=access,
            dependency_snapshot=binding["dependency_snapshot"],
            created_at=created.isoformat(),
            actual_invocation_at=None,
            current_memory_readset="CURRENT_VERIFIED_NOT_YET_SENT",
            current_episode_acl="CURRENT_READ_HISTORY_ONLY",
            real_dispatch_authorized=False,
        )
        slots.append(row)
        proofs.append(dict(slot=row["slot"], receipt=checked))
    after = population_receipt(rt)
    if before != after or not set(before_grants) <= set(rt.journal.entries(dev.GRANTS)):
        raise ValueError("R7_POPULATION_OR_OLD_GRANTS_CHANGED")
    binding = dict(
        root=str(instance.resolve()),
        installation_sha256=installation_sha256,
        instance_id=rt.record["instance_id"],
        grant_identities={
            k: blob_hash(raw.encode()) for k, raw in rt.journal.entries(dev.GRANTS)
        },
    )
    result = dict(
        version=version,
        operation_id=operation_id,
        slots=slots,
        development_instance=binding,
        original_population=before,
        final_population=after,
        nochange=control,
        current_checks=proofs,
        current_permission_is_not_continuing_authority=True,
        current_before_each_send_required=True,
        new_scientific_writes=0,
    )
    durable(
        output
        / (
            "H2_NEW_RUNTIME_AUTHORITY_BINDING.json"
            if release_contract == "H2_FIXED12_DEVELOPMENT_V1"
            else (
                "CURRENT_R9_MEMORY_AUTHORITY.json"
                if release_contract == "G113_R9_FOUR_SLOT_V1"
                else (
                    "CURRENT_R8_MEMORY_AUTHORITY.json"
                    if release_contract == "G113_R8_FOUR_SLOT_V1"
                    else "CURRENT_R7_MEMORY_AUTHORITY.json"
                )
            )
        ),
        canonical(result),
    )
    return result


def open_runtime(binding: dict[str, Any]) -> dev.DevelopmentRuntime:
    """Open only the exact installed instance and exact pinned grant journal."""
    return dev.DevelopmentRuntime(
        Path(binding["root"]),
        binding["installation_sha256"],
        binding["grant_identities"],
    )


def revalidate(
    output: Path,
    binding: dict[str, Any],
    rows: list[dict[str, Any]],
    catalog_loader: Callable[[dict[str, Any]], TaskCatalog],
) -> list[dict[str, Any]]:
    """Requery live development ACL and Memory through original authority gates."""
    rt = open_runtime(binding)
    checks = []
    for row in rows:
        _, _, receipt = sender.current_memory(
            ROOT, output, row, rt.authority(), catalog=catalog_loader(row)
        )
        checks.append(dict(slot=row["slot"], receipt=receipt))
    return checks
