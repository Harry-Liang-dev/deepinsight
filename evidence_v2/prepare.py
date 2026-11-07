"""Reconstruct actual H2 evidence, never regrade or resend its operation."""

from __future__ import annotations

import base64
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from evidence_v2.registry import Registry, build_registry, sha
from src.schemas.research_v2_shared import canonical
from src.services.native_preservation import NativeManifest


def leaf_locator(
    path: Path, expected_sha256: str
) -> Callable[[str], dict[str, dict[str, Any]]]:
    """Reuse pinned W5 JSON-position tooling without its semantic diagnoses."""
    if sha(path.read_bytes()) != expected_sha256:
        raise ValueError("PINNED_JSON_POSITION_TOOL_IDENTITY")
    spec = importlib.util.spec_from_file_location("retained_w5_json_positions", path)
    if spec is None or spec.loader is None:
        raise ValueError("JSON_POSITION_TOOL_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Callable[[str], dict[str, dict[str, Any]]], module.leaf_spans)


def load(root: Path, case_id: str) -> tuple[Registry, dict[str, Any]]:
    """Validate retained public raw sources before constructing candidate handles."""
    packet_path = root / "v2-evidence/cases" / case_id / "MODEL_INPUT.json"
    pin_rows = json.loads((root / "V2_INPUT_IDENTITY_VERIFICATION.json").read_text())[
        "original_cases"
    ]
    expected = next(row for row in pin_rows if row["case_id"] == case_id)
    if sha(packet_path.read_bytes()) != expected["model_input_sha256"]:
        raise ValueError("ORIGINAL_FROZEN_PACKET_IDENTITY")
    packet = dict(json.loads(packet_path.read_text()))
    documents = {}
    for sid in ("G105-GET-05", "G105-GET-09", "G105-GET-12"):
        p = root / "v2-evidence/sources" / sid
        raw = (p / "entity.raw").read_bytes()
        native = NativeManifest.model_validate_json(
            (p / "native-manifest.json").read_bytes()
        )
        if (
            base64.b64decode(native.acquisition.body_base64, validate=True) != raw
            or sha(raw) != native.acquisition.body_sha256
            or len(raw) != native.acquisition.size_bytes
            or native.acquisition.owner != packet["target"]["security"]
        ):
            raise ValueError("ORIGINAL_NATIVE_ACQUISITION_BINDING")
        source_meta = next(
            f
            for f in packet["source_fragments"]
            if f["binding"].get("metadata_key") == "original_sources"
        )
        if (
            native.content_identity
            != json.loads(source_meta["text"])[sid]["native_manifest_identity"]
        ):
            raise ValueError("NATIVE_MANIFEST_IDENTITY")
        documents[sid] = (raw, (p / "normalized.txt").read_text())
    tool = root / "v2-evidence/methods/w5_text_diagnostics.py"
    pin = json.loads((root / "V2_RETAINED_TOOL_PIN.json").read_text())["sha256"]
    mode = "FULL" if case_id in {"H2-C002", "H2-C003"} else "DELTA"
    catalog = json.loads(
        (root / "v2-evidence/reference-catalogs" / (mode + ".json")).read_text()
    )
    for view in catalog["views"].values():
        raw, text = documents[view["source_id"]]
        loc = view["locator"]
        if (
            sha(raw) != view["raw_sha256"]
            or sha(text.encode()) != loc["normalization_sha256"]
            or text[loc["start"] : loc["end"]] != view["content"]
        ):
            raise ValueError("ORIGINAL_VIEW_SOURCE_BINDING")
    return (
        build_registry(packet, documents, leaf_locator(tool, pin), catalog["views"]),
        packet,
    )


def prepare(root: Path, output: Path) -> None:
    """Export all original populations and candidate identity, not SDK requests."""
    output.mkdir(parents=True, exist_ok=False)
    registries: dict[str, str] = {}
    rows = []
    for i in range(1, 13):
        cid = f"H2-C{i:03}"
        registry, packet = load(root, cid)
        if registry.identity not in registries:
            name = f"registry-{len(registries) + 1:02}.json"
            (output / name).write_bytes(canonical(registry.export()))
            registries[registry.identity] = name
        rows.append(
            {
                "case_id": cid,
                "original_claim": packet["target"],
                "original_input_sha256": sha(
                    (root / "v2-evidence/cases" / cid / "MODEL_INPUT.json").read_bytes()
                ),
                "registry_id": registry.identity,
                "registry_file": registries[registry.identity],
                "handles": len(registry.entries),
                "original_research_as_of": packet["trusted_research_as_of"],
                "current_live_access": "NOT_CHECKED_OFFLINE_ONLY",
                "new_operation": None,
                "historical_native_verdict_replaced": False,
            }
        )
    (output / "H2_V2_OFFLINE_REGISTRY_POPULATION.json").write_bytes(
        canonical(
            {
                "scope": "COUNTERFACTUAL_MECHANISM_DEVELOPMENT_NOT_NEW_MODEL_REQUESTS",
                "cases": rows,
                "current_access_checker": "W1_ADAPTER_REQUIRED",
                "source_population_changed": False,
                "exact_quote_model_requirement": False,
                "provider_tool_selection_support": (
                    "NOT_VERIFIED_OFFLINE_INTERFACE_ONLY"
                ),
                "new_model_calls": 0,
                "new_provider_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    import sys

    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
