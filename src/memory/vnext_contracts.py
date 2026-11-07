"""G84 opt-in reference contracts; no new factual or execution authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import AgentName, MemoryLevel, ResearchScopeType
from src.models.types import DomainModel

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Role = AgentName | Literal["trader", "coordinator", "outcome_recorder"]
RecordKind = Literal[
    "FACT", "INFERENCE", "HYPOTHESIS", "RESEARCH_QUESTION", "TRADE_PROPOSAL", "OUTCOME"
]
Action = Literal[
    "READ_HISTORY",
    "CITE_VALIDATED_FACT",
    "PROPOSE_HYPOTHESIS",
    "APPEND_EVENT",
    "UPDATE_WORKING_STATE",
    "REVIEW_FINAL_STATE",
    "RECORD_OUTCOME",
]

ROLE_STAGES: tuple[tuple[Role, ...], ...] = (
    (
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    ),
    (AgentName.BULL_MANAGER, AgentName.BEAR_MANAGER),
    (AgentName.RISK_MANAGER,),
    ("trader",),
    (AgentName.RESEARCH_MANAGER,),
)


class Frozen(DomainModel):
    """Immutable, extra-forbidden interchange record with content identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def sha256(self) -> str:
        """Hash canonical UTF-8 JSON, independent of display formatting."""
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()


class Scope(Frozen):
    """Existing Phase4 Scope identity, orthogonal to L0–L4."""

    scope_type: ResearchScopeType
    scope_id: Text

    @model_validator(mode="after")
    def prefix(self) -> Self:
        """Keep the existing namespace convention; never imply membership."""
        prefix = {
            ResearchScopeType.GLOBAL: "GLOBAL:",
            ResearchScopeType.MACRO: "MACRO:",
            ResearchScopeType.SECTOR: "SECTOR:",
            ResearchScopeType.INDUSTRY_CHAIN: "CHAIN:",
            ResearchScopeType.ASSET: "ASSET:",
            ResearchScopeType.RESEARCH_EPISODE: "EPISODE:",
        }[self.scope_type]
        if (
            not self.scope_id.startswith(prefix)
            or not self.scope_id[len(prefix) :].strip()
        ):
            raise ValueError("SCOPE_ID_MISMATCH")
        return self


class ArtifactRef(Frozen):
    """Exact external identity; a reference is not a verification receipt."""

    artifact_id: Text
    sha256_digest: Digest
    version: Text
    owner: Text
    available_at: datetime
    observed_at: datetime
    ingested_at: datetime

    @field_validator("available_at", "observed_at", "ingested_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        """Require actual timezone-aware clocks without inventing availability."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AWARE_CLOCK_REQUIRED")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def observation_order(self) -> Self:
        """Never backdate ingestion before the retained observation."""
        if self.ingested_at < self.observed_at:
            raise ValueError("INGESTION_PRECEDES_OBSERVATION")
        return self

    def require_recorded_by(self, clock: datetime) -> None:
        """Check generated lineage against recording time, not event cutoff."""
        if max(self.available_at, self.observed_at, self.ingested_at) > clock:
            raise ValueError("FUTURE_LINEAGE")


class Envelope(Frozen):
    """Common owner, revision and time boundary for development interfaces."""

    owner: Text
    record_id: Text
    revision: int = Field(ge=1)
    supersedes: ArtifactRef | None = None
    created_at: datetime
    research_as_of: datetime
    scope: Scope
    source_refs: tuple[ArtifactRef, ...] = Field(min_length=1)
    mode: Literal["DEVELOPMENT_ONLY_OPT_IN"] = "DEVELOPMENT_ONLY_OPT_IN"

    @field_validator("created_at", "research_as_of")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        """Normalize clocks, preserving the distinction from source time."""
        return ArtifactRef.utc(value)

    @model_validator(mode="after")
    def lineage(self) -> Self:
        """Use conservative historical eligibility for this offline foundation."""
        if self.created_at < self.research_as_of:
            raise ValueError("CREATION_PRECEDES_CUTOFF")
        if (self.revision == 1) != (self.supersedes is None):
            raise ValueError("REVISION_PARENT_REQUIRED")
        if self.supersedes is not None:
            self.supersedes.require_recorded_by(self.created_at)
        for ref in self.source_refs:
            if (
                max(ref.available_at, ref.observed_at, ref.ingested_at)
                > self.research_as_of
            ):
                raise ValueError("FUTURE_SOURCE")
        if len({r.sha256 for r in self.source_refs}) != len(self.source_refs):
            raise ValueError("DUPLICATE_SOURCE_REFERENCE")
        return self


