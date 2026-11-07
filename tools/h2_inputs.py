"""Adopt only published W3 fixed12 bytes and bind original trusted source scope."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from tools import g113_r7_prepare as sdk
from tools import g113_r9_binding as parent
from tools.g112_task_freeze import check_span
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT

REPO = Path("/home/harry/deepinsight-g113-architecture-w3-h2-pilot")
SOURCE = "241efa50656a1f17105514de90838eb89f4933cf"
TREE = "02a5f0256844167da974ed73d1e8aa95eb16c7ea"
MANIFEST = "ca40e7a365c95f9478f79d4ddfa6d601c8399649b3c502da2a4b41667f15c048"
ORDER = tuple(f"H2-C{i:03}" for i in range(1, 13))
INTAKE = "artifacts/h2/intake"
FILES = (
    "CALL_CANDIDATE.json",
    "MODEL_INPUT.json",
    "RESPONSE_SCHEMA.json",
    "SDK_SERIALIZATION.json",
    "prompt.txt",
    "sdk-request.raw",
)


def git(path: str) -> bytes:
    """Read a pinned Git blob, not mutable branch contents."""
    return subprocess.check_output(
        ["git", "-C", str(REPO), "show", SOURCE + ":" + path]
    )


def published() -> dict[str, Any]:
    """Verify published source/tree and every member against both blob and file."""
    raw = (REPO / "EVIDENCE_MANIFEST.json").read_bytes()
    if blob_hash(raw) != MANIFEST:
        raise ValueError("H2_W3_MANIFEST")
    obj: dict[str, Any] = json.loads(raw)
    tree = (
        subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", SOURCE + "^{tree}"]
        )
        .decode()
        .strip()
    )
    if tree != TREE or obj["source_commit"] != SOURCE or obj["source_tree"] != TREE:
        raise ValueError("H2_W3_SOURCE_TREE")
    for entry in obj["source_files"]:
        name = entry["path"]
        path = (REPO / name).resolve()
        if (
            not path.is_relative_to(REPO)
            or blob_hash(path.read_bytes()) != entry["sha256"]
            or git(name) != path.read_bytes()
        ):
            raise ValueError("H2_W3_MEMBER:" + name)
    return obj


def population(root: Path = ROOT) -> list[dict[str, Any]]:
    """Return the unique twelve final rows, excluding all superseded drafts."""
    raw = (root / INTAKE / "FROZEN_DEVELOPMENT_EVALUATION_INPUTS.json").read_bytes()
    if raw != git("FROZEN_DEVELOPMENT_EVALUATION_INPUTS.json"):
        raise ValueError("H2_POPULATION_DRIFT")
    obj = json.loads(raw)
    if (
        tuple(r["case_id"] for r in obj["rows"]) != ORDER
        or obj["only_executable_candidate_population"] != "frozen-requests/"
        or obj["max_attempts"] != 12
        or obj["retries"] != 0
        or obj["max_attempts_per_claim"] != 1
    ):
        raise ValueError("H2_POPULATION_CONTRACT")
    return list(obj["rows"])


def checked(root: Path, case: str, name: str) -> bytes:
    """Accept only final versioned source blobs; no caller-selected path."""
    if case not in ORDER or name not in FILES:
        raise ValueError("H2_UNREGISTERED_INPUT")
    name = "frozen-requests/" + case + "/" + name
    raw = (root / INTAKE / name).read_bytes()
    if raw != git(name):
        raise ValueError("H2_INPUT_GIT_DRIFT")
    return raw


def call_for_case(root: Path, case: str) -> LLMProviderCall:
    """Keep W3 prompt/payload/schema exact and validate their SDK representation."""
    obj = json.loads(checked(root, case, "CALL_CANDIDATE.json"))
    call = LLMProviderCall(**obj)
    row = next(r for r in population(root) if r["case_id"] == case)
    if (
        call.model != sdk.active_model()
        or call.input_payload["case_id"] != case
        or call.system_prompt.encode() != checked(root, case, "prompt.txt")
        or call.input_payload != json.loads(checked(root, case, "MODEL_INPUT.json"))
        or call.response_schema
        != json.loads(checked(root, case, "RESPONSE_SCHEMA.json"))
    ):
        raise ValueError("H2_CALL_BINDING")
    if blob_hash(checked(root, case, "sdk-request.raw")) != row["request_sha256"]:
        raise ValueError("H2_REQUEST_HASH")
    return call


def catalog_for(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Project current authority separately from unchanged model-visible input."""
    case = row["sample_id"]
    if case not in ORDER or row["role"] != "fundamental_analyst":
        raise ValueError("H2_ROLE_OR_CASE")
    original = "B1" if case in {"H2-C002", "H2-C003"} else "B2"
    pr = next(r for r in parent.rows(root) if r["sample_id"] == original)
    catalog = parent.catalog_for(root, pr)
    payload: dict[str, Any] = dict(call_for_case(root, case).input_payload)
    claim_span(case, payload)
    original_row = parent.signed_row(root, original)
    scope = json.loads(parent.member(root, original_row, "input"))
    texts = json.loads(catalog.source_texts_json)
    spans = []
    keys = []
    for fragment in payload["source_fragments"]:
        binding = fragment["binding"]
        if fragment["kind"] == "SOURCE_SPAN":
            packet = {**binding, "content": fragment["text"]}
            check_span(packet, texts)
            matches = [
                p
                for p in scope["context_evidence"]
                if p["source_id"] == binding["source_id"]
                and p["locator"] == binding["locator"]
                and p["raw_sha256"] == binding["raw_sha256"]
                and p["content"] == fragment["text"]
            ]
            if (
                len(matches) != 1
                or binding["source_receipt_identity"]
                != scope["original_sources"][binding["source_id"]][
                    "native_manifest_identity"
                ]
            ):
                raise ValueError("H2_SOURCE_SCOPE")
            spans.append(matches[0])
        elif fragment["kind"] == "SYSTEM_METADATA":
            key = binding["metadata_key"]
            expected = scope.get(key)
            if key == "retained_reentry_context" and key not in scope:
                expected = {
                    "provided_in_original_scope": False,
                    "value": None,
                    "meaning": (
                        "Historical invocation/access/reentry checks "
                        "not provided; do not infer them."
                    ),
                }
            if (
                canonical(expected).decode() != fragment["text"]
                or blob_hash(fragment["text"].encode()) != binding["metadata_sha256"]
            ):
                raise ValueError("H2_HISTORICAL_METADATA")
            keys.append(key)
        else:
            raise ValueError("H2_FRAGMENT_KIND")
    if (
        spans != scope["context_evidence"]
        or len(keys) != 13
        or len(set(keys)) != 13
        or payload["trusted_research_as_of"] != scope["research_as_of"]
    ):
        raise ValueError("H2_SOURCE_COVERAGE_OR_CUTOFF")
    data = catalog.data()
    data["h2_authority_projection"] = {
        "case_id": case,
        "input_sha256": digest(payload),
        "parent_task_identity": catalog.identity,
        "purpose": "H2_FIXED_CLAIM_DEVELOPMENT_PILOT",
    }
    result = TaskCatalog(canonical(data).decode(), catalog.source_texts_json)
    if row.get("semantic_task_identity", result.identity) != result.identity:
        raise ValueError("H2_AUTHORITY_TASK_DRIFT")
    return result


