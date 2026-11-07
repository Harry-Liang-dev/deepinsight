"""Sole typed binding of the frozen Research v2 integration envelope."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def utc(value: datetime) -> datetime:
    """Reject naive clocks before normalization onto the UTC timeline."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("NAIVE_CLOCK")
    return value.astimezone(UTC)


Clock = Annotated[datetime, AfterValidator(utc)]
Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Namespace = Literal[
    "EVIDENCE",
    "CLAIM",
    "HYPOTHESIS",
    "STATE",
    "EPISODE",
    "PLAN",
    "RECEIPT",
    "MESSAGE",
    "QUESTION",
    "SECTOR_ENTITY",
    "SECTOR_EDGE",
    "EVENT",
    "DEFINITION",
    "MODEL",
    "PROMPT",
    "BUILD",
]


def canonical(value: object) -> bytes:
    """Encode the Main-frozen compact ASCII JSON identity convention."""

    def encode(item: object) -> object:
        """Validate the exact typed field and namespace invariants."""
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            return utc(item).isoformat().replace("+00:00", "Z")
        raise TypeError(f"Unsupported canonical type: {type(item).__name__}")

    return json.dumps(
        value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value: object) -> str:
    """Hash complete logical bytes, including business clocks."""
    return hashlib.sha256(canonical(value)).hexdigest()


class Frozen(BaseModel):
    """Strict, immutable wire object; unknown fields and coercions are forbidden."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def unique_arrays(self) -> Self:
        """Preserve JSON Schema uniqueItems for all tuple-valued fields."""
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, tuple):
                keys = [canonical(v) for v in value]
                if len(set(keys)) != len(keys):
                    raise ValueError(f"DUPLICATE_ITEMS:{name}")
        return self


class Reference(Frozen):
    """Exact immutable namespace, version and resolved-byte reference."""

    namespace: Namespace
    id: Text
    version: Text
    sha256: Digest

    def require(self, *namespaces: str) -> None:
        """Reject a reference in the wrong semantic field."""
        if self.namespace not in namespaces:
            raise ValueError("WRONG_REFERENCE_NAMESPACE")


def reference(
    namespace: Namespace, name: str, version: str, value: object
) -> Reference:
    """Bind a named artifact to its complete canonical content."""
    return Reference(
        namespace=namespace, id=name, version=version, sha256=digest(value)
    )


class RunBinding(Frozen):
    """Exact shared-interface RunBinding; null capture means offline, not unknown."""

    run_id: Text
    capture_id: Text | None
    episode: Reference
    plan: Reference
    research_as_of: Clock
    mode: Literal["SYNTHETIC_OFFLINE", "RETAINED_READONLY"]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.episode.require("EPISODE")
        self.plan.require("PLAN")
        if self.mode == "SYNTHETIC_OFFLINE" and self.capture_id is not None:
            raise ValueError("SYNTHETIC_CAPTURE_IMPERSONATION")
        return self


class Revision(Frozen):
    """Frozen wire revision binding, with explicit genesis/parent semantics."""

    state: Reference
    sequence: Annotated[int, Field(ge=0)]
    parent: Reference | None
    event_log_sha256: Digest

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.state.require("STATE")
        if self.parent:
            self.parent.require("STATE")
        if (self.sequence == 0) != (self.parent is None):
            raise ValueError("REVISION_PARENT")
        return self


class EventProvenance(Frozen):
    """Unmodified Main shared event envelope."""

    binding: RunBinding
    producer: Reference
    read_revision: Revision
    read_set: tuple[Reference, ...]
    event: Reference
    payload_sha256: Digest
    occurred_at: Clock
    idempotency_key: Text
    causal_refs: tuple[Reference, ...]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.producer.require("BUILD")
        self.event.require("EVENT")
        if self.occurred_at < self.binding.research_as_of:
            raise ValueError("EVENT_BEFORE_CUTOFF")
        return self


class EvidenceDecision(Frozen):
    """W3-owned validity/temporal decision; validity is not inferred from prose."""

    binding: RunBinding
    state_revision: Revision
    evidence: Reference
    canonical_namespace: Literal["STRUCTURED_EVIDENCE", "DOCUMENT_CHUNK_EVIDENCE"]
    owner_asset_id: Text
    source: Reference
    participation: Literal[
        "PIT_COUNTED_EVIDENCE",
        "DEPENDENCY_WITNESS",
        "DIAGNOSTIC_EVIDENCE",
        "UNUSABLE_EVIDENCE",
    ]
    research_usage: Literal[
        "ACCEPTED_FACT_SUPPORT",
        "ATTRIBUTED_DIAGNOSTIC_CONTEXT",
        "HYPOTHESIS_CONTEXT",
        "QUARANTINED",
    ]
    independently_valid: bool
    temporal_authority: Reference | None
    validation_receipt: Reference
    reason_codes: tuple[Text, ...]
    required_slot_satisfied: bool

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.evidence.require("EVIDENCE")
        self.source.require("RECEIPT")
        self.validation_receipt.require("RECEIPT")
        if self.temporal_authority:
            self.temporal_authority.require("RECEIPT")
        return self


class ClaimDecision(Frozen):
    """Claim decision preserves its entire required evidence denominator."""

    binding: RunBinding
    state_revision: Revision
    claim: Reference
    owner_asset_id: Text
    required_evidence: tuple[Reference, ...]
    eligible_for_pit_count: bool
    validation_receipt: Reference
    reason_codes: tuple[Text, ...]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.claim.require("CLAIM")
        self.validation_receipt.require("RECEIPT")
        for item in self.required_evidence:
            item.require("EVIDENCE")
        return self
