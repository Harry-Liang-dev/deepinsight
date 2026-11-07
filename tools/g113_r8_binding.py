"""Exact W3 final R8 task adoption; no model, approval or fact authority."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from tools import g113_r7_freeze as parent
from tools import g113_r7_prepare as sdk
from tools import g113_r8_contract as contract
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT, covers

INTAKE = "artifacts/g113-r8-live/w3-intake"
FINAL = "artifacts/g113-w3-r8/final-binding-v1/"
REPO = Path("/home/harry/deepinsight-g113-w3-r8")
SOURCE = "aa4bb9cb143e25652b7a669265731cd5cf3c63b2"
ISSUANCE = "37dae6be034fcc0cd53d5c73c9fa6d6b89b936f3"
MANIFEST = "af4b66fd6266d2bae2fda4d8ddebb3cf20142f27484c2271e8727a7c74785aa1"
MODULE = "3491e2d06440025fbbc4d983627c30826f6886df4fa8335807961f4358f57ba5"
ORDER = ("B1", "B2", "B3", "B4")
TASKS = (
    "68abaca72f1c136fb95d0c95583f6f92fe422542fc5dab09d2cfe4ddf9378a49",
    "24114bb844a6dd0e46bce3e1a26c07a920a017051b98c22b7a4245fcde486ff5",
    "9ca12f0a632eb024d2526226b54516dec5ca65e2e6a7bcc111396963acf9524e",
    "6b8de8c086d27a50716185fd4b7ddd96411daf1afd6ac0afc609cf4012c07dee",
)


def manifest(root: Path = ROOT) -> dict[str, Any]:
    """Require exact published manifest, source tree and Git issuance bytes."""
    path = FINAL + "SOURCE_MANIFEST.json"
    raw = (root / INTAKE / path).read_bytes()
    if blob_hash(raw) != MANIFEST:
        raise ValueError("R8_W3_MANIFEST_IDENTITY")
    obj: dict[str, Any] = json.loads(raw)
    if obj["source_commit"] != SOURCE or obj["W1_source_commit"] != (
        "26519ddac06420264963b5f1525974b742c2dfab"
    ):
        raise ValueError("R8_W3_SOURCE_IDENTITY")
    if (
        subprocess.check_output(["git", "-C", str(REPO), "show", ISSUANCE + ":" + path])
        != raw
    ):
        raise ValueError("R8_W3_ISSUANCE_BYTES")
    tree = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", SOURCE + "^{tree}"]
    )
    if tree.decode().strip() != obj["source_tree"]:
        raise ValueError("R8_W3_TREE_IDENTITY")
    if blob_hash((root / "tools/g113_r8_contract.py").read_bytes()) != MODULE:
        raise ValueError("R8_PUBLISHED_INTERFACE_CHANGED")
    return obj


def checked(root: Path, path: str) -> bytes:
    """Resolve a signed exact member without path repair or semantic rewriting."""
    entries = {f["path"]: f for f in manifest(root)["members"]}
    target = (root / INTAKE / path).resolve()
    if not target.is_relative_to((root / INTAKE).resolve()) or path not in entries:
        raise ValueError("R8_W3_MEMBER_PATH")
    raw = target.read_bytes()
    if (
        blob_hash(raw) != entries[path]["sha256"]
        or subprocess.check_output(
            ["git", "-C", str(REPO), "show", SOURCE + ":" + path]
        )
        != raw
    ):
        raise ValueError("R8_W3_MEMBER_IDENTITY")
    return raw


def matched(root: Path = ROOT) -> dict[str, Any]:
    """Consume the later genuine PASS; never edit the earlier pending receipt."""
    obj: dict[str, Any] = json.loads(
        checked(root, FINAL + "W3_R8_FINAL_TASK_BINDING.json")
    )
    rows = obj["candidates"]
    if (
        obj["W3_R8_FINAL_TASK_BINDING"] != "PASS"
        or obj["W1_interface_module_sha256"] != MODULE
        or obj["interface_version"] != contract.VERSION
        or obj["checker_version"] != contract.CHECKER_VERSION
        or tuple(r["sample"] for r in rows) != ORDER
        or tuple(r["task_identity"] for r in rows) != TASKS
        or any(r["SDK_request_sha256"] is not None for r in rows)
    ):
        raise ValueError("R8_W3_FINAL_POPULATION")
    return obj


def signed_row(root: Path, sample: str) -> dict[str, Any]:
    """Resolve only a member of the exact four-slot final population."""
    rows = [r for r in matched(root)["candidates"] if r["sample"] == sample]
    if len(rows) != 1:
        raise ValueError("R8_UNKNOWN_SAMPLE")
    return dict(rows[0])


def member(root: Path, row: dict[str, Any], key: str) -> bytes:
    """Verify both the final receipt member hash and original Git object."""
    f = row["files"][key]
    raw = checked(root, f["path"])
    if blob_hash(raw) != f["sha256"] or len(raw) != f["bytes"]:
        raise ValueError("R8_W3_RECEIPT_MEMBER")
    return raw


def catalog_for(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Rebind only W3-authorized task semantics over unchanged trusted sources."""
    signed = signed_row(root, row["sample_id"])
    if (
        row["semantic_task_identity"] != signed["task_identity"]
        or row["role"] != signed["role"]
    ):
        raise ValueError("R8_TASK_ROLE_IDENTITY")
    index = ORDER.index(row["sample_id"])
    original = parent.b_catalog(root, parent.matched(root)["slots"][index])
    data = json.loads(member(root, signed, "task"))
    expected = contract.prospective_catalog(original).data()
    semantic = {"task", "topics", "w3_task_requirements", "w3_task_version"}
    if any(data.get(k) != v for k, v in expected.items() if k not in semantic) or set(
        data
    ) != set(expected):
        raise ValueError("R8_SOURCE_MEMORY_CATALOG_DRIFT")
    catalog = TaskCatalog(
        json.dumps(data, ensure_ascii=False), original.source_texts_json
    )
    if (
        catalog.identity != signed["task_identity"]
        or data["parent_task_identity"] != signed["parent_task_identity"]
    ):
        raise ValueError("R8_FINAL_TASK_IDENTITY")
    for name, actual in (
        ("schema", contract.output_schema(catalog)),
        ("references", contract.reference_catalog(catalog)),
        ("temporal", contract.system_temporal_binding(catalog)),
        ("display_cards", contract.display_cards(catalog)),
    ):
        if json.loads(member(root, signed, name)) != actual:
            raise ValueError("R8_DERIVED_" + name.upper() + "_DRIFT")
    return catalog


