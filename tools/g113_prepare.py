"""Build offline G113 task projections from G112 retained bytes, never dispatch."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from src.memory.temporal_relations import BoundMemoryRelation
from src.schemas.research_v2_shared import digest
from src.services.native_preservation import blob_hash
from tools import g112_task_freeze as old
from tools.g111_r1_msft import MSFTMemory
from tools.g113_contract import TaskCatalog

BASE = "f6db55345feda0c8fc37f0bdf843671230b295eb"
ROOT = Path(__file__).resolve().parents[1]


def pinned(root: Path, name: str) -> Any:
    """Check original delivery manifest before consuming a retained JSON input."""
    manifest = old.read(root / "artifacts/g112-execution/SOURCE_MANIFEST.json")
    if (
        blob_hash((root / "artifacts/g112-execution/SOURCE_MANIFEST.json").read_bytes())
        != "7fc3846cdadcaad6668147083a550dc33a591fc7e2f6842000c7cbdd8d763ce9"
    ):
        raise ValueError("G113_PARENT_MANIFEST")
    entries = {x["path"]: x for x in manifest["files"]}
    raw = (root / name).read_bytes()
    if name not in entries or blob_hash(raw) != entries[name]["sha256"]:
        raise ValueError("G113_FROZEN_INPUT")
    return json.loads(raw)


def build_catalog(root: Path, role: str, arm: str) -> TaskCatalog:
    """Reverify actual native sources, persisted Memory/support and task scope.

    This fixture loader is MSFT-specific because its input is the frozen G112
    experiment. The output checker has no issuer literals or private Source
    resolver. A future live task still needs its own current Memory requery and
    forward freeze; this function issues no invocation or authority.
    """
    payload = pinned(root, f"artifacts/g112/inputs/{role}.{arm}.json")
    common = payload["common"]
    if common["role"] != role:
        raise ValueError("G113_ROLE_INPUT")
    texts, readset = old.source_texts(root)
    sources = {x["id"]: x for x in readset["sources"]}
    # Verify the original native registrations and six operand observations via
    # the existing issuer integration, only in a disposable store copy.
    with TemporaryDirectory(prefix="g113-native-") as td:
        dest = Path(td)
        shutil.copytree(
            root / "artifacts/g111-r1/delivery/actual/storage", dest / "storage"
        )
        memory = MSFTMemory(root, dest)
        for row in common["given_source_operand_metadata"]:
            fact = next(x for x in memory.facts if x["id"] == row["fact_id"])
            if fact["numeric_observation"] != row["native_observation"]:
                raise ValueError("G113_NATIVE_OPERAND_CHANGED")
            memory.check_numeric(fact)
        stored_relations = {
            k: json.loads(v) for k, v in memory.journal.entries("g111-r1-relations")
        }
        supports = [json.loads(v) for _, v in memory.journal.entries("g111-r1-support")]
        population = memory.id_map()
    views: dict[str, Any] = {}
    identities: dict[str, str] = {}

    def add(value: dict[str, Any]) -> str:
        quote = value.get("quote", value.get("content"))
        v = {
            "source_id": value["source_id"],
            "raw_sha256": value["raw_sha256"],
            "locator": value["locator"],
            "content": quote,
        }
        identity = digest(v)
        if identity in identities:
            return identities[identity]
        vid = value.get("packet_id", "G113:VIEW:" + identity)
        if not isinstance(vid, str):
            raise ValueError("G113_VIEW_ID_TYPE")
        if vid in views:
            raise ValueError("G113_VIEW_ID_COLLISION")
        old.check_span(v, texts)
        if v["raw_sha256"] != sources[v["source_id"]]["raw_sha256"]:
            raise ValueError("G113_VIEW_SOURCE_HASH")
        views[vid] = v
        identities[identity] = vid
        return vid

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if {"source_id", "raw_sha256", "locator"} <= value.keys() and (
                "quote" in value or "content" in value
            ):
                add(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    # Full payload, not just context_evidence: all IDs designate text actually
    # supplied in the prospective projection; no unseen document text is added.
    walk(payload["context_evidence"])
    walk({k: v for k, v in common.items() if k != "response_schema"})

    def support_id(e: dict[str, Any]) -> str:
        v = {
            "source_id": e["source_id"],
            "raw_sha256": e["raw_sha256"],
            "locator": e["locator"],
            "content": e["quote"],
        }
        # No implicit lazy fetch: absent exact quotes remain unavailable.
        return identities[digest(v)]

    relations = {}
    for raw in common["given_source_context_relations"]:
        rel = BoundMemoryRelation.model_validate(raw)
        if stored_relations.get(rel.relation_id) != raw:
            raise ValueError("G113_RELATION_RECEIPT")
        if rel.relation_id != digest(
            (
                rel.from_memory_id,
                rel.to_memory_id,
                rel.relation_type,
                list(rel.source_support),
                rel.effective_time,
            )
        ):
            raise ValueError("G113_RELATION_IDENTITY")
        relations[rel.relation_id] = dict(
            raw, support_view_ids=[support_id(e) for e in raw["source_support"]]
        )
    observations = {}
    for obs in common["given_system_delta"]:
        if population[obs["fact_id"]] != obs["memory_id"]:
            raise ValueError("G113_MEMORY_OBSERVATION_IDENTITY")
        matched = []
        for s in supports:
            if s["fact_id"] == obs["fact_id"]:
                try:
                    matched.append(support_id(s["evidence"]))
                except KeyError:
                    continue  # not in this task's actual visible projection
        observations[obs["fact_id"]] = dict(obs, support_view_ids=matched)
    operands = {}
    for item in common["given_source_operand_metadata"]:
        n = item["native_observation"]
        e = observations[item["fact_id"]]
        if not e["support_view_ids"]:
            raise ValueError("G113_OPERAND_EVIDENCE_NOT_SUPPLIED")
        operands[item["fact_id"]] = {
            "issuer": sources[n["source_id"]]["owner"],
            "series": digest((n["concept"], n["dimensions"])),
            "unit": "USD",
            "basis": "G112_ORIGINAL_RECAST_QUARTER_SOURCE_OBSERVATION",
            "start": n["period"]["startdate"],
            "end": n["period"]["enddate"],
            "value": n["value_usd"],
            "native_observation": n,
            "view_id": e["support_view_ids"][0],
            "canonical_financial_authority": False,
        }
    version_refs = common["actual_archived_MemoryReadSet"]["memory_refs"]
    data = {
        "contract_version": "G113_TASK_VIEW_PROJECTION_V1",
        "role": role,
        "arm": arm,
        "security": common["security"],
        "research_as_of": common["research_as_of"],
        "task": common["task"],
        "sources": {x["id"]: x for x in common["allowed_source_catalog"]},
        "views": views,
        "t0_ids": [x["memory_id"] for x in common["actual_T0_memory_context"]],
        "memory_versions": {x["artifact_id"]: x for x in version_refs},
        "observations": observations,
        "relations": relations,
        "operands": operands,
        "historical_memory": common["actual_T0_memory_context"],
        "native_scientific_admission": False,
        "current_execution_authority": "NONE_OFFLINE_HISTORICAL_CONTROL",
    }
    catalog = TaskCatalog(
        json.dumps(data, ensure_ascii=False), json.dumps(texts, ensure_ascii=False)
    )
    for vid in views:
        catalog.resolve_view(vid)
    return catalog
