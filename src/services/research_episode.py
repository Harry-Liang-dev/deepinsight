"""Pure ResearchEpisode construction from frozen State and execution metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from src.models.enums import AgentName
from src.schemas.research_episode import (
    ResearchEpisode,
    ResearchEpisodeBuildInput,
    ResearchEpisodeTraceQuality,
    ResearchEpisodeVersionReference,
)
from src.schemas.research_state import ResearchStateSection


class ResearchEpisodeBuildError(ValueError):
    """Raised when frozen run identities cannot form a coherent Episode."""


class ResearchEpisodeBuilder:
    """Freeze one research process without LLM, Provider, or report parsing."""

    def build(self, inputs: ResearchEpisodeBuildInput) -> ResearchEpisode:
        """Build one immutable Episode from existing run metadata.

        Args:
            inputs: Frozen ResearchState, Agent traces, and usage diagnostics.

        Returns:
            A stable reference-only ResearchEpisode.

        Raises:
            ResearchEpisodeBuildError: If State and execution identities disagree.
        """

        state = inputs.research_state
        traces = inputs.agent_traces
        trace_run_ids = tuple(item.agent_run_id for item in traces)
        if state.lineage.agent_run_ids and set(state.lineage.agent_run_ids) != set(
            trace_run_ids
        ):
            raise ResearchEpisodeBuildError(
                "ResearchState and Episode Agent run identities disagree"
            )
        if inputs.sector_usage:
            if state.lineage.sector_context_id is None:
                raise ResearchEpisodeBuildError(
                    "Sector usage requires a State Sector context"
                )
            if any(
                item.sector_context_id != state.lineage.sector_context_id
                for item in inputs.sector_usage
            ):
                raise ResearchEpisodeBuildError(
                    "Sector usage and State context identities disagree"
                )
            known_sector_claims = set(
                _sector_claim_ids(state.macro_state, state.sector_state)
            )
            provided_sector_claims = {
                claim_id
                for item in inputs.sector_usage
                for claim_id in item.provided_sector_claim_ids
            }
            if not provided_sector_claims <= known_sector_claims:
                raise ResearchEpisodeBuildError(
                    "Sector usage references a Claim absent from ResearchState"
                )

        provided = _ordered_unique(
            claim_id for trace in traces for claim_id in trace.provided_claim_ids
        )
        provided = _ordered_unique(
            (
                *provided,
                *(
                    claim_id
                    for usage in inputs.sector_usage
                    for claim_id in usage.provided_sector_claim_ids
                ),
            )
        )
        accepted = _ordered_unique(
            claim_id for trace in traces for claim_id in trace.accepted_claim_ids
        )
        rejected = _ordered_unique(
            claim_id for trace in traces for claim_id in trace.rejected_claim_ids
        )
        by_role: dict[AgentName, tuple[str, ...]] = {
            role: _ordered_unique(
                claim_id
                for trace in traces
                if trace.agent_role is role
                for claim_id in trace.accepted_claim_ids
            )
            for role in AgentName
        }
        final_claims = _ordered_unique(
            (
                *by_role[AgentName.RESEARCH_MANAGER],
                *by_role[AgentName.BULL_MANAGER],
                *by_role[AgentName.BEAR_MANAGER],
                *by_role[AgentName.RISK_MANAGER],
            )
        )
        sector_claims = _sector_claim_ids(state.macro_state, state.sector_state)
        trace_quality = (
            ResearchEpisodeTraceQuality.COMPLETE
            if not inputs.missing_metadata
            and all(
                trace.trace_quality is ResearchEpisodeTraceQuality.COMPLETE
                for trace in traces
            )
            else ResearchEpisodeTraceQuality.PARTIAL
        )
        if trace_quality is ResearchEpisodeTraceQuality.PARTIAL and not (
            inputs.missing_metadata or any(trace.missing_metadata for trace in traces)
        ):
            raise ResearchEpisodeBuildError(
                "partial Episode requires attributable missing metadata"
            )
        missing_metadata = _ordered_unique(
            (
                *inputs.missing_metadata,
                *(item for trace in traces for item in trace.missing_metadata),
            )
        )
        model_versions = tuple(
            ResearchEpisodeVersionReference(
                name=trace.agent_role.value,
                version=trace.model,
            )
            for trace in traces
        )
        prompt_versions = tuple(
            ResearchEpisodeVersionReference(
                name=trace.agent_role.value,
                version=trace.prompt_version,
            )
            for trace in traces
        )
        feature_versions = (
            ResearchEpisodeVersionReference(
                name="research_state",
                version=state.research_state_version,
            ),
            ResearchEpisodeVersionReference(
                name="research_state_feature",
                version=state.feature_version,
            ),
        )
        fingerprint = _fingerprint(inputs)
        return ResearchEpisode(
            episode_id=f"research_episode_{fingerprint[:24]}",
            asset_id=state.asset_id,
            market=state.asset_id.market,
            research_as_of=state.research_as_of,
            research_state_id=state.research_state_id,
            data_snapshot_id=(
                state.lineage.data_snapshot_id or state.lineage.data_bundle_id
            ),
            sector_context_id=state.lineage.sector_context_id,
            memory_context_id=state.lineage.memory_context_id,
            agent_run_ids=trace_run_ids,
            provided_claim_ids=provided,
            accepted_claim_ids=accepted,
            rejected_claim_ids=rejected,
            accepted_claim_count=sum(item.accepted_claim_count for item in traces),
            rejected_claim_count=sum(item.rejected_claim_count for item in traces),
            sector_claim_ids=sector_claims,
            bull_claim_ids=by_role[AgentName.BULL_MANAGER],
            bear_claim_ids=by_role[AgentName.BEAR_MANAGER],
            risk_claim_ids=by_role[AgentName.RISK_MANAGER],
            final_research_claim_ids=final_claims,
            report_id=inputs.report_id,
            model_versions=model_versions,
            prompt_versions=prompt_versions,
            feature_versions=feature_versions,
            agent_traces=traces,
            sector_usage=inputs.sector_usage,
            trace_quality=trace_quality,
            missing_metadata=missing_metadata,
            source_artifact_ids=inputs.source_artifact_ids,
            created_at=inputs.created_at,
            input_fingerprint=fingerprint,
        )


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _sector_claim_ids(*sections: ResearchStateSection) -> tuple[str, ...]:
    return _ordered_unique(
        claim_id
        for section in sections
        for feature in section.features
        for claim_id in feature.source_claim_ids
        if claim_id.startswith("sector:")
    )


def _fingerprint(inputs: ResearchEpisodeBuildInput) -> str:
    payload = inputs.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
