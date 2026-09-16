"""Black-box acceptance for a future Quant consumer of Day48 artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.schemas.opportunity import OpportunityCandidateBuildInput
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_quant_handoff import (
    ResearchQuantHandoffBuildInput,
    ResearchQuantHandoffBundle,
)
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.research_state_transition import TimingSatelliteBuildInput
from src.schemas.satellite_alpha import (
    SatelliteAlphaCoverageStatus,
    SelectionSatelliteBuildInput,
)
from src.services.opportunity import OpportunityCandidateBuilder
from src.services.research_quant_handoff import (
    ResearchQuantHandoffBuilder,
    ResearchQuantHandoffExporter,
    ResearchQuantHandoffExportError,
)
from src.services.research_state_transition import ResearchStateTransitionBuilder
from src.services.satellite_alpha import SatelliteAlphaMapper

_STATE_PATH = Path("data/research_state/day38/phase3_aapl_golden.research_state.json")
_EPISODE_PATH = Path(
    "data/research_episode/day39/phase3_aapl_golden.research_episode.json"
)
_MATERIALIZED_AT = datetime(2026, 9, 15, tzinfo=UTC)
_EXPORTED_AT = datetime(2026, 9, 16, tzinfo=UTC)


def _build_handoff(
    *,
    include_timing: bool = True,
    include_candidate: bool = True,
) -> ResearchQuantHandoffBundle:
    return ResearchQuantHandoffBuilder().build(
        _build_inputs(
            include_timing=include_timing,
            include_candidate=include_candidate,
        )
    )


def _build_inputs(
    *,
    include_timing: bool = True,
    include_candidate: bool = True,
) -> ResearchQuantHandoffBuildInput:
    state = ResearchStateSnapshot.model_validate_json(_STATE_PATH.read_text())
    episode = ResearchEpisode.model_validate_json(_EPISODE_PATH.read_text())
    selection = SatelliteAlphaMapper().build_selection(
        SelectionSatelliteBuildInput(
            research_state=state,
            source_episode=episode,
            available_at=_MATERIALIZED_AT,
            created_at=_MATERIALIZED_AT,
        )
    )
    timing_input = TimingSatelliteBuildInput(
        current_state=state,
        current_episode=episode,
        available_at=_MATERIALIZED_AT,
        created_at=_MATERIALIZED_AT,
    )
    timing_builder = ResearchStateTransitionBuilder()
    timing = timing_builder.build_timing(timing_input)
    candidate = OpportunityCandidateBuilder().build(
        OpportunityCandidateBuildInput(
            research_state=state,
            source_episode=episode,
            selection_observations=selection,
            created_at=_MATERIALIZED_AT,
        )
    )
    return ResearchQuantHandoffBuildInput(
        research_state=state,
        research_episode=episode,
        selection_observations=selection,
        timing_observations=timing if include_timing else (),
        opportunity_candidate=candidate if include_candidate else None,
        created_at=_EXPORTED_AT,
    )


def _consume_without_research_internals(path: Path) -> tuple[str, str]:
    """Read only the public JSON wire artifact as a separate repository would."""

    payload: dict[str, Any] = json.loads(path.read_text())
    assert payload["schema_version"] == "research_quant_handoff_bundle_v1"
    assert payload["versions"]["handoff_build_version"]
    assert payload["asset_id"]
    assert payload["research_as_of"]
    assert "opportunity_candidate_status" in payload
    assert payload["coverage_status"]

    observations = [
        *payload["selection_satellite_observations"],
        *payload["timing_satellite_observations"],
    ]
    assert observations
    required_observation_fields = {
        "observation_id",
        "satellite_alpha_id",
        "family",
        "usage",
        "comparison_scope",
        "coverage_status",
        "value",
        "value_components",
        "quality",
        "confidence",
        "missing_reasons",
        "definition_version",
        "transform_version",
        "available_at",
    }
    for observation in observations:
        assert required_observation_fields <= observation.keys()

    return payload["asset_id"], payload["research_as_of"]


def _wire_items(bundle: ResearchQuantHandoffBundle) -> list[dict[str, Any]]:
    payload: dict[str, Any] = json.loads(
        ResearchQuantHandoffExporter().serialize(bundle)
    )
    return [
        *payload["selection_satellite_observations"],
        *payload["timing_satellite_observations"],
    ]


def test_export_is_self_describing_for_external_quant_consumer(tmp_path: Path) -> None:
    artifact = tmp_path / "handoff.json"
    ResearchQuantHandoffExporter().export_bundle(_build_handoff(), artifact)

    join_key = _consume_without_research_internals(artifact)

    assert join_key == ("US:AAPL", "2026-08-14T23:59:59.999999Z")


def test_wire_projection_is_faithful_for_selection_and_timing() -> None:
    inputs = _build_inputs()
    bundle = ResearchQuantHandoffBuilder().build(inputs)
    wire_by_id = {item["observation_id"]: item for item in _wire_items(bundle)}
    sources = (*inputs.selection_observations, *inputs.timing_observations)

    assert inputs.selection_observations
    assert inputs.timing_observations
    assert set(wire_by_id) == {item.observation_id for item in sources}
    for source in sources:
        source_payload = source.model_dump(mode="json")
        wire = wire_by_id[source.observation_id]
        assert wire["satellite_alpha_id"] == source_payload["satellite_alpha_id"]
        assert wire["family"] == source_payload["satellite_alpha_id"]
        for field in (
            "definition_version",
            "transform_version",
            "usage",
            "comparison_scope",
            "coverage_status",
            "value",
            "value_components",
            "quality",
            "confidence",
            "available_at",
        ):
            assert wire[field] == source_payload[field]
        assert wire["missing_reasons"] == sorted(source_payload["missing_reasons"])


@pytest.mark.parametrize(
    "coverage_status",
    (
        SatelliteAlphaCoverageStatus.MISSING_INPUT,
        SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
        SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
        SatelliteAlphaCoverageStatus.UNSUPPORTED,
        SatelliteAlphaCoverageStatus.REQUIRES_HISTORY,
    ),
)
def test_unavailable_status_roundtrips_without_numeric_fill(
    coverage_status: SatelliteAlphaCoverageStatus,
) -> None:
    inputs = _build_inputs(include_candidate=False)
    source = inputs.selection_observations[0]
    unavailable = source.model_validate(
        {
            **source.model_dump(),
            "coverage_status": coverage_status,
            "value": None,
            "value_components": (),
            "missing_reasons": (f"acceptance_{coverage_status.value}",),
        }
    )
    selection = (unavailable, *inputs.selection_observations[1:])
    bundle = ResearchQuantHandoffBuilder().build(
        inputs.model_copy(update={"selection_observations": selection})
    )
    wire = next(
        item
        for item in _wire_items(bundle)
        if item["observation_id"] == unavailable.observation_id
    )

    assert wire["coverage_status"] == coverage_status.value
    assert wire["value"] is None
    assert wire["value_components"] == []
    assert wire["missing_reasons"] == [f"acceptance_{coverage_status.value}"]


def test_batch_rejects_duplicate_asset_cutoff_join_keys(tmp_path: Path) -> None:
    first = _build_handoff()
    second = _build_handoff(include_timing=False, include_candidate=False)

    with pytest.raises(
        ResearchQuantHandoffExportError,
        match="duplicate asset/cutoff",
    ) as exc_info:
        ResearchQuantHandoffExporter().export_batch(
            (first, second),
            tmp_path,
            generated_at=_EXPORTED_AT,
        )

    assert "asset_id=US:AAPL" in str(exc_info.value)
    assert "research_as_of=2026-08-14T23:59:59.999999+00:00" in str(exc_info.value)
    assert not tuple(tmp_path.iterdir())
