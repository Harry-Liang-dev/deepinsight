"""Offline eight-request freeze from exact W3 binding; no live execution entry.

Candidate Episode IDs are not installed ACLs, and historical Memory context is
not a current read authorization. The unchanged R6 sender/meter cannot dispatch
this new model population until separately integrated and independently reviewed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r6_contract as r6_contract
from tools import g113_r6_final as r6
from tools import g113_r7_contract as contract
from tools import g113_r7_prepare as preparation
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT, covers

VERSION = "G113_R7_OFFLINE_FINAL_REQUEST_FREEZE_V1"
INTAKE = "artifacts/g113-r7/w3-intake-v1"
FINAL = "artifacts/g113-r7/w3-final-binding-v1"
W3_REPOSITORY = Path("/home/harry/deepinsight-g113-w3-r7")
W3_SOURCE = "ef164e1ea591912c184242588f185894123915cc"
W3_ISSUANCE = "1eb7d7347e5d4284f0b5873e84e152dca83a85ec"
W3_MANIFEST = "02fc7eb7323ab6c55afd61481e0201eac79db10ae50658745f6f0fc92d6368c1"
W3_RECEIPT = "772e4ca58d76ee1165d9767261d562d2db32b0f99610ac9d6d92b7ef2a9b6fed"
W3_ORIGINAL_MANIFEST = (
    "0b6edc009176060533fb0394d6d356d74ff3db9fce866f5e27f8247da6de1041"
)
INTERFACE_SOURCE = "1be674e06d10a235a46814c2509f5df5393e528e"
INTERFACE_MANIFEST = "6d8424f563b095d7fea335cec9e04fddcd1841d0d6375bf7597e741b0fa7e3c8"
INTERFACE_MODULE = "df0b8704ba4e059ecf3b246df234286fb77178978cbfb2b98ce1100b5c5d02c0"
ORDER = ("A1", "B1", "B2", "A2", "A3", "B3", "B4", "A4")


def _git(repository: Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repository), "show", commit + ":" + path],
        stderr=subprocess.PIPE,
    )


def _manifest(root: Path) -> dict[str, Any]:
    raw = (root / FINAL / "SOURCE_MANIFEST.json").read_bytes()
    if blob_hash(raw) != W3_MANIFEST:
        raise ValueError("R7_FINAL_W3_MANIFEST")
    data: dict[str, Any] = json.loads(raw)
    if data["source_commit"] != W3_SOURCE:
        raise ValueError("R7_FINAL_W3_SOURCE")
    if raw != _git(
        W3_REPOSITORY,
        W3_ISSUANCE,
        "artifacts/g113-w3-r7/final-binding-v1/SOURCE_MANIFEST.json",
    ):
        raise ValueError("R7_FINAL_W3_GIT_MANIFEST")
    return data


def checked(root: Path, name: str) -> bytes:
    """Read exact unmodified W3 candidate from final manifest and Git source."""
    base = root / INTAKE
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("R7_W3_MEMBER_PATH")
    manifest = _manifest(root)
    full = "artifacts/g113-w3-r7/" + name
    entries = [e for e in manifest["members"] if e["path"] == full]
    raw = path.read_bytes()
    if (
        len(entries) != 1
        or blob_hash(raw) != entries[0]["sha256"]
        or raw != _git(W3_REPOSITORY, W3_SOURCE, full)
    ):
        raise ValueError("R7_W3_MEMBER_IDENTITY")
    return raw


def matched(root: Path = ROOT) -> dict[str, Any]:
    """Verify genuine prospective W3 final semantic binding, never a PASS constant."""
    _manifest(root)
    path = "artifacts/g113-w3-r7/final-binding-v1/W3_R7_FINAL_SEMANTIC_BINDING.json"
    raw = (root / FINAL / "W3_R7_FINAL_SEMANTIC_BINDING.json").read_bytes()
    if blob_hash(raw) != W3_RECEIPT or raw != _git(W3_REPOSITORY, W3_SOURCE, path):
        raise ValueError("R7_FINAL_W3_RECEIPT")
    if raw != _git(W3_REPOSITORY, W3_ISSUANCE, path):
        raise ValueError("R7_FINAL_W3_GIT_ISSUANCE")
    receipt: dict[str, Any] = json.loads(raw)
    published = (root / FINAL / "W1_PUBLISHED_SOURCE_MANIFEST.json").read_bytes()
    if (
        blob_hash(published) != INTERFACE_MANIFEST
        or json.loads(published)["source_commit"] != INTERFACE_SOURCE
        or blob_hash(_git(root, INTERFACE_SOURCE, "tools/g113_r7_contract.py"))
        != INTERFACE_MODULE
        or published
        != _git(
            W3_REPOSITORY,
            W3_SOURCE,
            "artifacts/g113-w3-r7/final-binding-v1/W1_PUBLISHED_SOURCE_MANIFEST.json",
        )
    ):
        raise ValueError("R7_INITIAL_INTERFACE_SOURCE")
    if (
        receipt["W3_R7_SEMANTIC_BINDING"] != "PASS"
        or receipt["W3_FINAL_TASK_BINDING"] != "PASS"
        or receipt["W1_source_commit"] != INTERFACE_SOURCE
        or receipt["W1_manifest_sha256"] != INTERFACE_MANIFEST
        or receipt["W1_interface_module_sha256"] != INTERFACE_MODULE
        or receipt["interface"] != contract.VERSION
        or receipt["checker"] != contract.CHECKER_VERSION
        or blob_hash((root / "tools/g113_r7_contract.py").read_bytes())
        != INTERFACE_MODULE
        or blob_hash((root / INTAKE / "SOURCE_MANIFEST.json").read_bytes())
        != W3_ORIGINAL_MANIFEST
    ):
        raise ValueError("R7_FINAL_W3_INTERFACE_MATCH")
    handoff = json.loads(checked(root, "W1_FINAL_FREEZE_HANDOFF.json"))
    if tuple(handoff["cross_arm_order_proposal"]) != ORDER:
        raise ValueError("R7_W3_SAMPLE_ORDER")
    original = r6.matched(root)["task_slots"]
    if [(s["role"], s["context"], s["slot"]) for s in receipt["slots"]] != [
        (s["role"], s["arm"], s["slot"]) for s in original
    ]:
        raise ValueError("R7_FINAL_W3_POPULATION")
    return receipt


def b_catalog(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Bind W3's exact topic selection while retaining the genuine source population."""
    signed = next(s for s in matched(root)["slots"] if s["slot"] == row["slot"])
    if row != signed:
        raise ValueError("R7_B_SLOT_IDENTITY")
    parent_row = next(
        s for s in r6.matched(root)["task_slots"] if s["slot"] == row["slot"]
    )
    parent = r6.catalog_for(root, parent_row)
    name = "candidates/B/" + row["slot"] + "/"
    data = json.loads(checked(root, name + "TASK_CATALOG.json"))
    expected = contract.prospective_catalog(
        parent, topic_observation_ids=data["topic_observation_ids"]
    )
    if data != expected.data() or expected.identity != row["task_identity"]:
        raise ValueError("R7_B_TRUSTED_CATALOG_DRIFT")
    actual = TaskCatalog(json.dumps(data, ensure_ascii=False), parent.source_texts_json)
    schema = json.loads(checked(root, name + "RESPONSE_SCHEMA.json"))
    if schema != contract.output_schema(actual):
        raise ValueError("R7_B_SCHEMA_DRIFT")
    return actual


