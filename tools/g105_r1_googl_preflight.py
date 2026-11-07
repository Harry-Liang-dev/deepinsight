"""Read-only G106 source/task qualification; never construct an AgentInvocation."""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.adapters.providers import _html_to_text
from src.services.native_preservation import blob_hash
from src.services.phase5d_temporal import pointer
from src.services.research_vnext.radar_pilot import encoded
from tools.g105_binding_controls import store


def read(path: Path) -> Any:
    """Read exact retained JSON, no retrieval or API access."""
    return json.loads(path.read_bytes())


def verify(root: Path) -> dict[str, Any]:
    """Verify source views with their restrictive wrapper, not its typed core."""
    frozen = root / "artifacts/g106/freeze-v2"
    binding = read(frozen / "W1_BINDING_INPUT.json")
    for item in binding["artifact_inputs"].values():
        if blob_hash((root / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("G105_R1_G106_FROZEN_INPUT_MISMATCH")
    mandate = read(frozen / "RESEARCH_MANDATE.json")
    spec = read(frozen / "MODEL_INPUT_SPEC.json")
    readset = read(frozen / "SOURCE_READSET.json")
    views = read(frozen / "EVIDENCE_VIEW.json")
    tasks = read(frozen / "SPECIALIST_RESEARCH_TASKS.json")
    memory = read(frozen / "MEMORY_READSET_REQUIREMENTS.json")
    allowed = {"G105-GET-02", "G105-GET-07"}
    if (
        set(mandate["allowed_source_ids"]) != allowed
        or mandate["allowed_security_ids"] != ["US:GOOGL"]
        or mandate["model_execution_authorized"]
        or mandate["AgentInvocation_authorization_published"]
        or spec["execution_authorized"]
        or spec["canonical_Claim_Evidence_IDs"]
        or spec["financial_proof_allowlist"]
        or spec["original_minimums"]
        != {"fundamental_analyst": 2, "news_event_analyst": 0}
        or memory["actual_AgentRun"] is not None
        or memory["actual_MemoryReadSet"] is not None
    ):
        raise ValueError("G105_R1_G106_RESTRICTIVE_WRAPPER")
    cutoff = datetime.fromisoformat(spec["research_as_of"])
    if readset["research_as_of"] != spec["research_as_of"]:
        raise ValueError("G105_R1_G106_ASOF")
    sources = {s["id"]: s for s in readset["sources"]}
    if set(sources) != allowed:
        raise ValueError("G105_R1_G106_SOURCE_SCOPE")
    decoded = {}
    for sid, source in sources.items():
        directory = (root / source["source_receipt_path"]).parent
        native_store = store(directory)
        n = native_store.recover(source["native_manifest_identity"])
        a = n.acquisition
        raw = (directory / (a.body_sha256 + ".raw")).read_bytes()
        if (
            a.body_sha256 != source["raw_sha256"]
            or blob_hash(raw) != source["raw_sha256"]
            or a.owner != "US:GOOGL"
            or a.endpoint != source["url"]
            or n.status_code != 200
            or datetime.fromisoformat(source["ingested_at"]) != n.ingested_at
            or datetime.fromisoformat(source["observed_at"]) != a.observed_at
            or max(n.ingested_at, a.observed_at) > cutoff
        ):
            raise ValueError("G105_R1_G106_NATIVE_IDENTITY")
        decoded[sid] = (
            gzip.decompress(raw) if a.content_encoding == "gzip" else raw
        ).decode()
    metadata = json.loads(decoded["G105-GET-02"])
    if (
        f"{int(metadata['cik']):010d}" != "0001652044"
        or "GOOGL" not in metadata["tickers"]
    ):
        raise ValueError("G105_R1_G106_ISSUER")
    verified_views = []
    for view in views["views"]:
        source = sources[view["source_id"]]
        if (
            view["canonical_Evidence_ID"] is not None
            or view["world_fact_authority"]
            or view["numeric_fact_admission"]
            or view["issuer_cik"] != "0001652044"
            or view["security_scope"] != "US:GOOGL"
            or view["raw_source_sha256"] != source["raw_sha256"]
            or view["native_manifest_identity"] != source["native_manifest_identity"]
            or view["source_url"] != source["url"]
            or datetime.fromisoformat(view["research_as_of"]) != cutoff
            or view["available_at"] != source["available_at_conservative"]
            or view["ingested_at"] != source["ingested_at"]
            or view["observed_at"] != source["observed_at"]
        ):
            raise ValueError("G105_R1_G106_VIEW_IDENTITY")
        loc = view["locator"]
        body = decoded[view["source_id"]]
        if loc["kind"] == "JSON_POINTER":
            content = pointer(json.loads(body), loc["pointer"])
        elif loc["kind"] == "NORMALIZED_UNICODE":
            text = _html_to_text(body)
            if blob_hash(text.encode()) != loc["normalization_sha256"]:
                raise ValueError("G105_R1_G106_NORMALIZATION")
            content = text[loc["start"] : loc["end"]]
            if content != loc["quote"]:
                raise ValueError("G105_R1_G106_LOCATOR")
        else:
            raise ValueError("G105_R1_G106_UNSUPPORTED_LOCATOR")
        if (
            content != view["content"]
            or blob_hash(encoded(content)) != view["content_identity"]
        ):
            raise ValueError("G105_R1_G106_VIEW_CONTENT")
        verified_views.append(
            {
                "view_id": view["view_id"],
                "source_id": view["source_id"],
                "locator": loc,
                "content_identity": view["content_identity"],
                "canonical_evidence_id": None,
                "world_fact_authority": False,
            }
        )
    if len(verified_views) != 19:
        raise ValueError("G105_R1_G106_VIEW_POPULATION")
    baseline_sha = blob_hash(
        (frozen / "DETERMINISTIC_BASELINE_FREEZE.json").read_bytes()
    )
    if (
        baseline_sha
        != "fc3b88a4c7f52435c17c844e5f672c64e1d38996d7b1d903b1c02e860aad78bf"
    ):
        raise ValueError("G105_R1_G106_BASELINE")
    task_bindings = []
    for task in tasks:
        if (
            set(task["source_ids"]) != allowed
            or task["security"] != "US:GOOGL"
            or task["CIK"] != "0001652044"
            or task["full_baseline_sha256"] != baseline_sha
            or datetime.fromisoformat(task["research_as_of"]) != cutoff
        ):
            raise ValueError("G105_R1_G106_TASK_SCOPE")
        task_bindings.append(
            {
                "original_task_id": task["task_id"],
                "original_task_sha256": blob_hash(encoded(task)),
                "role": task["agent_role"],
                "baseline_sha256": baseline_sha,
                "source_ids": task["source_ids"],
                "research_as_of": task["research_as_of"],
                "mandate_wrapper_sha256": blob_hash(
                    (frozen / "RESEARCH_MANDATE.json").read_bytes()
                ),
                "run_identity": None,
                "agent_invocation": None,
            }
        )
    contexts = []
    for row in spec["context_files"]:
        raw = (root / row["path"]).read_bytes()
        if blob_hash(raw) != row["sha256"] or len(raw) != row["utf8_bytes"]:
            raise ValueError("G105_R1_G106_MODEL_DRAFT")
        json.loads(raw)
        contexts.append(
            {
                **row,
                "json_parse": "PASS",
                "token_count": "NOT_MEASURED",
                "sdk_request": "NOT_CREATED",
                "execution_authorized": False,
            }
        )
    return {
        "schema": "G105_R1_G106_OFFLINE_QUALIFICATION_V1",
        "G106_GOOGL_SOURCE_BINDING": "PARTIAL",
        "native_source_views_verified": verified_views,
        "sources_verified": 2,
        "original_tasks_bound": task_bindings,
        "model_drafts": contexts,
        "G106_GOOGL_CANONICAL_EVIDENCE": "NOT_READY",
        "canonical_evidence_count": 0,
        "G106_GOOGL_NUMERIC_ADMISSION": "NOT_READY",
        "numeric_allowlist": [],
        "G106_GOOGL_SCIENTIFIC_EXECUTION": "BLOCKED",
        "G106_MANDATE_WRAPPER_PRESERVED": "PASS",
        "actual_run": None,
        "actual_memory_readset": None,
        "baseline_sha256": baseline_sha,
        "source_task_binder_invocation": "NOT_CALLED_NO_RUN_OR_EXECUTION_MANDATE",
        "remaining": [
            (
                "Preparation-only wrapper forbids model execution; "
                "compatibility projection is not a grant"
            ),
            (
                "No canonical Evidence and no native core-financial "
                "registration; Fundamental minimum two cannot be satisfied"
            ),
            "No permitted AgentRun or actual MemoryReadSet; none invented",
            (
                "Frozen tasks created after original research cutoff; a later "
                "binding must explicitly reconcile task-record clocks without "
                "backdating or changing frozen G106"
            ),
            (
                "No verified model/route/serialized SDK request or approved "
                "paid budget; byte sizes are not token counts"
            ),
        ],
        "new_model_calls": 0,
        "new_provider_calls": 0,
    }


def main() -> None:
    """Write a new non-execution report from pinned copies of G106."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.root)
    with args.output.open("x") as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
