"""Deterministic orchestration for the Golden point-in-time replay gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from src.models.enums import AgentName
from src.schemas.golden_replay import (
    GoldenReplayCheck,
    GoldenReplayManifest,
    GoldenReplayMemoryStatus,
    GoldenReplayStatus,
    GoldenReplayTrace,
    GoldenReplayTraceStatus,
    GoldenReplayVersionReference,
)
from src.schemas.research_attribution import ResearchEpisodeAttribution
from src.schemas.research_data import ResearchDataBundle, ResearchDataSection
from src.schemas.research_dataset import (
    ResearchDatasetBuildInput,
    ResearchDatasetSample,
)
from src.schemas.research_episode import ResearchEpisode, ResearchEpisodeBuildInput
from src.schemas.research_state import (
    ResearchStateBuildInput,
    ResearchStateClaimInput,
    ResearchStateSection,
    ResearchStateSnapshot,
)
from src.schemas.sector_context import SectorContextBundle
from src.schemas.temporal import TemporalMetadata, temporal_access_decision
from src.services.research_attribution import ResearchAttributionBuilder
from src.services.research_dataset import ResearchDatasetBuilder
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.research_state import ResearchStateBuilder


class GoldenReplayError(ValueError):
    """Raised when frozen artifacts cannot reproduce their semantic identity."""


@dataclass(frozen=True)
class GoldenReplayLeakageFixture:
    """One deliberate future temporal input expected to be rejected."""

    name: str
    metadata: TemporalMetadata


@dataclass(frozen=True)
class GoldenReplayInput:
    """Frozen inputs and expected artifacts for one offline replay."""

    replay_name: str
    source_run_id: str
    source_artifact_ids: tuple[str, ...]
    state_build_input: ResearchStateBuildInput
    episode_build_input: ResearchEpisodeBuildInput
    expected_state: ResearchStateSnapshot
    expected_episode: ResearchEpisode
    expected_sample: ResearchDatasetSample
    leakage_checks: tuple[GoldenReplayCheck, ...]
    created_at: datetime
    expected_attribution: ResearchEpisodeAttribution | None = None
    sector_context: SectorContextBundle | None = None
    memory_status: GoldenReplayMemoryStatus = (
        GoldenReplayMemoryStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )


class GoldenReplayService:
    """Rebuild Phase 4B artifacts with no Provider or LLM dependency."""

    def replay(self, inputs: GoldenReplayInput) -> GoldenReplayManifest:
        """Replay one frozen run and verify every deterministic identity.

        Args:
            inputs: Frozen builder inputs, expected artifacts, and leakage results.

        Returns:
            A credential-free versioned Golden replay manifest.

        Raises:
            GoldenReplayError: If any semantic identity or source link changes.
        """

        state = ResearchStateBuilder().build(inputs.state_build_input)
        episode_input = inputs.episode_build_input.model_copy(
            update={"research_state": state}
        )
        episode = ResearchEpisodeBuilder().build(episode_input)
        attribution = self._rebuild_attribution(inputs, episode)
        sample = ResearchDatasetBuilder().build(
            ResearchDatasetBuildInput(
                research_state=state,
                research_episode=episode,
                attribution=attribution,
                dataset_build_version=inputs.expected_sample.dataset_build_version,
                created_at=inputs.created_at,
            )
        )
        self._assert_expected(inputs, state, episode, attribution, sample)
        repeated_state = ResearchStateBuilder().build(inputs.state_build_input)
        repeated_episode = ResearchEpisodeBuilder().build(
            inputs.episode_build_input.model_copy(
                update={"research_state": repeated_state}
            )
        )
        repeated_sample = ResearchDatasetBuilder().build(
            ResearchDatasetBuildInput(
                research_state=repeated_state,
                research_episode=repeated_episode,
                attribution=self._rebuild_attribution(inputs, repeated_episode),
                dataset_build_version=sample.dataset_build_version,
                created_at=inputs.created_at,
            )
        )
        determinism = (
            _identity_check(
                "research_state_semantic_identity",
                state.research_state_id,
                repeated_state.research_state_id,
            ),
            _identity_check(
                "research_episode_identity",
                episode.episode_id,
                repeated_episode.episode_id,
            ),
            _identity_check(
                "research_dataset_sample_identity",
                sample.sample_id,
                repeated_sample.sample_id,
            ),
        )
        usages = episode.sector_usage
        retrieval_ids = (
            ()
            if attribution is None
            else tuple(item.retrieval_id for item in attribution.retrieval_records)
        )
        attribution_ids = (
            ()
            if attribution is None
            else (
                attribution.attribution_bundle_id,
                *(item.attribution_id for item in attribution.attributions),
            )
        )
        memory_empty = inputs.memory_status is GoldenReplayMemoryStatus.EMPTY_VALID
        fingerprint = _fingerprint(
            inputs=inputs,
            state=state,
            episode=episode,
            attribution=attribution,
            sample=sample,
        )
        return GoldenReplayManifest(
            replay_id=f"golden_replay_{fingerprint[:24]}",
            replay_name=inputs.replay_name,
            source_run_id=inputs.source_run_id,
            asset_id=state.asset_id,
            research_as_of=state.research_as_of,
            source_artifact_ids=inputs.source_artifact_ids,
            research_state_id=state.research_state_id,
            research_episode_id=episode.episode_id,
            research_dataset_sample_id=sample.sample_id,
            retrieval_ids=retrieval_ids,
            attribution_ids=attribution_ids,
            accepted_claim_count=episode.accepted_claim_count,
            rejected_claim_count=episode.rejected_claim_count,
            final_research_claim_count=len(episode.final_research_claim_ids),
            sector_claims_provided=sum(
                len(item.provided_sector_claim_ids) for item in usages
            ),
            sector_claims_used=sum(len(item.used_sector_claim_ids) for item in usages),
            events_provided=sum(len(item.provided_event_ids) for item in usages),
            events_used=sum(len(item.used_event_ids) for item in usages),
            memory_retrieval_count=len(retrieval_ids),
            memory_empty_valid=memory_empty,
            memory_status=inputs.memory_status,
            temporal_validation_status=GoldenReplayStatus.PASS,
            versions=_versions(state, episode, attribution, sample),
            determinism_checks=determinism,
            leakage_checks=inputs.leakage_checks,
            traceability_examples=_traceability_examples(
                inputs.state_build_input,
                state,
                episode,
                attribution,
                sample,
                inputs.sector_context,
            ),
            replay_status=GoldenReplayStatus.PASS,
            created_at=inputs.created_at,
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _rebuild_attribution(
        inputs: GoldenReplayInput,
        episode: ResearchEpisode,
    ) -> ResearchEpisodeAttribution | None:
        if inputs.expected_attribution is None:
            return None
        if inputs.sector_context is None:
            raise GoldenReplayError(
                "expected attribution requires its frozen Sector context"
            )
        return ResearchAttributionBuilder().build(
            episode=episode,
            sector_context=inputs.sector_context,
        )

    @staticmethod
    def _assert_expected(
        inputs: GoldenReplayInput,
        state: ResearchStateSnapshot,
        episode: ResearchEpisode,
        attribution: ResearchEpisodeAttribution | None,
        sample: ResearchDatasetSample,
    ) -> None:
        if state != inputs.expected_state:
            raise GoldenReplayError("ResearchState replay changed semantic content")
        if episode != inputs.expected_episode:
            raise GoldenReplayError("ResearchEpisode replay changed semantic content")
        if attribution != inputs.expected_attribution:
            raise GoldenReplayError("Research Attribution replay changed content")
        expected = inputs.expected_sample.model_dump(exclude={"created_at"})
        actual = sample.model_dump(exclude={"created_at"})
        if actual != expected:
            raise GoldenReplayError("ResearchDatasetSample replay changed identity")


def validate_leakage_challenges(
    fixtures: tuple[GoldenReplayLeakageFixture, ...],
    *,
    research_as_of: datetime,
) -> tuple[GoldenReplayCheck, ...]:
    """Require every deliberate future fixture to fail the shared PIT gate."""

    checks: list[GoldenReplayCheck] = []
    for fixture in fixtures:
        decision = temporal_access_decision(fixture.metadata, research_as_of)
        if decision.usable:
            raise GoldenReplayError(
                f"leakage challenge unexpectedly usable: {fixture.name}"
            )
        checks.append(
            GoldenReplayCheck(
                check_name=fixture.name,
                status=GoldenReplayStatus.PASS,
                evidence_ids=(decision.reason.value,),
                details=(
                    "Rejected by Unified Temporal Contract: " f"{decision.reason.value}"
                ),
            )
        )
    return tuple(checks)


def _identity_check(name: str, first: str, second: str) -> GoldenReplayCheck:
    if first != second:
        raise GoldenReplayError(f"non-deterministic identity: {name}")
    return GoldenReplayCheck(
        check_name=name,
        status=GoldenReplayStatus.PASS,
        evidence_ids=(first,),
        details="Repeated frozen-artifact build produced the same identity.",
    )


def _versions(
    state: ResearchStateSnapshot,
    episode: ResearchEpisode,
    attribution: ResearchEpisodeAttribution | None,
    sample: ResearchDatasetSample,
) -> tuple[GoldenReplayVersionReference, ...]:
    values = [
        ("temporal_contract", "temporal_contract_v1"),
        ("research_state_schema", state.schema_version),
        ("research_state", state.research_state_version),
        ("research_state_feature", state.feature_version),
        ("research_episode_schema", episode.schema_version),
        ("research_dataset_schema", sample.dataset_schema_version),
        ("research_dataset_build", sample.dataset_build_version),
    ]
    if attribution is not None:
        values.append(("research_attribution", attribution.attribution_version))
    return tuple(
        GoldenReplayVersionReference(component=component, version=version)
        for component, version in values
    )


def _traceability_examples(
    state_input: ResearchStateBuildInput,
    state: ResearchStateSnapshot,
    episode: ResearchEpisode,
    attribution: ResearchEpisodeAttribution | None,
    sample: ResearchDatasetSample,
    sector_context: SectorContextBundle | None,
) -> tuple[GoldenReplayTrace, ...]:
    traces: list[GoldenReplayTrace] = []
    deterministic = _deterministic_feature_trace(
        state_input.research_data_bundle,
        state,
    )
    if deterministic is not None:
        traces.append(deterministic)
    manager = _manager_claim_trace(state_input.accepted_claims)
    if manager is not None:
        traces.append(manager)
    if sector_context is not None:
        traces.append(_sector_claim_trace(episode, sector_context))
    if attribution is not None:
        traces.append(_context_usage_trace(attribution, episode))
    traces.append(
        GoldenReplayTrace(
            trace_name="dataset_to_episode_to_state",
            status=GoldenReplayTraceStatus.COMPLETE,
            reference_path=(
                sample.sample_id,
                sample.research_episode_id,
                sample.research_state_id,
            ),
        )
    )
    return tuple(traces)


def _deterministic_feature_trace(
    bundle: ResearchDataBundle,
    state: ResearchStateSnapshot,
) -> GoldenReplayTrace | None:
    evidence = {
        item.evidence_id: item
        for section in _bundle_sections(bundle)
        for item in section.items
    }
    for section in _state_sections(state):
        for feature in section.features:
            if not feature.source_evidence_ids:
                continue
            evidence_id = feature.source_evidence_ids[0]
            source = evidence.get(evidence_id)
            if source is None:
                continue
            provider = source.source.provider_name
            return GoldenReplayTrace(
                trace_name="deterministic_feature_to_evidence_provider",
                status=GoldenReplayTraceStatus.COMPLETE,
                reference_path=(
                    f"feature:{section.section_name.value}:{feature.feature_name}",
                    evidence_id,
                    source.source.normalized_record_key,
                ),
                terminal_providers=(provider,),
            )
    return None


def _manager_claim_trace(
    claims: tuple[ResearchStateClaimInput, ...],
) -> GoldenReplayTrace | None:
    index = {
        item.claim.claim_id: item.claim
        for item in claims
        if item.claim.claim_id is not None
    }
    for item in claims:
        claim = item.claim
        if (
            item.agent_role is not AgentName.RESEARCH_MANAGER
            or not claim.upstream_claim_ids
        ):
            continue
        parent = index.get(claim.upstream_claim_ids[0])
        if parent is None:
            continue
        providers = tuple(
            dict.fromkeys(
                reference.provider
                for reference in parent.source_references
                if reference.provider is not None
            )
        )
        evidence_id = parent.evidence_ids[0] if parent.evidence_ids else "no-direct-id"
        assert claim.claim_id is not None
        assert parent.claim_id is not None
        return GoldenReplayTrace(
            trace_name="asset_manager_claim_to_analyst_evidence",
            status=GoldenReplayTraceStatus.COMPLETE,
            reference_path=(claim.claim_id, parent.claim_id, evidence_id),
            terminal_providers=providers,
        )
    return None


def _sector_claim_trace(
    episode: ResearchEpisode,
    context: SectorContextBundle,
) -> GoldenReplayTrace:
    used = next(
        (
            (usage.agent_role, claim_id)
            for usage in episode.sector_usage
            for claim_id in usage.used_sector_claim_ids
        ),
        None,
    )
    if used is None:
        raise GoldenReplayError("Sector-aware replay has no used Sector Claim")
    role, claim_id = used
    claim = next(
        (item for item in context.accepted_claims if item.claim_id == claim_id),
        None,
    )
    if claim is None:
        raise GoldenReplayError("used Sector Claim is absent from frozen context")
    providers = tuple(
        dict.fromkeys(
            item.provider
            for item in claim.source_references
            if item.provider is not None
        )
    )
    return GoldenReplayTrace(
        trace_name="asset_manager_to_sector_claim_to_evidence",
        status=GoldenReplayTraceStatus.PARTIAL,
        reference_path=(
            "asset_manager_claim:not_available_at_source_run",
            f"agent_role:{role.value}",
            claim_id,
            *(claim.evidence_ids[:1]),
        ),
        terminal_providers=providers,
        limitation=(
            "Day36 retained Agent-role usage but not the accepted Asset Claim ID; "
            "the missing identity was not inferred."
        ),
    )


def _context_usage_trace(
    attribution: ResearchEpisodeAttribution,
    episode: ResearchEpisode,
) -> GoldenReplayTrace:
    used = next((item for item in attribution.attributions if item.used), None)
    if used is None:
        raise GoldenReplayError("attribution replay has no used context")
    path = [used.context_id, f"agent:{used.agent_role.value}"]
    status = GoldenReplayTraceStatus.COMPLETE
    limitation = None
    if used.used_by_claim_ids:
        path.extend((used.used_by_claim_ids[0], episode.episode_id))
    else:
        path.extend(("accepted_claim:not_available_at_source_run", episode.episode_id))
        status = GoldenReplayTraceStatus.PARTIAL
        limitation = (
            "The source run persisted context use but omitted downstream Claim IDs."
        )
    return GoldenReplayTrace(
        trace_name="context_to_agent_to_claim_to_episode",
        status=status,
        reference_path=tuple(path),
        terminal_providers=tuple(
            dict.fromkeys(
                item.provider
                for item in used.source_references
                if item.provider is not None
            )
        ),
        limitation=limitation,
    )


def _bundle_sections(bundle: ResearchDataBundle) -> tuple[ResearchDataSection, ...]:
    return (
        bundle.asset_identity,
        bundle.market_context,
        bundle.ohlcv,
        bundle.technical_features,
        bundle.fundamentals,
        bundle.valuation,
        bundle.corporate_events,
        bundle.filings,
        bundle.macro_indicators,
        bundle.industry_sector_context,
        bundle.news_evidence,
        bundle.sentiment_evidence,
    )


def _state_sections(state: ResearchStateSnapshot) -> tuple[ResearchStateSection, ...]:
    return (
        state.fundamental_state,
        state.valuation_state,
        state.technical_state,
        state.macro_state,
        state.market_context_state,
    )


def _fingerprint(
    *,
    inputs: GoldenReplayInput,
    state: ResearchStateSnapshot,
    episode: ResearchEpisode,
    attribution: ResearchEpisodeAttribution | None,
    sample: ResearchDatasetSample,
) -> str:
    payload = {
        "manifest_schema_version": "golden_replay_manifest_v1",
        "replay_name": inputs.replay_name,
        "source_run_id": inputs.source_run_id,
        "source_artifact_ids": inputs.source_artifact_ids,
        "state_id": state.research_state_id,
        "episode_id": episode.episode_id,
        "attribution_id": (
            None if attribution is None else attribution.attribution_bundle_id
        ),
        "sample_id": sample.sample_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
