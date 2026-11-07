"""Verified retained source decoding, with independent raw/normalized identities."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from research_eval.models import SourceRef


def digest(raw: bytes) -> str:
    """Hash source bytes before interpreting their content."""
    return hashlib.sha256(raw).hexdigest()


def verify_source_text(source: SourceRef, binding: dict[str, Any]) -> str:
    """Resolve a pinned W5 normalization; never guess or silently replace a source."""
    raw = Path(source.path).read_bytes()
    if digest(raw) != source.sha256 or binding["raw_sha256"] != source.sha256:
        raise ValueError("RAW_SOURCE_HASH_DRIFT")
    actual_encoding = "gzip" if raw.startswith(b"\x1f\x8b") else "identity"
    if (
        binding["raw_content_encoding"] != actual_encoding
        or binding["text_encoding"] != "utf-8"
    ):
        raise ValueError("SOURCE_ENCODING_MISMATCH")
    # Decode original raw entity too: a valid normalized cache never masks corrupt raw.
    (gzip.decompress(raw) if actual_encoding == "gzip" else raw).decode("utf-8")
    normalized = Path(binding["normalized_path"]).read_bytes()
    registry = Path(binding["registry_path"]).read_bytes()
    if (
        digest(normalized) != binding["normalized_sha256"]
        or digest(registry) != binding["registry_sha256"]
    ):
        raise ValueError("NORMALIZED_SOURCE_OR_REGISTRY_HASH_DRIFT")
    cases = [json.loads(line) for line in registry.splitlines() if line]
    matched = [c for c in cases if c["case_id"] == binding["case_id"]]
    if len(matched) != 1:
        raise ValueError("SOURCE_NORMALIZATION_BINDING_ABSENT")
    case = matched[0]
    refs = [
        r
        for r in case["source_snapshot_refs"]
        if r["kind"] == "HISTORICAL_SOURCE:" + source.source_id
    ]
    if (
        case["provenance"]["source_document_hashes"].get(source.source_id)
        != source.sha256
        or len(refs) != 2
        or {r["sha256"] for r in refs} != {source.sha256, digest(normalized)}
    ):
        raise ValueError("SOURCE_NORMALIZATION_MEMBERSHIP")
    return normalized.decode("utf-8")
