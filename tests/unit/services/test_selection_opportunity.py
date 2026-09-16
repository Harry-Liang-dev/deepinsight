"""Day46 Selection Satellite and OpportunityCandidate contract tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from src.models.enums import SectorId
from src.schemas.opportunity import (
    OpportunityCandidate,
    OpportunityCandidateBuildInput,
    OpportunityCandidateStatus,
    OpportunityType,
    ThesisDirection,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.satellite_alpha import (
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SelectionSatelliteBuildInput,
    SelectionSectorEventReference,
)
from src.schemas.temporal import TemporalLeakageError, validate_temporal_access
from src.services.opportunity import OpportunityCandidateBuilder
from src.services.satellite_alpha import SatelliteAlphaMapper

_STATE_ROOT = Path("data/research_state/day38")
_EPISODE_ROOT = Path("data/research_episode/day39")
_SECTOR_CONTEXT = Path(
    "data/live_sector_research/20260830T135456Z/" "AAPL.real_qwen_sector_context.json"
)
_BUILD_TIME = datetime(2026, 9, 15, tzinfo=UTC)


def _state(name: str) -> ResearchStateSnapshot:
    return ResearchStateSnapshot.model_validate_json(
        (_STATE_ROOT / f"{name}.research_state.json").read_text()
    )


def _episode(name: str) -> ResearchEpisode:
    return ResearchEpisode.model_validate_json(
        (_EPISODE_ROOT / f"{name}.research_episode.json").read_text()
    )


def _selection(
    state: ResearchStateSnapshot,
    *,
    episode: ResearchEpisode | None = None,
    created_at: datetime = _BUILD_TIME,
    include_real_sector_context: bool = False,
) -> tuple[SatelliteAlphaObservation, ...]:
    sector_id: SectorId | None = None
    sector_context_id: str | None = None
    sector_events: tuple[SelectionSectorEventReference, ...] = ()
    if include_real_sector_context:
        context = cast(dict[str, Any], json.loads(_SECTOR_CONTEXT.read_text()))
        sector_id = SectorId(context["sector_id"])
        sector_context_id = cast(str, context["context_id"])
        sector_events = tuple(
            SelectionSectorEventReference(
                event_id=item["event_id"],
                available_at=item["available_at"],
                chain_ids=tuple(item["chain_ids"]),
                supporting_sector_claim_ids=tuple(item["supporting_sector_claim_ids"]),
            )
            for item in context["active_events"]
        )
    inputs = SelectionSatelliteBuildInput(
        research_state=state,
        source_episode=episode,
        available_at=_BUILD_TIME,
        created_at=created_at,
        sector_id=sector_id,
        sector_context_id=sector_context_id,
        sector_events=sector_events,
    )
    return SatelliteAlphaMapper().build_selection(inputs)


def _semantic_fixture_state(
    asset_id: str,
    *,
    alignment: str,
    revision: str,
    logic_stage: str,
) -> ResearchStateSnapshot:
    """Build a TEST FIXTURE only; it asserts contracts, not real Alpha."""

    payload = _state("phase4a_aapl_sector_aware").model_dump(mode="json")
    suffix = hashlib.sha256(asset_id.encode()).hexdigest()[:24]
    payload["research_state_id"] = f"research_state_{suffix}"
    payload["asset_id"] = asset_id
    payload["hierarchy"]["asset_scope_id"] = f"ASSET:{asset_id}"
    payload["lineage"]["source_run_id"] = f"contract_fixture_{asset_id}"
    payload["lineage"]["input_fingerprint"] = hashlib.sha256(
        f"fixture:{asset_id}".encode()
    ).hexdigest()
    as_of = payload["research_as_of"]

    def feature(name: str, value: str, claim_id: str) -> dict[str, object]:
        return {
            "feature_name": name,
            "value": value,
            "feature_type": "semantic_categorical",
            "as_of": as_of,
            "available_at": as_of,
            "confidence": None,
            "quality": "pass",
            "source_claim_ids": [claim_id],
            "source_evidence_ids": [f"fixture_evidence:{claim_id}"],
            "source_artifact_ids": ["day46_contract_fixture"],
            "feature_version": "research_state_feature_v1",
            "transform_name": None,
            "transform_version": None,
            "missing_reason": None,
        }

    sector_claim = f"fixture:{asset_id}:sector"
    payload["sector_state"]["features"].append(
        feature("satellite.sector_chain_alignment", alignment, sector_claim)
    )
    payload["industry_chain_state"]["features"].extend(
        (
            feature(
                "satellite.chain_benefit.business_binding_depth",
                "direct_core",
                f"fixture:{asset_id}:chain_binding",
            ),
            feature(
                "satellite.chain_benefit.evidence_quality",
                "high",
                f"fixture:{asset_id}:chain_evidence",
            ),
        )
    )
    payload["event_state"] = {
        "section_name": "event_state",
        "status": "present",
        "features": [
            feature(
                "satellite.expectation_revision.direction",
                revision,
                f"fixture:{asset_id}:revision",
            ),
            feature(
                "satellite.expectation_revision.subtype",
                "demand",
                f"fixture:{asset_id}:revision_subtype",
            ),
            feature(
                "satellite.logic_certainty",
                logic_stage,
                f"fixture:{asset_id}:logic",
            ),
        ],
        "missing_reason": None,
    }
    payload["debate_state"] = {
        "section_name": "debate_state",
        "status": "present",
        "features": [
            feature(
                "claim.bull:bull_thesis:0",
                "contract_fixture_bull_case",
                f"fixture:{asset_id}:bull",
            ),
            feature(
                "claim.bear:bear_thesis:0",
                "contract_fixture_bear_case",
                f"fixture:{asset_id}:bear",
            ),
        ],
        "missing_reason": None,
    }
    payload["risk_state"] = {
        "section_name": "risk_state",
        "status": "present",
        "features": [
            feature(
                "claim.risk:confirmed_risks:0",
                "contract_fixture_confirmed_risk",
                f"fixture:{asset_id}:risk",
            )
        ],
        "missing_reason": None,
    }
    payload["thesis_state"] = {
        "section_name": "thesis_state",
        "status": "present",
        "features": [
            feature(
                "claim.research:summary_points:0",
                "contract_fixture_material_thesis",
                f"fixture:{asset_id}:thesis",
            )
        ],
        "missing_reason": None,
    }
    return ResearchStateSnapshot.model_validate(payload)


def _candidate(
    state: ResearchStateSnapshot,
    observations: tuple[SatelliteAlphaObservation, ...],
    *,
    episode: ResearchEpisode | None = None,
    created_at: datetime = _BUILD_TIME,
) -> OpportunityCandidate:
    return OpportunityCandidateBuilder().build(
        OpportunityCandidateBuildInput(
            research_state=state,
            source_episode=episode,
            selection_observations=observations,
            created_at=created_at,
        )
    )


@pytest.mark.parametrize(
    ("alignment", "expected"),
    (
        ("positive_alignment", "positive_alignment"),
        ("negative_alignment", "negative_alignment"),
        ("mixed", "mixed"),
        ("uncertain", "uncertain"),
    ),
)
def test_sector_chain_alignment_uses_only_explicit_structured_state(
    alignment: str, expected: str
) -> None:
    state = _semantic_fixture_state(
        "US:NVDA",
        alignment=alignment,
        revision="upgrade",
        logic_stage="order_confirmed",
    )
    observation = {item.satellite_alpha_id: item for item in _selection(state)}[
        SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT
    ]

    assert observation.value == expected
    assert observation.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
    assert observation.source_claim_ids


def test_research_disagreement_maps_paths_without_overstating_intensity() -> None:
    state = _state("phase3_aapl_golden")
    observation = {item.satellite_alpha_id: item for item in _selection(state)}[
        SatelliteAlphaFamily.RESEARCH_DISAGREEMENT
    ]

    assert observation.value == "mixed"
    assert observation.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert {item.component_name for item in observation.value_components} == {
        "bull_claim_count",
        "bear_claim_count",
    }


def test_risk_burden_preserves_coarse_components_as_partial() -> None:
    observation = {
        item.satellite_alpha_id: item
        for item in _selection(_state("phase3_aapl_golden"))
    }[SatelliteAlphaFamily.RISK_BURDEN]

    assert observation.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert {item.component_name for item in observation.value_components} == {
        "confirmed_risk_count",
        "scenario_risk_count",
        "watch_item_count",
    }


def test_expectation_and_logic_support_explicit_features_only() -> None:
    state = _semantic_fixture_state(
        "US:NVDA",
        alignment="positive_alignment",
        revision="upgrade",
        logic_stage="order_confirmed",
    )
    output = {item.satellite_alpha_id: item for item in _selection(state)}

    assert output[SatelliteAlphaFamily.EXPECTATION_REVISION].value == "upgrade"
    assert output[SatelliteAlphaFamily.LOGIC_CERTAINTY].value == "order_confirmed"
    assert all(
        output[family].coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
        for family in (
            SatelliteAlphaFamily.EXPECTATION_REVISION,
            SatelliteAlphaFamily.LOGIC_CERTAINTY,
        )
    )


def test_expectation_and_logic_do_not_parse_existing_claim_prose() -> None:
    output = {
        item.satellite_alpha_id: item
        for item in _selection(_state("phase3_aapl_golden"))
    }

    assert (
        output[SatelliteAlphaFamily.EXPECTATION_REVISION].coverage_status
        is SatelliteAlphaCoverageStatus.MISSING_INPUT
    )
    assert (
        output[SatelliteAlphaFamily.LOGIC_CERTAINTY].coverage_status
        is SatelliteAlphaCoverageStatus.MISSING_INPUT
    )


def test_chain_benefit_emits_only_supported_partial_components() -> None:
    state = _semantic_fixture_state(
        "US:NVDA",
        alignment="positive_alignment",
        revision="upgrade",
        logic_stage="order_confirmed",
    )
    observation = {item.satellite_alpha_id: item for item in _selection(state)}[
        SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY
    ]

    assert observation.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert {item.component_name for item in observation.value_components} == {
        "business_binding_depth",
        "evidence_quality",
    }
    assert all(item.source_evidence_ids for item in observation.value_components)


def test_multi_asset_fixture_is_same_cutoff_and_definition_comparable() -> None:
    fixtures = (
        ("US:NVDA", "positive_alignment", "upgrade", "order_confirmed"),
        ("US:MU", "mixed", "mixed", "expectation_forming"),
        ("US:AMD", "negative_alignment", "downgrade", "early_signal"),
    )
    outputs = [
        _selection(
            _semantic_fixture_state(
                asset,
                alignment=alignment,
                revision=revision,
                logic_stage=logic,
            )
        )
        for asset, alignment, revision, logic in fixtures
    ]

    assert {item.research_as_of for output in outputs for item in output} == {
        _state("phase4a_aapl_sector_aware").research_as_of
    }
    assert (
        len({tuple(item.satellite_alpha_id for item in output) for output in outputs})
        == 1
    )
    assert all(len(output) == 7 for output in outputs)
    assert len({item.asset_id.root for output in outputs for item in output}) == 3


def test_phase3_no_backfill_and_phase4a_source_only_rebuild() -> None:
    phase3 = {
        item.satellite_alpha_id: item
        for item in _selection(_state("phase3_aapl_golden"))
    }
    state = _state("phase4a_aapl_sector_aware")
    phase4a = _selection(
        state,
        episode=_episode("phase4a_aapl_sector_aware"),
        include_real_sector_context=True,
    )

    assert (
        phase3[SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT].coverage_status
        is SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )
    assert all(
        item.sector_id is SectorId.CONSUMER_ELECTRONICS_HARDWARE for item in phase4a
    )
    assert all(
        item.source_research_state_id == state.research_state_id for item in phase4a
    )


def test_candidate_schema_identity_provenance_and_partial_coverage() -> None:
    state = _state("phase3_aapl_golden")
    episode = _episode("phase3_aapl_golden")
    observations = _selection(state, episode=episode)
    first = _candidate(state, observations, episode=episode)
    later = _candidate(
        state,
        observations,
        episode=episode,
        created_at=_BUILD_TIME + timedelta(days=1),
    )

    assert first.status is OpportunityCandidateStatus.QUALIFIED
    assert first.candidate_id == later.candidate_id
    assert first.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert OpportunityType.MATERIAL_THESIS in first.opportunity_types
    assert first.source_research_state_id == state.research_state_id
    assert first.source_episode_id == episode.episode_id
    assert first.source_claim_ids
    assert first.satellite_observation_ids == tuple(
        sorted(item.observation_id for item in observations)
    )


def test_candidate_direction_comes_from_structured_alignment() -> None:
    state = _semantic_fixture_state(
        "US:AMD",
        alignment="negative_alignment",
        revision="downgrade",
        logic_stage="early_signal",
    )
    candidate = _candidate(state, _selection(state))

    assert candidate.thesis_direction is ThesisDirection.NEGATIVE
    assert OpportunityType.SECTOR_CHAIN in candidate.opportunity_types
    assert OpportunityType.EXPECTATION_CHANGE in candidate.opportunity_types


def test_unqualified_source_state_does_not_become_candidate_by_presence() -> None:
    state = _state("phase4a_aapl_sector_aware")
    candidate = _candidate(state, _selection(state))

    assert candidate.status is OpportunityCandidateStatus.INSUFFICIENT_RESEARCH
    assert not candidate.opportunity_types
    assert candidate.coverage_status is SatelliteAlphaCoverageStatus.MISSING_INPUT


def test_candidate_rejects_trading_fields_and_early_consumption() -> None:
    state = _state("phase3_aapl_golden")
    candidate = _candidate(state, _selection(state))
    payload = candidate.model_dump()
    payload["position_weight"] = 0.5

    with pytest.raises(ValidationError):
        OpportunityCandidate.model_validate(payload)
    with pytest.raises(TemporalLeakageError):
        validate_temporal_access(
            candidate.temporal_metadata(),
            candidate.available_at - timedelta(microseconds=1),
        )


def test_frozen_builders_have_zero_model_or_provider_dependency() -> None:
    for path in (
        Path("src/services/satellite_alpha.py"),
        Path("src/services/opportunity.py"),
    ):
        source = path.read_text().lower()
        assert "llm_gateway" not in source
        assert "provider." not in source
        assert "final_report" not in source
        assert "weighted_score" not in source
