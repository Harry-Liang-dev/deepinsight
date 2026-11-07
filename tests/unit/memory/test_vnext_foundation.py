"""G84 ENGINEERING_DEVELOPMENT contracts; no Provider or model execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.memory import MemoryService, ResearchContextRequest
from src.memory.vnext import (
    ImpactRule,
    MemoryAccessContext,
    ReuseQualification,
    content_sha256,
    permitted_actions,
    plan_impact,
    read_set_from_bundle,
    validate_write_proposal,
)
from src.memory.vnext_contracts import (
    ROLE_STAGES,
    ArtifactRef,
    MemoryDelta,
    MemoryReadSet,
    MemoryWriteProposal,
    ResearchMandate,
    ResearchReviewDecision,
    Scope,
    TradeProposal,
)
from src.models.enums import AgentName, Market, MemoryLevel, ResearchScopeType
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.schemas.common import SourceReference
from src.schemas.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    MemoryWriteRequest,
)
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind
from src.services.embedding import FakeEmbeddingService

NOW = datetime(2026, 10, 28, 10, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
SCOPE = Scope(scope_type=ResearchScopeType.SECTOR, scope_id="SECTOR:S03")
ANALYST = AgentName.FUNDAMENTAL_ANALYST


def ref(name: str, digest: str = "a" * 64) -> ArtifactRef:
    """Build retained synthetic lineage, not a scientific proof."""
    return ArtifactRef(
        artifact_id=name,
        sha256_digest=digest,
        version="v1",
        owner="test",
        available_at=EARLIER,
        observed_at=EARLIER,
        ingested_at=EARLIER,
    )


def common() -> dict[str, object]:
    """Return explicit offline envelope fields."""
    return dict(
        owner="test",
        record_id="record",
        revision=1,
        created_at=NOW,
        research_as_of=NOW,
        scope=SCOPE,
        source_refs=(ref("source"),),
    )


def mandate() -> ResearchMandate:
    """Represent a synthetic preauthorized research-only decision."""
    return ResearchMandate.model_validate(
        {
            **common(),
            "source_refs": (ref("card"), ref("authorization")),
            "opportunity": ref("card"),
            "authorization": ref("authorization"),
            "selection": "HUMAN_SELECTION",
            "allowed_scopes": (SCOPE,),
            "allowed_roles": tuple(r for stage in ROLE_STAGES for r in stage),
            "expires_at": NOW + timedelta(days=1),
        }
    )


def delta(material: bool = True) -> MemoryDelta:
    """Compare retained source content, using an explicit materiality rule."""
    return MemoryDelta.model_validate(
        {
            **common(),
            "memory_level": "L0",
            "change_kind": "MARKET_SNAPSHOT",
            "before": ref("source", "b" * 64),
            "after": ref("source"),
            "source_refs": (ref("source", "b" * 64), ref("source")),
            "change_detector": ref("detector"),
            "materiality_rule": ref("materiality"),
            "material": material,
        }
    )


def rule() -> ImpactRule:
    """Only Technical is directly impacted by this synthetic price rule."""
    return ImpactRule(
        owner="W3",
        scope=SCOPE,
        change_kind="MARKET_SNAPSHOT",
        direct_roles=(AgentName.TECHNICAL_TEXT_ANALYST,),
        rationale="Synthetic material price threshold crossed",
    )


def reuse() -> ReuseQualification:
    """Require all four independent reuse dimensions."""
    return ReuseQualification(
        state=ref("state"),
        previous_dependencies="a" * 64,
        current_dependencies="a" * 64,
        previous_source_policy="b" * 64,
        current_source_policy="b" * 64,
        previous_strategy="c" * 64,
        current_strategy="c" * 64,
        valid_until=NOW + timedelta(hours=1),
    )


def payload() -> MemoryWriteRequest:
    """Reuse the original Phase4 request and metadata contracts."""
    return MemoryWriteRequest(
        memory_level=MemoryLevel.L3,
        namespace_key=SCOPE.scope_id,
        effective_ts=EARLIER,
        summary_text="Retained research hypothesis",
        memory_type="episode_reference",
        importance_score=0.8,
        source_ref_json=SourceReference(document_id="source"),
        created_by="test",
        metadata=LearningMemoryMetadata(
            usage_class=LearningMemoryUsageClass.EPISODIC,
            scope_type=SCOPE.scope_type,
            scope_id=SCOPE.scope_id,
            parent_scope_id="MACRO:US",
            episode_id="research_episode_" + "1" * 24,
            research_state_id="research_state_" + "2" * 24,
            content_kind=EpisodicMemoryContentKind.EPISODE_REFERENCE,
            temporal=TemporalMetadata(
                source_kind=TemporalSourceKind.MEMORY,
                available_at=EARLIER,
                ingested_at=EARLIER,
            ),
        ),
    )


def proposal() -> MemoryWriteProposal:
    """Do not promote this valid proposal into an accepted Claim."""
    return MemoryWriteProposal.model_validate(
        {
            **common(),
            "agent_role": ANALYST,
            "agent_run_id": "run",
            "action": "PROPOSE_HYPOTHESIS",
            "record_kind": "HYPOTHESIS",
            "payload": ref("payload", content_sha256(payload())),
            "read_set": ref("reads"),
        }
    )


def test_default_disabled_and_existing_roles_unchanged() -> None:
    with pytest.raises(ValueError, match="VNEXT_DISABLED"):
        plan_impact(delta(), mandate(), policy=rule())
    assert len(AgentName) == 8
    assert ROLE_STAGES[-2:] == (("trader",), (AgentName.RESEARCH_MANAGER,))
    assert tuple(MemoryLevel) == tuple(MemoryLevel(f"L{i}") for i in range(5))


def test_selective_closure_not_all_analysts() -> None:
    plan = plan_impact(delta(), mandate(), policy=rule(), enabled=True)
    assert plan.disposition == "SELECTIVE_EXECUTION"
    assert plan.execution_stages[0] == (AgentName.TECHNICAL_TEXT_ANALYST,)
    assert plan.execution_stages[1:] == ROLE_STAGES[1:]
    assert ANALYST not in {r for stage in plan.execution_stages for r in stage}
    assert plan.policy_sha256 == rule().sha256


def test_daily_nonmaterial_change_reuses_without_dispatch() -> None:
    plan = plan_impact(
        delta(False), mandate(), policy=rule(), reuse=reuse(), enabled=True
    )
    assert plan.disposition == "REUSE"
    assert plan.execution_stages == ()
    assert plan.reusable_state == ref("state")


@pytest.mark.parametrize(
    "field",
    [
        "current_dependencies",
        "current_source_policy",
        "current_strategy",
        "valid_until",
    ],
)
def test_stale_reuse_is_blocked_not_full_rerun(field: str) -> None:
    data = reuse().model_dump()
    data[field] = NOW if field == "valid_until" else "f" * 64
    plan = plan_impact(
        delta(False),
        mandate(),
        policy=rule(),
        reuse=ReuseQualification.model_validate(data),
        enabled=True,
    )
    assert plan.disposition == "BLOCKED_REUSE"
    assert plan.execution_stages == ()


def test_no_material_change_without_reuse_evidence_blocks() -> None:
    assert (
        plan_impact(delta(False), mandate(), policy=rule(), enabled=True).disposition
        == "BLOCKED_REUSE"
    )


def test_downstream_outside_mandate_cannot_run() -> None:
    data = mandate().model_dump()
    data["allowed_roles"] = (AgentName.TECHNICAL_TEXT_ANALYST,)
    plan = plan_impact(
        delta(), ResearchMandate.model_validate(data), policy=rule(), enabled=True
    )
    assert plan.disposition == "BLOCKED_MANDATE"
    assert plan.execution_stages == ()


def test_expired_mandate_and_wrong_impact_scope_block() -> None:
    late = delta().model_dump()
    late["created_at"] = NOW + timedelta(days=2)
    result = plan_impact(
        MemoryDelta.model_validate(late), mandate(), policy=rule(), enabled=True
    )
    assert result.disposition == "BLOCKED_MANDATE"
    wrong = rule().model_dump()
    wrong["scope"] = Scope(scope_type=ResearchScopeType.SECTOR, scope_id="SECTOR:OTHER")
    with pytest.raises(ValueError, match="IMPACT_POLICY_SCOPE_MISMATCH"):
        plan_impact(
            delta(), mandate(), policy=ImpactRule.model_validate(wrong), enabled=True
        )


def test_missing_policy_roots_block_material_delta() -> None:
    empty = ImpactRule.model_validate({**rule().model_dump(), "direct_roles": ()})
    result = plan_impact(delta(), mandate(), policy=empty, enabled=True)
    assert result.disposition == "BLOCKED_REUSE"
    assert result.execution_stages == ()


@pytest.mark.parametrize("field", ["available_at", "observed_at", "ingested_at"])
def test_future_state_is_not_reusable(field: str) -> None:
    data = reuse().model_dump()
    state = ref("state").model_dump()
    state[field] = NOW + timedelta(days=1)
    if field == "observed_at":
        state["ingested_at"] = state[field]
    data["state"] = state
    plan = plan_impact(
        delta(False),
        mandate(),
        policy=rule(),
        reuse=ReuseQualification.model_validate(data),
        enabled=True,
    )
    assert plan.disposition == "BLOCKED_REUSE"


@pytest.mark.parametrize(
    "scope_type,prefix",
    [
        ("global", "GLOBAL"),
        ("macro", "MACRO"),
        ("sector", "SECTOR"),
        ("industry_chain", "CHAIN"),
        ("asset", "ASSET"),
        ("research_episode", "EPISODE"),
    ],
)
def test_scope_contract(scope_type: str, prefix: str) -> None:
    assert Scope.model_validate({"scope_type": scope_type, "scope_id": prefix + ":x"})
    with pytest.raises(ValidationError, match="SCOPE_ID_MISMATCH"):
        Scope.model_validate({"scope_type": scope_type, "scope_id": "WRONG:x"})


def test_unchanged_content_cannot_be_material() -> None:
    data = delta().model_dump()
    data["before"] = ref("source")
    data["source_refs"] = (ref("source"),)
    with pytest.raises(ValidationError, match="UNCHANGED_CONTENT_NOT_MATERIAL"):
        MemoryDelta.model_validate(data)


def test_future_outcome_cannot_leak_into_history() -> None:
    future = ref("future").model_copy(update={"available_at": NOW + timedelta(days=1)})
    with pytest.raises(ValidationError, match="FUTURE_SOURCE"):
        MemoryWriteProposal.model_validate(
            {**proposal().model_dump(), "source_refs": (future,)}
        )


@pytest.mark.parametrize("role", [*AgentName, "trader"])
def test_agents_cannot_record_outcomes_or_update_state(role: str) -> None:
    access = MemoryAccessContext.model_validate(
        dict(owner="test", role=role, scopes=(SCOPE,), enabled=True)
    )
    for action in ("RECORD_OUTCOME", "UPDATE_WORKING_STATE"):
        with pytest.raises(ValueError, match="MEMORY_PERMISSION_DENIED"):
            access.require(action, SCOPE)
    if role != "research_manager":
        with pytest.raises(ValueError, match="MEMORY_PERMISSION_DENIED"):
            access.require("REVIEW_FINAL_STATE", SCOPE)


def test_coordinator_cannot_review_and_manager_cannot_execute() -> None:
    assert "REVIEW_FINAL_STATE" not in permitted_actions("coordinator")
    decision = ResearchReviewDecision.model_validate(
        {
            **common(),
            "proposal": ref("proposal"),
            "working_state": ref("state"),
            "decision": "APPROVE_RESEARCH",
            "reasons": ("Synthetic research review",),
        }
    )
    assert not decision.execution_authorized and not decision.production_admission
    with pytest.raises(ValidationError):
        ResearchReviewDecision.model_validate(
            {**decision.model_dump(), "execution_authorized": True}
        )


def test_trade_proposal_cannot_be_an_order() -> None:
    data = {
        **common(),
        "mandate_sha256": mandate().sha256,
        "thesis": "Hypothesis",
        "invalidation_conditions": ("Evidence contradicts thesis",),
        "risk_review": ref("risk"),
    }
    assert TradeProposal.model_validate(data).authority == "NON_EXECUTABLE_RESEARCH"
    for field in ("order", "position_weight", "target_price"):
        with pytest.raises(ValidationError):
            TradeProposal.model_validate({**data, field: 10})


def test_pending_append_proposal_and_identity_checks() -> None:
    access = MemoryAccessContext(
        owner="test", role=ANALYST, scopes=(SCOPE,), enabled=True
    )
    result = validate_write_proposal(proposal(), payload(), access=access)
    assert result.status == "PENDING_EXISTING_VALIDATION"
    changed = payload()
    changed.summary_text = "Different text"
    with pytest.raises(ValueError, match="PAYLOAD_IDENTITY_MISMATCH"):
        validate_write_proposal(proposal(), changed, access=access)
    with pytest.raises(ValueError, match="WRITER_IDENTITY_MISMATCH"):
        validate_write_proposal(
            proposal(), payload(), access=access.model_copy(update={"owner": "other"})
        )
    with pytest.raises(ValidationError, match="RECORD_KIND_ACTION_MISMATCH"):
        MemoryWriteProposal.model_validate(
            {**proposal().model_dump(), "record_kind": "FACT"}
        )


def test_disabled_and_cross_scope_proposal_denied() -> None:
    access = MemoryAccessContext(owner="test", role=ANALYST, scopes=(SCOPE,))
    with pytest.raises(ValueError, match="VNEXT_DISABLED"):
        validate_write_proposal(proposal(), payload(), access=access)
    other = Scope(scope_type=ResearchScopeType.SECTOR, scope_id="SECTOR:OTHER")
    with pytest.raises(ValueError, match="MEMORY_PERMISSION_DENIED"):
        validate_write_proposal(
            proposal(),
            payload(),
            access=access.model_copy(update={"enabled": True, "scopes": (other,)}),
        )


def test_append_revision_requires_parent_and_frozen_objects() -> None:
    with pytest.raises(ValidationError, match="REVISION_PARENT_REQUIRED"):
        MemoryWriteProposal.model_validate({**proposal().model_dump(), "revision": 2})
    revised = MemoryWriteProposal.model_validate(
        {**proposal().model_dump(), "revision": 2, "supersedes": ref("previous")}
    )
    assert revised.sha256 != proposal().sha256
    with pytest.raises(ValidationError):
        revised.owner = "other"


def test_existing_duckdb_faiss_memoryservice_to_read_set(tmp_path: Path) -> None:
    """Use the actual old service; no parallel Memory implementation."""
    database = DuckDBDatabase(tmp_path / "memory.duckdb")
    database.bootstrap()
    embedder = FakeEmbeddingService(
        {payload().summary_text: [1.0, 0.0], "query": [1.0, 0.0]}
    )
    service = MemoryService(
        MemoryItemRepository(database),
        FaissVectorRepository(
            tmp_path / "faiss",
            embedder_model=embedder.model_name,
            embedding_dim=embedder.dimension,
        ),
        embedder,
        clock=lambda: EARLIER,
        memory_id_factory=lambda: "memory-g84",
    )
    write = service.write(payload())
    bundle = service.retrieve_context(
        ResearchContextRequest(
            query_text="query",
            as_of=NOW,
            market=Market.US,
            namespace_keys=[SCOPE.scope_id],
            memory_levels=[MemoryLevel.L3],
        )
    )
    item = bundle.prior_research[0]
    assert item.memory_id == write.memory_id
    access = MemoryAccessContext(
        owner="test", role=ANALYST, scopes=(SCOPE,), enabled=True
    )
    bundle_ref = ref("bundle", content_sha256(bundle))
    memory_refs = {item.memory_id: ref(item.memory_id, content_sha256(item))}

    def read() -> MemoryReadSet:
        return read_set_from_bundle(
            bundle,
            bundle_ref=bundle_ref,
            memory_refs=memory_refs,
            access=access,
            scope=SCOPE,
            agent_run_id="run",
            record_id="reads",
            created_at=NOW,
        )

    reads = read()
    assert reads.memory_refs[0].artifact_id == write.memory_id
    assert reads.authority == "CONTEXT_ONLY"
    assert reads.sha256 == read().sha256
    original_ref = memory_refs[item.memory_id]
    memory_refs[item.memory_id] = original_ref.model_copy(update={"owner": "other"})
    with pytest.raises(ValueError, match="MEMORY_READ_LINEAGE_MISMATCH"):
        read()
    memory_refs[item.memory_id] = original_ref
    bundle.prior_research[0].summary_text = "Tampered"
    with pytest.raises(ValueError, match="BUNDLE_IDENTITY_MISMATCH"):
        read()
