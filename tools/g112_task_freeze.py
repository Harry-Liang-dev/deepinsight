"""G112 read-only evidence inspection and isolated request freeze; never dispatch."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import duckdb

from src.adapters.providers import _html_to_text
from src.memory.contracts import ResearchContextSection
from src.memory.hybrid import HybridRead
from src.memory.hybrid_contracts import NarrativeRecord
from src.memory.temporal_relations import BoundMemoryRelation
from src.memory.vnext import content_sha256
from src.memory.vnext_contracts import MemoryReadSet
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import NativeManifest
from src.services.phase5d_temporal import receipt_bytes
from src.services.pilot_model_readiness import SNAPSHOT, request_audit

W6_COMMIT = "2f3437e871dceb899812bed65c32d3931016eaf8"
W6_MANIFEST = "564c03c2c1dd3be44e0a8102819f4ec91963c2ea59ea26d32dfb20b453b1934f"
ROLES = ("fundamental_analyst", "news_event_analyst")
ARMS = ("FULL_CONTEXT_CONTROL", "MEMORY_DELTA_CONTEXT")


def read(path: Path) -> Any:
    """Read a frozen local artifact, without touching any repository API."""
    return json.loads(path.read_text())


def sha(raw: bytes) -> str:
    """Hash exact bytes, not a wrapper identity."""
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: Any) -> None:
    """Write only the caller's G112 output directory."""
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def verify_w6(root: Path) -> int:
    """Verify original frozen W6 evidence; shared docs use their original blob."""
    manifest = root / "artifacts/g111-r1/MANIFEST.json"
    if sha(manifest.read_bytes()) != W6_MANIFEST:
        raise ValueError("G112_W6_MANIFEST_IDENTITY")
    entries = read(manifest)["files"]
    for entry in entries:
        name = entry["path"]
        if name in {"docs/MODULE_STATUS.md", "docs/DECISIONS.md"}:
            raw = subprocess.check_output(
                ["git", "show", f"{W6_COMMIT}:{name}"], cwd=root
            )
        else:
            raw = (root / name).read_bytes()
        if sha(raw) != entry["sha256"] or len(raw) != entry["bytes"]:
            raise ValueError("G112_W6_MEMBER_DRIFT:" + name)
    return len(entries)


