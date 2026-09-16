"""ResearchEpisode v1 identity, audit, and privacy tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.models.enums import AgentName, AgentStatus
from src.schemas.research_episode import (
    AgentExecutionTrace,
    ResearchEpisodeBuildInput,
    ResearchEpisodeTraceQuality,
)
from src.schemas.research_state import ResearchStateBuildInput, ResearchStateSnapshot
from src.schemas.sector_usage import SectorContextUsageDiagnostic
from src.services.research_episode import (
    ResearchEpisodeBuilder,
    ResearchEpisodeBuildError,
)
from src.services.research_state import ResearchStateBuilder
from tests.unit.agents.test_input_contracts import AS_OF, _data_bundle
from tests.unit.services.test_research_state import _claim_inputs, _sector_input
from tests.unit.services.test_sector_context import _aligned_asset_bundles


def _state() -> ResearchStateSnapshot:
    return ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            accepted_claims=_claim_inputs(),
            source_run_id="episode-fixture",
        )
    )


def _complete_traces() -> tuple[AgentExecutionTrace, ...]:
    return (
        AgentExecutionTrace(
            agent_role=AgentName.FUNDAMENTAL_ANALYST,
            agent_run_id="run:fundamental",
            status=AgentStatus.OK,
            input_context_ids=("rdb_fixture",),
            output_claim_ids=(
                "fundamental:claim:0",
                "rejected_claim_000000000000000000000001",
            ),
            accepted_claim_ids=("fundamental:claim:0",),
            rejected_claim_ids=("rejected_claim_000000000000000000000001",),
            accepted_claim_count=1,
            rejected_claim_count=1,
            latency_ms=10,
            provider="fake_offline",
            model="fixed-model",
            prompt_version="v1",
            trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
        ),
        AgentExecutionTrace(
            agent_role=AgentName.RESEARCH_MANAGER,
            agent_run_id="run:research",
            status=AgentStatus.OK,
            input_context_ids=("rdb_fixture",),
            provided_claim_ids=("fundamental:claim:0",),
            output_claim_ids=("research:claim:0",),
            accepted_claim_ids=("research:claim:0",),
            accepted_claim_count=1,
            rejected_claim_count=0,
            latency_ms=8,
            provider="fake_offline",
            model="fixed-model",
            prompt_version="v1",
            trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
        ),
    )


def test_complete_episode_references_state_and_claim_identities() -> None:
    """Episode records the process while State remains a separate artifact."""

    state = _state()
    episode = ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=_complete_traces(),
            report_id="report-fixture",
            created_at=AS_OF + timedelta(minutes=1),
            source_artifact_ids=("fixture-agent-db",),
        )
    )

    assert episode.research_state_id == state.research_state_id
    assert episode.data_snapshot_id == state.lineage.data_snapshot_id
    assert episode.accepted_claim_ids == (
        "fundamental:claim:0",
        "research:claim:0",
    )
    assert episode.rejected_claim_ids == ("rejected_claim_000000000000000000000001",)
    assert episode.final_research_claim_ids == ("research:claim:0",)
    assert episode.trace_quality is ResearchEpisodeTraceQuality.COMPLETE
    assert "research_state" not in type(episode).model_fields


def test_episode_is_deterministic_and_immutable() -> None:
    """The same frozen process produces one identity and cannot be overwritten."""

    inputs = ResearchEpisodeBuildInput(
        research_state=_state(),
        agent_traces=_complete_traces(),
        created_at=AS_OF + timedelta(minutes=1),
    )
    first = ResearchEpisodeBuilder().build(inputs)
    second = ResearchEpisodeBuilder().build(inputs)

    assert first == second
    assert first.episode_id == second.episode_id
    with pytest.raises(ValidationError, match="frozen"):
        first.report_id = "changed-report"


def test_private_reasoning_is_not_an_episode_or_trace_field() -> None:
    """Extra reasoning/COT payloads are rejected instead of persisted."""

    values = _complete_traces()[0].model_dump()
    values["private_reasoning"] = "hidden chain of thought"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentExecutionTrace.model_validate(values)

    assert "private_reasoning" not in AgentExecutionTrace.model_fields
    assert "chain_of_thought" not in AgentExecutionTrace.model_fields


def test_partial_legacy_episode_keeps_counts_without_inventing_claim_ids() -> None:
    """Old summaries can remain measurable while identity gaps stay explicit."""

    partial = AgentExecutionTrace(
        agent_role=AgentName.FUNDAMENTAL_ANALYST,
        agent_run_id="fixed:fundamental_analyst",
        status=AgentStatus.OK,
        input_context_ids=("rdb_fixture",),
        accepted_claim_count=5,
        rejected_claim_count=1,
        provider="qwen",
        model="qwen3.7-flash",
        prompt_version="v10",
        trace_quality=ResearchEpisodeTraceQuality.PARTIAL,
        missing_metadata=(
            "accepted_claim_ids_not_persisted",
            "rejected_claim_ids_not_persisted",
        ),
    )
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            source_run_id="legacy-summary",
        )
    )
    episode = ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(partial,),
            created_at=AS_OF + timedelta(minutes=1),
            missing_metadata=("asset_claim_identities_not_persisted",),
        )
    )

    assert episode.accepted_claim_count == 5
    assert episode.accepted_claim_ids == ()
    assert episode.rejected_claim_count == 1
    assert episode.trace_quality is ResearchEpisodeTraceQuality.PARTIAL


def test_complete_trace_cannot_hide_missing_claim_identities() -> None:
    """COMPLETE means retained IDs exactly match the recorded counts."""

    with pytest.raises(ValidationError, match="all accepted Claim IDs"):
        AgentExecutionTrace(
            agent_role=AgentName.FUNDAMENTAL_ANALYST,
            agent_run_id="run:fundamental",
            status=AgentStatus.OK,
            accepted_claim_count=1,
            rejected_claim_count=0,
            provider="fake",
            model="fixed",
            prompt_version="v1",
            trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
        )


def test_sector_usage_reuses_day36_diagnostic_contract() -> None:
    """Episode embeds the existing usage metadata without a second schema."""

    data, _ = _aligned_asset_bundles()
    sector = _sector_input()
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=data,
            sector_context=sector,
            source_run_id="sector-episode-fixture",
        )
    )
    sector_claim_id = next(
        claim.claim_id for claim in sector.accepted_claims if claim.claim_id is not None
    )
    usage = SectorContextUsageDiagnostic(
        sector_context_id=sector.context_id,
        agent_role=AgentName.RESEARCH_MANAGER,
        provided_sector_claim_ids=(sector_claim_id,),
        used_sector_claim_ids=(sector_claim_id,),
        provided_event_ids=("event-1",),
        used_event_ids=("event-1",),
        serialized_context_chars=100,
    )
    trace = AgentExecutionTrace(
        agent_role=AgentName.RESEARCH_MANAGER,
        agent_run_id="fixed:research_manager",
        status=AgentStatus.OK,
        provided_claim_ids=(sector_claim_id,),
        accepted_claim_count=0,
        rejected_claim_count=0,
        provider="qwen",
        model="qwen3.7-flash",
        prompt_version="v6",
        trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
    )
    episode = ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(trace,),
            sector_usage=(usage,),
            created_at=AS_OF + timedelta(days=24),
        )
    )
    assert episode.sector_usage == (usage,)
    assert episode.provided_claim_ids == (sector_claim_id,)


def test_state_and_episode_agent_run_mismatch_is_rejected() -> None:
    """A complete State cannot be paired with a different execution identity."""

    trace = _complete_traces()[0].model_copy(update={"agent_run_id": "different:run"})
    with pytest.raises(ResearchEpisodeBuildError, match="identities disagree"):
        ResearchEpisodeBuilder().build(
            ResearchEpisodeBuildInput(
                research_state=_state(),
                agent_traces=(trace,),
                created_at=AS_OF + timedelta(minutes=1),
            )
        )
