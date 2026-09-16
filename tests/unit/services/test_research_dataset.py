"""Day42 point-in-time ResearchDatasetSample contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.enums import AgentName, AgentStatus
from src.schemas.research_attribution import ResearchEpisodeAttribution
from src.schemas.research_dataset import (
    ResearchDatasetBuildInput,
    ResearchDatasetComponentStatus,
    ResearchDatasetLabelStatus,
)
from src.schemas.research_episode import (
    AgentExecutionTrace,
    ResearchEpisode,
    ResearchEpisodeBuildInput,
    ResearchEpisodeTraceQuality,
)
from src.schemas.research_state import (
    ResearchStateBuildInput,
    ResearchStateMemoryContextInput,
    ResearchStateSnapshot,
)
from src.schemas.temporal import TemporalLeakageError, validate_temporal_access
from src.services.research_dataset import (
    ResearchDatasetBuilder,
    ResearchDatasetBuildError,
)
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.research_state import ResearchStateBuilder
from tests.unit.agents.test_input_contracts import AS_OF, _data_bundle

ROOT = Path(__file__).parents[3]
PHASE3_STATE = ROOT / "data/research_state/day38/phase3_aapl_golden.research_state.json"
PHASE3_EPISODE = (
    ROOT / "data/research_episode/day39/phase3_aapl_golden.research_episode.json"
)
DAY36_STATE = (
    ROOT / "data/research_state/day38/phase4a_aapl_sector_aware.research_state.json"
)
DAY36_EPISODE = (
    ROOT / "data/research_episode/day39/phase4a_aapl_sector_aware.research_episode.json"
)
DAY36_ATTRIBUTION = (
    ROOT
    / "data/research_attribution/day41"
    / "phase4a_aapl_sector_aware.research_attribution.json"
)
CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _golden_inputs(
    *,
    version: str = "pit_research_dataset_build_v1",
) -> ResearchDatasetBuildInput:
    return ResearchDatasetBuildInput(
        research_state=ResearchStateSnapshot.model_validate_json(
            PHASE3_STATE.read_text(encoding="utf-8")
        ),
        research_episode=ResearchEpisode.model_validate_json(
            PHASE3_EPISODE.read_text(encoding="utf-8")
        ),
        dataset_build_version=version,
        created_at=CREATED_AT,
    )


def _day36_inputs() -> ResearchDatasetBuildInput:
    return ResearchDatasetBuildInput(
        research_state=ResearchStateSnapshot.model_validate_json(
            DAY36_STATE.read_text(encoding="utf-8")
        ),
        research_episode=ResearchEpisode.model_validate_json(
            DAY36_EPISODE.read_text(encoding="utf-8")
        ),
        attribution=ResearchEpisodeAttribution.model_validate_json(
            DAY36_ATTRIBUTION.read_text(encoding="utf-8")
        ),
        dataset_build_version="pit_research_dataset_build_v1",
        created_at=CREATED_AT,
    )


def test_sample_identity_is_stable_and_reference_only() -> None:
    """Canonical frozen identities produce one sample without copied objects."""

    inputs = _golden_inputs()
    first = ResearchDatasetBuilder().build(inputs)
    second = ResearchDatasetBuilder().build(
        inputs.model_copy(update={"created_at": CREATED_AT + timedelta(hours=1)})
    )

    assert first.sample_id == second.sample_id
    assert first.input_fingerprint == second.input_fingerprint
    assert first.label_status is ResearchDatasetLabelStatus.PENDING
    assert first.label_ids == ()
    assert not {
        "research_state",
        "research_episode",
        "claims",
        "evidence",
        "report",
        "memory",
    } & set(type(first).model_fields)


def test_phase3_golden_sample_never_backfills_sector() -> None:
    """The pre-Sector Golden run retains an explicit null Sector reference."""

    sample = ResearchDatasetBuilder().build(_golden_inputs())

    assert str(sample.asset_id) == "US:AAPL"
    assert sample.sector_id is None
    assert sample.industry_chain_ids == ()
    assert sample.sector_context_id is None
    assert sample.attribution_bundle_id is None
    assert sample.quality.sector_context_status is (
        ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN
    )


def test_sector_aware_sample_links_state_episode_and_attribution() -> None:
    """Day36 hierarchy and Day41 attribution remain stable references."""

    inputs = _day36_inputs()
    sample = ResearchDatasetBuilder().build(inputs)
    assert inputs.attribution is not None

    assert sample.sector_id == "CONSUMER_ELECTRONICS"
    assert sample.industry_chain_ids == ("APPLE_CHAIN",)
    assert sample.sector_context_id == inputs.research_episode.sector_context_id
    assert sample.attribution_bundle_id == inputs.attribution.attribution_bundle_id
    assert sample.quality.attribution_status is (
        ResearchDatasetComponentStatus.AVAILABLE
    )
    assert sample.quality.episode_status is ResearchDatasetComponentStatus.PARTIAL


def test_builder_reuses_unified_temporal_contract_and_rejects_future_episode() -> None:
    """A future source artifact is rejected by Day37 rather than local logic."""

    inputs = _golden_inputs()
    with patch(
        "src.services.research_dataset.validate_temporal_access",
        wraps=validate_temporal_access,
    ) as temporal_validator:
        ResearchDatasetBuilder().build(inputs)
    assert temporal_validator.call_count == 2

    future_episode = inputs.research_episode.model_copy(
        update={
            "created_at": inputs.research_state.research_as_of + timedelta(seconds=1)
        }
    )
    with pytest.raises(TemporalLeakageError):
        ResearchDatasetBuilder().build(
            inputs.model_copy(update={"research_episode": future_episode})
        )


def test_empty_valid_memory_is_not_invalid() -> None:
    """A completed empty retrieval is a legal sample component."""

    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            memory_context=ResearchStateMemoryContextInput(
                snapshot_id="memory-snapshot-empty",
                as_of=AS_OF,
                status="empty_valid",
                result_count=0,
            ),
            source_run_id="empty-memory-run",
        )
    )
    trace = AgentExecutionTrace(
        agent_role=AgentName.RESEARCH_MANAGER,
        agent_run_id="run:empty-memory",
        status=AgentStatus.OK,
        accepted_claim_count=0,
        rejected_claim_count=0,
        provider="fake_offline",
        model="fixed",
        prompt_version="v1",
        trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
    )
    episode = ResearchEpisodeBuilder().build(
        ResearchEpisodeBuildInput(
            research_state=state,
            agent_traces=(trace,),
            created_at=AS_OF,
        )
    )
    sample = ResearchDatasetBuilder().build(
        ResearchDatasetBuildInput(
            research_state=state,
            research_episode=episode,
            dataset_build_version="pit_research_dataset_build_v1",
            created_at=CREATED_AT,
        )
    )
    assert sample.quality.memory_context_status is (
        ResearchDatasetComponentStatus.EMPTY_VALID
    )
    assert sample.quality.status.value != "invalid"


def test_invalid_upstream_reference_is_rejected() -> None:
    """A Sample cannot pair an Episode with another frozen State identity."""

    inputs = _golden_inputs()
    invalid_episode = inputs.research_episode.model_copy(
        update={"research_state_id": "research_state_000000000000000000000000"}
    )
    with pytest.raises(ResearchDatasetBuildError, match="different ResearchState"):
        ResearchDatasetBuilder().build(
            inputs.model_copy(update={"research_episode": invalid_episode})
        )


def test_build_version_changes_sample_identity_without_future_labels() -> None:
    """Build-version changes are identity-bearing but cannot create labels."""

    first = ResearchDatasetBuilder().build(_golden_inputs(version="build-v1"))
    second = ResearchDatasetBuilder().build(_golden_inputs(version="build-v2"))

    assert first.sample_id != second.sample_id
    assert first.label_ids == second.label_ids == ()
    assert first.versions.research_state_version == "research_state_v1"
    assert first.versions.research_episode_schema_version == "research_episode_v1"
