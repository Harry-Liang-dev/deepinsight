"""G84 pure compatibility helpers; no dispatch, persistence or approval service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import Field

from src.memory.contracts import ResearchContextBundle, ResearchContextSection
from src.memory.vnext_contracts import (
    ROLE_STAGES,
    Action,
    ArtifactRef,
    Digest,
    Frozen,
    MemoryDelta,
    MemoryReadSet,
    MemoryWriteProposal,
    ResearchImpactPlan,
    ResearchMandate,
    Role,
    Scope,
    Text,
)
from src.models.enums import AgentName
from src.models.types import DomainModel
from src.schemas.memory import MemoryWriteRequest
from src.schemas.temporal import validate_temporal_access


def content_sha256(value: DomainModel) -> str:
    """Hash an existing typed payload without changing its schema."""
    return hashlib.sha256(
        json.dumps(
            value.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def permitted_actions(role: Role) -> frozenset[Action]:
    """Return the frozen logical matrix, not a caller-authentication mechanism."""
    if role == "outcome_recorder":
        return frozenset(("READ_HISTORY", "RECORD_OUTCOME"))
    if role == "coordinator":
        return frozenset(("READ_HISTORY", "UPDATE_WORKING_STATE"))
    common: frozenset[Action] = frozenset(
        (
            "READ_HISTORY",
            "CITE_VALIDATED_FACT",
            "PROPOSE_HYPOTHESIS",
            "APPEND_EVENT",
        )
    )
    if role == AgentName.RESEARCH_MANAGER:
        return common | {"REVIEW_FINAL_STATE"}
    if role not in {r for stage in ROLE_STAGES for r in stage}:
        raise ValueError("UNKNOWN_ROLE")
    return common


class MemoryAccessContext(Frozen):
    """Composition-root assigned identity/scopes; never filled from model JSON."""

    owner: Text
    role: Role
    scopes: tuple[Scope, ...] = Field(min_length=1)
    enabled: bool = False

    def require(self, action: Action, scope: Scope) -> None:
        """Fail closed on disabled access, role privilege or Scope mismatch."""
        if not self.enabled:
            raise ValueError("VNEXT_DISABLED")
        if action not in permitted_actions(self.role) or scope not in self.scopes:
            raise ValueError("MEMORY_PERMISSION_DENIED")


def validate_write_proposal(
    proposal: MemoryWriteProposal,
    payload: MemoryWriteRequest,
    *,
    access: MemoryAccessContext,
) -> MemoryWriteProposal:
    """Check a pending append proposal; do not call write or validate facts.

    W6 must resolve accepted Claims with existing validators before persistence.
    This function cannot return MemoryWriteResult or publication authority.
    """
    proposal = MemoryWriteProposal.model_validate_json(proposal.model_dump_json())
    payload = MemoryWriteRequest.model_validate_json(payload.model_dump_json())
    access.require(proposal.action, proposal.scope)
    if proposal.owner != access.owner or proposal.agent_role != access.role:
        raise ValueError("WRITER_IDENTITY_MISMATCH")
    if (
        payload.created_by != access.owner
        or payload.namespace_key != proposal.scope.scope_id
    ):
        raise ValueError("PAYLOAD_OWNER_SCOPE_MISMATCH")
    if content_sha256(payload) != proposal.payload.sha256_digest:
        raise ValueError("PAYLOAD_IDENTITY_MISMATCH")
    if payload.effective_ts > proposal.research_as_of:
        raise ValueError("FUTURE_MEMORY_PAYLOAD")
    if payload.metadata is None:
        raise ValueError("VERSIONED_MEMORY_METADATA_REQUIRED")
    if payload.metadata.scope_type != proposal.scope.scope_type:
        raise ValueError("PAYLOAD_SCOPE_TYPE_MISMATCH")
    validate_temporal_access(payload.metadata.temporal, proposal.research_as_of)
    if proposal.record_kind == "OUTCOME" and payload.metadata.outcome_id is None:
        raise ValueError("OUTCOME_REFERENCE_REQUIRED")
    return proposal


def read_set_from_bundle(
    bundle: ResearchContextBundle,
    *,
    bundle_ref: ArtifactRef,
    memory_refs: Mapping[str, ArtifactRef],
    access: MemoryAccessContext,
    scope: Scope,
    agent_run_id: str,
    record_id: str,
    created_at: datetime,
) -> MemoryReadSet:
    """Bind actual MemoryService output, including sources, to supplied context.

    This records delivery, not a claim that the LLM used every item. Source
    observation clocks come from retained records, never inferred from retrieval.
    """
    access.require("READ_HISTORY", scope)
    bundle = ResearchContextBundle.model_validate_json(bundle.model_dump_json())
    if content_sha256(bundle) != bundle_ref.sha256_digest:
        raise ValueError("BUNDLE_IDENTITY_MISMATCH")
    items = [
        item
        for section in ResearchContextSection
        for item in bundle.items_for_section(section)
    ]
    resolved: dict[str, ArtifactRef] = {}
    for item in items:
        if item.namespace_key not in {s.scope_id for s in access.scopes}:
            raise ValueError("MEMORY_SCOPE_LEAK")
        ref = memory_refs.get(item.memory_id)
        if (
            ref is None
            or ref.artifact_id != item.memory_id
            or ref.sha256_digest != content_sha256(item)
        ):
            raise ValueError("MEMORY_READ_IDENTITY_MISMATCH")
        if ref.owner != item.created_by or ref.available_at != item.available_at:
            raise ValueError("MEMORY_READ_LINEAGE_MISMATCH")
        if item.metadata is not None and (
            item.metadata.temporal.ingested_at is not None
            and ref.ingested_at != item.metadata.temporal.ingested_at
        ):
            raise ValueError("MEMORY_INGESTION_MISMATCH")
        if item.memory_id in resolved and resolved[item.memory_id] != ref:
            raise ValueError("CONFLICTING_MEMORY_VERSION")
        resolved[item.memory_id] = ref
    if set(memory_refs) != set(resolved):
        raise ValueError("READ_SET_POPULATION_MISMATCH")
    refs = tuple(resolved.values())
    return MemoryReadSet(
        owner=access.owner,
        record_id=record_id,
        revision=1,
        created_at=created_at,
        research_as_of=bundle.retrieval_metadata.as_of,
        scope=scope,
        source_refs=refs,
        bundle_ref=bundle_ref,
        agent_role=access.role,
        agent_run_id=agent_run_id,
        retrieval_query_id=bundle.retrieval_metadata.query_id,
        bundle_sha256=bundle_ref.sha256_digest,
        memory_refs=refs,
    )


class ReuseQualification(Frozen):
    """Exact resolver comparisons; completeness remains the resolver's duty."""

    state: ArtifactRef
    previous_dependencies: Digest
    current_dependencies: Digest
    previous_source_policy: Digest
    current_source_policy: Digest
    previous_strategy: Digest
    current_strategy: Digest
    valid_until: datetime

    def eligible(self, as_of: datetime) -> bool:
        """Reject expiry, future sources, and changed dependency/policy versions."""
        expiry = ArtifactRef.utc(self.valid_until)
        return (
            expiry > as_of
            and max(
                self.state.available_at, self.state.observed_at, self.state.ingested_at
            )
            <= as_of
            and self.previous_dependencies == self.current_dependencies
            and self.previous_source_policy == self.current_source_policy
            and self.previous_strategy == self.current_strategy
        )


