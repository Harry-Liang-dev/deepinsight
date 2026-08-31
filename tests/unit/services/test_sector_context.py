"""Day36 Sector-to-asset context routing and projection tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agents import SectorResearchAgent, SectorResearchPromptLoader
from src.agents.base import _llm_input_payload
from src.agents.contracts import AgentExecutionResult, ResearchTaskRequest
from src.agents.coordinator import _sector_context_usage
from src.agents.input_contracts import (
    AgentInputProjector,
    ResearchManagerInputV1,
)
from src.memory.contracts import ResearchContextBundle
from src.models.enums import (
    AgentName,
    AgentStatus,
    ReportMarketScope,
    SectorCapabilityStatus,
)
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.schemas.agents import AgentContext
from src.schemas.research_data import DataCapability, ResearchDataBundle
from src.schemas.sector_context import (
    SectorContextBundle,
    SectorContextResolution,
)
from src.schemas.sector_research import SectorResearchInput
from src.services.sector_context import SectorContextBuilder, SectorContextProjector
from tests.unit.agents.test_input_contracts import (
    _analyst_outputs,
    _data_bundle,
    _memory_bundle,
)
from tests.unit.agents.test_sector_research_agent import (
    AS_OF,
    FixedGateway,
    _research_input,
    _response,
)

PROMPTS = Path("config/prompts")


def _resolved(
    *, partial: bool = False, with_event: bool = True
) -> tuple[SectorResearchInput, SectorContextResolution]:
    research_input = _research_input(partial=partial, with_event=with_event)
    result = SectorResearchAgent(
        FixedGateway(_response(research_input)),
        SectorResearchPromptLoader(PROMPTS),
    ).run(
        run_id="sector-context-fixture",
        model_name="fixed-sector-model",
        research_input=research_input,
    )
    assert result.status is AgentStatus.OK
    assert result.output is not None
    membership = next(
        item
        for item in research_input.memberships
        if item.asset_id == AssetId("US:NVDA")
    )
    resolution = SectorContextBuilder.build(
        asset_id=membership.asset_id,
        research_as_of=AS_OF,
        sector_name=research_input.sector_name,
        memberships=(membership,),
        sector_output=result.output,
        sector_snapshot=research_input.sector_snapshot,
        macro_snapshot=research_input.macro_snapshot,
        anomaly_events=research_input.anomaly_events,
        industry_chains=research_input.industry_chains,
    )
    assert resolution.bundle is not None
    return research_input, resolution


def _aapl_bundle() -> SectorContextBundle:
    research_input, resolution = _resolved()
    output = resolution.bundle
    assert output is not None
    membership = research_input.memberships[0].model_copy(
        update={"asset_id": AssetId("US:AAPL")}
    )
    rebuilt = SectorContextBuilder.build(
        asset_id=AssetId("US:AAPL"),
        research_as_of=AS_OF,
        sector_name=research_input.sector_name,
        memberships=(membership,),
        sector_output=SectorResearchAgent(
            FixedGateway(_response(research_input)),
            SectorResearchPromptLoader(PROMPTS),
        )
        .run(
            run_id="aapl-sector-fixture",
            model_name="fixed",
            research_input=research_input,
        )
        .output,
        sector_snapshot=research_input.sector_snapshot,
        macro_snapshot=research_input.macro_snapshot,
        anomaly_events=research_input.anomaly_events,
        industry_chains=research_input.industry_chains,
    )
    assert rebuilt.bundle is not None
    return rebuilt.bundle


def _aligned_asset_bundles() -> tuple[ResearchDataBundle, ResearchContextBundle]:
    raw_data = _data_bundle().model_dump(mode="json")
    raw_data["as_of"] = AS_OF.isoformat()
    raw_data["window_end"] = AS_OF.date().isoformat()
    for capability in DataCapability:
        section = raw_data[capability.value]
        assert isinstance(section, dict)
        section["as_of"] = AS_OF.isoformat()
        freshness = section["freshness"]
        assert isinstance(freshness, dict)
        freshness["evaluated_at"] = AS_OF.isoformat()
    data = ResearchDataBundle.model_validate(raw_data)
    raw_memory = _memory_bundle().model_dump(mode="json")
    metadata = raw_memory["retrieval_metadata"]
    assert isinstance(metadata, dict)
    metadata["as_of"] = AS_OF.isoformat()
    return data, ResearchContextBundle.model_validate(raw_memory)


def test_asset_resolves_to_sector_and_chain_point_in_time() -> None:
    """NVDA should resolve through effective membership, never ticker guessing."""

    _, resolution = _resolved()
    bundle = resolution.bundle
    assert bundle is not None
    assert bundle.asset_id == AssetId("US:NVDA")
    assert bundle.sector_id.value == "S01"
    assert bundle.active_chain_ids == ("NVIDIA_AI_INFRA",)
    assert resolution.status is SectorCapabilityStatus.PARTIAL
    assert bundle.coverage.seed_only_membership is True


def test_no_membership_and_sector_agent_failure_degrade_explicitly() -> None:
    """Missing routing or Sector output must preserve the Phase 3 fallback."""

    research_input = _research_input()
    missing = SectorContextBuilder.build(
        asset_id=AssetId("US:UNKNOWN"),
        research_as_of=AS_OF,
        sector_name=research_input.sector_name,
        memberships=research_input.memberships,
        sector_output=None,
        sector_snapshot=research_input.sector_snapshot,
        macro_snapshot=research_input.macro_snapshot,
    )
    assert missing.status is SectorCapabilityStatus.MISSING
    assert missing.bundle is None

    failed_agent = SectorContextBuilder.build(
        asset_id=AssetId("US:NVDA"),
        research_as_of=AS_OF,
        sector_name=research_input.sector_name,
        memberships=research_input.memberships,
        sector_output=None,
        sector_snapshot=research_input.sector_snapshot,
        macro_snapshot=research_input.macro_snapshot,
    )
    assert failed_agent.status is SectorCapabilityStatus.MISSING
    assert "Agent" in (failed_agent.reason or "")


def test_no_chain_is_empty_valid_without_fabrication() -> None:
    """An effective Sector membership need not invent an Industry Chain."""

    research_input, resolution = _resolved(with_event=False)
    bundle = resolution.bundle
    assert bundle is not None
    membership = research_input.memberships[0].model_copy(
        update={"asset_id": AssetId("US:NVDA"), "chain_ids": ()}
    )
    no_chain = SectorContextBuilder.build(
        asset_id=AssetId("US:NVDA"),
        research_as_of=AS_OF,
        sector_name=research_input.sector_name,
        memberships=(membership,),
        sector_output=SectorResearchAgent(
            FixedGateway(_response(research_input)),
            SectorResearchPromptLoader(PROMPTS),
        )
        .run(
            run_id="no-chain",
            model_name="fixed",
            research_input=research_input,
        )
        .output,
        sector_snapshot=research_input.sector_snapshot,
        macro_snapshot=research_input.macro_snapshot,
        anomaly_events=(),
        industry_chains=research_input.industry_chains,
    )
    assert no_chain.bundle is not None
    assert no_chain.bundle.active_chain_ids == ()


def test_role_specific_projection_is_least_privilege() -> None:
    """Roles should receive different Claim categories and event detail."""

    _, resolution = _resolved()
    bundle = resolution.bundle
    assert bundle is not None
    fundamental = SectorContextProjector.for_role(bundle, AgentName.FUNDAMENTAL_ANALYST)
    technical = SectorContextProjector.for_role(
        bundle, AgentName.TECHNICAL_TEXT_ANALYST
    )
    news = SectorContextProjector.for_role(bundle, AgentName.NEWS_EVENT_ANALYST)
    manager = SectorContextProjector.for_role(bundle, AgentName.RESEARCH_MANAGER)

    assert fundamental.context_claims
    assert not fundamental.validated_claims
    assert {item.category.value for item in technical.context_claims} <= {
        "trend",
        "breadth",
        "leaders_laggards",
        "cycle",
        "anomalies",
    }
    assert news.event_references
    assert not technical.event_references
    assert manager.validated_claims
    assert not manager.context_claims


def test_sector_claim_is_manager_upstream_not_regrounded_raw_evidence() -> None:
    """Manager projections should preserve direct Claim-to-Evidence lineage."""

    _, resolution = _resolved()
    bundle = resolution.bundle
    assert bundle is not None
    manager = SectorContextProjector.for_role(bundle, AgentName.RESEARCH_MANAGER)
    assert manager.validated_claims
    assert all(item.evidence_ids for item in manager.validated_claims)
    assert all(not item.upstream_claim_ids for item in manager.validated_claims)
    assert all(item.source_references for item in manager.validated_claims)


def test_radar_event_propagates_only_through_accepted_sector_claim() -> None:
    """Event references must name the accepted Sector Claim carrying lineage."""

    _, resolution = _resolved()
    bundle = resolution.bundle
    assert bundle is not None
    assert len(bundle.active_events) == 1
    event = bundle.active_events[0]
    assert event.supporting_sector_claim_ids
    assert set(event.supporting_sector_claim_ids) <= {
        item.claim_id for item in bundle.accepted_claims
    }


def test_partial_sector_state_preserves_quality_and_uncertainty() -> None:
    """Proxy or limited state must remain partial at every projection."""

    _, resolution = _resolved(partial=True)
    assert resolution.status is SectorCapabilityStatus.PARTIAL
    bundle = resolution.bundle
    assert bundle is not None
    assert bundle.uncertainties
    risk = SectorContextProjector.for_role(bundle, AgentName.RISK_MANAGER)
    assert risk.quality is SectorCapabilityStatus.PARTIAL
    assert risk.uncertainties


def test_future_context_and_event_cannot_enter_asset_research() -> None:
    """PIT alignment rejects future Sector output and excludes future events."""

    research_input, resolution = _resolved()
    bundle = resolution.bundle
    assert bundle is not None
    with pytest.raises(ValueError, match="cutoff"):
        SectorContextBuilder.build(
            asset_id=AssetId("US:NVDA"),
            research_as_of=AS_OF - timedelta(days=1),
            sector_name=research_input.sector_name,
            memberships=research_input.memberships,
            sector_output=SectorResearchAgent(
                FixedGateway(_response(research_input)),
                SectorResearchPromptLoader(PROMPTS),
            )
            .run(
                run_id="future-output",
                model_name="fixed",
                research_input=research_input,
            )
            .output,
            sector_snapshot=research_input.sector_snapshot,
            macro_snapshot=research_input.macro_snapshot,
        )
    dumped = bundle.model_dump(mode="json")
    dumped["active_events"][0]["available_at"] = (
        AS_OF + timedelta(seconds=1)
    ).isoformat()
    with pytest.raises(ValidationError, match="future Sector event"):
        SectorContextBundle.model_validate(dumped)


def test_eight_agent_contract_receives_role_projection_and_manager_claims() -> None:
    """Existing inputs should carry Sector context without changing Claim schemas."""

    bundle = _aapl_bundle()
    data, memory = _aligned_asset_bundles()
    analyst = AgentInputProjector.analyst(
        data,
        memory,
        AgentName.TECHNICAL_TEXT_ANALYST,
        bundle,
    )
    assert analyst.sector_context is not None
    assert analyst.sector_context.context_claims
    assert not analyst.sector_context.validated_claims

    manager_context = AgentInputProjector.manager_context(
        data,
        memory,
        AgentName.RESEARCH_MANAGER,
        _analyst_outputs(),
        bundle,
    )
    manager = ResearchManagerInputV1(context=manager_context)
    projected = _llm_input_payload(
        {
            "input_context": {},
            "research_contract": manager.model_dump(mode="json"),
        }
    )
    contract = projected["research_contract"]
    assert isinstance(contract, dict)
    upstream = contract["validated_upstream_claims"]
    assert isinstance(upstream, list)
    sector_ids = {item.claim_id for item in bundle.accepted_claims}
    assert sector_ids <= {
        item["claim_id"] for item in upstream if isinstance(item, dict)
    }
    research_context = contract["research_context"]
    assert isinstance(research_context, dict)
    sector_context = research_context["sector_context"]
    assert isinstance(sector_context, dict)
    assert "validated_claims" not in sector_context


def test_usage_diagnostics_follow_recursive_sector_provenance() -> None:
    """Manager use should map back to the Sector Claim and its Radar event."""

    bundle = _aapl_bundle()
    event_claim = next(
        claim
        for claim in bundle.accepted_claims
        if any(item.startswith("event:") for item in claim.evidence_ids)
    )
    assert event_claim.claim_id is not None
    manager_claim: JsonObject = {
        "claim_id": "research:sector-event",
        "claim_path": "analysis.summary_points[0]",
        "claim_text": "Sector event relevance remains conditional.",
        "upstream_claim_ids": [event_claim.claim_id],
    }
    manager_result = AgentExecutionResult(
        run_id="usage-research-manager",
        agent_name=AgentName.RESEARCH_MANAGER,
        status=AgentStatus.OK,
        output={
            "analysis": {
                "summary_points": ["Sector event relevance remains conditional."],
                "claim_evidence": [manager_claim],
            }
        },
    )
    data, memory = _aligned_asset_bundles()
    request = ResearchTaskRequest(
        task_id="sector-usage",
        model_name="fixed",
        input_context=AgentContext(
            report_date=data.window_end,
            market_scope=ReportMarketScope.US,
            asset_id=data.asset_id,
            structured_features={},
        ),
        data_bundle=data,
        context_bundle=memory,
        sector_context_bundle=bundle,
    )
    diagnostics = _sector_context_usage(
        request,
        {AgentName.RESEARCH_MANAGER: manager_result},
    )
    manager_usage = next(
        item for item in diagnostics if item.agent_role is AgentName.RESEARCH_MANAGER
    )
    assert event_claim.claim_id in manager_usage.used_sector_claim_ids
    assert manager_usage.used_event_ids == tuple(
        item.event_id for item in bundle.active_events
    )