def validate_payload(
    catalog: TaskCatalog,
    payload: dict[str, Any],
    parent_payload: dict[str, Any],
) -> None:
    """Require exact evidence/index; never infer content support."""
    data = catalog.data()
    if (
        payload["output_schema"] != contract.output_schema(catalog)
        or payload["task_identity"] != catalog.identity
    ):
        raise ValueError("R7_B_PAYLOAD_SCHEMA_IDENTITY")
    # W3 changed only these three existing payload fields and added three trusted
    # projections. It did not remove context/counterevidence or change research.
    for key in parent_payload.keys() - {
        "output_schema",
        "task_identity",
        "task_version",
    }:
        if payload.get(key) != parent_payload[key]:
            raise ValueError("R7_B_SOURCE_MEMORY_PAYLOAD_DRIFT")
    additions = {
        "provided_memory_inventory",
        "research_cutoff_authority",
        "topic_selection_index",
    }
    if set(payload) != set(parent_payload) | additions:
        raise ValueError("R7_B_PAYLOAD_FIELD_DRIFT")
    for key in additions:
        if payload[key] != data[key]:
            raise ValueError("R7_B_TRUSTED_PROJECTION_DRIFT")
    texts = json.loads(catalog.source_texts_json)
    for packet in payload["context_evidence"]:
        if not covers(packet, packet, texts):
            raise ValueError("R7_B_SOURCE_SPAN")
    for view in data["views"].values():
        if not any(
            covers(packet, view, texts) for packet in payload["context_evidence"]
        ):
            raise ValueError("R7_B_REQUIRED_EVIDENCE_COVERAGE")


