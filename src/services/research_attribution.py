"""Pure Day41 construction of Episode-scoped research context attribution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.memory.contracts import ResearchContextBundle, ResearchContextMemory
from src.models.enums import AgentName, ResearchScopeType
from src.schemas.common import SourceReference
from src.schemas.research_attribution import (
    ClaimLinkStatus,
    ContextClaimLinkStatus,
    MemoryRetrievalCandidate,
    MemoryRetrievalRecord,
    MemoryRetrievalScopeFilters,
    ResearchContextAttribution,
    ResearchContextClaimLink,
    ResearchContextType,
    ResearchEpisodeAttribution,
)
from src.schemas.research_episode import (
    AgentExecutionTrace,
    ResearchEpisode,
    ResearchEpisodeTraceQuality,
)
from src.schemas.sector_context import SectorContextBundle
from src.schemas.sector_research import SectorValidatedClaim
from src.schemas.sector_usage import SectorContextUsageDiagnostic
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind


class ResearchAttributionBuildError(ValueError):
    """Raised when frozen context cannot form truthful attribution."""


@dataclass(frozen=True)
class MemoryContextProvision:
    """One role's exact Day40 Memory bundle and retrieval purpose."""

    agent_role: AgentName
    agent_run_id: str
    retrieval_purpose: str
    context_bundle: ResearchContextBundle