def rows(root: Path = ROOT) -> list[dict[str, Any]]:
    """Operational envelope only; old candidates never replace final task IDs."""
    return [
        dict(
            sample_id=r["sample"],
            slot=f"{i:02}-{r['sample']}-{r['role']}-{r['context']}",
            arm=r["context"],
            context=r["context"],
            role=r["role"],
            semantic_task_identity=r["task_identity"],
            parent_task_identity=r["parent_task_identity"],
            checker=contract.CHECKER_VERSION,
        )
        for i, r in enumerate(matched(root)["candidates"], 1)
    ]


def call_for(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Use exact W3 input/Prompt and original Qwen SDK call contract."""
    candidates = [
        r for r in matched()["candidates"] if r["task_identity"] == catalog.identity
    ]
    if len(candidates) != 1:
        raise ValueError("R8_CALL_TASK_NOT_FINAL")
    row = candidates[0]
    if prompt.encode() != member(ROOT, row, "prompt") or len(prompt.encode()) != 2213:
        raise ValueError("R8_PROMPT_DRIFT")
    payload = json.loads(member(ROOT, row, "input"))
    data = catalog.data()
    if (
        payload["task_identity"] != catalog.identity
        or payload["role"] != data["role"]
        or payload["required_topics"] != data["topics"]
        or payload["research_as_of"] != data["research_as_of"]
        or payload["task_version"] != data["w3_task_version"]
        or payload["output_schema"] != contract.output_schema(catalog)
        or payload["reference_catalog"] != contract.reference_catalog(catalog)
        or payload["system_display_cards"]
        != {
            handle: {
                k: v
                for k, v in card.items()
                if k not in {"original_native", "native_scientific_admission"}
            }
            for handle, card in contract.display_cards(catalog).items()
        }
    ):
        raise ValueError("R8_MODEL_PAYLOAD_BINDING")
    original_freeze = json.loads(
        (
            ROOT / "artifacts/g113-r7/final-freeze-v1/FINAL_R7_EXECUTION_FREEZE.json"
        ).read_bytes()
    )
    old_row = next(
        r for r in original_freeze["slots"] if r["sample_id"] == row["sample"]
    )
    old = json.loads(
        (
            ROOT
            / "artifacts/g113-r7/final-freeze-v1"
            / old_row["slot"]
            / "MODEL_INPUT.json"
        ).read_bytes()
    )
    changed = {
        "output_schema",
        "task_identity",
        "task_version",
        "required_topics",
        "research_cutoff_authority",
    }
    if any(payload.get(k) != v for k, v in old.items() if k not in changed):
        raise ValueError("R8_SOURCE_MEMORY_PAYLOAD_DRIFT")
    additions = {"reference_catalog", "system_display_cards"}
    if row["role"] == "news_event_analyst":
        additions.add("retained_reentry_context")
    if set(payload) != (set(old) - {"research_cutoff_authority"}) | additions:
        raise ValueError("R8_MODEL_PAYLOAD_FIELDS")
    texts = json.loads(catalog.source_texts_json)
    for packet in payload["context_evidence"]:
        if not covers(packet, packet, texts):
            raise ValueError("R8_SOURCE_SPAN")
    for view in data["views"].values():
        if not any(
            covers(packet, view, texts) for packet in payload["context_evidence"]
        ):
            raise ValueError("R8_REQUIRED_COUNTEREVIDENCE_COVERAGE")
    return LLMProviderCall(
        sdk.active_model(), prompt, payload, contract.output_schema(catalog)
    )
