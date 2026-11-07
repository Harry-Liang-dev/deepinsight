"""Offline cross-window preparation using the original Memory and SDK adapters."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.hybrid import HybridRead
from src.memory.temporal_relations import require_delivered
from src.memory.temporal_versions import (
    qualified_delivery,
    qualified_relations,
    version_snapshot,
    version_status,
)
from src.models.enums import AgentName
from src.schemas.research_v2_shared import digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import SNAPSHOT, request_audit
from tools.g111_r1_msft import SOURCE_IDS, MSFTMemory, save
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import INPUT, ROOT, compose, covers, w6
from tools.g113_r1_contract import VERSION, output_schema
from tools.g113_temporal_reuse import (
    changes_and_impact,
    observation_census,
    process,
    reject_revision,
    resolve_view,
)


def copy_memory(root: Path, output: Path, case: str) -> MSFTMemory:
    """Copy only verified retained storage; never open the original for writes."""
    base = root / INPUT / "w6"
    manifest = json.loads((base / "artifacts/g113/MANIFEST.json").read_bytes())
    source = f"artifacts/g113/release/{case}/storage/"
    for entry in manifest["files"]:
        if entry["path"].startswith(source):
            raw = (base / entry["path"]).read_bytes()
            if blob_hash(raw) != entry["sha256"]:
                raise ValueError("R1_STORAGE_IDENTITY")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base / source, output / "storage")
    return MSFTMemory(root, output)


def current_binding(
    memory: MSFTMemory, catalog: TaskCatalog, label: str
) -> dict[str, Any]:
    """Actually requery original MemoryService for the explicitly assigned role."""
    if str(memory.access.role) != catalog.data()["role"]:
        raise ValueError("R1_MEMORY_CONSUMER_ROLE")
    delivery = memory.retrieve(label)
    return check_delivery(memory, delivery, catalog, datetime.now(UTC))


def check_delivery(
    memory: MSFTMemory, delivery: HybridRead, catalog: TaskCatalog, at: datetime
) -> dict[str, Any]:
    """Recheck original ACL, expiry, versions, source and historical cutoff."""
    data = catalog.data()
    if (
        delivery.read_set.agent_role != memory.access.role
        or str(memory.access.role) != data["role"]
    ):
        raise ValueError("R1_READSET_ROLE")
    allowed = require_delivered(delivery, memory.journal, memory.access)
    qualified = qualified_delivery(memory.journal, delivery, memory.access, valid_at=at)
    refs = {r["artifact_id"]: r for r in qualified["accepted"]}
    required = set(data["memory_versions"])
    if not required <= allowed or not required <= refs.keys():
        raise ValueError("R1_MEMORY_NOT_CURRENTLY_DELIVERABLE")
    if any(
        version_status(memory.journal, mid, knowledge_as_of=at) != "ACTIVE"
        for mid in required | set(data["relations"])
    ):
        raise ValueError("R1_CURRENT_VERSION_INVALIDATED")
    if any(refs[mid] != ref for mid, ref in data["memory_versions"].items()):
        raise ValueError("R1_MEMORY_VERSION_CHANGED")
    cutoff = datetime.fromisoformat(data["research_as_of"])
    for receipt in delivery.supplied_records:
        if receipt.result.memory_id not in required:
            continue
        record = receipt.record
        if (
            not record.proposal.created_at <= cutoff
            or not receipt.persisted_at <= cutoff
        ):
            raise ValueError("R1_FUTURE_MEMORY_FOR_HISTORICAL_CUTOFF")
        if at >= record.review_due_at or at < delivery.read_set.created_at:
            raise ValueError("R1_EXPIRED_OR_FUTURE_DELIVERY")
        memory.resolver.validate(record.proposal)
    relations = qualified_relations(
        memory.journal,
        qualified,
        access=memory.access,
        validate_revision_support=reject_revision,
        validate_support=memory.validate_support,
    )
    relation_map = {r["relation_id"]: r for r in relations}
    for rid, original in data["relations"].items():
        row = relation_map.get(rid)
        if row is None or datetime.fromisoformat(row["created_at"]) > cutoff:
            raise ValueError("R1_RELATION_NOT_CURRENT_OR_FUTURE")
        for key in (
            "from_memory_id",
            "to_memory_id",
            "source_support",
            "effective_time",
            "relation_type",
        ):
            if row[key] != original[key]:
                raise ValueError("R1_RELATION_SNAPSHOT_CHANGED")
    for vid in data["views"]:
        catalog.resolve_view(vid)
        v = data["views"][vid]
        memory.fetch_evidence(
            dict(
                source_id=v["source_id"],
                raw_sha256=v["raw_sha256"],
                native_manifest_identity=memory.source_catalog[v["source_id"]][
                    "native_manifest_identity"
                ],
                locator=v["locator"],
                quote=v["content"],
            )
        )
    identity = dict(
        task_identity=catalog.identity,
        role=data["role"],
        information_cutoff=data["research_as_of"],
        current_checked_at=at.isoformat(),
        memory_readset=delivery.read_set.model_dump(mode="json"),
        original_memory_versions=data["memory_versions"],
        current_qualified_readset=qualified,
        relation_ids=sorted(data["relations"]),
        version_snapshot=version_snapshot(memory.journal),
        population_sha256=digest(memory.population()),
        source_readset=data["sources"],
        source_view_sha256=digest(data["views"]),
        calculation_cards_sha256=digest(data["calculation_cards"]),
    )
    return dict(
        identity,
        dependency_snapshot=digest(identity),
        status="OFFLINE_CURRENT_REQUERY_NOT_DISPATCH_AUTHORIZATION",
        retrieved=True,
        provided_to_model=False,
        actually_consumed=False,
        applied=False,
        live_requery_required=True,
        scientific_admission=False,
    )


def no_change(memory: MSFTMemory) -> dict[str, Any]:
    """Reenter the real existing population using W6/G111 delta and G85 impact."""
    before, snapshot = memory.population(), version_snapshot(memory.journal)
    ids = memory.id_map()
    supports = {k for k, _ in memory.journal.entries("g111-r1-support")}
    cycles = [process(memory, sid, "g113-r1-daily-" + sid) for sid in SOURCE_IDS]
    rows = observation_census(memory, ids, supports)
    impact = changes_and_impact(memory, rows, [])
    if memory.population() != before or version_snapshot(memory.journal) != snapshot:
        raise ValueError("R1_NOCHANGE_DEPENDENCY_CHANGED")
    if any(r["kind"] != "UNCHANGED" for r in rows) or impact["affected_tasks"]:
        raise ValueError("R1_NOCHANGE_HAS_AFFECTED_TASK")
    return dict(
        mode="ORDINARY_INCREMENTAL_REENTRY",
        disposition="NO_EFFECTIVE_CHANGE",
        new_research_tasks=0,
        model_calls=0,
        before=len(before),
        after=len(memory.population()),
        counts=dict(Counter(r["kind"] for r in rows)),
        cycles=cycles,
        impact_plan=impact,
        source_dependency_snapshot=snapshot,
        qualified_agent_result_reuse="NOT_EVALUABLE",
        calls_saved="NOT_MEASURED",
    )


def bridge_controlled(
    root: Path, memory: MSFTMemory, catalog: TaskCatalog
) -> dict[str, Any]:
    """Prove cross-store content/edge equivalence without replacing original IDs."""
    d, texts = catalog.data(), json.loads(catalog.source_texts_json)
    packet = w6(root, "release/controlled/W1_INPUT.json")[d["role"]]
    mapping, remap = [], {}
    for row in w6(root, "release/controlled/DELTA_CENSUS.json"):
        obs = d["observations"][row["fact_id"]]
        if row["observation"] != obs["observation"]:
            raise ValueError("R1_CONTROLLED_CONTENT_MISMATCH")
        remap[row["memory_id"]] = obs["memory_id"]
        mapping.append(
            dict(
                observation_id=row["fact_id"],
                controlled_memory_id=row["memory_id"],
                original_memory_id=obs["memory_id"],
                transferred_authority=False,
            )
        )
    edge_mapping = []
    for entry in w6(root, "release/controlled/RELATION_DELTA.json"):
        rel = entry["relation"]
        original_identity = digest(
            (
                rel["from_memory_id"],
                rel["to_memory_id"],
                rel["relation_type"],
                rel["source_support"],
                rel["effective_time"],
            )
        )
        if original_identity != rel["relation_id"]:
            raise ValueError("R1_CONTROLLED_RELATION_IDENTITY")
        actual_identity = digest(
            (
                remap[rel["from_memory_id"]],
                remap[rel["to_memory_id"]],
                rel["relation_type"],
                rel["source_support"],
                rel["effective_time"],
            )
        )
        if actual_identity not in d["relations"]:
            raise ValueError("R1_CONTROLLED_RELATION_EQUIVALENCE")
        edge_mapping.append(
            dict(
                controlled_relation=original_identity,
                original_relation=actual_identity,
                identity_transfer=False,
            )
        )
    views = []
    for vid in packet["evidence_view_catalog"]:
        v = resolve_view(memory, packet["evidence_view_catalog_id"], vid)
        views.append(
            dict(
                w6_view_id=vid,
                original_locator=v["locator"],
                w3_exact_or_containing=[
                    key for key, x in d["views"].items() if covers(x, v, texts)
                ],
                w3_contained_exact_ranges=[
                    key for key, x in d["views"].items() if covers(v, x, texts)
                ],
                same_source_not_same_memory_identity=True,
            )
        )
    return dict(
        mode="CONTROLLED_HISTORICAL_CONVERSION_NOT_DAILY_EVENT",
        memory_mapping=mapping,
        relation_mapping=edge_mapping,
        view_mapping=views,
        controlled_created_at_not_backdated=True,
        used_original_memory_ids=True,
        controlled_input_is_not_live_readset=True,
        current_permissions_not_transferred=True,
    )


def candidate_call(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Build a preview only; no authorization or actual Invocation is issued."""
    schema = output_schema(catalog)
    # Original W3 prompt and Full/Delta context remain intact. The prospective
    # interface/card projection is explicit; W3 must match this new version.
    payload = dict(
        catalog.data()["w3_original_payload"],
        g113_r1_binding=dict(
            contract_version=VERSION,
            task_identity=catalog.identity,
            mode=catalog.data()["mode"],
            view_catalog=catalog.data()["views"],
            calculation_cards=catalog.data()["calculation_cards"],
            prior_qualified_agent_judgment=None,
        ),
    )
    # Proposed version change only; never present contradictory old/new output
    # schemas in one preview. The frozen W3 payload remains stored unmodified.
    payload["common"]["response_schema_candidate"] = schema
    return LLMProviderCall(SNAPSHOT, prompt, payload, schema)


