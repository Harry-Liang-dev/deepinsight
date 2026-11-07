"""Read-only historical diagnostic provenance, never historical rescoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_eval.models import FailureKind


def verify_manifest(root: Path, name: str, expected: str) -> int:
    """Check every retained original byte without writing or deriving authority."""
    raw = (root / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("HISTORICAL_MANIFEST_DRIFT")
    manifest = json.loads(raw)
    for row in manifest["files"]:
        path = Path(row["path"])
        if not path.is_absolute():
            path = root / path
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("HISTORICAL_MEMBER_DRIFT")
    return len(manifest["files"])


def missing_proposals(
    matrix: Path, expected_sha256: str, archive: Path
) -> list[dict[str, Any]]:
    """Retain W5's 24 original failure metadata and authenticate actual Assistant."""
    raw = matrix.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("HISTORICAL_EVALUATION_DRIFT")
    data = json.loads(raw)
    manifest = json.loads((archive / "EXECUTION_MANIFEST.json").read_bytes())
    assistant_hashes = {}
    for entry in manifest["files"]:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = archive / path
        if path.name == "assistant.txt":
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != entry["sha256"]:
                raise ValueError("HISTORICAL_RAW_BINDING")
            assistant_hashes[actual] = str(path)
    rows = []
    for row in data["rows"]:
        if (
            row["original_sha256"] not in assistant_hashes
            or "proposals" not in row["missing_root"]
        ):
            raise ValueError("HISTORICAL_RAW_BINDING")
        rows.append(
            dict(
                sample_id=row["sample_id"],
                raw_sha256=row["original_sha256"],
                original_path=assistant_hashes[row["original_sha256"]],
                original_native_status="FAIL",
                failure_kind=FailureKind.SCHEMA_FAILURE.value,
                pointer="/proposals",
                rule="MISSING_REQUIRED_PROPOSALS_ORIGINAL_CONTRACT",
                diagnosis_only=True,
                original_result_changed=False,
            )
        )
    return rows
