"""Day45 Satellite Alpha ontology and deterministic mapper tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.satellite_alpha import (
    SatelliteAlphaBuildInput,
    SatelliteAlphaComparisonScope,
    SatelliteAlphaComponent,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaDefinitionStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SatelliteAlphaUsage,
)
from src.schemas.temporal import TemporalLeakageError, validate_temporal_access
from src.services.satellite_alpha import (
    SatelliteAlphaMapper,
    build_satellite_alpha_registry_v1,
    research_state_semantic_support_audit_v1,
)

_STATE_ROOT = Path("data/research_state/day38")
_EPISODE_ROOT = Path("data/research_episode/day39")
_BUILD_TIME = datetime(2026, 9, 15, tzinfo=UTC)


def _state(name: str) -> ResearchStateSnapshot:
    return ResearchStateSnapshot.model_validate_json(
        (_STATE_ROOT / f"{name}.research_state.json").read_text()
    )


def _episode(name: str) -> ResearchEpisode:
    return ResearchEpisode.model_validate_json(
        (_EPISODE_ROOT / f"{name}.research_episode.json").read_text()
    )


def _observations(
    name: str = "phase4a_aapl_sector_aware",
    *,
    created_at: datetime = _BUILD_TIME,
) -> dict[SatelliteAlphaFamily, SatelliteAlphaObservation]:
    state = _state(name)
    built = SatelliteAlphaMapper().build(
        SatelliteAlphaBuildInput(
            research_state=state,
            source_episode=_episode(name),
            available_at=_BUILD_TIME,
            created_at=created_at,
        )
    )
    return {item.satellite_alpha_id: item for item in built}


def test_registry_covers_selection_timing_and_both_definitions() -> None:
    registry = build_satellite_alpha_registry_v1()

    assert len(registry.definitions) == len(SatelliteAlphaFamily) == 14
    assert {item.usage for item in registry.definitions} == {
        SatelliteAlphaUsage.SELECTION,
        SatelliteAlphaUsage.TIMING,
        SatelliteAlphaUsage.BOTH,
    }
    assert SatelliteAlphaComparisonScope.PEER_GROUP not in {
        item.comparison_scope
        for item in registry.definitions
        if item.status is not SatelliteAlphaDefinitionStatus.UNSUPPORTED
    }


def test_history_definitions_are_implemented_without_fabricated_history() -> None:
    definitions = {
        item.family: item for item in build_satellite_alpha_registry_v1().definitions
    }

    expected_points = {
        SatelliteAlphaFamily.STATE_TRANSITION: 2,
        SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY: 3,
        SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE: 2,
        SatelliteAlphaFamily.RISK_ESCALATION: 2,
        SatelliteAlphaFamily.EVIDENCE_CONFIRMATION: 2,
    }
    for family, points in expected_points.items():
        assert definitions[family].requires_history is True
        assert definitions[family].minimum_history_points == points
        assert definitions[family].status is SatelliteAlphaDefinitionStatus.IMPLEMENTED


def test_mapper_emits_categorical_and_multi_component_values() -> None:
    output = _observations()
    alignment = output[SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT]
    evidence = output[SatelliteAlphaFamily.EVIDENCE_STRENGTH]

    assert alignment.value == "uncertain"
    assert alignment.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert len(evidence.value_components) >= 2


def test_numeric_components_are_typed_grounded_and_attributable() -> None:
    observation = _observations()[SatelliteAlphaFamily.EVIDENCE_STRENGTH]

    assert observation.value_components
    for component in observation.value_components:
        assert isinstance(component.value, int)
        assert component.unit == "count"
        assert component.scale == "integer_count"
        assert component.source_state_feature_refs
        assert (
            component.source_claim_ids
            or component.source_evidence_ids
            or component.source_artifact_ids
        )


def test_observation_identity_is_deterministic_and_ignores_created_at() -> None:
    first = _observations(created_at=_BUILD_TIME)
    later = _observations(created_at=_BUILD_TIME + timedelta(days=1))

    assert {key: value.observation_id for key, value in first.items()} == {
        key: value.observation_id for key, value in later.items()
    }


def test_phase3_later_semantics_are_not_backfilled() -> None:
    output = _observations("phase3_aapl_golden")

    assert (
        output[SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY].coverage_status
        is SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )
    assert (
        output[SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT].coverage_status
        is SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )


def test_phase4a_uses_only_source_run_sector_chain_context() -> None:
    output = _observations()
    chain = output[SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY]

    assert chain.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL
    assert chain.chain_ids == ("APPLE_CHAIN",)
    assert chain.sector_id is None
    assert chain.source_state_feature_refs
    assert all("::" in item for item in chain.source_state_feature_refs)


def test_missing_input_not_replaced_by_numeric_zero() -> None:
    observation = _observations()[SatelliteAlphaFamily.EXPECTATION_REVISION]

    assert observation.coverage_status in {
        SatelliteAlphaCoverageStatus.MISSING_INPUT,
        SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
    }
    assert observation.value is None
    assert not observation.value_components
    assert observation.missing_reasons


def test_not_applicable_when_source_run_has_no_chain_membership() -> None:
    payload = _state("phase4a_aapl_sector_aware").model_dump(mode="json")
    payload["hierarchy"]["industry_chain_scope_ids"] = []
    payload["industry_chain_state"] = {
        "section_name": "industry_chain_state",
        "status": "missing",
        "features": [],
        "missing_reason": "no PIT-valid chain membership",
    }
    state = ResearchStateSnapshot.model_validate(payload)
    output = SatelliteAlphaMapper().build(
        SatelliteAlphaBuildInput(
            research_state=state,
            available_at=_BUILD_TIME,
            created_at=_BUILD_TIME,
        )
    )

    chain = next(
        item
        for item in output
        if item.satellite_alpha_id is SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY
    )
    assert chain.coverage_status is SatelliteAlphaCoverageStatus.NOT_APPLICABLE
    assert chain.value is None


def test_observation_provenance_closes_state_episode_claim_evidence() -> None:
    observation = _observations()[SatelliteAlphaFamily.EVIDENCE_STRENGTH]

    assert observation.source_research_state_id.startswith("research_state_")
    assert observation.source_episode_id is not None
    assert observation.source_claim_ids
    assert observation.source_evidence_ids
    assert observation.source_research_state_id in observation.source_artifact_ids


def test_observation_pit_rejects_use_before_available_at() -> None:
    observation = _observations()[SatelliteAlphaFamily.EVIDENCE_STRENGTH]

    with pytest.raises(TemporalLeakageError):
        validate_temporal_access(
            observation.temporal_metadata(),
            observation.available_at - timedelta(microseconds=1),
        )


def test_no_arbitrary_numeric_or_trade_semantics_enter_contract() -> None:
    with pytest.raises(ValidationError, match="unit and scale"):
        SatelliteAlphaComponent(
            component_name="opaque_score",
            value=0.87,
            source_state_feature_refs=("risk_state::risk",),
            source_claim_ids=("claim_1",),
            transform_version="bad_v1",
        )

    payload = _observations()[SatelliteAlphaFamily.EVIDENCE_STRENGTH].model_dump()
    payload["value"] = "BUY"
    with pytest.raises(ValidationError):
        SatelliteAlphaObservation.model_validate(payload)

    payload["value"] = None
    payload["trade_signal"] = "BUY"
    with pytest.raises(ValidationError):
        SatelliteAlphaObservation.model_validate(payload)


def test_mapper_has_no_llm_provider_or_report_dependency() -> None:
    source = Path("src/services/satellite_alpha.py").read_text()

    assert "llm_gateway" not in source.lower()
    assert "provider." not in source.lower()
    assert "research_report" not in source.lower()
    assert "final_report" not in source.lower()


def test_semantic_support_audit_is_explicit_and_honest() -> None:
    audit = research_state_semantic_support_audit_v1()

    assert len(audit) == 8
    assert all(item.missing_fields for item in audit)
    assert all(
        item.support_level.value in {"supported", "partial", "missing"}
        for item in audit
    )
    assert all(item.support_level.value != "supported" for item in audit)


def test_registry_json_has_no_quant_or_execution_output_fields() -> None:
    schema = json.dumps(
        build_satellite_alpha_registry_v1().model_dump(mode="json"),
        sort_keys=True,
    ).lower()

    forbidden = (
        "buy_score",
        "sell_score",
        "position_weight",
        "order_id",
        "target_price",
        "factor_zscore",
    )
    assert all(term not in schema for term in forbidden)