class MemoryDelta(Envelope):
    """Observed before/after identities, not an LLM assertion of change."""

    schema_version: Literal["memory_delta_v1"] = "memory_delta_v1"
    memory_level: MemoryLevel
    change_kind: Literal["MARKET_SNAPSHOT", "EVENT", "FILING", "CORRECTION", "RESEARCH"]
    before: ArtifactRef | None
    after: ArtifactRef
    change_detector: ArtifactRef
    materiality_rule: ArtifactRef
    material: bool

    @model_validator(mode="after")
    def change_binding(self) -> Self:
        """Require detector evidence and reject material no-op changes."""
        refs = {r.sha256 for r in self.source_refs}
        required = (self.after,)
        self.change_detector.require_recorded_by(self.created_at)
        self.materiality_rule.require_recorded_by(self.created_at)
        if any(r.sha256 not in refs for r in required):
            raise ValueError("DELTA_EVIDENCE_MISSING")
        if self.before is not None:
            if self.before.sha256 not in refs:
                raise ValueError("BEFORE_EVIDENCE_MISSING")
            if self.before.artifact_id != self.after.artifact_id:
                raise ValueError("DELTA_SUBJECT_MISMATCH")
            if self.before.sha256_digest == self.after.sha256_digest and self.material:
                raise ValueError("UNCHANGED_CONTENT_NOT_MATERIAL")
        return self


class MemoryReadSet(Envelope):
    """Actual supplied Memory versions, wrapping existing retrieval contracts."""

    schema_version: Literal["memory_read_set_v1"] = "memory_read_set_v1"
    agent_role: Role
    agent_run_id: Text
    retrieval_query_id: Text
    source_refs: tuple[ArtifactRef, ...] = ()
    bundle_ref: ArtifactRef
    bundle_sha256: Digest
    memory_refs: tuple[ArtifactRef, ...]
    authority: Literal["CONTEXT_ONLY"] = "CONTEXT_ONLY"

    @model_validator(mode="after")
    def read_population(self) -> Self:
        """Every unique read must be bound to retained source evidence."""
        self.bundle_ref.require_recorded_by(self.created_at)
        if self.bundle_sha256 != self.bundle_ref.sha256_digest:
            raise ValueError("BUNDLE_IDENTITY_MISMATCH")
        if len({r.artifact_id for r in self.memory_refs}) != len(self.memory_refs):
            raise ValueError("DUPLICATE_MEMORY_READ")
        if any(r not in self.source_refs for r in self.memory_refs):
            raise ValueError("UNBOUND_MEMORY_READ")
        return self


class MemoryWriteProposal(Envelope):
    """Proposal for existing MemoryWriteRequest; never an accepted fact/write."""

    schema_version: Literal["memory_write_proposal_v1"] = "memory_write_proposal_v1"
    agent_role: Role
    agent_run_id: Text
    action: Action
    record_kind: RecordKind
    payload: ArtifactRef
    read_set: ArtifactRef
    status: Literal["PENDING_EXISTING_VALIDATION"] = "PENDING_EXISTING_VALIDATION"

    @model_validator(mode="after")
    def proposal_binding(self) -> Self:
        """Bind a payload and read set without promoting their contents."""
        self.payload.require_recorded_by(self.created_at)
        self.read_set.require_recorded_by(self.created_at)
        allowed: dict[Action, tuple[RecordKind, ...]] = {
            "CITE_VALIDATED_FACT": ("FACT",),
            "PROPOSE_HYPOTHESIS": ("HYPOTHESIS", "RESEARCH_QUESTION", "INFERENCE"),
            "APPEND_EVENT": (
                "INFERENCE",
                "HYPOTHESIS",
                "RESEARCH_QUESTION",
                "TRADE_PROPOSAL",
            ),
            "UPDATE_WORKING_STATE": ("INFERENCE",),
            "REVIEW_FINAL_STATE": ("INFERENCE",),
            "RECORD_OUTCOME": ("OUTCOME",),
            "READ_HISTORY": (),
        }
        if self.record_kind not in allowed[self.action]:
            raise ValueError("RECORD_KIND_ACTION_MISMATCH")
        if self.record_kind == "TRADE_PROPOSAL" and self.agent_role != "trader":
            raise ValueError("TRADER_REQUIRED")
        return self