class ResearchAttributionBuilder:
    """Compose Memory and Day36 diagnostics without Agent pipeline changes."""

    def build(
        self,
        *,
        episode: ResearchEpisode,
        memory_contexts: tuple[MemoryContextProvision, ...] = (),
        sector_context: SectorContextBundle | None = None,
        claim_links: tuple[ResearchContextClaimLink, ...] = (),
    ) -> ResearchEpisodeAttribution:
        """Build one immutable context attribution artifact.

        Args:
            episode: Existing frozen Day39 process artifact.
            memory_contexts: Role-specific Memory retrievals actually projected.
            sector_context: Optional frozen Day36 Sector context.
            claim_links: Explicit accepted or rejected context references.

        Returns:
            A deterministic Episode-scoped attribution artifact.

        Raises:
            ResearchAttributionBuildError: If identities, lineage, or PIT disagree.
        """

        traces = {trace.agent_run_id: trace for trace in episode.agent_traces}
        links = self._validate_links(episode, traces, claim_links)
        retrievals: list[MemoryRetrievalRecord] = []
        attributions: list[ResearchContextAttribution] = []

        for provision in memory_contexts:
            trace = self._trace_for(
                traces,
                provision.agent_role,
                provision.agent_run_id,
            )
            bundle = provision.context_bundle
            if bundle.retrieval_metadata.as_of != episode.research_as_of:
                raise ResearchAttributionBuildError(
                    "Memory retrieval cutoff differs from ResearchEpisode"
                )
            retrieval = _memory_retrieval_record(episode, provision, bundle)
            retrievals.append(retrieval)
            for candidate in retrieval.candidates:
                item_links = links.get(
                    (
                        trace.agent_run_id,
                        ResearchContextType.MEMORY,
                        candidate.memory_id,
                    ),
                    (),
                )
                accepted, rejected = _partition_links(item_links)
                if (accepted or rejected) and not candidate.selected:
                    raise ResearchAttributionBuildError(
                        "unselected Memory cannot have a downstream Claim link"
                    )
                if candidate.scope_type is None or candidate.scope_id is None:
                    raise ResearchAttributionBuildError(
                        "Memory candidate has no attributable research Scope"
                    )
                attributions.append(
                    _attribution(
                        episode=episode,
                        trace=trace,
                        context_type=ResearchContextType.MEMORY,
                        context_id=candidate.memory_id,
                        provided=candidate.selected,
                        selected=candidate.selected,
                        used=bool(accepted),
                        accepted=accepted,
                        rejected=rejected,
                        scope_type=candidate.scope_type,
                        scope_id=candidate.scope_id,
                        temporal=TemporalMetadata(
                            source_kind=TemporalSourceKind.MEMORY,
                            event_time=candidate.effective_ts,
                            available_at=candidate.available_at,
                            effective_from=candidate.effective_ts,
                        ),
                        source_references=candidate.source_references,
                        retrieval_id=retrieval.retrieval_id,
                        rank=candidate.rank,
                        retrieval_score=candidate.retrieval_score,
                        retrieval_reason=candidate.retrieval_reason,
                    )
                )

        if sector_context is not None:
            attributions.extend(
                self._sector_attributions(
                    episode=episode,
                    traces=traces,
                    sector_context=sector_context,
                    links=links,
                )
            )
        elif episode.sector_usage:
            raise ResearchAttributionBuildError(
                "Episode Sector diagnostics require their frozen Sector context"
            )

        attribution_keys = {
            (item.agent_run_id, item.context_type, item.context_id)
            for item in attributions
        }
        if not set(links) <= attribution_keys:
            raise ResearchAttributionBuildError(
                "context Claim link references context absent from attribution"
            )

        fingerprint = _fingerprint(
            episode.episode_id,
            episode.research_as_of.isoformat(),
            tuple(retrievals),
            tuple(attributions),
        )
        return ResearchEpisodeAttribution(
            attribution_bundle_id=f"research_attribution_{fingerprint[:24]}",
            episode_id=episode.episode_id,
            research_as_of=episode.research_as_of,
            retrieval_records=tuple(retrievals),
            attributions=tuple(attributions),
            input_fingerprint=fingerprint,
        )

    def _validate_links(
        self,
        episode: ResearchEpisode,
        traces: dict[str, AgentExecutionTrace],
        claim_links: tuple[ResearchContextClaimLink, ...],
    ) -> dict[
        tuple[str, ResearchContextType, str], tuple[ResearchContextClaimLink, ...]
    ]:
        indexed: dict[
            tuple[str, ResearchContextType, str], list[ResearchContextClaimLink]
        ] = {}
        identities: set[tuple[str, ResearchContextType, str, str]] = set()
        for link in claim_links:
            trace = self._trace_for(traces, link.agent_role, link.agent_run_id)
            identity = (
                link.agent_run_id,
                link.context_type,
                link.context_id,
                link.claim_id,
            )
            if identity in identities:
                raise ResearchAttributionBuildError(
                    "context Claim links must be unique"
                )
            identities.add(identity)
            allowed = (
                trace.accepted_claim_ids
                if link.claim_status is ContextClaimLinkStatus.ACCEPTED
                else trace.rejected_claim_ids
            )
            if link.claim_id not in allowed:
                raise ResearchAttributionBuildError(
                    "context link references a Claim outside the Agent trace"
                )
            indexed.setdefault(identity[:3], []).append(link)
        return {key: tuple(value) for key, value in indexed.items()}

    def _sector_attributions(
        self,
        *,
        episode: ResearchEpisode,
        traces: dict[str, AgentExecutionTrace],
        sector_context: SectorContextBundle,
        links: dict[
            tuple[str, ResearchContextType, str],
            tuple[ResearchContextClaimLink, ...],
        ],
    ) -> list[ResearchContextAttribution]:
        if sector_context.context_id != episode.sector_context_id:
            raise ResearchAttributionBuildError(
                "Sector context identity differs from ResearchEpisode"
            )
        if sector_context.research_as_of != episode.research_as_of:
            raise ResearchAttributionBuildError(
                "Sector context cutoff differs from ResearchEpisode"
            )
        claim_index = {
            claim.claim_id: claim
            for claim in sector_context.accepted_claims
            if claim.claim_id is not None
        }
        event_index = {item.event_id: item for item in sector_context.active_events}
        result: list[ResearchContextAttribution] = []
        for usage in episode.sector_usage:
            trace = _trace_for_role(traces, usage.agent_role)
            result.extend(
                self._sector_claim_attributions(
                    episode,
                    trace,
                    usage,
                    sector_context,
                    claim_index,
                    links,
                )
            )
            for event_id in usage.provided_event_ids:
                event = event_index.get(event_id)
                if event is None:
                    raise ResearchAttributionBuildError(
                        "Sector diagnostic references an unknown Radar Event"
                    )
                item_links = links.get(
                    (trace.agent_run_id, ResearchContextType.RADAR_EVENT, event_id),
                    (),
                )
                accepted, rejected = _partition_links(item_links)
                diagnostic_used = event_id in usage.used_event_ids
                link_status = _link_status(episode, diagnostic_used, accepted)
                _validate_diagnostic_link(diagnostic_used, accepted)
                sources = _event_sources(event.supporting_sector_claim_ids, claim_index)
                result.append(
                    _attribution(
                        episode=episode,
                        trace=trace,
                        context_type=ResearchContextType.RADAR_EVENT,
                        context_id=event_id,
                        provided=True,
                        selected=True,
                        used=diagnostic_used,
                        accepted=accepted,
                        rejected=rejected,
                        claim_link_status=link_status,
                        scope_type=ResearchScopeType.SECTOR,
                        scope_id=sector_context.sector_scope_id,
                        temporal=TemporalMetadata(
                            source_kind=TemporalSourceKind.SECTOR_ANOMALY,
                            event_time=event.available_at,
                            available_at=event.available_at,
                        ),
                        source_references=sources,
                    )
                )
        return result

    def _sector_claim_attributions(
        self,
        episode: ResearchEpisode,
        trace: AgentExecutionTrace,
        usage: SectorContextUsageDiagnostic,
        sector_context: SectorContextBundle,
        claim_index: dict[str, SectorValidatedClaim],
        links: dict[
            tuple[str, ResearchContextType, str],
            tuple[ResearchContextClaimLink, ...],
        ],
    ) -> list[ResearchContextAttribution]:
        result: list[ResearchContextAttribution] = []
        for claim_id in usage.provided_sector_claim_ids:
            claim = claim_index.get(claim_id)
            if claim is None:
                raise ResearchAttributionBuildError(
                    "Sector diagnostic references an unknown Sector Claim"
                )
            item_links = links.get(
                (trace.agent_run_id, ResearchContextType.SECTOR_CLAIM, claim_id),
                (),
            )
            accepted, rejected = _partition_links(item_links)
            diagnostic_used = claim_id in usage.used_sector_claim_ids
            link_status = _link_status(episode, diagnostic_used, accepted)
            _validate_diagnostic_link(diagnostic_used, accepted)
            result.append(
                _attribution(
                    episode=episode,
                    trace=trace,
                    context_type=ResearchContextType.SECTOR_CLAIM,
                    context_id=claim_id,
                    provided=True,
                    selected=True,
                    used=diagnostic_used,
                    accepted=accepted,
                    rejected=rejected,
                    claim_link_status=link_status,
                    scope_type=ResearchScopeType.SECTOR,
                    scope_id=sector_context.sector_scope_id,
                    temporal=TemporalMetadata(
                        source_kind=TemporalSourceKind.SECTOR_RESEARCH_CLAIM,
                        available_at=sector_context.research_as_of,
                        as_of=sector_context.research_as_of,
                    ),
                    source_references=claim.source_references,
                )
            )
        return result

    @staticmethod
    def _trace_for(
        traces: dict[str, AgentExecutionTrace],
        role: AgentName,
        run_id: str,
    ) -> AgentExecutionTrace:
        trace = traces.get(run_id)
        if trace is None or trace.agent_role is not role:
            raise ResearchAttributionBuildError(
                "attribution role/run identity is absent from ResearchEpisode"
            )
        return trace


