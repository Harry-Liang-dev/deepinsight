"""Preissued handles over existing raw sources and canonical system metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from src.schemas.research_v2_shared import canonical


def sha(raw: bytes) -> str:
    """Compute an identity from actual bytes, never a model-generated hash."""
    return hashlib.sha256(raw).hexdigest()


def time(value: str) -> datetime:
    """Require timezone-aware instants, without conflating source/local clocks."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed


@dataclass(frozen=True)
class Entry:
    """Immutable system identity and one continuous original span."""

    handle: str
    fragment_id: str
    authority_kind: str
    source_id: str
    text: str
    provenance_json: str
    observation_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    allowed_scope: str
    available_at: str

    def provenance(self) -> dict[str, Any]:
        """Return a copy; callers cannot mutate the registry's trusted object."""
        return dict(json.loads(self.provenance_json))


@dataclass(frozen=True)
class Access:
    """Injected checker receipt, not a model field or a fresh grant."""

    registry_id: str
    scope: str
    checked_at: str
    valid_until: str
    checks: tuple[tuple[str, str], ...]
    receipt_identity: str
    authority: str


class AccessChecker(Protocol):
    """W1 adapts its existing F01/ACL/TTL/CAS controls to this dependency."""

    def check(self, registry_id: str, scope: str, at: str) -> Access: ...


class Registry:
    """Request-local projection over existing authority, not a new Source DB."""

    def __init__(self, entries: tuple[Entry, ...], binding: dict[str, Any]) -> None:
        """Accept only trusted builder output, never deserialize model entries."""
        if len({e.handle for e in entries}) != len(entries):
            raise ValueError("DUPLICATE_HANDLE")
        self.entries: Mapping[str, Entry] = MappingProxyType(
            {e.handle: e for e in entries}
        )
        self._binding = canonical(binding)
        self.identity = sha(
            canonical({"entries": [asdict(e) for e in entries], "binding": binding})
        )

    def export(self) -> dict[str, Any]:
        """Export complete immutable system-owned candidate registry identity."""
        return {
            "registry_id": self.identity,
            "binding": json.loads(self._binding),
            "entries": [asdict(e) for e in self.entries.values()],
        }

    def catalog(self) -> list[dict[str, str]]:
        """Expose actual text and handles, not model-authored authority fields."""
        return [
            {
                "handle": e.handle,
                "text": e.text,
                "source_id": e.source_id,
                "authority_kind": e.authority_kind,
            }
            for e in self.entries.values()
        ]


def build_registry(
    packet: dict[str, Any],
    documents: dict[str, tuple[bytes, str]],
    leaf_locator: Callable[[str], dict[str, dict[str, Any]]],
    view_index: dict[str, Any],
) -> Registry:
    """Validate source bytes and project all original citable fragments/paths.

    No semantic filtering, quote search or answer-based selection is performed.
    Root and leaf metadata handles retain different path identities even when
    their text repeats. The original noncitable top-level flags stay noncitable.
    """
    fragments = packet["source_fragments"]
    metadata = {
        f["binding"]["metadata_key"]: json.loads(f["text"])
        for f in fragments
        if f["kind"] == "SYSTEM_METADATA"
    }
    sources = metadata["original_sources"]
    asof = packet["trusted_research_as_of"]
    observations = metadata["given_observations"]
    relations = metadata["given_relations"]
    entries: list[Entry] = []
    for fragment in fragments:
        binding = fragment["binding"]
        source = fragment["source_id"]
        text = fragment["text"]
        kind = fragment["kind"]
        original: dict[str, Any] = {
            "original_fragment_id": fragment["fragment_id"],
            "original_fragment_sha256": sha(text.encode()),
            "original_binding": binding,
            "registry_version": "EVIDENCE_CONTRACT_V2_OFFLINE_CANDIDATE_1",
        }
        obs_ids: tuple[str, ...] = ()
        rel_ids: tuple[str, ...] = ()
        if kind == "SOURCE_SPAN":
            raw, normalized = documents[source]
            info = sources[source]
            locator = binding["locator"]
            if (
                sha(raw) != info["raw_sha256"]
                or sha(raw) != binding["raw_sha256"]
                or sha(normalized.encode()) != info["normalized_sha256"]
                or sha(normalized.encode()) != locator["normalization_sha256"]
                or info["native_manifest_identity"]
                != binding["source_receipt_identity"]
                or not (0 <= locator["start"] < locator["end"] <= len(normalized))
                or normalized[locator["start"] : locator["end"]] != text
            ):
                raise ValueError("SOURCE_AUTHORITY_OR_SPAN_IDENTITY")
            if info["owner"] != packet["target"]["security"]:
                raise ValueError("SOURCE_ISSUER_SCOPE")
            available = info["available_at_conservative"]
            if any(
                time(info[k]) > time(asof)
                for k in ("published_at", "observed_at", "ingested_at")
            ):
                raise ValueError("HISTORICAL_SOURCE_NOT_AVAILABLE")

            def contained(support: dict[str, Any]) -> bool:
                loc = support["locator"]
                return bool(
                    support["source_id"] == source
                    and support["raw_sha256"] == binding["raw_sha256"]
                    and loc["normalization_sha256"] == locator["normalization_sha256"]
                    and locator["start"] <= loc["start"] < loc["end"] <= locator["end"]
                )

            matching_views = [
                vid for vid, view in view_index.items() if contained(view)
            ]
            links = [
                support
                for support in metadata["source_support_index"]
                if set(support["visible_view_ids"]) & set(matching_views)
            ]
            obs_ids = tuple(sorted({support["observation_id"] for support in links}))
            rel_ids = tuple(
                sorted(
                    rid
                    for rid, relation in relations.items()
                    if any(contained(support) for support in relation["source_support"])
                )
            )
            original.update(
                source_identity=info,
                continuous_source_span=locator,
                registered_view_ids=matching_views,
                registered_source_support=links,
                membership_scope="REGISTERED_SUPPORT_WITHIN_SPAN_NOT_SEMANTIC_ENTAILMENT",
            )
        else:
            if sha(text.encode()) != binding["metadata_sha256"]:
                raise ValueError("SYSTEM_METADATA_IDENTITY")
            available = asof
            original.update(
                system_metadata_key=binding["metadata_key"],
                metadata_pointer="",
                source_fact_authority=False,
            )
        if time(available) > time(asof):
            raise ValueError("SOURCE_NOT_VISIBLE_AT_RESEARCH_AS_OF")
        # Root projection never implies every leaf supports every observation.
        rows = [("", text, original, obs_ids, rel_ids)]
        if kind == "SYSTEM_METADATA":
            key = binding["metadata_key"]
            for pointer, leaf in leaf_locator(text).items():
                if not pointer:
                    continue  # Scalar root already has its single full-fragment handle.
                parts = [
                    p.replace("~1", "/").replace("~0", "~")
                    for p in pointer.split("/")[1:]
                ]
                oid = (
                    parts[0]
                    if key == "given_observations"
                    and parts
                    and parts[0] in observations
                    else None
                )
                rid = (
                    parts[0]
                    if key == "given_relations" and parts and parts[0] in relations
                    else None
                )
                detail = dict(
                    original,
                    metadata_pointer=pointer,
                    metadata_unicode_start=leaf["unicode_start"],
                    metadata_unicode_end=leaf["unicode_end"],
                    metadata_utf8_start=leaf["utf8_start"],
                    metadata_utf8_end=leaf["utf8_end"],
                )
                rows.append(
                    (
                        pointer,
                        leaf["raw_text"],
                        detail,
                        (oid,) if oid else (),
                        (rid,) if rid else (),
                    )
                )
        for pointer, content, provenance, oids, rids in rows:
            handle = f"H{len(entries) + 1:04}"
            entries.append(
                Entry(
                    handle,
                    fragment["fragment_id"],
                    kind,
                    source,
                    content,
                    canonical(provenance).decode(),
                    oids,
                    rids,
                    "ASSET:" + packet["target"]["security"],
                    available,
                )
            )
    return Registry(
        tuple(entries),
        {
            "evidence_universe_id": packet["evidence_universe_id"],
            "historical_research_as_of": asof,
            "source_population": sources,
            "source_of_truth": "EXISTING_RETAINED_RAW_SOURCE_AND_SYSTEM_CONTEXT",
            "current_access": "REQUIRES_INJECTED_W1_CHECKER_NOT_HISTORICAL_METADATA",
        },
    )