class ResearchMandate(Envelope):
    """Research-only selection record; runtime must resolve actual authority."""

    schema_version: Literal["research_mandate_v1"] = "research_mandate_v1"
    opportunity: ArtifactRef
    authorization: ArtifactRef
    selection: Literal["HUMAN_SELECTION", "PREAUTHORIZED_MANDATE"]
    allowed_scopes: tuple[Scope, ...] = Field(min_length=1)
    allowed_roles: tuple[Role, ...] = Field(min_length=1)
    expires_at: datetime
    authority: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime) -> datetime:
        """Require an explicit authorization expiry."""
        return ArtifactRef.utc(value)

    @model_validator(mode="after")
    def mandate_binding(self) -> Self:
        """Bind the opportunity/decision and prohibit already expired scope."""
        if (
            self.opportunity not in self.source_refs
            or self.authorization not in self.source_refs
        ):
            raise ValueError("MANDATE_AUTHORITY_REFERENCE_MISSING")
        if self.expires_at <= self.created_at or self.scope not in self.allowed_scopes:
            raise ValueError("INVALID_MANDATE_SCOPE_OR_EXPIRY")
        if len(set(self.allowed_roles)) != len(self.allowed_roles):
            raise ValueError("DUPLICATE_MANDATE_ROLE")
        return self


class ResearchImpactPlan(Envelope):
    """Deterministic dependency closure; not a dispatch or publication grant."""

    schema_version: Literal["research_impact_plan_v1"] = "research_impact_plan_v1"
    delta_sha256: Digest
    mandate_sha256: Digest
    policy_sha256: Digest
    direct_roles: tuple[Role, ...]
    execution_stages: tuple[tuple[Role, ...], ...]
    reusable_state: ArtifactRef | None
    disposition: Literal[
        "SELECTIVE_EXECUTION", "REUSE", "BLOCKED_REUSE", "BLOCKED_MANDATE"
    ]
    reason: Text


class TradeProposal(Envelope):
    """Non-executable thesis/risk/counterevidence submitted by logical Trader."""

    schema_version: Literal["trade_proposal_v1"] = "trade_proposal_v1"
    mandate_sha256: Digest
    author_role: Literal["trader"] = "trader"
    thesis: Text
    invalidation_conditions: tuple[Text, ...] = Field(min_length=1)
    risk_review: ArtifactRef
    authority: Literal["NON_EXECUTABLE_RESEARCH"] = "NON_EXECUTABLE_RESEARCH"

    @model_validator(mode="after")
    def risk_binding(self) -> Self:
        """Require actual preceding risk-review lineage."""
        self.risk_review.require_recorded_by(self.created_at)
        return self


class ResearchReviewDecision(Envelope):
    """Final research-only review; existing State builders still own admission."""

    schema_version: Literal["research_review_decision_v1"] = (
        "research_review_decision_v1"
    )
    reviewer_role: Literal["research_manager"] = "research_manager"
    proposal: ArtifactRef
    working_state: ArtifactRef
    decision: Literal["APPROVE_RESEARCH", "REVISE", "REJECT", "ABSTAIN"]
    reasons: tuple[Text, ...] = Field(min_length=1)
    execution_authorized: Literal[False] = False
    production_admission: Literal[False] = False

    @model_validator(mode="after")
    def review_binding(self) -> Self:
        """Preserve both proposal and prior working State identities."""
        self.proposal.require_recorded_by(self.created_at)
        self.working_state.require_recorded_by(self.created_at)
        return self