def _memory_retrieval_record(
    episode: ResearchEpisode,
    provision: MemoryContextProvision,
    bundle: ResearchContextBundle,
) -> MemoryRetrievalRecord:
    metadata = bundle.retrieval_metadata
    candidates = metadata.eligible_candidates or _legacy_candidates(bundle)
    retrieval_fingerprint = _fingerprint(
        episode.episode_id,
        provision.agent_run_id,
        metadata.query_id,
        provision.retrieval_purpose,
    )
    return MemoryRetrievalRecord(
        retrieval_id=f"memory_retrieval_{retrieval_fingerprint[:24]}",
        episode_id=episode.episode_id,
        research_as_of=episode.research_as_of,
        agent_role=provision.agent_role,
        agent_run_id=provision.agent_run_id,
        query_text=metadata.query_text,
        retrieval_purpose=provision.retrieval_purpose,
        candidate_memory_ids=tuple(item.memory_id for item in candidates),
        selected_memory_ids=tuple(
            item.memory_id for item in candidates if item.selected
        ),
        candidates=candidates,
        scope_filters=MemoryRetrievalScopeFilters(
            namespace_keys=tuple(metadata.namespace_keys),
            memory_levels=tuple(metadata.requested_levels),
            scope_types=tuple(metadata.scope_types or ()),
            scope_ids=tuple(metadata.scope_ids or ()),
            usage_classes=tuple(item.value for item in metadata.usage_classes or ()),
            episode_ids=tuple(metadata.episode_ids or ()),
            asset_id=None if metadata.asset_id is None else str(metadata.asset_id),
            market=metadata.market.value,
            min_importance_score=metadata.min_importance_score,
        ),
        snapshot_id=metadata.snapshot_id,
        excluded_future_count=metadata.excluded_future_count,
        empty_valid=metadata.empty_valid,
    )


def _legacy_candidates(
    bundle: ResearchContextBundle,
) -> tuple[MemoryRetrievalCandidate, ...]:
    items = [
        item
        for section in type(bundle).model_fields
        if section not in {"schema_version", "retrieval_metadata", "missing_context"}
        for item in getattr(bundle, section)
    ]
    items.sort(
        key=lambda item: (
            -item.retrieval_score,
            -item.importance_score,
            -item.effective_ts.timestamp(),
            item.memory_id,
        )
    )
    return tuple(
        _candidate_from_memory(item, rank) for rank, item in enumerate(items, start=1)
    )