def b_call(root: Path, row: dict[str, Any]) -> tuple[LLMProviderCall, TaskCatalog]:
    """Assemble only the original signed W3 bytes and original Provider call type."""
    catalog = b_catalog(root, row)
    prefix = "candidates/B/" + row["slot"] + "/"
    payload = json.loads(checked(root, prefix + "MODEL_INPUT_CANDIDATE.json"))
    parent_row = next(
        s for s in r6.matched(root)["task_slots"] if s["slot"] == row["slot"]
    )
    old, _ = preparation.model_only_call(parent_row)
    validate_payload(catalog, payload, old.input_payload)
    prompt = checked(root, prefix + "prompt.txt").decode()
    return (
        LLMProviderCall(
            preparation.active_model(), prompt, payload, contract.output_schema(catalog)
        ),
        catalog,
    )


def source_binding(root: Path, source_commit: str) -> dict[str, Any]:
    """Pin actual SDK/config/interface modules to a real immutable source object."""
    names = {
        *r6.runtime(root),
        "src/core/settings.py",
        "tools/g113_r7_prepare.py",
        "tools/g113_r7_contract.py",
        "tools/g113_r7_freeze.py",
    }
    runtime = {p: blob_hash((root / p).read_bytes()) for p in sorted(names)}
    for path, sha in runtime.items():
        if blob_hash(_git(root, source_commit, path)) != sha:
            raise ValueError("R7_EXECUTION_SOURCE_DRIFT")
    return dict(
        source_commit=source_commit,
        source_manifest_ref="SOURCE_MANIFEST.json",
        runtime_modules=runtime,
    )


