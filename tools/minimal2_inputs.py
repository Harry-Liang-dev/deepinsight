"""Exact W5 two-probe inputs and real offline SDK serialization; no grants."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
from pathlib import Path
from typing import Any

import httpx
from openai.resources.responses import Responses

from evidence_v2.mechanism import FixedClaim
from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    MINIMAL2_EVIDENCE_PROFILE,
    MINIMAL2_SCHEMA_PROFILE,
    ModelExecutionProfile,
)
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import request_audit
from tools import evidence_v2_runtime as base
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT
from tools.minimal_semantic_carrier import proposal_schema

RELEASE = "MINIMAL2_TWO_PROBE_V1"
VERSION = "MINIMAL2_CURRENT_RUNTIME_V1"
DESIGN_SOURCE = "c9a4a7dc095b4f944b90dc8ba2646f7b4c848e1b"
DESIGN_DELIVERY = "aa6365fc968911a46de4a41f2360843287a52302"
DESIGN_MANIFEST = "61ee9c92423e11a3275b7e829c989aed0770dddc83908349b798c12218a1b6a1"
INTAKE = ROOT / "artifacts/minimal2/w5"
ORDER = ("MINIMAL2-PROBE-01", "MINIMAL2-PROBE-02")
SOURCE_CASE = "H2-C004"


def sdk_identity() -> dict[str, Any]:
    """Pin installed serializer versions and implementation bytes, not server claims."""
    files = [
        inspect.getfile(Responses),
        inspect.getfile(httpx.Client),
    ]
    return dict(
        versions={
            name: importlib.metadata.version(name)
            for name in ("openai", "httpx", "pydantic")
        },
        module_sha256={path: blob_hash(Path(path).read_bytes()) for path in files},
    )


def read(name: str) -> Any:
    """Read pinned design, never an execution authorization."""
    return json.loads((INTAKE / name).read_bytes())


def verify_design() -> None:
    """Check every adopted original W5 file and the exact six-field contract."""
    raw = (INTAKE / "EVIDENCE_MANIFEST.json").read_bytes()
    if blob_hash(raw) != DESIGN_MANIFEST:
        raise ValueError("MINIMAL2_DESIGN_MANIFEST")
    indexed = {f["path"]: f["sha256"] for f in json.loads(raw)["files"]}
    for p in INTAKE.iterdir():
        if p.name in {"EVIDENCE_MANIFEST.json", "DESIGN_GIT_SEAL.json"}:
            continue
        if blob_hash(p.read_bytes()) != indexed.get(p.name):
            raise ValueError("MINIMAL2_DESIGN_MEMBER")
    if read("FROZEN_SIX_FIELD_SCHEMA.json") != proposal_schema():
        raise ValueError("MINIMAL2_SCHEMA_VERSION")


def cases() -> list[dict[str, Any]]:
    """Return only the two signed inputs, excluding evaluator sidecars."""
    verify_design()
    rows = read("EXACT_PROBE_POPULATION.json")["probes"]
    if tuple(r["design_slot_id"] for r in rows) != ORDER:
        raise ValueError("MINIMAL2_POPULATION")
    for row in rows:
        if (
            digest(row["model_input"]) != row["model_input_sha256"]
            or blob_hash(row["model_instructions"].encode())
            != row["instructions_sha256"]
        ):
            raise ValueError("MINIMAL2_TASK_DRIFT")
    return list(rows)


def profile(index: int) -> ModelExecutionProfile:
    """Two code-owned output ceilings, no caller-chosen paid envelope."""
    if index not in (0, 1):
        raise ValueError("MINIMAL2_BUDGET")
    return (MINIMAL2_SCHEMA_PROFILE, MINIMAL2_EVIDENCE_PROFILE)[index]


def call(index: int) -> LLMProviderCall:
    """Construct only the exact signed instructions/input/schema."""
    row = cases()[index]
    return LLMProviderCall(
        "qwen3.8-flash",
        row["model_instructions"],
        row["model_input"],
        proposal_schema(),
    )


def serialize(index: int) -> dict[str, Any]:
    """Actual QwenProvider and installed SDK; in-memory capture, zero network."""
    c = call(index)
    audit = request_audit(
        c, output_cap=profile(index).output_cap, model_profile=profile(index)
    )
    body = json.loads(audit["serialized_http_body"])
    expected = read("PROVIDER_PARAMETER_REQUIREMENTS.json")["native_format_parameter"][
        "text"
    ]
    instructions = body["instructions"]
    marker = "MINIMAL_OUTPUT_CONTRACT="
    if (
        body.get("text") != expected
        or instructions != c.system_prompt
        or instructions.count(marker) != 1
        or json.loads(instructions.split(marker)[1]) != proposal_schema()
        or body["max_output_tokens"] != profile(index).output_cap
        or any(
            k in body
            for k in ("response_format", "messages", "tools", "previous_response_id")
        )
    ):
        raise ValueError("MINIMAL2_SCHEMA_NOT_ON_WIRE")
    return audit


def catalog() -> TaskCatalog:
    """Original trusted source projection, not an old research task/population."""
    parent = base.catalog_for(SOURCE_CASE)
    data = parent.data()
    data["minimal2"] = {
        "version": VERSION,
        "task_identity": digest(cases()[1]["model_input"]),
    }
    return TaskCatalog(canonical(data).decode(), parent.source_texts_json)


def source() -> tuple[Any, dict[str, Any], FixedClaim]:
    """Keep original registry and exact new complete causal parent separately."""
    registry, packet, _ = base.fixed(SOURCE_CASE)
    binding = read("PROBE2_SOURCE_BINDING.json")
    if registry.identity != binding["source_registry_identity"]:
        raise ValueError("MINIMAL2_REGISTRY_DRIFT")
    exported = {e["handle"]: e for e in registry.export()["entries"]}
    for e in binding["entries"]:
        if canonical(exported[e["handle"]]) != canonical(e):
            raise ValueError("MINIMAL2_SOURCE_SPAN_DRIFT")
    row = cases()[1]
    visible = row["model_input"]["offered_evidence"]
    if [x["handle"] for x in visible] != ["H0005", "H0006"] or any(
        x["text"] != registry.entries[x["handle"]].text for x in visible
    ):
        raise ValueError("MINIMAL2_VISIBLE_EVIDENCE_DRIFT")
    parent = FixedClaim(
        ORDER[1],
        row["model_input"]["original_complete_claim"],
        canonical(row["model_input"]).decode(),
        row["model_input_sha256"],
    )
    return registry, packet, parent