def rows(root: Path = ROOT) -> list[dict[str, Any]]:
    """Create twelve operational receivers without editing W3 request bytes."""
    result = []
    for i, case in enumerate(ORDER, 1):
        row = dict(
            sample_id=case,
            slot=f"{i:02}-{case}",
            role="fundamental_analyst",
            context="FULL" if case in {"H2-C002", "H2-C003"} else "DELTA",
            arm="H2",
            checker="H2_EVIDENCE_SUPPORT_VERIFIER_DEVELOPMENT_V1",
        )
        row["semantic_task_identity"] = catalog_for(root, row).identity
        result.append(row)
    return result


def call_for(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Resolve exact source-owned call; current permission is outside payload."""
    case = catalog.data()["h2_authority_projection"]["case_id"]
    call = call_for_case(ROOT, case)
    if prompt != call.system_prompt:
        raise ValueError("H2_PROMPT_DRIFT")
    return call


def claim_span(case: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Recheck the original target bytes without treating developer labels as Gold."""
    base = Path("/home/harry/deepinsight-g113-architecture-w3-claim-evaluation")
    raw = (base / "FIXED_CLAIM_EVALUATION_FIXTURES.json").read_bytes()
    if (
        blob_hash(raw)
        != "233a771df65537728943e4ededc2125fc0bfcad0031d5cb987fa7d01d60aeee7"
    ):
        raise ValueError("H2_FIXED_CLAIM_POPULATION_DRIFT")
    item = json.loads(raw)["cases"][ORDER.index(case)]
    span = item["candidate"]["original_span"]["value"]
    path = Path(span["artifact"]).resolve()
    history = Path("/home/harry/deepinsight-g113-r9-live-execution/raw-archive")
    if not (path.is_relative_to(base / "fixed_inputs") or path.is_relative_to(history)):
        raise ValueError("H2_CLAIM_ORIGINAL_PATH")
    original = path.read_bytes()
    if (
        blob_hash(original) != span["sha256"]
        or original[span["utf8_start"] : span["utf8_end"]].decode() != span["text"]
        or span["text"] != payload["target"]["statement"]
    ):
        raise ValueError("H2_CLAIM_ORIGINAL_SPAN")
    return dict(
        original_claim_id=item["candidate"]["claim_id"],
        original_sha256=span["sha256"],
        original_span_verified=True,
        independent_gold=False,
    )