def _candidate_from_memory(
    item: ResearchContextMemory,
    rank: int,
) -> MemoryRetrievalCandidate:
    if item.metadata is not None:
        scope_type = item.metadata.scope_type
        scope_id = item.metadata.scope_id
    elif item.asset_id is not None:
        scope_type = ResearchScopeType.ASSET
        scope_id = f"ASSET:{item.asset_id}"
    else:
        scope_type = ResearchScopeType.GLOBAL
        scope_id = item.namespace_key
    return MemoryRetrievalCandidate(
        memory_id=item.memory_id,
        rank=rank,
        retrieval_score=item.retrieval_score,
        retrieval_reason=item.retrieval_reason,
        selected=True,
        memory_level=item.memory_level,
        scope_type=scope_type,
        scope_id=scope_id,
        effective_ts=item.effective_ts,
        available_at=item.available_at or item.effective_ts,
        source_references=(item.source,),
    )


def _partition_links(
    links: tuple[ResearchContextClaimLink, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    accepted = tuple(
        item.claim_id
        for item in links
        if item.claim_status is ContextClaimLinkStatus.ACCEPTED
    )
    rejected = tuple(
        item.claim_id
        for item in links
        if item.claim_status is ContextClaimLinkStatus.REJECTED
    )
    return accepted, rejected


def _link_status(
    episode: ResearchEpisode,
    diagnostic_used: bool,
    accepted: tuple[str, ...],
) -> ClaimLinkStatus:
    if diagnostic_used and not accepted:
        if episode.trace_quality is ResearchEpisodeTraceQuality.COMPLETE:
            raise ResearchAttributionBuildError(
                "used context requires exact accepted Claim linkage"
            )
        return ClaimLinkStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    return ClaimLinkStatus.COMPLETE


def _validate_diagnostic_link(
    diagnostic_used: bool,
    accepted: tuple[str, ...],
) -> None:
    if accepted and not diagnostic_used:
        raise ResearchAttributionBuildError(
            "accepted context link disagrees with Day36 usage diagnostic"
        )


def _event_sources(
    supporting_claim_ids: tuple[str, ...],
    claim_index: dict[str, SectorValidatedClaim],
) -> tuple[SourceReference, ...]:
    sources: list[SourceReference] = []
    seen: set[str] = set()
    for claim_id in supporting_claim_ids:
        claim = claim_index.get(claim_id)
        if claim is None:
            raise ResearchAttributionBuildError(
                "Radar Event references an unknown supporting Sector Claim"
            )
        for source in claim.source_references:
            identity = json.dumps(
                source.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            if identity not in seen:
                seen.add(identity)
                sources.append(source)
    if not sources:
        raise ResearchAttributionBuildError(
            "Radar Event attribution requires canonical source lineage"
        )
    return tuple(sources)


def _trace_for_role(
    traces: dict[str, AgentExecutionTrace],
    role: AgentName,
) -> AgentExecutionTrace:
    matches = [trace for trace in traces.values() if trace.agent_role is role]
    if len(matches) != 1:
        raise ResearchAttributionBuildError(
            "Sector diagnostic requires exactly one matching Agent trace"
        )
    return matches[0]


def _attribution(
    *,
    episode: ResearchEpisode,
    trace: AgentExecutionTrace,
    context_type: ResearchContextType,
    context_id: str,
    provided: bool,
    selected: bool,
    used: bool,
    accepted: tuple[str, ...],
    rejected: tuple[str, ...],
    scope_type: ResearchScopeType,
    scope_id: str,
    temporal: TemporalMetadata,
    source_references: tuple[SourceReference, ...],
    claim_link_status: ClaimLinkStatus = ClaimLinkStatus.COMPLETE,
    retrieval_id: str | None = None,
    rank: int | None = None,
    retrieval_score: float | None = None,
    retrieval_reason: str | None = None,
) -> ResearchContextAttribution:
    identity = _fingerprint(
        episode.episode_id,
        trace.agent_run_id,
        context_type.value,
        context_id,
    )
    return ResearchContextAttribution(
        attribution_id=f"context_attribution_{identity[:24]}",
        episode_id=episode.episode_id,
        research_as_of=episode.research_as_of,
        agent_role=trace.agent_role,
        agent_run_id=trace.agent_run_id,
        context_type=context_type,
        context_id=context_id,
        provided=provided,
        selected=selected,
        used=used,
        used_by_claim_ids=accepted,
        rejected_by_claim_ids=rejected,
        claim_link_status=claim_link_status,
        rank=rank,
        retrieval_score=retrieval_score,
        retrieval_reason=retrieval_reason,
        scope_type=scope_type,
        scope_id=scope_id,
        retrieval_id=retrieval_id,
        temporal=temporal,
        source_references=source_references,
    )


def _fingerprint(*values: object) -> str:
    payload = [_json_value(value) for value in values]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _json_value(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
