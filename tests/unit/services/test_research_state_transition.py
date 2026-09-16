"""Day47 deterministic ResearchState transition and Timing contract tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.enums import MemoryLevel, ResearchScopeType
from src.schemas.common import SourceReference
from src.schemas.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    MemorySearchResult,
)
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import (
    ResearchStateFeature,
    ResearchStateFeatureType,
    ResearchStateSection,
    ResearchStateSectionName,
    ResearchStateSectionStatus,
    ResearchStateSnapshot,
)
from src.schemas.research_state_transition import (
    EventWindowPosition,
    EvidenceTransitionStatus,
    ExpectationChangeOrder,
    ResearchStateTransition,
    ResearchStateTransitionDirection,
    RiskTransitionStatus,
    ThesisTransitionStatus,
    TimingEventKind,
    TimingEventReference,
    TimingSatelliteBuildInput,
)
from src.schemas.satellite_alpha import (
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
)
from src.schemas.temporal import (
    TemporalLeakageError,
    TemporalMetadata,
    TemporalSourceKind,
)
from src.services.research_state_transition import (
    ResearchStateTransitionBuilder,
    ResearchStateTransitionBuildError,
)

_STATE_ROOT = Path("data/research_state/day38")
_EPISODE_ROOT = Path("data/research_episode/day39")
_T1 = datetime(2026, 9, 1, tzinfo=UTC)
_T2 = datetime(2026, 9, 11, tzinfo=UTC)
_T3 = datetime(2026, 9, 21, tzinfo=UTC)
_BUILT = datetime(2026, 9, 22, tzinfo=UTC)


def _base(name: str = "phase4a_aapl_sector_aware") -> ResearchStateSnapshot:
    return ResearchStateSnapshot.model_validate_json(
        (_STATE_ROOT / f"{name}.research_state.json").read_text()
    )


def _episode(name: str) -> ResearchEpisode:
    return ResearchEpisode.model_validate_json(
        (_EPISODE_ROOT / f"{name}.research_episode.json").read_text()
    )


def _identifier(prefix: str, label: str) -> str:
    return prefix + hashlib.sha256(label.encode()).hexdigest()[:24]


def _feature(
    name: str,
    value: str | float,
    as_of: datetime,
    label: str,
) -> ResearchStateFeature:
    return ResearchStateFeature(
        feature_name=name,
        value=value,
        feature_type=(
            ResearchStateFeatureType.DETERMINISTIC_NUMERIC
            if isinstance(value, float)
            else ResearchStateFeatureType.SEMANTIC_CATEGORICAL
        ),
        as_of=as_of,
        available_at=as_of,
        quality=DataQualityStatus.PASS,
        source_claim_ids=(f"claim_{label}_{name}",),
        source_evidence_ids=(f"evidence_{label}_{name}",),
        source_artifact_ids=(f"artifact_{label}_{name}",),
        feature_version="research_state_feature_v1",
    )


def _section(
    name: ResearchStateSectionName,
    features: tuple[ResearchStateFeature, ...],
) -> ResearchStateSection:
    return ResearchStateSection(
        section_name=name,
        status=ResearchStateSectionStatus.PRESENT,
        features=features,
    )


def _state(
    label: str,
    as_of: datetime,
    *,
    logic: str,
    expectation: float,
    thesis: str,
    risk: str,
    evidence: str,
) -> ResearchStateSnapshot:
    payload = _base().model_dump(mode="python")
    payload["research_state_id"] = _identifier("research_state_", label)
    payload["research_as_of"] = as_of
    payload["event_state"] = _section(
        ResearchStateSectionName.EVENT,
        (
            _feature("satellite.logic_certainty", logic, as_of, label),
            _feature("satellite.hypothesis.order.status", evidence, as_of, label),
        ),
    )
    payload["thesis_state"] = _section(
        ResearchStateSectionName.THESIS,
        (
            _feature("satellite.expectation_revision.value", expectation, as_of, label),
            _feature(
                "satellite.expectation_revision.direction",
                "upgrade" if expectation >= 10 else "downgrade",
                as_of,
                label,
            ),
            _feature("satellite.thesis.disposition", thesis, as_of, label),
        ),
    )
    payload["risk_state"] = _section(
        ResearchStateSectionName.RISK,
        (_feature("satellite.risk.customer.status", risk, as_of, label),),
    )
    return ResearchStateSnapshot.model_validate(payload)


@pytest.fixture
def states() -> tuple[ResearchStateSnapshot, ...]:
    """Three ordered CONTRACT FIXTURE States, not historical validation."""

    return (
        _state(
            "t1",
            _T1,
            logic="order_expectation",
            expectation=10.0,
            thesis="neutral",
            risk="active",
            evidence="unresolved",
        ),
        _state(
            "t2",
            _T2,
            logic="order_confirmed",
            expectation=20.0,
            thesis="positive",
            risk="escalating",
            evidence="confirmed",
        ),
        _state(
            "t3",
            _T3,
            logic="revenue_realized",
            expectation=35.0,
            thesis="positive",
            risk="resolved",
            evidence="confirmed",
        ),
    )


def _inputs(
    current: ResearchStateSnapshot,
    history: tuple[ResearchStateSnapshot, ...],
    *,
    events: tuple[TimingEventReference, ...] = (),
    memories: tuple[MemorySearchResult, ...] = (),
    created_at: datetime = _BUILT,
) -> TimingSatelliteBuildInput:
    return TimingSatelliteBuildInput(
        current_state=current,
        historical_states=history,
        events=events,
        retrieved_memories=memories,
        available_at=_BUILT,
        created_at=created_at,
    )


def _timing(
    inputs: TimingSatelliteBuildInput,
) -> dict[SatelliteAlphaFamily, SatelliteAlphaObservation]:
    return {
        item.satellite_alpha_id: item
        for item in ResearchStateTransitionBuilder().build_timing(inputs)
    }


def _event(
    event_time: datetime,
    available_at: datetime,
    *,
    kind: TimingEventKind = TimingEventKind.EVENT,
    outcome: str | None = None,
    outcome_available_at: datetime | None = None,
) -> TimingEventReference:
    return TimingEventReference(
        event_id=f"event_{kind.value}",
        kind=kind,
        event_time=event_time,
        available_at=available_at,
        source_state_feature_ref="event_state::satellite.hypothesis.order.status",
        source_claim_ids=("claim_event",),
        source_evidence_ids=("evidence_event",),
        outcome_disposition=outcome,
        outcome_available_at=outcome_available_at,
    )


def test_transition_schema_and_deterministic_identity(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    builder = ResearchStateTransitionBuilder()
    first = builder.build_transition(_inputs(states[1], (states[0],)))
    later = builder.build_transition(
        _inputs(states[1], (states[0],), created_at=_BUILT + timedelta(days=1))
    )

    assert first is not None and later is not None
    assert first.transition_id == later.transition_id
    assert first.schema_version == "research_state_transition_v1"
    assert first.previous_state_id == states[0].research_state_id
    assert first.current_state_id == states[1].research_state_id


def test_existing_episode_lineage_is_preserved() -> None:
    previous = _base("phase3_aapl_golden")
    current = _base("phase4a_aapl_sector_aware")
    previous_episode = _episode("phase3_aapl_golden")
    current_episode = _episode("phase4a_aapl_sector_aware")
    transition = ResearchStateTransitionBuilder().build_transition(
        TimingSatelliteBuildInput(
            current_state=current,
            historical_states=(previous,),
            current_episode=current_episode,
            historical_episodes=(previous_episode,),
            available_at=_BUILT,
            created_at=_BUILT,
        )
    )

    assert transition is not None
    assert transition.previous_episode_id == previous_episode.episode_id
    assert transition.current_episode_id == current_episode.episode_id


def test_transition_schema_enforces_strict_time_order(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    transition = ResearchStateTransitionBuilder().build_transition(
        _inputs(states[1], (states[0],))
    )
    assert transition is not None
    payload = transition.model_dump()
    payload["previous_as_of"] = payload["current_as_of"]
    with pytest.raises(ValidationError, match="previous_as_of < current_as_of"):
        ResearchStateTransition.model_validate(payload)


def test_nearest_prior_state_is_selected_deterministically(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    predecessor = ResearchStateTransitionBuilder().select_predecessor(
        states[2], (states[0], states[1])
    )

    assert predecessor == states[1]


def test_same_time_and_future_state_leakage_are_rejected(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    same_time = states[1].model_copy(
        update={"research_state_id": _identifier("research_state_", "same")}
    )
    builder = ResearchStateTransitionBuilder()

    with pytest.raises(ResearchStateTransitionBuildError, match="same-time"):
        builder.select_predecessor(states[1], (same_time,))
    with pytest.raises(TemporalLeakageError):
        builder.select_predecessor(states[1], (states[2],))


def test_history_is_asset_isolated(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    payload = states[0].model_dump(mode="python")
    payload["asset_id"] = "US:MSFT"
    payload["hierarchy"]["asset_scope_id"] = "ASSET:US:MSFT"
    other_asset = ResearchStateSnapshot.model_validate(payload)

    assert (
        ResearchStateTransitionBuilder().select_predecessor(states[1], (other_asset,))
        is None
    )


def test_future_evidence_leakage_cannot_be_backwritten_into_earlier_state(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    payload = states[0].model_dump(mode="python")
    payload["event_state"]["features"][0]["available_at"] = _T2

    with pytest.raises(ValidationError, match="future_available"):
        ResearchStateSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    ("previous_index", "current_index", "expected_stage", "expected_direction"),
    (
        (0, 1, "order_confirmed", ResearchStateTransitionDirection.UPGRADE),
        (1, 2, "revenue_realized", ResearchStateTransitionDirection.UPGRADE),
    ),
)
def test_logic_stage_upgrade_paths(
    states: tuple[ResearchStateSnapshot, ...],
    previous_index: int,
    current_index: int,
    expected_stage: str,
    expected_direction: ResearchStateTransitionDirection,
) -> None:
    transition = ResearchStateTransitionBuilder().build_transition(
        _inputs(states[current_index], (states[previous_index],))
    )

    assert transition is not None
    assert transition.logic_stage_to == expected_stage
    assert transition.direction is expected_direction


def test_downgrade_and_unchanged_paths(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    invalidated = _state(
        "invalidated",
        _T2,
        logic="invalidated",
        expectation=5.0,
        thesis="invalidated",
        risk="active",
        evidence="contradicted",
    )
    unchanged = _state(
        "unchanged",
        _T2,
        logic="order_expectation",
        expectation=10.0,
        thesis="neutral",
        risk="active",
        evidence="unresolved",
    )
    builder = ResearchStateTransitionBuilder()
    down = builder.build_transition(_inputs(invalidated, (states[0],)))
    flat = builder.build_transition(_inputs(unchanged, (states[0],)))

    assert down is not None and flat is not None
    assert down.direction is ResearchStateTransitionDirection.DOWNGRADE
    assert down.thesis_change is ThesisTransitionStatus.INVALIDATED
    assert flat.direction is ResearchStateTransitionDirection.UNCHANGED


def test_missing_logic_stage_does_not_guess_from_prose(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    payload = states[1].model_dump(mode="python")
    payload["event_state"] = _section(
        ResearchStateSectionName.EVENT,
        (_feature("satellite.hypothesis.order.status", "confirmed", _T2, "x"),),
    )
    current = ResearchStateSnapshot.model_validate(payload)
    output = _timing(_inputs(current, (states[0],)))[
        SatelliteAlphaFamily.STATE_TRANSITION
    ]

    assert output.coverage_status is SatelliteAlphaCoverageStatus.MISSING_INPUT
    assert output.value is None


def test_risk_escalation_resolution_and_evidence_lineage(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    builder = ResearchStateTransitionBuilder()
    escalation = builder.build_transition(_inputs(states[1], (states[0],)))
    resolution = builder.build_transition(_inputs(states[2], (states[1],)))

    assert escalation is not None and resolution is not None
    assert escalation.risk_changes[0].classification == RiskTransitionStatus.ESCALATING
    assert resolution.risk_changes[0].classification == RiskTransitionStatus.RESOLVED
    assert (
        escalation.evidence_changes[0].classification
        == EvidenceTransitionStatus.CONFIRMED
    )


def test_evidence_contradiction_requires_distinct_later_evidence(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    contradicted = _state(
        "contradicted",
        _T2,
        logic="invalidated",
        expectation=5.0,
        thesis="invalidated",
        risk="active",
        evidence="contradicted",
    )
    output = _timing(_inputs(contradicted, (states[0],)))[
        SatelliteAlphaFamily.EVIDENCE_CONFIRMATION
    ]

    assert output.value == EvidenceTransitionStatus.CONTRADICTED
    assert output.source_evidence_ids


def test_two_points_have_direction_and_rate_but_no_second_order(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    output = _timing(_inputs(states[1], (states[0],)))[
        SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY
    ]
    names = {item.component_name for item in output.value_components}

    assert output.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert {"direction", "delta", "change_rate"} <= names
    assert "second_order_change" not in names
    assert ExpectationChangeOrder.ACCELERATING.value not in json.dumps(
        output.model_dump(mode="json")
    )


def test_three_points_allow_acceleration(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    output = _timing(_inputs(states[2], (states[0], states[1])))[
        SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY
    ]
    second_order = next(
        item
        for item in output.value_components
        if item.component_name == "second_order_change"
    )

    assert output.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
    assert second_order.value == ExpectationChangeOrder.ACCELERATING


def test_three_points_allow_deceleration(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    slower = _state(
        "slower_t3",
        _T3,
        logic="revenue_realized",
        expectation=25.0,
        thesis="positive",
        risk="resolved",
        evidence="confirmed",
    )
    output = _timing(_inputs(slower, (states[0], states[1])))[
        SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY
    ]
    second_order = next(
        item
        for item in output.value_components
        if item.component_name == "second_order_change"
    )

    assert second_order.value == ExpectationChangeOrder.DECELERATING


def test_single_state_requires_history() -> None:
    state = _base()
    output = _timing(_inputs(state, ()))[SatelliteAlphaFamily.STATE_TRANSITION]

    assert output.coverage_status is SatelliteAlphaCoverageStatus.REQUIRES_HISTORY
    assert output.previous_research_state_id is None
    assert output.source_transition_id is None


def test_event_pre_post_and_catalyst_windows(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    pre = _event(_T2 + timedelta(days=5), _T2 - timedelta(days=1))
    post = _event(_T3 - timedelta(days=10), _T1)
    catalyst = _event(
        _T2 + timedelta(days=6),
        _T1,
        kind=TimingEventKind.CATALYST,
    )

    pre_output = _timing(_inputs(states[1], (states[0],), events=(pre, catalyst)))
    post_output = _timing(_inputs(states[2], (states[1],), events=(post,)))

    assert (
        pre_output[SatelliteAlphaFamily.EVENT_WINDOW].value
        == EventWindowPosition.PRE_EVENT
    )
    assert (
        post_output[SatelliteAlphaFamily.EVENT_WINDOW].value
        == EventWindowPosition.POST_EVENT
    )
    assert pre_output[SatelliteAlphaFamily.CATALYST_PROXIMITY].value == "imminent"


def test_future_event_and_post_event_outcome_leakage_are_rejected(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    future = _event(_T3, _T2 + timedelta(seconds=1))
    leaked_outcome = _event(
        _T3,
        _T1,
        outcome="confirmed",
        outcome_available_at=_T2,
    )
    builder = ResearchStateTransitionBuilder()

    with pytest.raises(TemporalLeakageError):
        builder.build_timing(_inputs(states[1], (states[0],), events=(future,)))
    with pytest.raises(ResearchStateTransitionBuildError, match="post-event outcome"):
        builder.build_timing(_inputs(states[1], (states[0],), events=(leaked_outcome,)))


def _memory(
    state: ResearchStateSnapshot,
    *,
    available_at: datetime,
) -> MemorySearchResult:
    claim_id = state.thesis_state.features[0].source_claim_ids[0]
    episode_id = _identifier("research_episode_", "memory_episode")
    metadata = LearningMemoryMetadata(
        usage_class=LearningMemoryUsageClass.EPISODIC,
        scope_type=ResearchScopeType.ASSET,
        scope_id="ASSET:US:AAPL",
        parent_scope_id="CHAIN:APPLE_CHAIN",
        episode_id=episode_id,
        research_state_id=_identifier("research_state_", "memory_source"),
        source_claim_ids=(claim_id,),
        temporal=TemporalMetadata(
            source_kind=TemporalSourceKind.MEMORY,
            available_at=available_at,
            effective_from=_T1,
        ),
        content_kind=EpisodicMemoryContentKind.VALIDATED_CLAIM,
    )
    return MemorySearchResult(
        memory_id="memory_contract_fixture",
        memory_level=MemoryLevel.L3,
        namespace_key="ASSET:US:AAPL",
        summary_text="Contract fixture only",
        score=0.9,
        effective_ts=_T1,
        available_at=available_at,
        asset_id=state.asset_id,
        memory_type="episodic_claim",
        importance_score=0.8,
        source_ref_json=SourceReference(document_id="contract_fixture"),
        created_by="test",
        metadata=metadata,
    )


def test_non_empty_memory_positive_contract_and_future_memory_leakage_rejection(
    states: tuple[ResearchStateSnapshot, ...],
) -> None:
    usable = _memory(states[1], available_at=_T1)
    transition = ResearchStateTransitionBuilder().build_transition(
        _inputs(states[1], (states[0],), memories=(usable,))
    )

    assert transition is not None
    assert usable.memory_id in transition.source_artifact_ids

    future = _memory(states[1], available_at=_T2 + timedelta(seconds=1))
    with pytest.raises(TemporalLeakageError):
        ResearchStateTransitionBuilder().build_timing(
            _inputs(states[1], (states[0],), memories=(future,))
        )


@pytest.mark.parametrize("name", ("phase3_aapl_golden", "phase4a_aapl_sector_aware"))
def test_frozen_runs_never_receive_synthetic_history(name: str) -> None:
    state = _base(name)
    output = ResearchStateTransitionBuilder().build_timing(_inputs(state, ()))

    assert all(item.previous_research_state_id is None for item in output)
    assert all(item.source_transition_id is None for item in output)
    assert all(
        item.coverage_status
        in {
            SatelliteAlphaCoverageStatus.REQUIRES_HISTORY,
            SatelliteAlphaCoverageStatus.MISSING_INPUT,
            SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
        }
        for item in output
    )


def test_transition_and_timing_contracts_contain_no_trading_fields() -> None:
    source = (
        Path("src/schemas/research_state_transition.py").read_text()
        + Path("src/services/research_state_transition.py").read_text()
    ).lower()
    forbidden = (
        "buy\n",
        "sell\n",
        "entry_price",
        "exit_price",
        "position_weight",
        "stop_loss",
        "take_profit",
        "expected_return",
        "alpha_score",
        "timing_score",
        "trade_signal",
    )

    assert all(value not in source for value in forbidden)
    assert "llm_gateway" not in source
    assert "provider." not in source
