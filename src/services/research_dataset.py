"""Deterministic point-in-time dataset construction from frozen artifacts."""

from __future__ import annotations

import hashlib
import json

from src.schemas.research_dataset import (
    ResearchDatasetBuildInput,
    ResearchDatasetComponentStatus,
    ResearchDatasetLabelStatus,
    ResearchDatasetQuality,
    ResearchDatasetQualityStatus,
    ResearchDatasetSample,
    ResearchDatasetVersionLineage,
)
from src.schemas.research_episode import ResearchEpisodeTraceQuality
from src.schemas.research_state import (
    ResearchStateSection,
    ResearchStateSectionStatus,
    ResearchStateSnapshot,
)
from src.schemas.temporal import TemporalMetadata, validate_temporal_access


class ResearchDatasetBuildError(ValueError):
    """Raised when frozen upstream references cannot form a safe sample."""


class ResearchDatasetBuilder:
    """Build one reference-only sample without LLM or Provider dependencies."""

    def build(self, inputs: ResearchDatasetBuildInput) -> ResearchDatasetSample:
        """Build a stable point-in-time sample from State and Episode.

        Args:
            inputs: Frozen State, Episode, optional attribution, and build version.

        Returns:
            One immutable reference-only dataset sample.

        Raises:
            ResearchDatasetBuildError: If identity or temporal lineage is invalid.
        """

        state = inputs.research_state
        episode = inputs.research_episode
        attribution = inputs.attribution
        self._validate_identity(state_id=state.research_state_id, inputs=inputs)
        self._validate_temporal(inputs)
        quality = _quality(inputs)
        fingerprint = _fingerprint(inputs)
        return ResearchDatasetSample(
            sample_id=f"research_sample_{fingerprint[:24]}",
            asset_id=state.asset_id,
            market=episode.market,
            sector_id=_scope_member(state.hierarchy.sector_scope_id, "SECTOR:"),
            industry_chain_ids=tuple(
                _required_scope_member(value, "CHAIN:")
                for value in state.hierarchy.industry_chain_scope_ids
            ),
            research_as_of=state.research_as_of,
            research_state_id=state.research_state_id,
            research_episode_id=episode.episode_id,
            data_snapshot_id=episode.data_snapshot_id,
            sector_context_id=episode.sector_context_id,
            memory_context_id=episode.memory_context_id,
            attribution_bundle_id=(
                None if attribution is None else attribution.attribution_bundle_id
            ),
            agent_run_ids=episode.agent_run_ids,
            versions=ResearchDatasetVersionLineage(
                research_state_schema_version=state.schema_version,
                research_state_version=state.research_state_version,
                research_episode_schema_version=episode.schema_version,
                research_episode_trace_quality=episode.trace_quality.value,
                source_dataset_version=state.lineage.dataset_version,
                attribution_version=(
                    None if attribution is None else attribution.attribution_version
                ),
                model_versions=episode.model_versions,
                prompt_versions=episode.prompt_versions,
                feature_versions=episode.feature_versions,
            ),
            label_status=ResearchDatasetLabelStatus.PENDING,
            label_ids=(),
            quality=quality,
            dataset_build_version=inputs.dataset_build_version,
            created_at=inputs.created_at,
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _validate_identity(
        *,
        state_id: str,
        inputs: ResearchDatasetBuildInput,
    ) -> None:
        state = inputs.research_state
        episode = inputs.research_episode
        attribution = inputs.attribution
        if episode.research_state_id != state_id:
            raise ResearchDatasetBuildError(
                "ResearchEpisode references a different ResearchState"
            )
        if (
            episode.asset_id != state.asset_id
            or episode.research_as_of != state.research_as_of
        ):
            raise ResearchDatasetBuildError(
                "ResearchState and ResearchEpisode identity or cutoff differs"
            )
        state_snapshot = state.lineage.data_snapshot_id or state.lineage.data_bundle_id
        if episode.data_snapshot_id != state_snapshot:
            raise ResearchDatasetBuildError(
                "ResearchEpisode data snapshot differs from ResearchState"
            )
        if episode.sector_context_id != state.lineage.sector_context_id:
            raise ResearchDatasetBuildError(
                "ResearchEpisode Sector context differs from ResearchState"
            )
        if episode.memory_context_id != state.lineage.memory_context_id:
            raise ResearchDatasetBuildError(
                "ResearchEpisode Memory context differs from ResearchState"
            )
        if state.lineage.agent_run_ids and set(episode.agent_run_ids) != set(
            state.lineage.agent_run_ids
        ):
            raise ResearchDatasetBuildError(
                "ResearchEpisode Agent runs differ from ResearchState"
            )
        if attribution is not None:
            if attribution.episode_id != episode.episode_id:
                raise ResearchDatasetBuildError(
                    "attribution references a different ResearchEpisode"
                )
            if attribution.research_as_of != state.research_as_of:
                raise ResearchDatasetBuildError(
                    "attribution cutoff differs from ResearchState"
                )

    @staticmethod
    def _validate_temporal(inputs: ResearchDatasetBuildInput) -> None:
        cutoff = inputs.research_state.research_as_of
        visible = (
            TemporalMetadata(
                available_at=inputs.research_state.research_as_of,
                as_of=inputs.research_state.research_as_of,
            ),
            TemporalMetadata(
                available_at=inputs.research_episode.created_at,
                as_of=inputs.research_episode.research_as_of,
            ),
        )
        for metadata in visible:
            validate_temporal_access(metadata, cutoff)
        if inputs.attribution is not None:
            validate_temporal_access(
                TemporalMetadata(
                    available_at=inputs.attribution.research_as_of,
                    as_of=inputs.attribution.research_as_of,
                ),
                cutoff,
            )


def _quality(inputs: ResearchDatasetBuildInput) -> ResearchDatasetQuality:
    state = inputs.research_state
    episode = inputs.research_episode
    state_status = _state_status(state)
    episode_status = (
        ResearchDatasetComponentStatus.AVAILABLE
        if episode.trace_quality is ResearchEpisodeTraceQuality.COMPLETE
        else ResearchDatasetComponentStatus.PARTIAL
    )
    sector_status = _optional_section_status(
        state.sector_state,
        episode.sector_context_id,
    )
    memory_status = _memory_status(
        state.memory_context_state,
        episode.memory_context_id,
    )
    attribution_status = (
        ResearchDatasetComponentStatus.AVAILABLE
        if inputs.attribution is not None
        else ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN
    )
    missing: list[str] = []
    if state_status is ResearchDatasetComponentStatus.PARTIAL:
        missing.append("research_state_partial")
    if episode_status is ResearchDatasetComponentStatus.PARTIAL:
        missing.append("research_episode_partial")
    if sector_status is ResearchDatasetComponentStatus.PARTIAL:
        missing.append("sector_context_partial")
    elif sector_status is ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN:
        missing.append("sector_context_not_available_in_source_run")
    if memory_status is ResearchDatasetComponentStatus.PARTIAL:
        missing.append("memory_context_partial")
    elif memory_status is ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN:
        missing.append("memory_context_not_available_in_source_run")
    if attribution_status is ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN:
        missing.append("attribution_not_available_in_source_run")
    overall = (
        ResearchDatasetQualityStatus.AVAILABLE
        if not missing
        else ResearchDatasetQualityStatus.PARTIAL
    )
    return ResearchDatasetQuality(
        status=overall,
        state_status=state_status,
        episode_status=episode_status,
        sector_context_status=sector_status,
        memory_context_status=memory_status,
        attribution_status=attribution_status,
        missing_reasons=tuple(missing),
    )


def _state_status(state: ResearchStateSnapshot) -> ResearchDatasetComponentStatus:
    sections = (
        state.identity,
        state.macro_state,
        state.fundamental_state,
        state.valuation_state,
        state.technical_state,
        state.sentiment_state,
        state.event_state,
        state.market_context_state,
        state.debate_state,
        state.risk_state,
        state.thesis_state,
        state.data_quality_state,
    )
    return (
        ResearchDatasetComponentStatus.AVAILABLE
        if all(item.status is ResearchStateSectionStatus.PRESENT for item in sections)
        else ResearchDatasetComponentStatus.PARTIAL
    )


def _optional_section_status(
    section: ResearchStateSection,
    context_id: str | None,
) -> ResearchDatasetComponentStatus:
    if context_id is None:
        return ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN
    if section.status is ResearchStateSectionStatus.PRESENT:
        return ResearchDatasetComponentStatus.AVAILABLE
    return ResearchDatasetComponentStatus.PARTIAL


def _memory_status(
    section: ResearchStateSection,
    context_id: str | None,
) -> ResearchDatasetComponentStatus:
    if context_id is None:
        return ResearchDatasetComponentStatus.NOT_AVAILABLE_IN_SOURCE_RUN
    result_count = next(
        (
            item.value
            for item in section.features
            if item.feature_name == "result_count"
        ),
        None,
    )
    if result_count == 0:
        return ResearchDatasetComponentStatus.EMPTY_VALID
    if section.status is ResearchStateSectionStatus.PRESENT:
        return ResearchDatasetComponentStatus.AVAILABLE
    return ResearchDatasetComponentStatus.PARTIAL


def _scope_member(scope_id: str | None, prefix: str) -> str | None:
    return None if scope_id is None else _required_scope_member(scope_id, prefix)


def _required_scope_member(scope_id: str, prefix: str) -> str:
    if not scope_id.startswith(prefix) or len(scope_id) == len(prefix):
        raise ResearchDatasetBuildError(f"invalid {prefix[:-1]} scope identity")
    return scope_id.removeprefix(prefix)


def _fingerprint(inputs: ResearchDatasetBuildInput) -> str:
    payload = {
        "dataset_schema_version": "research_dataset_sample_v1",
        "dataset_build_version": inputs.dataset_build_version,
        "research_state_id": inputs.research_state.research_state_id,
        "research_state_fingerprint": inputs.research_state.lineage.input_fingerprint,
        "research_episode_id": inputs.research_episode.episode_id,
        "research_episode_fingerprint": inputs.research_episode.input_fingerprint,
        "attribution_bundle_id": (
            None
            if inputs.attribution is None
            else inputs.attribution.attribution_bundle_id
        ),
        "attribution_fingerprint": (
            None if inputs.attribution is None else inputs.attribution.input_fingerprint
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