def prepare(root: Path, output: Path) -> dict[str, Any]:
    """Create four SDK serialization previews, explicitly pending W3 final match."""
    output.mkdir(parents=True, exist_ok=False)
    actual = copy_memory(root, output / "actual-requery", "actual")
    controlled = copy_memory(root, output / "controlled-read", "controlled")
    preserved = actual.population()
    daily = no_change(actual)
    save(output / "NO_CHANGE.json", daily)
    slots = []
    prompt_path = "artifacts/g113-w3/inputs/COMMON_PROMPT_CANDIDATE.txt"
    base = root / INPUT / "w3"
    manifest = json.loads((base / "artifacts/g113-w3/SOURCE_MANIFEST.json").read_text())
    prompt = (base / prompt_path).read_bytes()
    expected = next(
        e["sha256"] for e in manifest["members"] if e["path"] == prompt_path
    )
    if blob_hash(prompt) != expected:
        raise ValueError("R1_PROMPT_IDENTITY")
    for index, (role, arm) in enumerate(
        (
            ("fundamental_analyst", "FULL"),
            ("fundamental_analyst", "DELTA"),
            ("news_event_analyst", "FULL"),
            ("news_event_analyst", "DELTA"),
        ),
        1,
    ):
        catalog = compose(root, role, arm)
        actual.access = actual.access.model_copy(update={"role": AgentName(role)})
        slot = output / f"{index:02d}-{role}-{arm}"
        slot.mkdir()
        label = "G113-R1-PREP-" + catalog.identity[:24]
        binding = current_binding(actual, catalog, label)
        bridge = bridge_controlled(root, controlled, catalog)
        save(slot / "CURRENT_BINDING.json", binding)
        save(slot / "W6_IDENTITY_BRIDGE.json", bridge)
        save(slot / "TASK_CATALOG.json", catalog.data())
        schema = output_schema(catalog)
        save(slot / "RESPONSE_SCHEMA.json", schema)
        call = candidate_call(catalog, prompt.decode())
        audit = request_audit(call, output_cap=8192)
        wire = audit["serialized_http_body"].encode()
        (slot / "request-preview.raw").write_bytes(wire)
        save(slot / "SERIALIZER_PREVIEW.json", audit)
        row = dict(
            slot=index,
            role=role,
            arm=arm,
            task_identity=catalog.identity,
            episode_candidate_id=label,
            invocation_candidate_id=label + "-invocation",
            created_at=datetime.now(UTC).isoformat(),
            source_readset_sha256=digest(catalog.data()["sources"]),
            dependency_snapshot=binding["dependency_snapshot"],
            request_preview_sha256=blob_hash(wire),
            final_request_sha256=None,
            status="PENDING_W3_FINAL_BINDING",
            actual_invocation_authorized=False,
            model_calls=0,
        )
        slots.append(row)
        save(slot / "IDENTITY.json", row)
    if actual.population() != preserved:
        raise ValueError("R1_MEMORY_BUSINESS_ROWS_CHANGED")
    result = dict(
        status="PENDING_W3_FINAL_BINDING",
        interface=VERSION,
        slots=slots,
        daily_disposition=daily["disposition"],
        daily_tasks=0,
        actual_memory_rows=len(preserved),
        memory_business_rows_unchanged=True,
        scientific_memory_writes=0,
        researchstate_writes=0,
        model_calls=0,
        provider_calls=0,
        native_scientific_admission="BLOCKED",
        W4_scoped_review="REQUIRED",
        W5_new_prereg="REQUIRED",
        full_delta_new_freeze="NOT_ISSUED",
        historical_G112="UNCHANGED",
    )
    save(output / "SUMMARY.json", result)
    return result


def main() -> int:
    """Offline only; existing serializer uses capture/MockTransport, never sends."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
