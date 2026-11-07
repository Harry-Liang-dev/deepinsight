"""Build and verify G107 request designs offline; no dispatch capability."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

ROLES = ("fundamental_analyst", "news_event_analyst")
ARMS = {"A0": ("T0", "P0"), "A1": ("T1", "P0"), "A2": ("T0", "P1"), "A3": ("T1", "P1")}
BASELINE_SHA = "fc3b88a4c7f52435c17c844e5f672c64e1d38996d7b1d903b1c02e860aad78bf"
REQUEST_SHA = {
    "fundamental_analyst": (
        "56841992679bdba70d5387f4b064d79d5d8b18aa3f6fcd21f863f6991e6fbeff"
    ),
    "news_event_analyst": (
        "b7e3acd66799cda1cc7e3c195f4efdf37d14c58154d8ce18a04c04b800c93c2f"
    ),
}


def sha(raw: bytes) -> str:
    """Hash exact bytes without interpreting their content."""
    return hashlib.sha256(raw).hexdigest()


def load(path: Path) -> Any:
    """Load a local design JSON artifact."""
    return json.loads(path.read_text())


def context(body: dict[str, Any]) -> dict[str, Any]:
    """Decode the original provider-visible user message envelope."""
    prefix = "JSON input:\n"
    if not body["input"].startswith(prefix):
        raise ValueError("INPUT_ENVELOPE")
    return cast(dict[str, Any], json.loads(body["input"][len(prefix) :]))


def encode(body: dict[str, Any]) -> bytes:
    """Serialize a design body; A0 retains its original unencoded bytes."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def verify_inputs(design: Path) -> None:
    """Verify all original input/native bytes against the intake manifest."""
    for item in load(design / "INPUT_BYTE_MANIFEST.json")["files"]:
        path = design / item["path"]
        raw = path.read_bytes()
        if len(raw) != item["bytes"] or sha(raw) != item["sha256"]:
            raise ValueError("INPUT_BYTE_IDENTITY:" + item["path"])


