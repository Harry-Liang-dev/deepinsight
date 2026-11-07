"""Offline G113-R1 delivery over existing stores; no reseeding or dispatch."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory.delivery import (
    ROLES,
    STREAM,
    DependencyCheckpoint,
    MemoryDelivery,
    dependency_changes,
    record_checkpoint,
    require_recorded_delivery,
    selective_plan,
)
from src.memory.hybrid import SourceAdmission
from src.memory.temporal_delta import ContentNode, visible
from src.memory.temporal_relations import BoundMemoryRelation
from src.memory.temporal_versions import (
    qualified_delivery,
    qualified_relations,
    version_snapshot,
)
from src.memory.vnext_contracts import Scope
from src.models.enums import ResearchScopeType
from src.schemas.research_v2_shared import digest
from tools.g111_r1_msft import SOURCE_IDS, MSFTMemory, census, research_inputs, save
from tools.g111_temporal_memory import read
from tools.g113_temporal_reuse import (
    bind_view_candidates,
    changes_and_impact,
    historical_read,
    observation_census,
    process,
    reject_revision,
)

PINS = {
    "fundamental_analyst.json": (
        "03925f9eef136a01ad678ddd45a56f0d53176c0d26e45cfb72c32b9c23ec90c1"
    ),
    "news_event_analyst.json": (
        "10c3973dd5e018bd8b031dd8baef05ed9ad1b52a560e7ab59c8a6863c99e507f"
    ),
    "W3_TASK_FREEZE.json": (
        "db9e6bd95d3d9c19e7642fe923323d6547e494f3f943b95c41cb58f89d4f4cfe"
    ),
    "W1_TRUSTED_EXPORT.json": (
        "670959e07abd2afc0e882a7bc0e50ee93fcfb8044de12170a2101c28cb39b017"
    ),
}


def pinned_inputs(root: Path) -> dict[str, Any]:
    """Only code-pinned exports of W1's trusted loader, never caller JSON trust."""
    result = {}
    for name, sha in PINS.items():
        raw = (root / "artifacts/g113-r1/inputs" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("DELIVERY_INPUT_PIN:" + name)
        result[name] = json.loads(raw)
    return result


def checked_state(memory: MSFTMemory, label: str) -> dict[str, Any]:
    """Requery MemoryService and validate current bytes, ACL, clocks and endpoints."""
    inputs = pinned_inputs(memory.root)
    if memory.access.role not in ROLES:
        raise ValueError("DELIVERY_UNREGISTERED_CONSUMER_ROLE")
    for key, body in memory.journal.entries("g100-source-catalog"):
        receipt = SourceAdmission.model_validate_json(body)
        if (
            receipt.record.proposal.subject == "US:MSFT"
            and key != receipt.record.sha256
        ):
            raise ValueError("DELIVERY_MEMORY_VERSION_IDENTITY")
    delivery = memory.retrieve(label)
    readset = qualified_delivery(memory.journal, delivery, memory.access)
    allowed = {r["artifact_id"] for r in readset["accepted"]}
    mapping = memory.id_map()
    if set(mapping.values()) - allowed:
        raise ValueError("DELIVERY_INACTIVE_EXPIRED_OR_MISSING_MEMORY")
    records = []
    dependencies: dict[str, str] = {}
    for r in delivery.supplied_records:
        mid = r.result.memory_id
        if mid not in mapping.values():
            continue
        if r.record.review_due_at <= memory.at:
            raise ValueError("DELIVERY_EXPIRED_MEMORY")
        p = r.record.proposal
        memory.access.require("READ_HISTORY", p.scope)
        records.append(
            {
                "memory_id": mid,
                "level": "L2",
                "scope": p.scope.model_dump(mode="json"),
                "owner": p.owner,
                "version": p.revision,
                "record": r.record.model_dump(mode="json"),
            }
        )
        dependencies["MEMORY:" + mid] = digest(records[-1])
    sources = []
    for sid in SOURCE_IDS:
        s = memory.temporal_sources[sid]
        raw = (memory.output / "native" / sid / (s.raw_sha256 + ".raw")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != s.raw_sha256 or not visible(s, memory.at):
            raise ValueError("DELIVERY_SOURCE_HASH_OR_CLOCK")
        row = {
            **s.model_dump(mode="json"),
            "native_manifest_identity": memory.sources[sid].manifest_identity,
            "reported_source_publication": memory.source_catalog[sid].get(
                "published_at"
            ),
            "first_public_at": None,
            "remote_unchanged_verified": False,
        }
        sources.append(row)
        dependencies["SOURCE:" + sid] = digest(row)
    # Bind complete support to its frozen observation, including authorized supplements.
    evidence = {f["id"]: {digest(e) for e in f["evidence"]} for f in memory.facts}
    supports = []
    for key, body in memory.journal.entries("g111-r1-support"):
        row = json.loads(body)
        if (
            row["fact_id"] not in evidence
            or digest(row["evidence"]) not in evidence[row["fact_id"]]
            or key != digest((row["fact_id"], row["evidence"]))
            or mapping.get(row["fact_id"]) != row["memory_id"]
        ):
            raise ValueError("DELIVERY_SOURCE_SUPPORT_MISMATCH")
        memory.validate_support(row["evidence"])
        supports.append(row)
        dependencies["SUPPORT:" + key] = digest(row)
    relations = qualified_relations(
        memory.journal,
        readset,
        access=memory.access,
        validate_revision_support=reject_revision,
        validate_support=memory.validate_support,
    )
    expected = read(memory.case / "expected/EXPECTED_RELATION_DELTA.json")["relations"]
    seeds = {s["record_id"]: s["fact_id"] for s in memory.seed_rows}
    trusted_edges = {
        digest(
            (
                mapping[p["NewFactID"]],
                mapping[seeds[p["RelatedHistoricalMemoryID"]]],
                p["RelationType"],
                p["EvidenceSupport"],
                p["EffectiveTime"],
            )
        )
        for p in expected
    }
    if {r["relation_id"] for r in relations} != trusted_edges:
        raise ValueError("DELIVERY_RELATION_ENDPOINT_OR_VERSION")
    for key, body in memory.journal.entries("g111-r1-relations"):
        edge = BoundMemoryRelation.model_validate_json(body)
        identity = digest(
            (
                edge.from_memory_id,
                edge.to_memory_id,
                edge.relation_type,
                edge.source_support,
                edge.effective_time,
            )
        )
        if (
            key != identity
            or edge.relation_id != identity
            or identity not in trusted_edges
        ):
            raise ValueError("DELIVERY_RELATION_IDENTITY_OR_SUPPORT")
        dependencies["RELATION:" + key] = digest(json.loads(body))
    record_scopes = {digest(r["scope"]): r["scope"] for r in records}
    dependencies["PERMISSION:MSFT"] = digest(
        {
            "owner": memory.access.owner,
            "allowed_consumer_roles": ROLES,
            "enabled": memory.access.enabled,
            "required_scopes": record_scopes,
        }
    )
    for stream in ("g111-invalidations", "g113-version-events"):
        dependencies["VALIDITY:" + stream] = digest(
            [
                (k, b)
                for k, b in memory.journal.entries(stream)
                if any(mid in b for mid in (*mapping.values(), *trusted_edges))
            ]
        )
    for role in ROLES:
        dependencies["TASK_CONTRACT:" + role] = digest(
            {
                "W3": inputs["W3_TASK_FREEZE.json"]["tasks"][role],
                "W1": inputs[role + ".json"]["catalog_identity"],
            }
        )
    dependencies["CONTRACT:delivery"] = digest(MemoryDelivery.model_json_schema())
    # Bind executable local dependencies independently of Git HEAD.
    paths = sorted(
        {
            *memory.root.glob("src/**/*.py"),
            *memory.root.glob("contracts/*.json"),
            *(
                memory.root / "tools" / p
                for p in (
                    "g111_temporal_memory.py",
                    "g111_r1_msft.py",
                    "g113_temporal_reuse.py",
                    "g113_r1_delivery.py",
                )
            ),
        }
    )
    code = {
        str(p.relative_to(memory.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    dependencies["CONTRACT:implementation_closure"] = digest(code)
    cp = DependencyCheckpoint(
        checked_at=memory.at,
        memory_snapshot=version_snapshot(memory.journal),
        dependencies=dependencies,
    )
    return {
        "checkpoint": cp,
        "readset": readset,
        "relations": relations,
        "sources": sources,
        "records": records,
        "supports": supports,
        "code_fingerprints": code,
        "delivery": delivery,
    }


def view_mapping(memory: MSFTMemory, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Map exact W1 views through original native validation, never fuzzy text."""
    inputs = pinned_inputs(memory.root)
    result: list[dict[str, Any]] = []
    for role in ROLES:
        fetched_views = []
        start_index = len(result)
        cat = inputs[role + ".json"]
        if cat["catalog_identity"] != digest(cat["catalog"]):
            raise ValueError("DELIVERY_W1_CATALOG_ID")
        for vid, v in cat["resolved_views"].items():
            if v != cat["catalog"]["views"][vid]:
                raise ValueError("DELIVERY_W1_RESOLVED_VIEW")
            e = dict(
                source_id=v["source_id"],
                raw_sha256=v["raw_sha256"],
                native_manifest_identity=memory.sources[
                    v["source_id"]
                ].manifest_identity,
                locator=v["locator"],
                quote=v["content"],
            )
            fetched = memory.fetch_evidence(e)
            fetched_views.append(fetched)
            ident = "g113-view:" + digest(
                {
                    k: fetched[k]
                    for k in (
                        "source_id",
                        "source_sha256",
                        "native_manifest_identity",
                        "locator",
                        "returned_text",
                    )
                }
            )
            mids = sorted(
                {s["memory_id"] for s in state["supports"] if s["evidence"] == e}
            )
            edges = sorted(
                r["relation_id"] for r in state["relations"] if e in r["source_support"]
            )
            result.append(
                {
                    "role": role,
                    "w1_view_id": vid,
                    "w1_catalog_identity": cat["catalog_identity"],
                    "w6_view_id": ident,
                    "source_support": e,
                    "exact_memory_support_ids": mids,
                    "exact_relation_support_ids": edges,
                    "purpose": (
                        "ENDPOINT_SUPPORT"
                        if mids or edges
                        else "REQUIRED_CONTEXT_AND_LIMITATIONS"
                    ),
                    "mapping_basis": "EXACT_SOURCE_HASH_NORMALIZATION_SPAN_AND_TEXT",
                    "trust_basis": PINS[role + ".json"],
                    "current_readset": digest(state["readset"]),
                }
            )
        catalog = bind_view_candidates(
            memory,
            {
                role: {
                    "required_source_excerpt_views": fetched_views,
                }
            },
        )[role]
        for row in result[start_index:]:
            row["w6_catalog_id"] = catalog["evidence_view_catalog_id"]
    return result


def revalidate_for_send(
    memory: MSFTMemory, candidate: MemoryDelivery
) -> dict[str, Any]:
    """Trusted composition calls this immediately before W1 sends any candidate."""
    require_recorded_delivery(memory.journal, candidate)
    current = checked_state(memory, "r1-presend-revalidation")
    cp = current["checkpoint"]
    if (
        candidate.checkpoint.memory_snapshot != cp.memory_snapshot
        or candidate.checkpoint.dependencies != cp.dependencies
    ):
        raise ValueError("DELIVERY_STALE_DEPENDENCY_OR_CAS")
    if candidate.research_as_of > cp.checked_at:
        raise ValueError("DELIVERY_FUTURE_CUTOFF")
    # Every handed-off exact span is fetched again under the current ACL.
    views = view_mapping(memory, current)
    expected = [
        {k: v for k, v in r.items() if k not in ("current_readset", "w6_catalog_id")}
        for r in views
    ]
    prior = [
        {k: v for k, v in r.items() if k not in ("current_readset", "w6_catalog_id")}
        for r in candidate.evidence_view_mapping
    ]
    if prior != expected:
        raise ValueError("DELIVERY_VIEW_MAPPING_CHANGED")
    return {
        "status": "REVALIDATED_CANDIDATE_NOT_DISPATCH_AUTHORIZATION",
        "current_readset": current["readset"],
        "checkpoint": cp.model_dump(mode="json"),
        "actually_consumed_memory_ids": [],
    }


def resolve_delivery_view(
    memory: MSFTMemory, candidate: MemoryDelivery, *, role: str, w1_view_id: str
) -> dict[str, Any]:
    """Use trusted current reader credentials, then resolve exact candidate support."""
    if memory.access.role != role or role not in ROLES:
        raise ValueError("DELIVERY_CONSUMER_ROLE")
    revalidate_for_send(memory, candidate)
    row = next(
        (
            r
            for r in candidate.evidence_view_mapping
            if r["role"] == role and r["w1_view_id"] == w1_view_id
        ),
        None,
    )
    if row is None:
        raise ValueError("DELIVERY_UNKNOWN_VIEW")
    return memory.fetch_evidence(row["source_support"])


def run_case(root: Path, output: Path, *, controlled: bool) -> dict[str, Any]:
    """Copy complete frozen stores and reconstruct history without reseeding."""
    original = (
        root / "artifacts/g113/release" / ("controlled" if controlled else "actual")
    )
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(original / "storage", output / "storage")
    m = MSFTMemory(root, output)
    before = m.population()
    before_snapshot = m.snapshot()
    state0 = checked_state(m, "r1-initial")
    cp0 = state0["checkpoint"]
    record_checkpoint(m.journal, cp0, expected=m.journal.entries_with_sequence(STREAM))
    ids = m.id_map()
    support_ids = {k for k, _ in m.journal.entries("g111-r1-support")}
    history = None
    cutoff = None
    if controlled:
        archived = read(original / "RESULT.json")["t0"]["temporal_cycle"]
        t0_ids = {n["memory_id"] for n in archived["nodes"]}
        node_times = [
            ContentNode.model_validate(n).created_at for n in archived["nodes"]
        ]
        cutoff = max(node_times)
        history = historical_read(m, cutoff, "r1-real-persisted-t0")
        if {r["artifact_id"] for r in history["accepted"]} != t0_ids:
            raise ValueError("DELIVERY_HISTORICAL_T0_NOT_REPRODUCED")
        ids = {k: v for k, v in ids.items() if v in t0_ids}
        support_ids = {
            k
            for k, b in m.journal.entries("g111-r1-support")
            if datetime.fromisoformat(json.loads(b)["created_at"]) <= cutoff
        }
    repeats = [process(m, sid, "r1-retained-repeat-" + sid) for sid in SOURCE_IDS]
    state = checked_state(m, "r1-current")
    cp = state["checkpoint"]
    checked_changes = dependency_changes(m.journal, cp0, cp)
    if checked_changes:
        raise ValueError("DELIVERY_UNEXPECTED_BASELINE_DEPENDENCY_CHANGE")
    rows = observation_census(m, ids, support_ids)
    relation_delta = [
        {
            "relation_id": r["relation_id"],
            "kind": (
                "RELATION_UPDATE"
                if cutoff is not None
                and datetime.fromisoformat(r["created_at"]) > cutoff
                else "UNCHANGED"
            ),
            "relation": r,
        }
        for r in state["relations"]
    ]
    changes = [
        {
            "key": ("SUPPORT:" if r["kind"] == "ADDITIONAL_EVIDENCE" else "MEMORY:")
            + r["memory_id"],
            "cause": r["kind"],
            "memory_id": r["memory_id"],
        }
        for r in rows
        if r["kind"] != "UNCHANGED"
    ] + [
        {"key": "RELATION:" + r["relation_id"], "cause": r["kind"]}
        for r in relation_delta
        if r["kind"] != "UNCHANGED"
    ]
    tasks = pinned_inputs(root)["W3_TASK_FREEZE.json"]["tasks"]
    plan = selective_plan(
        at=cp.checked_at,
        previous_identity=cp0.identity,
        changes=changes,
        dependencies=cp.dependencies,
        tasks=tasks,
        scope=Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:US:MSFT"),
    )
    inputs = research_inputs(
        m, state["delivery"], census(m, ids, support_ids), state["relations"]
    )
    views = view_mapping(m, state)
    for role, packet in inputs.items():
        packet["task_contract"] = tasks[role]
        original_access = m.access
        m.access = original_access.model_copy(update={"role": role})
        q = historical_read(m, cp.checked_at, "r1-role-cutoff-" + role)
        m.access = original_access
        packet["qualified_memory_readset"] = q
        packet["memory_readset"] = q["upstream_g84_readset"]
        packet["research_as_of"] = cp.checked_at.isoformat()
        for view in packet["required_source_excerpt_views"]:
            view["retrieved_at"] = view["research_as_of"]
            view["research_as_of"] = cp.checked_at.isoformat()
        packet["required_evidence_and_counterevidence"] = [
            v for v in views if v["role"] == role
        ]
        packet["given_delta_credit"] = "SYSTEM_SUPPLIED_NOT_MODEL_DISCOVERY"
        packet["mode"] = "HISTORICAL_DIAGNOSTIC_NOT_NEW_MARKET_EVENT"
        packet["qualified_agent_result_reuse"] = "NOT_EVALUABLE"
        packet["w1_task_operands"] = pinned_inputs(root)[role + ".json"]["catalog"][
            "operands"
        ]
        packet["do_not_transplant_old_catalog_memory_ids"] = True
    inputs = bind_view_candidates(m, inputs)
    coverage = {
        r: {
            "trusted_w1_views_required": 13,
            "exact_views_retained": len([v for v in views if v["role"] == r]),
            "dropped_views": [],
            "shortened_to_save_tokens": False,
        }
        for r in ROLES
    }
    candidate = MemoryDelivery(
        mode=(
            "HISTORICAL_DIAGNOSTIC_NOT_NEW_MARKET_EVENT"
            if controlled
            else "ACTUAL_NOCHANGE"
        ),
        research_as_of=cp.checked_at,
        checkpoint=cp,
        previous_checkpoint_id=cp0.identity,
        historical_memory_ids=tuple(sorted(ids.values())),
        current_memory=tuple(state["records"]),
        sources=tuple(state["sources"]),
        delta_census=tuple(rows),
        relation_delta=tuple(relation_delta),
        qualified_memory_readset=state["readset"],
        impact_plan=plan,
        specialist_inputs=inputs,
        evidence_view_mapping=tuple(views),
        evidence_coverage=coverage,
        dependency_receipt={
            "actual_current_dependency_changes": checked_changes,
            "baseline": cp0.model_dump(mode="json"),
            "historical_readset": history,
            "historical_delta_is_new_now": False,
            "code_fingerprints": state["code_fingerprints"],
            "input_pins": PINS,
        },
        known_unknowns=(
            "REAL_SOURCE_REVISION_NOT_DEMONSTRATED",
            "REAL_CROSS_COMPANY_NOT_DEMONSTRATED",
            "QUALIFIED_AGENT_RESULT_NOT_EVALUABLE",
            "FIRST_PUBLIC_TIME_UNKNOWN",
            "NO_REMOTE_UNCHANGED_PROOF",
            "NO_PRE_R1_TASK_CHECKPOINT_NO_CLAIM_OF_AGENTRESULT_REUSE",
            "NO_SCIENTIFIC_ADMISSION",
            "AZURE_STANDALONE_PROFIT_AI_ROI_AND_CAUSALITY_NOT_ESTABLISHED",
        ),
    )
    body = candidate.model_dump(mode="json")
    with m.journal.serialized():
        if version_snapshot(m.journal) != cp.memory_snapshot:
            raise ValueError("DELIVERY_STALE_SNAPSHOT")
        m.journal.append(
            "g113-r1-deliveries",
            digest(body),
            json.dumps(body, sort_keys=True),
            len(m.journal.entries("g113-r1-deliveries")),
        )
    reopened = MSFTMemory(root, output)
    presend = revalidate_for_send(reopened, candidate)
    assert before == reopened.population() and before_snapshot == reopened.snapshot()
    assert all(r["temporal_cycle"]["duplicate_research_skipped"] for r in repeats)
    reuse = changes_and_impact(reopened, rows, relation_delta)["agent_result_reuse"]
    result = {
        "mode": candidate.mode,
        "initial_memory_count": len(before),
        "final_memory_count": len(before),
        "msft_memory_count": len(reopened.id_map()),
        "counts": dict(Counter(r["kind"] for r in rows)),
        "affected_candidates": plan["affected_specialist_candidates"],
        "new_memory_writes": 0,
        "duplicate_relation_writes": 0,
        "content_and_original_streams_unchanged": True,
        "audit_writes_only": True,
        "repeated_retained_sources_skipped": len(repeats),
        "extractor_calls": sum(r["temporal_cycle"]["extractor_calls"] for r in repeats),
        "admission_calls": sum(r["temporal_cycle"]["admission_calls"] for r in repeats),
        "model_calls": 0,
        "provider_gets": 0,
        "actual_model_calls_saved": "NOT_MEASURED",
        "actual_remote_gets_saved": "UNKNOWN",
        "token_savings": "UNKNOWN",
        "agent_result_reuse": reuse,
        "next_cycle_revalidation": presend["status"],
        "w1_view_mappings": len(views),
        "historical_status_unchanged": "PARTIAL",
    }
    for name, value in {
        "DELIVERY": body,
        "RESULT": result,
        "BEFORE_SNAPSHOT": before_snapshot,
        "AFTER_SNAPSHOT": reopened.snapshot(),
        "POPULATION_BEFORE": before,
        "POPULATION_AFTER": reopened.population(),
        "DELTA_CENSUS": rows,
        "RELATION_DELTA": relation_delta,
        "IMPACT_PLAN": plan,
        "READSET": state["readset"],
        "EVIDENCE_VIEW_MAP": views,
        "NEXT_CYCLE_REVALIDATION": presend,
        "REPEAT_RECEIPTS": repeats,
        "W1_INPUT": inputs,
    }.items():
        save(output / (name + ".json"), value)
    return result


def main() -> int:
    """Run isolated actual and historical cases with network access rejected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def deny(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("G113_R1_NETWORK_FORBIDDEN")

    socket.socket.connect = deny  # type: ignore[method-assign]
    socket.create_connection = deny
    root = Path(__file__).resolve().parents[1]
    results = {
        k: run_case(root, args.output / k, controlled=k == "controlled")
        for k in ("actual", "controlled")
    }
    save(args.output / "RESULTS.json", results)
    print(
        json.dumps(
            {
                k: {
                    x: v[x]
                    for x in ("counts", "affected_candidates", "w1_view_mappings")
                }
                for k, v in results.items()
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