def resolve(
    registry: Registry,
    handle: str,
    checker: AccessChecker,
    *,
    scope: str,
    research_as_of: str,
    checked_at: str,
    observation_id: str | None = None,
    relation_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an exact handle with independent current authority; never infer."""
    result: dict[str, Any] = {
        "selected_handle": handle,
        "selection_state": "EVIDENCE_SELECTED",
        "resolution_state": "UNRESOLVED",
        "reason": None,
        "candidates": [],
        "system_bound": None,
    }
    entry = registry.entries.get(handle)
    if entry is None:
        # A diagnostic prefix yields all candidates but never chooses one.
        candidates = [k for k in registry.entries if k.startswith(handle)]
        result.update(
            resolution_state="AMBIGUOUS" if candidates else "UNRESOLVED",
            candidates=candidates,
            reason="EXACT_ISSUED_HANDLE_REQUIRED",
        )
        return result
    try:
        receipt = checker.check(registry.identity, scope, checked_at)
        if (
            receipt.registry_id != registry.identity
            or receipt.scope != scope
            or not receipt.receipt_identity
            or time(receipt.checked_at) != time(checked_at)
            or time(receipt.valid_until) < time(checked_at)
        ):
            raise ValueError("CURRENT_PERMISSION_RECEIPT_IDENTITY_OR_EXPIRY")
        checks = dict(receipt.checks)
        if any(
            checks.get(k) != "PASS"
            for k in ("F01", "ACL", "TTL", "CAS", "REVOCATION", "SOURCE_VERSION")
        ):
            raise ValueError("CURRENT_AUTHORITY_CHECK_NOT_PASS")
        if entry.allowed_scope != scope or time(entry.available_at) > time(
            research_as_of
        ):
            raise ValueError("SCOPE_OR_HISTORICAL_VISIBILITY")
        if observation_id and observation_id not in entry.observation_ids:
            raise ValueError("OBSERVATION_OWNERSHIP_NOT_REGISTERED")
        if relation_id and relation_id not in entry.relation_ids:
            raise ValueError("RELATION_OWNERSHIP_NOT_REGISTERED")
        result.update(
            resolution_state="EVIDENCE_RESOLVED",
            system_bound={
                "registry_id": registry.identity,
                "entry": asdict(entry),
                "authority_receipt": asdict(receipt),
                "field_owner": "SYSTEM_BOUND",
                "claim_support_granted": False,
            },
        )
    except Exception as exc:
        result.update(resolution_state="INELIGIBLE", reason=str(exc))
    return result