class ImpactRule(Frozen):
    """Frozen scope-specific policy; changes require a new policy identity."""

    version: Literal["g84_impact_rule_v1"] = "g84_impact_rule_v1"
    owner: Text
    scope: Scope
    change_kind: Literal["MARKET_SNAPSHOT", "EVENT", "FILING", "CORRECTION", "RESEARCH"]
    direct_roles: tuple[Role, ...]
    rationale: Text


def plan_impact(
    delta: MemoryDelta,
    mandate: ResearchMandate,
    *,
    policy: ImpactRule,
    reuse: ReuseQualification | None = None,
    enabled: bool = False,
) -> ResearchImpactPlan:
    """Compute one-scope closure after a retained detector and Mandate resolution.

    Direct roles are the frozen impact policy's output, never Agent preference.
    W3 retains topology/coverage judgments; W6 resolves deltas and reuse evidence.
    Nothing here schedules an Agent, approves payment or writes ResearchState.
    """
    if not enabled:
        raise ValueError("VNEXT_DISABLED")
    delta = MemoryDelta.model_validate_json(delta.model_dump_json())
    mandate = ResearchMandate.model_validate_json(mandate.model_dump_json())
    policy = ImpactRule.model_validate_json(policy.model_dump_json())
    if policy.scope != delta.scope or policy.change_kind != delta.change_kind:
        raise ValueError("IMPACT_POLICY_SCOPE_MISMATCH")
    direct_roles = policy.direct_roles
    all_roles = {r for stage in ROLE_STAGES for r in stage}
    if set(direct_roles) - all_roles or len(set(direct_roles)) != len(direct_roles):
        raise ValueError("INVALID_IMPACT_ROLE_POPULATION")
    affected: set[Role] = set(direct_roles) if delta.material else set()
    stages: list[tuple[Role, ...]] = []
    for stage in ROLE_STAGES:
        selected = tuple(r for r in stage if r in affected)
        if selected:
            stages.append(selected)
            for downstream in ROLE_STAGES[ROLE_STAGES.index(stage) + 1 :]:
                affected.update(downstream)
    reusable = None
    disposition: Literal[
        "SELECTIVE_EXECUTION", "REUSE", "BLOCKED_REUSE", "BLOCKED_MANDATE"
    ]
    if (
        delta.scope not in mandate.allowed_scopes
        or mandate.created_at > delta.created_at
        or mandate.expires_at <= delta.created_at
        or affected - set(mandate.allowed_roles)
    ):
        disposition, reason = (
            "BLOCKED_MANDATE",
            "Scope, expiry or downstream roles outside research Mandate",
        )
        stages = []
    elif delta.material and stages:
        disposition, reason = (
            "SELECTIVE_EXECUTION",
            "Material delta and explicit policy dependency closure",
        )
    elif (
        not delta.material
        and reuse is not None
        and reuse.eligible(delta.research_as_of)
    ):
        disposition, reason, reusable = (
            "REUSE",
            "Exact dependencies, source policy, strategy and freshness match",
            reuse.state,
        )
    else:
        disposition, reason = (
            "BLOCKED_REUSE",
            "Missing impact mapping or unqualified prior State; no full rerun",
        )
    return ResearchImpactPlan(
        owner="coordinator",
        record_id=f"impact:{delta.sha256}",
        revision=1,
        created_at=delta.created_at,
        research_as_of=delta.research_as_of,
        scope=delta.scope,
        source_refs=delta.source_refs,
        delta_sha256=delta.sha256,
        mandate_sha256=mandate.sha256,
        policy_sha256=policy.sha256,
        direct_roles=direct_roles if delta.material else (),
        execution_stages=tuple(stages),
        reusable_state=reusable,
        disposition=disposition,
        reason=reason,
    )
