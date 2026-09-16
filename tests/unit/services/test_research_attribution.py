"""Day41 unified Research Context and Retrieval Attribution tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.memory.contracts import (
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import (
    AgentName,
    Market,
    MarketScope,
    MemoryLevel,
    ResearchScopeType,
)
from src.models.identifiers import AssetId
from src.schemas.common import SourceReference
from src.schemas.research_attribution import (
    ClaimLinkStatus,
    ContextClaimLinkStatus,
    MemoryRetrievalCandidate,
    ResearchContextClaimLink,
    ResearchContextType,
)
from src.schemas.research_episode import AgentExecutionTrace, ResearchEpisode
from src.schemas.sector_context import SectorContextBundle
from src.schemas.sector_usage import SectorContextUsageDiagnostic
from src.services.research_attribution import (
    MemoryContextProvision,
    ResearchAttributionBuilder,
)

ROOT = Path(__file__).parents[3]
PHASE3_EPISODE_PATH = (
    ROOT / "data/research_episode/day39/phase3_aapl_golden.research_episode.json"
)
DAY36_EPISODE_PATH = (
    ROOT / "data/research_episode/day39/phase4a_aapl_sector_aware.research_episode.json"
)
DAY36_SECTOR_PATH = (
    ROOT
    / "data/live_sector_research/20260830T135456Z/AAPL.real_qwen_sector_context.json"
)
SOURCE = SourceReference(
    document_id="attribution-fixture",
    excerpt_ref="claim-source",
    provider="deterministic_fixture",
)


def _load_episode(path: Path) -> ResearchEpisode:
    return ResearchEpisode.model_validate(json.loads(path.read_text()))


def _sector_context() -> SectorContextBundle:
    return SectorContextBundle.model_validate(json.loads(DAY36_SECTOR_PATH.read_text()))


def _complete_sector_episode(*, include_used: bool = True) -> ResearchEpisode:
    episode = _load_episode(PHASE3_EPISODE_PATH)
    sector = _sector_context()
    sector_claim_ids = tuple(
        claim.claim_id for claim in sector.accepted_claims if claim.claim_id
    )
    event_ids = tuple(event.event_id for event in sector.active_events)
    research_trace = next(
        item
        for item in episode.agent_traces
        if item.agent_role is AgentName.RESEARCH_MANAGER
    )
    fundamental_trace = next(
        item
        for item in episode.agent_traces
        if item.agent_role is AgentName.FUNDAMENTAL_ANALYST
    )
    usage = (
        SectorContextUsageDiagnostic(
            sector_context_id=sector.context_id,
            agent_role=AgentName.RESEARCH_MANAGER,
            provided_sector_claim_ids=sector_claim_ids[:2],
            used_sector_claim_ids=sector_claim_ids[:1] if include_used else (),
            provided_event_ids=event_ids[:1],
            used_event_ids=event_ids[:1] if include_used else (),
            serialized_context_chars=100,
        ),
        SectorContextUsageDiagnostic(
            sector_context_id=sector.context_id,
            agent_role=AgentName.FUNDAMENTAL_ANALYST,
            provided_sector_claim_ids=sector_claim_ids[1:2],
            serialized_context_chars=50,
        ),
    )
    payload = episode.model_dump(mode="json")
    payload.update(
        research_as_of=sector.research_as_of.isoformat(),
        sector_context_id=sector.context_id,
        provided_claim_ids=list(
            dict.fromkeys((*episode.provided_claim_ids, *sector_claim_ids[:2]))
        ),
        sector_claim_ids=list(sector_claim_ids),
        sector_usage=[item.model_dump(mode="json") for item in usage],
    )
    assert research_trace.accepted_claim_ids
    assert fundamental_trace.rejected_claim_ids
    return ResearchEpisode.model_validate(payload)


def _memory_item(
    memory_id: str,
    *,
    score: float,
    scope_id: str,
) -> ResearchContextMemory:
    return ResearchContextMemory(
        memory_id=memory_id,
        section=ResearchContextSection.PRIOR_RESEARCH,
        memory_level=MemoryLevel.L3,
        namespace_key=scope_id,
        market=MarketScope.GLOBAL,
        memory_type="episode_thesis",
        summary_text=f"Structured {memory_id}",
        effective_ts=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        importance_score=0.8,
        retrieval_score=score,
        retrieval_reason=f"semantic_relevance;scope={scope_id}",
        source=SOURCE,
        created_by="deterministic_fixture",
    )


def _memory_bundle(
    as_of: datetime,
    *,
    items: tuple[ResearchContextMemory, ...] = (),
    future_count: int = 0,
) -> ResearchContextBundle:
    candidates = tuple(
        MemoryRetrievalCandidate(
            memory_id=item.memory_id,
            rank=rank,
            retrieval_score=item.retrieval_score,
            retrieval_reason=item.retrieval_reason,
            selected=True,
            memory_level=item.memory_level,
            scope_type=(
                ResearchScopeType.SECTOR
                if item.namespace_key.startswith("SECTOR:")
                else ResearchScopeType.INDUSTRY_CHAIN
            ),
            scope_id=item.namespace_key,
            effective_ts=item.effective_ts,
            available_at=item.available_at or item.effective_ts,
            source_references=(item.source,),
        )
        for rank, item in enumerate(items, start=1)
    )
    status = RetrievalStatus.EMPTY if not items else RetrievalStatus.PARTIAL
    return ResearchContextBundle(
        current_snapshot=[],
        macro_events=[],
        asset_events=[],
        prior_research=list(items),
        prior_risk=[],
        historical_analogs=[],
        regime_context=[],
        retrieval_metadata=RetrievalMetadata(
            query_id="query-attribution",
            query_text="retrieve prior structured research",
            as_of=as_of,
            market=Market.US,
            asset_id=AssetId("US:AAPL"),
            namespace_keys=["SECTOR:S03", "CHAIN:APPLE_CHAIN"],
            requested_levels=[MemoryLevel.L3],
            scope_ids=["SECTOR:S03", "CHAIN:APPLE_CHAIN"],
            min_importance_score=0,
            top_k_per_section=4,
            snapshot_id="snapshot-attribution",
            candidate_count=len(items) + future_count,
            eligible_count=len(items),
            result_count=len(items),
            excluded_future_count=future_count,
            excluded_namespace_count=0,
            excluded_asset_count=0,
            excluded_market_count=0,
            excluded_importance_count=0,
            excluded_expired_count=0,
            excluded_current_report_count=0,
            eligible_candidates=candidates,
            section_counts={
                section: (
                    len(items)
                    if section is ResearchContextSection.PRIOR_RESEARCH
                    else 0
                )
                for section in ResearchContextSection
            },
            status=status,
            no_relevant_memory=not items,
            empty_valid=not items,
        ),
        missing_context=[],
    )


def _role_trace(
    episode: ResearchEpisode,
    role: AgentName,
) -> AgentExecutionTrace:
    return next(item for item in episode.agent_traces if item.agent_role is role)


def test_memory_provided_used_and_relevance_ordering_across_scopes() -> None:
    """Selected Memory preserves rank/score and links only accepted Claims."""

    episode = _load_episode(PHASE3_EPISODE_PATH)
    trace = _role_trace(episode, AgentName.RISK_MANAGER)
    items = (
        _memory_item("mem-sector", score=0.95, scope_id="SECTOR:S03"),
        _memory_item("mem-chain", score=0.75, scope_id="CHAIN:APPLE_CHAIN"),
    )
    bundle = ResearchAttributionBuilder().build(
        episode=episode,
        memory_contexts=(
            MemoryContextProvision(
                agent_role=trace.agent_role,
                agent_run_id=trace.agent_run_id,
                retrieval_purpose="risk history",
                context_bundle=_memory_bundle(episode.research_as_of, items=items),
            ),
        ),
        claim_links=(
            ResearchContextClaimLink(
                agent_role=trace.agent_role,
                agent_run_id=trace.agent_run_id,
                context_type=ResearchContextType.MEMORY,
                context_id="mem-sector",
                claim_id=trace.accepted_claim_ids[0],
                claim_status=ContextClaimLinkStatus.ACCEPTED,
            ),
        ),
    )

    record = bundle.retrieval_records[0]
    assert record.candidate_memory_ids == ("mem-sector", "mem-chain")
    assert record.selected_memory_ids == ("mem-sector", "mem-chain")
    assert [item.rank for item in record.candidates] == [1, 2]
    assert [item.retrieval_score for item in record.candidates] == [0.95, 0.75]
    by_id = {item.context_id: item for item in bundle.attributions}
    assert by_id["mem-sector"].used is True
    assert by_id["mem-sector"].used_by_claim_ids == (trace.accepted_claim_ids[0],)
    assert by_id["mem-chain"].provided is True
    assert by_id["mem-chain"].selected is True
    assert by_id["mem-chain"].used is False
    assert {item.scope_id for item in bundle.attributions} == {
        "SECTOR:S03",
        "CHAIN:APPLE_CHAIN",
    }


def test_sector_claim_and_radar_event_adapt_day36_diagnostic() -> None:
    """Day36 usage maps into one contract with exact accepted Claim linkage."""

    episode = _complete_sector_episode()
    trace = _role_trace(episode, AgentName.RESEARCH_MANAGER)
    usage = next(
        item
        for item in episode.sector_usage
        if item.agent_role is AgentName.RESEARCH_MANAGER
    )
    sector_claim = usage.used_sector_claim_ids[0]
    event_id = usage.used_event_ids[0]
    accepted_claim = trace.accepted_claim_ids[0]
    links = tuple(
        ResearchContextClaimLink(
            agent_role=trace.agent_role,
            agent_run_id=trace.agent_run_id,
            context_type=context_type,
            context_id=context_id,
            claim_id=accepted_claim,
            claim_status=ContextClaimLinkStatus.ACCEPTED,
        )
        for context_type, context_id in (
            (ResearchContextType.SECTOR_CLAIM, sector_claim),
            (ResearchContextType.RADAR_EVENT, event_id),
        )
    )

    bundle = ResearchAttributionBuilder().build(
        episode=episode,
        sector_context=_sector_context(),
        claim_links=links,
    )

    used = {
        (item.context_type, item.context_id): item
        for item in bundle.attributions
        if item.used
    }
    assert used[(ResearchContextType.SECTOR_CLAIM, sector_claim)].used_by_claim_ids == (
        accepted_claim,
    )
    assert used[(ResearchContextType.RADAR_EVENT, event_id)].used_by_claim_ids == (
        accepted_claim,
    )
    assert all(item.source_references for item in bundle.attributions)


def test_provided_but_rejected_downstream_is_not_used() -> None:
    """A rejected Claim reference is retained but never counted as usage."""

    episode = _complete_sector_episode(include_used=False)
    trace = _role_trace(episode, AgentName.FUNDAMENTAL_ANALYST)
    usage = next(
        item
        for item in episode.sector_usage
        if item.agent_role is AgentName.FUNDAMENTAL_ANALYST
    )
    claim_id = usage.provided_sector_claim_ids[0]
    rejected_id = trace.rejected_claim_ids[0]
    bundle = ResearchAttributionBuilder().build(
        episode=episode,
        sector_context=_sector_context(),
        claim_links=(
            ResearchContextClaimLink(
                agent_role=trace.agent_role,
                agent_run_id=trace.agent_run_id,
                context_type=ResearchContextType.SECTOR_CLAIM,
                context_id=claim_id,
                claim_id=rejected_id,
                claim_status=ContextClaimLinkStatus.REJECTED,
            ),
        ),
    )
    item = next(
        item for item in bundle.attributions if item.agent_run_id == trace.agent_run_id
    )
    assert item.provided is True
    assert item.selected is True
    assert item.used is False
    assert item.used_by_claim_ids == ()
    assert item.rejected_by_claim_ids == (rejected_id,)


def test_empty_valid_retrieval_is_never_omitted() -> None:
    """An empty Memory result still creates one explicit RetrievalRecord."""

    episode = _load_episode(PHASE3_EPISODE_PATH)
    trace = _role_trace(episode, AgentName.RESEARCH_MANAGER)
    result = ResearchAttributionBuilder().build(
        episode=episode,
        memory_contexts=(
            MemoryContextProvision(
                agent_role=trace.agent_role,
                agent_run_id=trace.agent_run_id,
                retrieval_purpose="prior research",
                context_bundle=_memory_bundle(episode.research_as_of),
            ),
        ),
    )
    assert len(result.retrieval_records) == 1
    assert result.retrieval_records[0].empty_valid is True
    assert result.retrieval_records[0].candidate_memory_ids == ()
    assert result.attributions == ()


def test_future_memory_candidate_is_rejected_by_unified_temporal_contract() -> None:
    """A future Memory candidate cannot enter a Day41 RetrievalRecord."""

    episode = _load_episode(PHASE3_EPISODE_PATH)
    trace = _role_trace(episode, AgentName.RESEARCH_MANAGER)
    item = _memory_item("mem-future", score=1.0, scope_id="SECTOR:S03")
    future = item.model_copy(
        update={"available_at": episode.research_as_of + timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError, match="future_available"):
        ResearchAttributionBuilder().build(
            episode=episode,
            memory_contexts=(
                MemoryContextProvision(
                    agent_role=trace.agent_role,
                    agent_run_id=trace.agent_run_id,
                    retrieval_purpose="future safety",
                    context_bundle=_memory_bundle(
                        episode.research_as_of,
                        items=(future,),
                    ),
                ),
            ),
        )


def test_future_radar_event_is_rejected_before_attribution() -> None:
    """The reused Day37 contract rejects future Radar Event availability."""

    sector = _sector_context()
    future_event = sector.active_events[0].model_copy(
        update={"available_at": sector.research_as_of + timedelta(seconds=1)}
    )
    payload = sector.model_dump()
    payload["active_events"] = (future_event, *sector.active_events[1:])
    with pytest.raises(ValidationError, match="future_available"):
        SectorContextBundle.model_validate(payload)


def test_old_phase3_path_without_sector_context_remains_valid() -> None:
    """A pre-Sector Episode can carry explicit empty Memory attribution."""

    episode = _load_episode(PHASE3_EPISODE_PATH)
    trace = _role_trace(episode, AgentName.FUNDAMENTAL_ANALYST)
    result = ResearchAttributionBuilder().build(
        episode=episode,
        memory_contexts=(
            MemoryContextProvision(
                agent_role=trace.agent_role,
                agent_run_id=trace.agent_run_id,
                retrieval_purpose="legacy Memory",
                context_bundle=_memory_bundle(episode.research_as_of),
            ),
        ),
    )
    assert result.retrieval_records[0].empty_valid is True
    assert not any(
        item.context_type is not ResearchContextType.MEMORY
        for item in result.attributions
    )


def test_real_day36_episode_preserves_usage_without_fabricated_claim_ids() -> None:
    """Historical AAPL usage survives while missing Claim linkage stays explicit."""

    episode = _load_episode(DAY36_EPISODE_PATH)
    result = ResearchAttributionBuilder().build(
        episode=episode,
        sector_context=_sector_context(),
    )

    assert result.retrieval_records == ()
    assert episode.memory_context_id is None
    used = [item for item in result.attributions if item.used]
    assert any(item.context_type is ResearchContextType.SECTOR_CLAIM for item in used)
    assert any(item.context_type is ResearchContextType.RADAR_EVENT for item in used)
    assert all(
        item.claim_link_status is ClaimLinkStatus.NOT_AVAILABLE_AT_SOURCE_RUN
        for item in used
    )
    assert all(item.used_by_claim_ids == () for item in used)
    assert all(item.research_as_of == episode.research_as_of for item in used)