def build_body(design: Path, role: str, arm: str) -> bytes:
    """Construct one frozen request without loading credentials or a Provider."""
    verify_inputs(design)
    task, prompt = ARMS[arm]
    raw = (design / "audit/original" / role / "request.raw").read_bytes()
    if sha(raw) != REQUEST_SHA[role]:
        raise ValueError("ORIGINAL_REQUEST_IDENTITY")
    if arm == "A0":
        return raw
    body = json.loads(raw)
    ctx = context(body)
    if task == "T1":
        ctx["task"] = load(design / "TASK_VARIANTS.json")["T1"][role]
    if prompt == "P1":
        variants = load(design / "PROMPT_VARIANTS.json")
        body["instructions"] = variants["P1_prompts"][role]
        ctx["original_role_schema"] = variants["P1_schemas"][role]
    body["input"] = "JSON input:\n" + json.dumps(
        ctx, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return encode(body)


def check_body(design: Path, role: str, arm: str, raw: bytes) -> None:
    """Fail on any unregistered factor change or input identity drift."""
    if raw != build_body(design, role, arm):
        raise ValueError("UNREGISTERED_REQUEST_DIFFERENCE")
    old_raw = (design / "audit/original" / role / "request.raw").read_bytes()
    old, new = json.loads(old_raw), json.loads(raw)
    oc, nc = context(old), context(new)
    task, prompt = ARMS[arm]
    for key in set(old) | set(new):
        if key not in {"input", "instructions"} and old.get(key) != new.get(key):
            raise ValueError("EXECUTION_SETTING_DRIFT")
    for key in set(oc) | set(nc):
        if key not in {"task", "original_role_schema"} and oc.get(key) != nc.get(key):
            raise ValueError("MODEL_VISIBLE_CONTROL_DRIFT")
    if task == "T0" and oc["task"] != nc["task"]:
        raise ValueError("T0_DRIFT")
    if task == "T1":
        changed = {k for k in oc["task"] if oc["task"][k] != nc["task"][k]}
        if changed != {"common_instructions", "role_instructions"}:
            raise ValueError("TASK_FACTOR_SCOPE")
    if prompt == "P0":
        if old["instructions"] != new["instructions"]:
            raise ValueError("P0_PROMPT_DRIFT")
        if oc["original_role_schema"] != nc["original_role_schema"]:
            raise ValueError("P0_SCHEMA_DRIFT")
    if new["max_output_tokens"] != 8192 or new["enable_thinking"] or new["store"]:
        raise ValueError("SAMPLING_OR_MODE_DRIFT")


def schedule() -> list[dict[str, Any]]:
    """Balance arm order within role/repeat using a fixed hash permutation."""
    rows: list[dict[str, Any]] = []
    for repeat in (1, 2):
        for role in ROLES:
            arms = sorted(
                ARMS,
                key=lambda arm: sha(f"G107_ORDER_V1:{role}:{repeat}:{arm}".encode()),
            )
            for arm in arms:
                rows.append(
                    {
                        "ordinal": len(rows) + 1,
                        "sample_id": f"G107:{arm}:{role}:R{repeat}",
                        "arm": arm,
                        "role": role,
                        "repeat": repeat,
                        "request_file": f"requests/{arm}/{role}.request.json",
                        "execution_episode": "NEW_AT_EXECUTION_NOT_G106",
                        "state": "PLANNED_NOT_ATTEMPTED",
                    }
                )
    return rows


def validate_p1(
    result: dict[str, Any], schema: dict[str, Any], views: list[dict[str, Any]]
) -> None:
    """Validate syntax and exact visible citations, never confer scientific value."""
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    Draft202012Validator(schema).validate(result)
    by_id = {v["view_id"]: v for v in views}
    for item in result["items"]:
        refs = item["EvidenceLocator"]
        for ref in refs:
            view = by_id.get(ref["ViewID"])
            if view is None or ref["SourceID"] != view["source_id"]:
                raise ValueError("INVISIBLE_SOURCE")
            expected = {
                k: v for k, v in view["locator"].items() if k not in {"quote", "page"}
            }
            if ref["Locator"] != expected:
                raise ValueError("LOCATOR_IDENTITY")
            content = view["content"]
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            if ref["Quote"] not in content:
                raise ValueError("QUOTE_NOT_VISIBLE")
        for premise in item["SourcePremises"]:
            if premise["EvidenceLocatorIndex"] >= len(refs):
                raise ValueError("PREMISE_REFERENCE")


def materialize(design: Path, destination: Path) -> dict[str, Any]:
    """Freeze eight bodies and sixteen planned samples with no live artifacts."""
    if (
        sha((design / "inputs/DETERMINISTIC_BASELINE_FREEZE.json").read_bytes())
        != BASELINE_SHA
    ):
        raise ValueError("BASELINE_IDENTITY")
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for role in ROLES:
        for arm in ARMS:
            raw = build_body(design, role, arm)
            check_body(design, role, arm, raw)
            relative = f"requests/{arm}/{role}.request.json"
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append({"path": relative, "sha256": sha(raw), "bytes": len(raw)})
    rows = schedule()
    identities = {f["path"]: f["sha256"] for f in files}
    for row in rows:
        row["request_sha256"] = identities[row["request_file"]]
    receipt = {
        "schema": "G107_OFFLINE_REQUEST_DESIGN_V1",
        "files": files,
        "samples": rows,
        "count": 16,
        "new_model_calls": 0,
        "new_provider_calls": 0,
        "attempts_created": 0,
        "scientific_admission": "BLOCKED",
        "schema_syntax_test_is_not_economic_evaluation": True,
    }
    (destination / "REQUEST_MATRIX.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return deepcopy(receipt)


def main() -> None:
    """Materialize local design previews only; never dispatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = materialize(args.design, args.output)
    print(
        json.dumps(
            {
                "status": "OFFLINE_DESIGN_ONLY",
                "samples": result["count"],
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
