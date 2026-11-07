"""Exact W3 R9 task adoption over retained evidence and the original Qwen SDK."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from tools import g113_r7_prepare as sdk
from tools import g113_r8_binding as previous
from tools import g113_r8_contract as parent_contract
from tools import g113_r9_contract as contract
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT, covers

INTAKE = "artifacts/g113-r9-live/w3-intake"
FINAL = "artifacts/g113-w3-r9/"
REPO = Path("/home/harry/deepinsight-g113-w3-r9")
SOURCE = "95721f27a2cd0a6077cc542b013b7f0c85855678"
ISSUANCE = "4a38a2e181414306e0b3180ac4d636b6faff168b"
MANIFEST = "852689d8967f814da3b4309ed11d75a27d7ebf90797e7c2b1b4d047eac962ffc"
MODULE = "30b16e514ad97dbda13be16730ab116d2383f6e5dd81d7af671a73a7bb7b0e12"
INTEGRITY_MODULE = "c065c4cdaeb2271cf5464258292351fcdec18bf5fdd701a5befac2b0f4905f16"
ORDER = ("B1", "B2", "B3", "B4")
TASKS = (
    "8bfeff1dff8e134bdbfac63a8e3c52246296e5372a5130791d750ecfa336b146",
    "b1fa215535e0fea256cae8f55f2bf47ff498bafd2de2138b8b8e9a88f2dbccd0",
    "a2098b6ce857bd21b826658195c35c279b35f3385a03f1c98fbb37bea8c30881",
    "dd41abff2232a8a890a0e6e734c536e0eee03a8dd15f0b962a85dec8fd94eead",
)


def manifest(root: Path = ROOT) -> dict[str, Any]:
    """Bind actual W3 source tree and separately sealed manifest bytes."""
    path = FINAL + "SOURCE_MANIFEST.json"
    raw = (root / INTAKE / path).read_bytes()
    if blob_hash(raw) != MANIFEST:
        raise ValueError("R9_W3_MANIFEST_IDENTITY")
    obj: dict[str, Any] = json.loads(raw)
    if obj["source_commit"] != SOURCE or obj["W1_source_commit"] != (
        "be53b6899bc8981308929f86a6104209b705baab"
    ):
        raise ValueError("R9_W3_SOURCE_IDENTITY")
    if (
        subprocess.check_output(["git", "-C", str(REPO), "show", ISSUANCE + ":" + path])
        != raw
    ):
        raise ValueError("R9_W3_ISSUANCE_BYTES")
    tree = (
        subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", SOURCE + "^{tree}"]
        )
        .decode()
        .strip()
    )
    if tree != obj["source_tree"]:
        raise ValueError("R9_W3_TREE_IDENTITY")
    for name, sha in (("contract", MODULE), ("integrity", INTEGRITY_MODULE)):
        if blob_hash((root / f"tools/g113_r9_{name}.py").read_bytes()) != sha:
            raise ValueError("R9_PUBLISHED_INTERFACE_CHANGED")
    return obj


def checked(root: Path, path: str) -> bytes:
    """Resolve exact signed data, never caller-selected authority or path repair."""
    entries = {e["path"]: e for e in manifest(root)["members"]}
    target = (root / INTAKE / path).resolve()
    if not target.is_relative_to((root / INTAKE).resolve()) or path not in entries:
        raise ValueError("R9_W3_MEMBER_PATH")
    raw = target.read_bytes()
    if (
        blob_hash(raw) != entries[path]["sha256"]
        or subprocess.check_output(
            ["git", "-C", str(REPO), "show", SOURCE + ":" + path]
        )
        != raw
    ):
        raise ValueError("R9_W3_MEMBER_IDENTITY")
    return raw


def matched(root: Path = ROOT) -> dict[str, Any]:
    """Adopt the later independent W3 binding without rewriting old PENDING."""
    obj: dict[str, Any] = json.loads(
        checked(root, FINAL + "W1_R9_INTERFACE_BINDING.json")
    )
    rows = obj["candidates"]
    if (
        obj["FINAL_TASK_BINDING"] != "PASS"
        or obj["interface"] != contract.VERSION
        or obj["checker"] != contract.CHECKER_VERSION
        or obj["modules"]
        != {
            "tools/g113_r9_contract.py": MODULE,
            "tools/g113_r9_integrity.py": INTEGRITY_MODULE,
        }
        or tuple(r["sample"] for r in rows) != ORDER
        or tuple(r["task_identity"] for r in rows) != TASKS
        or any(r["SDK_request_sha256"] is not None for r in rows)
        or obj["optional_new_navigation_in_model_input"] is not False
    ):
        raise ValueError("R9_W3_FINAL_POPULATION")
    return obj


def signed_row(root: Path, sample: str) -> dict[str, Any]:
    """Resolve only one member of the four signed tasks."""
    matches = [r for r in matched(root)["candidates"] if r["sample"] == sample]
    if len(matches) != 1:
        raise ValueError("R9_UNKNOWN_SAMPLE")
    return dict(matches[0])


def member(root: Path, row: dict[str, Any], key: str) -> bytes:
    """Require both receipt identity and underlying source Git blob."""
    record = row["files"][key]
    raw = checked(root, record["path"])
    if blob_hash(raw) != record["sha256"] or len(raw) != record["bytes"]:
        raise ValueError("R9_W3_RECEIPT_MEMBER")
    return raw


def original_catalog(root: Path, sample: str) -> TaskCatalog:
    """Use the verified R8 task solely as source/Memory lineage."""
    old = next(r for r in previous.rows(root) if r["sample_id"] == sample)
    return previous.catalog_for(root, old)


def catalog_for(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Adopt signed semantic changes; prove all factual/permission data unchanged."""
    signed = signed_row(root, row["sample_id"])
    if (
        row["semantic_task_identity"] != signed["task_identity"]
        or row["role"] != signed["role"]
    ):
        raise ValueError("R9_TASK_ROLE_IDENTITY")
    original = original_catalog(root, row["sample_id"])
    data = json.loads(member(root, signed, "task"))
    catalog = TaskCatalog(
        json.dumps(data, ensure_ascii=False), original.source_texts_json
    )
    parent = contract.parent_catalog(catalog)
    before, after = original.data(), parent.data()
    semantic = {"task", "topics", "w3_task_version"}
    if set(before) != set(after) or any(
        before[k] != after[k] for k in before if k not in semantic
    ):
        raise ValueError("R9_SOURCE_MEMORY_CATALOG_DRIFT")
    if signed["role"] == "fundamental_analyst":
        if before["task"] != after["task"] or before["topics"] != after["topics"]:
            raise ValueError("R9_FUNDAMENTAL_SEMANTIC_DRIFT")
    else:
        for key in ("task", "topics"):
            if set(before[key]) != set(after[key]) or any(
                before[key][topic] != after[key][topic]
                for topic in before[key]
                if topic != "N_TEMPORAL_NO_CHANGE"
            ):
                raise ValueError("R9_NEWS_SEMANTIC_DRIFT")
    if (
        catalog.identity != signed["task_identity"]
        or original.identity != signed["original_R8_task_identity"]
        or parent.identity != signed["semantic_R8_style_parent_identity"]
        or data["topics"] != signed["required_topics"]
    ):
        raise ValueError("R9_FINAL_TASK_IDENTITY")
    for name, actual in (
        ("schema", contract.output_schema(catalog)),
        ("references", parent_contract.reference_catalog(parent)),
        ("temporal", parent_contract.system_temporal_binding(parent)),
        ("full_trusted_display", contract.display_cards(catalog)),
    ):
        if json.loads(member(root, signed, name)) != actual:
            raise ValueError("R9_DERIVED_" + name.upper() + "_DRIFT")
    return catalog