def prepare(output: Path, *, source_commit: str, root: Path = ROOT) -> dict[str, Any]:
    """Serialize eight final offline requests; expose no sending or ACL installation."""
    preparation.active_model()
    receipt = matched(root)
    source = source_binding(root, source_commit)
    output.mkdir(parents=True, exist_ok=False)
    at = datetime.now(UTC)
    operation = "G113-R7-OFFLINE-FREEZE-" + at.strftime("%Y%m%dT%H%M%S%fZ")
    population = []
    parents = r6.matched(root)["task_slots"]
    for ordinal, label in enumerate(ORDER, 1):
        i, arm = int(label[1:]) - 1, label[0]
        row = parents[i]
        if arm == "A":
            call, _ = preparation.model_only_call(row)
            catalog = r6.catalog_for(root, row)
            checker = r6_contract.CHECKER_VERSION
        else:
            call, catalog = b_call(root, receipt["slots"][i])
            checker = contract.CHECKER_VERSION
        audit = preparation.sdk_preview(call)
        repeat = preparation.sdk_preview(call)
        if audit["raw"] != repeat["raw"]:
            raise ValueError("R7_FINAL_SDK_NONDETERMINISTIC")
        raw = audit.pop("raw").encode()
        if arm == "A":
            old_raw = (
                root
                / "artifacts/g113-r6-final/freeze-final"
                / row["slot"]
                / "sdk-request.raw"
            ).read_bytes()
            old, new = json.loads(old_raw), json.loads(raw)
            if (
                old.pop("model") != "qwen3.7-flash-2026-07-15"
                or new.pop("model") != preparation.MODEL
                or old != new
            ):
                raise ValueError("R7_A_ONLY_MODEL_CHANGE")
        name = f"{ordinal:02}-{label}-{row['role']}-{row['arm']}"
        folder = output / name
        identity = dict(
            ordinal=ordinal,
            sample_id=label,
            slot=name,
            arm=arm,
            context=row["arm"],
            role=row["role"],
            semantic_task_identity=catalog.identity,
            operational_task_id=operation + ":task:" + label,
            episode_candidate_id=operation + ":episode:" + label,
            invocation_candidate_id=operation + ":invocation:" + label,
            request_sha256=blob_hash(raw),
            response_schema_identity=digest(call.response_schema),
            checker=checker,
            current_memory_readset="NOT_INSTALLED",
            current_episode_acl="NOT_INSTALLED",
            real_dispatch_authorized=False,
        )
        durable(folder / "sdk-request.raw", raw)
        durable(
            folder / "SDK_SERIALIZATION.json",
            canonical(
                {
                    **audit,
                    "status": "FINAL_OFFLINE_SERIALIZATION_NOT_LIVE_AUTHORIZATION",
                }
            ),
        )
        durable(folder / "TASK_CATALOG.json", canonical(catalog.data()))
        durable(folder / "MODEL_INPUT.json", canonical(call.input_payload))
        durable(folder / "RESPONSE_SCHEMA.json", canonical(call.response_schema))
        durable(folder / "prompt.txt", call.system_prompt.encode())
        durable(folder / "INVOCATION_CANDIDATE.json", canonical(identity))
        durable(
            folder / "SOURCE_MEMORY_CONTEXT_BINDING.json",
            canonical(
                dict(
                    source_identity=catalog.data()["sources"],
                    memory_versions=catalog.data()["memory_versions"],
                    relations=catalog.data()["relations"],
                    information_cutoff=catalog.data()["research_as_of"],
                    provenance="HISTORICAL_CONTEXT_NOT_CURRENT_PERMISSION",
                    current_memory_readset=None,
                    send_time_requirements=[
                        "CURRENT_INSTANCE",
                        "R7_EPISODE_ACL",
                        "F01",
                        "SOURCE_CLOCK",
                        "TTL_REVOCATION",
                        "RELATION_ENDPOINT",
                        "VERSION_CAS",
                        "W4_W5_EXACT_RELEASES",
                    ],
                )
            ),
        )
        population.append(identity)
    freeze = dict(
        version=VERSION,
        status="OFFLINE_REQUEST_FREEZE_FOR_INDEPENDENT_REVIEW_NOT_LIVE_READY",
        created_at=at.isoformat(),
        operation_id=operation,
        population_identity=digest(population),
        source=source,
        W3_source_commit=W3_SOURCE,
        W3_issuance_commit=W3_ISSUANCE,
        W3_manifest_sha256=W3_MANIFEST,
        W3_receipt_sha256=W3_RECEIPT,
        W3_final_semantic_binding="PASS_EXACT_INTERFACE",
        planned_samples=8,
        slots=population,
        order=list(ORDER),
        order_authority="W3_PROPOSAL_PENDING_W5_PREREGISTRATION",
        model=preparation.MODEL,
        region="cn-beijing",
        enable_thinking=False,
        store=False,
        actual_vendor_retention="UNVERIFIED",
        max_output_tokens=8192,
        concurrency=1,
        retry=0,
        fallback="NONE",
        research_as_of=receipt["slots"][0]["research_as_of"],
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        actual_model_calls=0,
        release_pins=[],
        R6_release_pins_applicable=False,
        current_memory_readset="NOT_INSTALLED",
        current_R7_episode_acl="NOT_INSTALLED",
        remaining_live_blockers=[
            "QWEN38_SENDER_AND_METER_PROFILE_NOT_INTEGRATED",
            "CURRENT_R7_MEMORY_AUTHORITY_NOT_INSTALLED",
            "NEW_W4_REVIEW_REQUIRED",
            "W5_PREREGISTRATION_REQUIRED",
        ],
        ordinary_nochange_model_tasks=0,
        ordinary_nochange_authority="RETAINED_CONTROL_NOT_NEW_REQUERY",
        new_scientific_writes=0,
        native_scientific_admission="BLOCKED",
        real_execution="PROHIBITED_THIS_COMMAND",
    )
    durable(output / "FINAL_R7_EXECUTION_FREEZE.json", canonical(freeze))
    durable(
        output / "EXACT_SDK_REQUEST_MANIFEST.json",
        canonical(
            dict(
                operation_id=operation,
                population_identity=freeze["population_identity"],
                slots=population,
                execution_freeze_sha256=blob_hash(canonical(freeze)),
                response_format="MODEL_VISIBLE_SCHEMA_AND_LOCAL_CHECKER_NO_ADDED_SERVER_FORMAT",
            )
        ),
    )
    return freeze


def main() -> int:
    """Only offline serialization, deliberately no live mode or release override."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["DEVELOPMENT"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    prepare(args.output, source_commit=args.source_commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
