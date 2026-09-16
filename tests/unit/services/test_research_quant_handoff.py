"""Day48 Research-to-Quant handoff contract and export tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.identifiers import AssetId
from src.schemas.opportunity import (
    OpportunityCandidate,
    OpportunityCandidateBuildInput,
    OpportunityCandidateStatus,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_quant_handoff import (
    ResearchQuantHandoffBuildInput,
    ResearchQuantHandoffBundle,
)
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.research_state_transition import (
    ResearchStateTransition,
    TimingSatelliteBuildInput,
)
from src.schemas.satellite_alpha import (
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SelectionSatelliteBuildInput,
)
from src.schemas.temporal import TemporalLeakageError
from src.services.opportunity import OpportunityCandidateBuilder
from src.services.research_quant_handoff import (
    ResearchQuantHandoffBuilder,
    ResearchQuantHandoffBuildError,
    ResearchQuantHandoffExporter,
    ResearchQuantHandoffExportError,
)
from src.services.research_state_transition import ResearchStateTransitionBuilder
from src.services.satellite_alpha import SatelliteAlphaMapper

_STATE_ROOT = Path("data/research_state/day38")
_EPISODE_ROOT = Path("data/research_episode/day39")
_DERIVED_AT = datetime(2026, 9, 15, tzinfo=UTC)
_EXPORTED_AT = datetime(2026, 9, 16, tzinfo=UTC)


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
    episode: ResearchEpisode,
) -> tuple[SatelliteAlphaObservation, ...]:
    return SatelliteAlphaMapper().build_selection(
        SelectionSatelliteBuildInput(
            research_state=state,
            source_episode=episode,
            available_at=_DERIVED_AT,
            created_at=_DERIVED_AT,
        )
    )


def _candidate(
    state: ResearchStateSnapshot,
    episode: ResearchEpisode,
    selection: tuple[SatelliteAlphaObservation, ...],
) -> OpportunityCandidate:
    return OpportunityCandidateBuilder().build(
        OpportunityCandidateBuildInput(
            research_state=state,
            source_episode=episode,
            selection_observations=selection,
            created_at=_DERIVED_AT,
        )
    )


def _timing(
    state: ResearchStateSnapshot,
    episode: ResearchEpisode,
    *,
    previous_state: ResearchStateSnapshot | None = None,
    previous_episode: ResearchEpisode | None = None,
) -> tuple[tuple[SatelliteAlphaObservation, ...], ResearchStateTransition | None]:
    history = () if previous_state is None else (previous_state,)
    historical_episodes = () if previous_episode is None else (previous_episode,)
    inputs = TimingSatelliteBuildInput(
        current_state=state,
        historical_states=history,
        current_episode=episode,
        historical_episodes=historical_episodes,
        available_at=_DERIVED_AT,
        created_at=_DERIVED_AT,
    )
    builder = ResearchStateTransitionBuilder()
    return builder.build_timing(inputs), builder.build_transition(inputs)


def _inputs(
    name: str,
    *,
    include_selection: bool = True,
    include_timing: bool = True,
    include_candidate: bool = True,
    include_history: bool = False,
    created_at: datetime = _EXPORTED_AT,
) -> ResearchQuantHandoffBuildInput:
    state = _state(name)
    episode = _episode(name)
    selection = _selection(state, episode) if include_selection else ()
    candidate = (
        _candidate(state, episode, selection)
        if include_candidate and selection
        else None
    )
    previous_state = _state("phase3_aapl_golden") if include_history else None
    previous_episode = _episode("phase3_aapl_golden") if include_history else None
    timing, transition = (
        _timing(
            state,
            episode,
            previous_state=previous_state,
            previous_episode=previous_episode,
        )
        if include_timing
        else ((), None)
    )
    return ResearchQuantHandoffBuildInput(
        research_state=state,
        research_episode=episode,
        selection_observations=selection,
        timing_observations=timing,
        opportunity_candidate=candidate,
        research_state_transition=transition,
        created_at=created_at,
    )


def _build(
    name: str,
    *,
    include_selection: bool = True,
    include_timing: bool = True,
    include_candidate: bool = True,
    include_history: bool = False,
    created_at: datetime = _EXPORTED_AT,
) -> ResearchQuantHandoffBundle:
    return ResearchQuantHandoffBuilder().build(
        _inputs(
            name,
            include_selection=include_selection,
            include_timing=include_timing,
            include_candidate=include_candidate,
            include_history=include_history,
            created_at=created_at,
        )
    )


def test_bundle_schema_and_reference_only_payload() -> None:
    bundle = _build(name="phase4a_aapl_sector_aware", include_history=True)

    assert bundle.schema_version == "research_quant_handoff_bundle_v1"
    assert bundle.research_state_id.startswith("research_state_")
    assert bundle.research_episode_id.startswith("research_episode_")
    assert bundle.research_state_transition_id is not None
    payload = bundle.model_dump(mode="json")
    assert "research_state" not in payload
    assert "research_episode" not in payload
    assert "evidence_payload" not in payload


def test_bundle_identity_is_deterministic_and_ignores_created_at() -> None:
    first = _build(name="phase3_aapl_golden")
    later = _build(
        name="phase3_aapl_golden",
        created_at=_EXPORTED_AT + timedelta(days=1),
    )

    assert first.bundle_id == later.bundle_id


def test_observation_input_order_is_canonical() -> None:
    inputs = _inputs("phase3_aapl_golden")
    reversed_inputs = inputs.model_copy(
        update={
            "selection_observations": tuple(reversed(inputs.selection_observations)),
            "timing_observations": tuple(reversed(inputs.timing_observations)),
        }
    )
    first = ResearchQuantHandoffBuilder().build(inputs)
    second = ResearchQuantHandoffBuilder().build(reversed_inputs)

    assert first.bundle_id == second.bundle_id
    assert first.selection_satellite_observations == tuple(
        sorted(
            first.selection_satellite_observations,
            key=lambda item: item.observation_id,
        )
    )


def test_satellite_wire_payload_faithfully_roundtrips_descriptor() -> None:
    inputs = _inputs("phase3_aapl_golden")
    source = next(
        item
        for item in inputs.selection_observations
        if item.value is not None and item.value_components
    )
    payload = next(
        item
        for item in ResearchQuantHandoffBuilder()
        .build(inputs)
        .selection_satellite_observations
        if item.observation_id == source.observation_id
    )

    assert payload.satellite_alpha_id is source.satellite_alpha_id
    assert payload.family is source.satellite_alpha_id
    assert payload.usage is source.usage
    assert payload.comparison_scope is source.comparison_scope
    assert payload.coverage_status is source.coverage_status
    assert payload.value == source.value
    assert payload.value_components == source.value_components
    assert payload.quality is source.quality
    assert payload.confidence == source.confidence
    assert payload.missing_reasons == source.missing_reasons
    assert payload.definition_version == source.definition_version


def test_satellite_wire_numeric_component_roundtrip() -> None:
    inputs = _inputs("phase3_aapl_golden")
    source = next(
        item
        for item in inputs.selection_observations
        if any(
            isinstance(component.value, (int, float))
            and not isinstance(component.value, bool)
            for component in item.value_components
        )
    )
    numeric_component = next(
        component
        for component in source.value_components
        if isinstance(component.value, (int, float))
        and not isinstance(component.value, bool)
    )
    numeric_source = SatelliteAlphaObservation.model_validate(
        {**source.model_dump(), "value": numeric_component.value}
    )
    selection = tuple(
        numeric_source if item.observation_id == source.observation_id else item
        for item in inputs.selection_observations
    )
    payload = next(
        item
        for item in ResearchQuantHandoffBuilder()
        .build(inputs.model_copy(update={"selection_observations": selection}))
        .selection_satellite_observations
        if item.observation_id == source.observation_id
    )

    assert payload.value == numeric_component.value
    assert payload.value_components == source.value_components
    assert any(
        isinstance(component.value, (int, float))
        and not isinstance(component.value, bool)
        for component in payload.value_components
    )


def test_selection_only_bundle_and_optional_candidate() -> None:
    bundle = _build(
        name="phase4a_aapl_sector_aware",
        include_timing=False,
        include_candidate=False,
    )

    assert bundle.selection_satellite_observations
    assert not bundle.timing_satellite_observations
    assert bundle.opportunity_candidate_id is None


def test_timing_enabled_bundle_closes_transition() -> None:
    bundle = _build(name="phase4a_aapl_sector_aware", include_history=True)

    assert bundle.timing_satellite_observations
    assert bundle.research_state_transition_id is not None
    assert bundle.versions.transition_version == "research_state_transition_v1"
    assert bundle.research_state_transition_id in bundle.provenance.source_artifact_ids


def test_bundle_without_history_preserves_requires_history() -> None:
    bundle = _build(name="phase3_aapl_golden")

    coverage = {
        item.family: item.coverage_status
        for item in bundle.timing_satellite_observations
    }
    assert (
        coverage[SatelliteAlphaFamily.STATE_TRANSITION]
        is SatelliteAlphaCoverageStatus.REQUIRES_HISTORY
    )
    assert bundle.research_state_transition_id is None


def test_nonqualified_candidate_is_exportable() -> None:
    bundle = _build(name="phase4a_aapl_sector_aware")

    assert (
        bundle.opportunity_candidate_status
        is OpportunityCandidateStatus.INSUFFICIENT_RESEARCH
    )
    assert bundle.opportunity_candidate_id is not None


def test_partial_and_historical_missing_semantics_are_preserved() -> None:
    bundle = _build(name="phase3_aapl_golden")
    statuses = {
        item.coverage_status for item in bundle.selection_satellite_observations
    }

    assert SatelliteAlphaCoverageStatus.PARTIAL in statuses
    assert SatelliteAlphaCoverageStatus.MISSING_INPUT in statuses
    assert SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN in statuses


def test_candidate_state_mismatch_is_rejected() -> None:
    inputs = _inputs("phase4a_aapl_sector_aware")
    assert inputs.opportunity_candidate is not None
    candidate = inputs.opportunity_candidate.model_copy(
        update={"source_research_state_id": "research_state_0123456789abcdef01234567"}
    )

    with pytest.raises(ResearchQuantHandoffBuildError, match="Candidate"):
        ResearchQuantHandoffBuilder().build(
            inputs.model_copy(update={"opportunity_candidate": candidate})
        )


def test_transition_current_state_mismatch_is_rejected() -> None:
    inputs = _inputs("phase4a_aapl_sector_aware", include_history=True)
    assert inputs.research_state_transition is not None
    transition = inputs.research_state_transition.model_copy(
        update={"current_state_id": "research_state_0123456789abcdef01234567"}
    )

    with pytest.raises(ResearchQuantHandoffBuildError, match="Transition"):
        ResearchQuantHandoffBuilder().build(
            inputs.model_copy(update={"research_state_transition": transition})
        )


def test_future_satellite_reference_leakage_is_rejected() -> None:
    inputs = _inputs("phase3_aapl_golden")
    first = inputs.selection_observations[0].model_copy(
        update={"created_at": _EXPORTED_AT + timedelta(seconds=1)}
    )
    changed = (first, *inputs.selection_observations[1:])

    with pytest.raises(TemporalLeakageError):
        ResearchQuantHandoffBuilder().build(
            inputs.model_copy(update={"selection_observations": changed})
        )


@pytest.mark.parametrize(
    "name",
    ("phase3_aapl_golden", "phase4a_aapl_sector_aware"),
)
def test_frozen_historical_export_uses_only_source_run(name: str) -> None:
    bundle = _build(name=name)
    state = _state(name)

    assert bundle.research_state_id == state.research_state_id
    assert bundle.source_run_id == state.lineage.source_run_id
    if name == "phase3_aapl_golden":
        assert bundle.sector_id is None
        assert not bundle.chain_ids


def test_deterministic_frozen_rebuild_uses_no_model_or_provider() -> None:
    first = _build(name="phase4a_aapl_sector_aware", include_history=True)
    second = _build(name="phase4a_aapl_sector_aware", include_history=True)
    source = Path("src/services/research_quant_handoff.py").read_text().lower()

    assert first.bundle_id == second.bundle_id
    assert "src.services.llm" not in source
    assert "src.services.llm_provider" not in source
    assert "src.adapters" not in source


def test_provenance_closes_state_episode_candidate_satellite_and_evidence() -> None:
    bundle = _build(name="phase3_aapl_golden")
    artifacts = set(bundle.provenance.source_artifact_ids)

    assert bundle.research_state_id in artifacts
    assert bundle.research_episode_id in artifacts
    assert bundle.opportunity_candidate_id is not None
    assert bundle.opportunity_candidate_id in artifacts
    assert {
        item.observation_id
        for item in (
            *bundle.selection_satellite_observations,
            *bundle.timing_satellite_observations,
        )
    } <= artifacts
    assert bundle.provenance.source_claim_ids
    assert bundle.provenance.source_evidence_ids
    assert set(bundle.risk_refs) <= set(bundle.provenance.source_claim_ids)
    assert set(bundle.invalidator_refs) <= set(bundle.provenance.source_claim_ids)
    assert set(bundle.catalyst_refs) <= set(bundle.provenance.source_event_ids)


def test_single_json_serialization_is_stable(tmp_path: Path) -> None:
    bundle = _build(name="phase3_aapl_golden")
    exporter = ResearchQuantHandoffExporter()
    path = tmp_path / "handoff.json"

    first = exporter.serialize(bundle)
    exporter.export_bundle(bundle, path)

    assert path.read_text() == first + "\n"
    assert exporter.serialize(bundle) == first


def test_batch_jsonl_manifest_supports_mixed_coverage(tmp_path: Path) -> None:
    selection = _build(
        name="phase3_aapl_golden",
        include_timing=False,
    )
    inputs = _inputs(
        "phase3_aapl_golden",
        include_selection=False,
        include_candidate=False,
    )
    state_only = next(
        item
        for item in inputs.timing_observations
        if item.satellite_alpha_id is SatelliteAlphaFamily.STATE_TRANSITION
    )
    history_missing = ResearchQuantHandoffBuilder().build(
        inputs.model_copy(update={"timing_observations": (state_only,)})
    )
    history_missing = history_missing.model_copy(
        update={
            "asset_id": AssetId("US:MSFT"),
            "bundle_id": "research_quant_handoff_0123456789abcdef01234567",
        }
    )
    exporter = ResearchQuantHandoffExporter()
    manifest = exporter.export_batch(
        (history_missing, selection),
        tmp_path,
        generated_at=_EXPORTED_AT,
    )

    assert manifest.bundle_count == 2
    assert {item.status for item in manifest.coverage_summary} == {
        SatelliteAlphaCoverageStatus.PARTIAL,
        SatelliteAlphaCoverageStatus.REQUIRES_HISTORY,
    }
    lines = (tmp_path / manifest.artifact_path).read_text().splitlines()
    assert len(lines) == 2
    assert (tmp_path / f"{manifest.export_id}.manifest.json").is_file()


def test_batch_rejects_duplicate_asset_cutoff_join_key(tmp_path: Path) -> None:
    first = _build(name="phase3_aapl_golden")
    second = _build(
        name="phase3_aapl_golden",
        include_timing=False,
        include_candidate=False,
    )

    with pytest.raises(
        ResearchQuantHandoffExportError,
        match=(
            "duplicate asset/cutoff join key: asset_id=US:AAPL "
            "research_as_of=2026-08-14"
        ),
    ):
        ResearchQuantHandoffExporter().export_batch(
            (first, second), tmp_path, generated_at=_EXPORTED_AT
        )
    assert not tuple(tmp_path.iterdir())


def test_batch_allows_different_assets_at_same_cutoff(tmp_path: Path) -> None:
    first = _build(name="phase3_aapl_golden")
    second = first.model_copy(
        update={
            "asset_id": AssetId("US:MSFT"),
            "bundle_id": "research_quant_handoff_0123456789abcdef01234567",
        }
    )

    manifest = ResearchQuantHandoffExporter().export_batch(
        (first, second), tmp_path, generated_at=_EXPORTED_AT
    )

    assert manifest.asset_count == 2
    assert manifest.research_as_of == first.research_as_of
    assert manifest.research_as_of_values == (first.research_as_of,)


def test_batch_allows_same_asset_at_different_cutoffs_and_is_order_stable(
    tmp_path: Path,
) -> None:
    first = _build(name="phase3_aapl_golden")
    second = _build(name="phase4a_aapl_sector_aware")
    exporter = ResearchQuantHandoffExporter()

    forward = exporter.export_batch(
        (first, second), tmp_path / "forward", generated_at=_EXPORTED_AT
    )
    reverse = exporter.export_batch(
        (second, first), tmp_path / "reverse", generated_at=_EXPORTED_AT
    )

    assert forward.export_id == reverse.export_id
    assert forward.research_as_of is None
    assert forward.research_as_of_values == tuple(
        sorted((first.research_as_of, second.research_as_of))
    )
    assert (tmp_path / "forward" / forward.artifact_path).read_text() == (
        tmp_path / "reverse" / reverse.artifact_path
    ).read_text()


def test_contract_contains_no_quant_or_trading_outputs() -> None:
    fields = set(ResearchQuantHandoffBundle.model_fields)
    forbidden = {
        "rank",
        "zscore",
        "factor_exposure",
        "ic",
        "rankic",
        "alpha_forecast",
        "expected_return",
        "top_k",
        "buy",
        "sell",
        "position",
        "portfolio_weight",
        "entry",
        "exit",
        "order",
    }

    assert not fields & forbidden
