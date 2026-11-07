"""Strict JSON and local artifact access; no network, deserialization or writes to sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ArtifactRef, EvaluationCase


def sha(body: bytes) -> str:
    """Return original byte hash."""
    return hashlib.sha256(body).hexdigest()


def canonical(value: Any) -> bytes:
    """Use stable evaluation identity independent of display formatting."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def strict_json(text: str | bytes) -> Any:
    """Reject duplicate keys, nonfinite constants, wrappers and malformed roots."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in items:
            if k in result:
                raise ValueError("DUPLICATE_JSON_KEY:" + k)
            result[k] = v
        return result

    def invalid(value: str) -> None:
        raise ValueError("NONFINITE_JSON:" + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def artifact(root: Path, ref: ArtifactRef) -> bytes:
    """Read only the identified local file; prevent traversal and symlink escapes."""
    rel = Path(ref.path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("UNSAFE_ARTIFACT")
    target = root / rel
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("UNSAFE_ARTIFACT")
    body = target.read_bytes()
    if sha(body) != ref.sha256:
        raise ValueError("ARTIFACT_HASH_MISMATCH:" + ref.path)
    return body


def clock(value: str) -> datetime:
    """Require an explicit timezone, never substitute Invocation for ResearchAsOf."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("NAIVE_CLOCK")
    return dt


def case_fingerprint(case: EvaluationCase) -> str:
    """Bind the exact source universe, evidence and cutoff for comparisons."""
    return sha(
        canonical(
            {
                "sources": [r.model_dump() for r in case.source_snapshot_refs],
                "catalog": case.evidence_catalog_ref.model_dump(),
                "clocks": case.clocks,
                "asof": case.research_as_of,
            }
        )
    )


def load_cases(
    root: Path,
    path: str = "HISTORICAL_REGRESSION_DATASET.jsonl",
    audience: str = "evaluator",
) -> list[EvaluationCase]:
    """Validate every planned case; developer access never exposes blind/prospective cases."""
    rows = [
        EvaluationCase.model_validate(strict_json(line))
        for line in (root / path).read_bytes().splitlines()
        if line.strip()
    ]
    if len({r.case_id for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_CASE_ID")
    for row in rows:
        clock(row.research_as_of)
        if audience != "evaluator" and row.dataset_split in (
            "BLIND_HOLDOUT",
            "PROSPECTIVE",
            "PENDING_LABEL",
        ):
            raise PermissionError("SPLIT_ACCESS_DENIED")
        if row.dataset_split == "BLIND_HOLDOUT" and row.provenance.get(
            "previously_exposed", True
        ):
            raise ValueError("EXPOSED_CASE_IS_NOT_HOLDOUT")
        for ref in [
            *row.source_snapshot_refs,
            row.evidence_catalog_ref,
            *row.native_schema_refs.values(),
        ]:
            artifact(root, ref)
        if row.evaluation_reference:
            artifact(root, row.evaluation_reference)
        for source in row.clocks.values():
            for value in source.values():
                if value is not None:
                    clock(value)
    exposed = [r for r in rows if r.dataset_split in ("DEVELOPMENT", "REGRESSION")]
    for row in rows:
        if row.dataset_split == "BLIND_HOLDOUT":
            docs = {r.sha256 for r in row.source_snapshot_refs}
            if any(
                row.exposure_cluster == e.exposure_cluster
                or (row.security and row.security == e.security)
                or docs.intersection(r.sha256 for r in e.source_snapshot_refs)
                for e in exposed
            ):
                raise ValueError("HOLDOUT_ISSUER_DOCUMENT_CLUSTER_LEAKAGE")
    return rows


def task_fingerprint(case: EvaluationCase) -> str:
    """Bind complete Claim strength and task obligations independently of Source IDs."""
    return sha(
        canonical(
            {
                "case_id": case.case_id,
                "case_version": case.case_version,
                "claim": case.original_complete_claim,
                "question": case.research_question,
                "task_family": case.task_family,
                "obligations": case.expected_task_behavior,
            }
        )
    )


def load_prompt_variant(root: Path, path: str) -> Any:
    """Verify a W3 candidate artifact hash without granting execution authority."""
    from .models import PromptVariant

    variant = PromptVariant.model_validate(strict_json((root / path).read_bytes()))
    artifact(root, variant.prompt_ref)
    return variant