def rows(root: Path = ROOT) -> list[dict[str, Any]]:
    """Bind new operational identities outside the model-visible payload."""
    return [
        dict(
            sample_id=r["sample"],
            slot=f"{i:02}-{r['sample']}-{r['role']}-{r['context']}",
            arm=r["context"],
            context=r["context"],
            role=r["role"],
            semantic_task_identity=r["task_identity"],
            parent_task_identity=r["original_R8_task_identity"],
            checker=contract.CHECKER_VERSION,
        )
        for i, r in enumerate(matched(root)["candidates"], 1)
    ]


def call_for(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Use W3 bytes/content exactly; no optional navigation or runtime ACL injection."""
    rows_ = [
        r for r in matched()["candidates"] if r["task_identity"] == catalog.identity
    ]
    if len(rows_) != 1:
        raise ValueError("R9_CALL_TASK_NOT_FINAL")
    row = rows_[0]
    if prompt.encode() != member(ROOT, row, "prompt") or len(prompt.encode()) != 2191:
        raise ValueError("R9_PROMPT_DRIFT")
    payload = json.loads(member(ROOT, row, "input"))
    old = json.loads(
        previous.member(ROOT, previous.signed_row(ROOT, row["sample"]), "input")
    )
    changed = {
        "task_identity",
        "task_version",
        "required_topics",
        "output_schema",
        "reference_catalog",
        "system_display_cards",
    }
    if set(payload) != set(old) or any(
        payload[k] != old[k] for k in old if k not in changed
    ):
        raise ValueError("R9_SOURCE_MEMORY_PAYLOAD_DRIFT")
    fields = (
        "value",
        "currency",
        "unit",
        "scale",
        "canonical_text",
        "rounding",
        "decimal_places",
        "authority",
        "fiscal_period",
        "periods",
        "source_view",
        "calculation_id",
        "operation",
        "observation_ids",
    )
    parent = contract.parent_catalog(catalog)
    expected = dict(
        task_identity=catalog.identity,
        task_version=catalog.data()["w3_task_version"],
        required_topics=catalog.data()["topics"],
        output_schema=contract.output_schema(catalog),
        reference_catalog=parent_contract.reference_catalog(parent),
        system_display_cards={
            handle: {k: card[k] for k in fields if k in card}
            for handle, card in contract.display_cards(catalog).items()
        },
    )
    if any(payload[k] != value for k, value in expected.items()):
        raise ValueError("R9_MODEL_PAYLOAD_BINDING")
    texts = json.loads(catalog.source_texts_json)
    for packet in payload["context_evidence"]:
        if not covers(packet, packet, texts):
            raise ValueError("R9_SOURCE_SPAN")
    for view in catalog.data()["views"].values():
        if not any(
            covers(packet, view, texts) for packet in payload["context_evidence"]
        ):
            raise ValueError("R9_REQUIRED_COUNTEREVIDENCE_COVERAGE")
    return LLMProviderCall(
        sdk.active_model(), prompt, payload, contract.output_schema(catalog)
    )