def source_texts(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Use existing NativeManifest decoding, never NativePreserver.recover locks."""
    base = root / "artifacts/g111-r1/w3-input/artifacts/g110"
    readset = read(base / "SOURCE_READSET.json")
    if readset["source_ids"] != ["G105-GET-05", "G105-GET-09", "G105-GET-12"]:
        raise ValueError("G112_SOURCE_SCOPE")
    texts = {}
    for s in readset["sources"]:
        body = (base / s["paths"]["raw"]).read_bytes()
        manifest = NativeManifest.model_validate_json(
            (base / s["paths"]["manifest"]).read_bytes()
        )
        if (
            sha(body) != s["raw_sha256"]
            or base64.b64decode(manifest.acquisition.body_base64) != body
            or manifest.content_identity != s["native_manifest_identity"]
            or manifest.acquisition.owner != "US:MSFT"
            or manifest.acquisition.endpoint != s["url"]
        ):
            raise ValueError("G112_NATIVE_SOURCE_IDENTITY")
        text = _html_to_text(receipt_bytes(manifest.acquisition).decode())
        if sha(text.encode()) != s["normalized_sha256"]:
            raise ValueError("G112_NORMALIZATION_IDENTITY")
        texts[s["id"]] = text
    return texts, readset


def check_span(evidence: dict[str, Any], texts: dict[str, str]) -> None:
    """Reject inaccurate Unicode spans, summaries masquerading as quotations."""
    sid = evidence["source_id"]
    loc = evidence["locator"]
    text = texts[sid]
    quote = evidence.get("quote", evidence.get("content"))
    if (
        loc["kind"] != "NORMALIZED_UNICODE"
        or loc["normalization_sha256"] != sha(text.encode())
        or not 0 <= loc["start"] < loc["end"] <= len(text)
        or text[loc["start"] : loc["end"]] != quote
    ):
        raise ValueError("G112_EXACT_SOURCE_SPAN")


def no_change(root: Path) -> dict[str, Any]:
    """Consume actual populated-store reentry receipts; do not rerun the store."""
    base = root / "artifacts/g111-r1/delivery/existing-msft-reentry"
    result = read(base / "result.json")
    if (
        result["t1_counts"]
        != {"NEW_FACT": 0, "NEW_EVIDENCE_FOR_EXISTING_FACT": 0, "UNCHANGED": 11}
        or read(base / "W1_SELECTIVE_RESEARCH_INPUT.json") != {}
        or result["initial_population"] != result["final_population"]
        or result["initial_memory_snapshot"] != result["final_memory_snapshot"]
        or result["repeat_affected_research_topics"] != []
        or result["repeat_new_relation_edges"] != 0
        or result["duplicate_memory_writes"] != 0
        or result["initial_msft_population"] != 11
    ):
        raise ValueError("G112_REENTRY_NOT_NO_CHANGE")
    return {
        "control": "NO_CHANGE_SKIP_CONTROL",
        "origin": "ACTUAL_POPULATED_STORE_REENTRY",
        "input": "artifacts/g111-r1/delivery/existing-msft-reentry/result.json",
        "input_sha256": sha((base / "result.json").read_bytes()),
        "new_model_tasks": [],
        "model_request_body": None,
        "correct_disposition": "SKIP_NO_NEW_RESEARCH_TASK",
        "new_reentry_executed_by_W3": False,
        "not_a_claim_of_validated_AgentResult_reuse": True,
    }


def inspect_memory(root: Path, output: Path) -> dict[str, Any]:
    """Read frozen persisted deliveries through read-only SQL; no Memory writes."""
    count = verify_w6(root)
    base = root / "artifacts/g111-r1/delivery/actual"
    candidate = read(base / "W1_SELECTIVE_RESEARCH_INPUT.json")
    mapping = read(root / "artifacts/g111-r1/ACTUAL_ID_MAPPING.json")["actual"]
    ids = set(mapping["all_observation_ids"].values())
    historical = set(mapping["t0_alias_map"].values())
    texts, _ = source_texts(root)
    dbpath = base / "storage/memory.duckdb"
    before = sha(dbpath.read_bytes())
    delivery_refs = {}
    with duckdb.connect(str(dbpath), read_only=True) as conn:
        for role in ROLES:
            item = candidate[role]
            rs = MemoryReadSet.model_validate(item["memory_readset"])
            rows = conn.execute(
                "SELECT identity,payload FROM memory_incremental_journal "
                "WHERE stream=? AND payload LIKE ? ORDER BY sequence",
                ["g100-deliveries", "%" + rs.record_id + "%"],
            ).fetchall()
            matches = []
            for key, body in rows:
                delivery = HybridRead.model_validate_json(body)
                if delivery.read_set == rs:
                    if (
                        delivery.sha256 != key
                        or content_sha256(delivery.bundle) != rs.bundle_sha256
                    ):
                        raise ValueError("G112_PERSISTED_DELIVERY_IDENTITY")
                    matches.append((key, body, delivery))
            if len(matches) != 1:
                raise ValueError("G112_ROLE_DELIVERY_NOT_UNIQUE")
            key, body, delivery = matches[0]
            actual_items = [
                i
                for section in ResearchContextSection
                for i in delivery.bundle.items_for_section(section)
            ]
            refs = {r.artifact_id: r for r in rs.memory_refs}
            if set(refs) != ids or {i.memory_id for i in actual_items} != ids:
                raise ValueError("G112_READSET_POPULATION")
            for memory in actual_items:
                if content_sha256(memory) != refs[memory.memory_id].sha256_digest:
                    raise ValueError("G112_MEMORY_ITEM_BINDING")
            for record in item["source_attributed_memory"]:
                n = NarrativeRecord.model_validate(record["source_record"])
                if n.proposal.subject != "US:MSFT" or n.world_fact_authority:
                    raise ValueError("G112_SOURCE_MEMORY_AUTHORITY")
                check_span(
                    {
                        "source_id": n.proposal.source_ref.document_id,
                        "locator": n.proposal.evidence_locator.model_dump(),
                        "quote": n.proposal.statement,
                    },
                    texts,
                )
            save(output / f"{role}.MemoryReadSet.json", item["memory_readset"])
            (output / f"{role}.PersistedDelivery.json").write_text(body)
            delivery_refs[role] = {
                "original_record_id": rs.record_id,
                "canonical_readset_sha256": rs.sha256,
                "persisted_delivery_identity": key,
                "raw_delivery_sha256": sha(body.encode()),
                "memory_ids": sorted(refs),
                "historical_memory_ids": sorted(historical),
                "original_research_as_of": rs.research_as_of.isoformat(),
                "role": role,
                "actually_consumed_by_G112_LLM": [],
                "artifact": f"evidence/{role}.MemoryReadSet.json",
                "status": "HISTORICAL_ACTUAL_RETRIEVAL_NOT_G112_AGENT_RUN",
            }
    if sha(dbpath.read_bytes()) != before:
        raise ValueError("G112_READ_ONLY_DB_CHANGED")
    supports = read(base / "g111-r1-support.json")
    for s in supports:
        if s["memory_id"] not in ids:
            raise ValueError("G112_SUPPORT_MEMORY_ID")
        check_span(s["evidence"], texts)
    relations = read(base / "g111-r1-relations.json")
    for row in relations:
        relation = BoundMemoryRelation.model_validate(row)
        if {relation.from_memory_id, relation.to_memory_id} - ids:
            raise ValueError("G112_RELATION_ENDPOINT")
        for s in relation.source_support:
            check_span(s, texts)
    result = {
        "W6_commit": W6_COMMIT,
        "W6_manifest_sha256": W6_MANIFEST,
        "verified_manifest_members": count,
        "scope": "ACTUAL_EXISTING_MEMORY_DIFF",
        "persisted_MSFT_memory_ids": sorted(ids),
        "historical_T0_memory_ids": sorted(historical),
        "source_support_rows": len(supports),
        "relation_rows": len(relations),
        "role_readsets": delivery_refs,
        "read_only_database_sha256": before,
        "database_unchanged": True,
        "MemoryService_instantiated": False,
        "current_permissions_rechecked": False,
        "runtime_revalidation": (
            "REQUIRED; original W6 role readsets are immutable historical "
            "delivery proof, "
            "not a newly issued permission or AgentRun."
        ),
    }
    save(output / "MEMORY_INSPECTION.json", result)
    return result


def wire(
    payload: dict[str, Any], prompt: str, schema: dict[str, Any]
) -> dict[str, Any]:
    """Reuse existing in-memory SDK serializer; no key or socket access."""
    return request_audit(
        LLMProviderCall(SNAPSHOT, prompt, payload, schema), output_cap=8192
    )


def check_pair(
    full: dict[str, Any], delta: dict[str, Any], required: list[dict[str, Any]]
) -> None:
    """Match all controls and cover essential original text without Full padding."""
    if full["common"] != delta["common"]:
        raise ValueError("G112_UNMATCHED_COMMON_INPUT")
    for payload in (full, delta):
        for target in required:
            wanted = target["locator"]
            covered = False
            for parent in payload["context_evidence"]:
                loc = parent["locator"]
                if (
                    parent["source_id"] == target["source_id"]
                    and loc["normalization_sha256"] == wanted["normalization_sha256"]
                    and loc["start"] <= wanted["start"] < wanted["end"] <= loc["end"]
                ):
                    a, b = wanted["start"] - loc["start"], wanted["end"] - loc["start"]
                    covered = parent["content"][a:b] == target["content"]
                    if covered:
                        break
            if not covered:
                raise ValueError(
                    "G112_MISSING_ESSENTIAL_CONTEXT:" + target["packet_id"]
                )
        if "evaluator_answers" in payload or "expected_correct_answer" in payload:
            raise ValueError("G112_HIDDEN_ANSWER_LEAK")


def main() -> None:
    """Inspect an immutable archive read-only; no live execution interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = inspect_memory(args.root, args.output)
    save(args.output / "NO_CHANGE_SKIP_CONTROL.json", no_change(args.root))
    print(
        json.dumps(
            {
                "inspection": "PASS",
                "persisted_memory_ids": len(result["persisted_MSFT_memory_ids"]),
                "model_calls": 0,
                "memory_writes": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
