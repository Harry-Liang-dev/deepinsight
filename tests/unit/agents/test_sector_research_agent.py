"""Deterministic unit tests for the Day35 Sector Research Agent."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from src.agents import (
    SectorResearchAgent,
    SectorResearchPromptLoader,
    build_sector_research_evidence,
)
from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import (
    AgentStatus,
    AnomalyDirection,
    EventSeverity,
    MacroCycleDirection,
    Market,
    MarketScope,
    MemoryLevel,
    OntologyStatus,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorCapabilityStatus,
    SectorId,
)
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject
from src.repositories import DuckDBDatabase, LLMCacheRepository
from src.schemas.common import SourceReference
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.schemas.research_data import DataQualityStatus
from src.schemas.sector_research import (
    SectorClaimCategory,
    SectorResearchDraftResponse,
    SectorResearchExecutionResult,
    SectorResearchInput,
)
from src.schemas.sectors import (
    CoveredSectorMetric,
    MacroCycleDimensionState,
    MacroSensitivity,
    MacroSensitivityEstimate,
    MacroSeriesCycleSignal,
    SectorAnomalyEvent,
    SectorBenchmarkMapping,
    SectorBreadthState,
    SectorCycleState,
    SectorFundamentalState,
    SectorMacroSnapshot,
    SectorMarketState,
    SectorResearchCoverage,
    SectorResearchSnapshot,
    SectorUniverseCoverage,
    SectorUniverseSnapshot,
    SectorValuationState,
)
from src.services import FakeLLMProvider, LLMGateway, build_sector_ontology_seed_v1

PROMPT_ROOT = Path("config/prompts")
AS_OF = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)


class FixedGateway:
    """Return one deterministic response and retain the compact prompt payload."""

    def __init__(self, response: JsonObject) -> None:
        self.response = response
        self.payload: JsonObject | None = None

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[DomainModel],
    ) -> JsonObject:
        del model, system_prompt, prompt_version, schema_version
        assert response_model is SectorResearchDraftResponse
        self.payload = input_payload
        return self.response


class RecordingMemory:
    """Record only public Memory writes made after Claim validation."""

    def __init__(self) -> None:
        self.requests: list[MemoryWriteRequest] = []

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Retain one structured Claim write for assertions."""

        self.requests.append(request)
        return MemoryWriteResult(
            memory_id=f"memory-{len(self.requests)}",
            faiss_namespace=request.namespace_key,
            faiss_vector_id=len(self.requests) - 1,
        )

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Fail if Day35 tries an undeclared runtime retrieval."""

        del request
        raise AssertionError("validated ResearchContextBundle is the read boundary")


def _metric(
    value: float | None,
    *,
    status: SectorCapabilityStatus = SectorCapabilityStatus.AVAILABLE,
    count: int = 3,
    universe: int = 3,
) -> CoveredSectorMetric:
    return CoveredSectorMetric(
        value=value,
        coverage_count=0 if status is SectorCapabilityStatus.MISSING else count,
        universe_count=universe,
        status=status,
    )


def _memory() -> ResearchContextBundle:
    missing = [
        MissingContext(
            section=section,
            reason=MissingContextReason.NO_RELEVANT_MEMORY,
            detail="No relevant historical Memory was available.",
            requested_levels=list(MemoryLevel),
        )
        for section in ResearchContextSection
    ]
    return ResearchContextBundle(
        current_snapshot=[],
        macro_events=[],
        asset_events=[],
        prior_research=[],
        prior_risk=[],
        historical_analogs=[],
        regime_context=[],
        retrieval_metadata=RetrievalMetadata(
            query_id="sector-query-v1",
            query_text="S01 Sector research",
            as_of=AS_OF,
            market=Market.US,
            namespace_keys=["SECTOR:SEMICONDUCTORS_AI", "CHAIN:NVIDIA_AI_INFRA"],
            requested_levels=list(MemoryLevel),
            min_importance_score=0.0,
            top_k_per_section=2,
            snapshot_id="memory-empty-v1",
            candidate_count=0,
            eligible_count=0,
            result_count=0,
            excluded_future_count=0,
            excluded_namespace_count=0,
            excluded_asset_count=0,
            excluded_market_count=0,
            excluded_importance_count=0,
            excluded_expired_count=0,
            excluded_current_report_count=0,
            section_counts={section: 0 for section in ResearchContextSection},
            status=RetrievalStatus.EMPTY,
            no_relevant_memory=True,
        ),
        missing_context=missing,
    )


def _research_input(
    *,
    partial: bool = False,
    with_event: bool = True,
) -> SectorResearchInput:
    sector_id = SectorId.SEMICONDUCTORS_AI_COMPUTE
    status = (
        SectorCapabilityStatus.PARTIAL if partial else SectorCapabilityStatus.AVAILABLE
    )
    count = 1 if partial else 3
    universe = 1 if partial else 3
    market_values = {
        name: _metric(0.12, status=status, count=count, universe=universe)
        for name in SectorMarketState.model_fields
    }
    breadth_values = {
        name: _metric(0.8, status=status, count=count, universe=universe)
        for name in SectorBreadthState.model_fields
    }
    fundamental_values = {
        name: _metric(0.2, status=status, count=count, universe=universe)
        for name in SectorFundamentalState.model_fields
    }
    valuation = SectorValuationState(
        median_pe=_metric(31.7, status=status, count=count, universe=universe),
        median_pb=_metric(8.1, status=status, count=count, universe=universe),
    )
    state = SectorResearchSnapshot(
        snapshot_id="sector_research_0123456789abcdef01234567",
        sector_id=sector_id,
        as_of=AS_OF.date(),
        market_state=SectorMarketState(**market_values),
        breadth_state=SectorBreadthState(**breadth_values),
        fundamental_state=SectorFundamentalState(**fundamental_values),
        valuation_state=valuation,
        coverage=SectorResearchCoverage(
            universe_count=universe,
            market_coverage_count=count,
            fundamental_coverage_count=count,
            benchmark_coverage_count=1,
        ),
        source_ids=("alpaca_market_data", "financial_modeling_prep"),
        feature_version="sector_state_features_v1",
        status=status,
    )
    signal = MacroSeriesCycleSignal(
        series_id="FEDFUNDS",
        transformation="monthly_level_change",
        latest_observation_date=date(2026, 8, 1),
        latest_value=5.25,
        change_3m=0.25,
        change_12m=1.0,
        direction=MacroCycleDirection.RISING,
        source_id="fred:FEDFUNDS:2026-08-01",
    )
    dimension = MacroCycleDimensionState(
        direction=MacroCycleDirection.RISING,
        signals=(signal,),
        coverage_count=1,
        expected_count=1,
        status=SectorCapabilityStatus.AVAILABLE,
    )
    cycle = SectorCycleState(
        sector_id=sector_id,
        as_of=AS_OF.date(),
        rates=dimension,
        inflation=dimension.model_copy(
            update={"direction": MacroCycleDirection.FALLING}
        ),
        labor=dimension,
        growth=dimension.model_copy(update={"direction": MacroCycleDirection.FALLING}),
        financial_stress=dimension,
        sector_momentum=_metric(0.12, status=status, count=count, universe=universe),
        source_ids=("fred", state.snapshot_id),
        feature_version="sector_macro_features_v1",
        status=status,
    )
    sensitivity = MacroSensitivity(
        sector_id=sector_id,
        as_of=AS_OF.date(),
        benchmark_id=AssetId("US:SOXX"),
        estimates=(
            MacroSensitivityEstimate(
                series_id="FEDFUNDS",
                transformation="monthly_level_change",
                beta=-0.45,
                correlation=-0.62,
                observation_count=36,
                required_count=24,
                window_months=36,
                source_id="fred:FEDFUNDS",
                status=SectorCapabilityStatus.AVAILABLE,
            ),
        ),
        source_ids=("fred", "alpaca:SOXX"),
        feature_version="sector_macro_features_v1",
        status=status,
    )
    macro = SectorMacroSnapshot(
        snapshot_id="sector_macro_0123456789abcdef01234567",
        sector_id=sector_id,
        as_of=AS_OF.date(),
        cycle_state=cycle,
        macro_sensitivity=sensitivity,
        source_sector_snapshot_id=state.snapshot_id,
        feature_version="sector_macro_features_v1",
        status=status,
    )
    universe_snapshot = SectorUniverseSnapshot(
        snapshot_id="sector_universe_0123456789abcdef01234567",
        sector_id=sector_id,
        as_of=AS_OF.date(),
        asset_ids=(
            (AssetId("US:NVDA"),)
            if partial
            else (
                AssetId("US:AMD"),
                AssetId("US:NVDA"),
                AssetId("US:TSM"),
            )
        ),
        benchmark_ids=(AssetId("US:SOXX"),),
        membership_version="sector_universe_membership_v1",
        source="internal_curated_research_universe",
        coverage=SectorUniverseCoverage(
            membership_count=universe,
            classified_asset_count=universe,
            benchmark_count=1,
            classification_ratio=1.0,
        ),
        quality=DataQualityStatus.PASS,
    )
    mapping = SectorBenchmarkMapping(
        sector_id=sector_id,
        benchmark_ids=(AssetId("US:SOXX"),),
        status=status,
        source="validated_alpaca_benchmark",
        valid_from=date(2026, 1, 1),
        version="us_sector_benchmarks_v1",
    )
    events: tuple[SectorAnomalyEvent, ...] = ()
    if with_event:
        events = (
            SectorAnomalyEvent(
                event_id="sector_anomaly_0123456789abcdef01234567",
                event_type=SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION,
                sector_id=sector_id,
                chain_ids=("NVIDIA_AI_INFRA",),
                source_asset_ids=(AssetId("US:NVDA"),),
                affected_asset_ids=(AssetId("US:AMD"),),
                direction=AnomalyDirection.UNKNOWN,
                severity=EventSeverity.HIGH,
                confidence=0.8,
                event_time=AS_OF - timedelta(hours=3),
                published_at=AS_OF - timedelta(hours=3),
                available_at=AS_OF - timedelta(hours=2),
                ingested_at=AS_OF - timedelta(hours=1),
                as_of=AS_OF,
                source_evidence_ids=("event:nvda",),
                summary="NVIDIA event produced a graph-grounded propagation candidate.",
                propagation_hypothesis=(
                    "Candidate relevance through NVIDIA AI Infrastructure."
                ),
                status=SectorAnomalyStatus.PROPAGATION_CANDIDATE,
            ),
        )
    seed = build_sector_ontology_seed_v1()
    chains = tuple(
        item
        for item in seed.chains
        if item.sector_id is sector_id
        and item.status is OntologyStatus.ACTIVE
        and item.is_effective(AS_OF.date())
    )
    memberships = tuple(
        item
        for item in seed.memberships
        if item.sector_id is sector_id and item.is_effective(AS_OF.date())
    )
    return SectorResearchInput(
        research_as_of=AS_OF,
        sector_id=sector_id,
        sector_name="Semiconductors & AI Compute",
        sector_scope_id="SECTOR:SEMICONDUCTORS_AI",
        chain_scope_ids=("CHAIN:NVIDIA_AI_INFRA",),
        universe_snapshot=universe_snapshot,
        sector_snapshot=state,
        macro_snapshot=macro,
        benchmark_mapping=mapping,
        anomaly_events=events,
        industry_chains=chains,
        memberships=memberships,
        graph_nodes=tuple(
            item for item in seed.nodes if item.is_effective(AS_OF.date())
        ),
        graph_edges=tuple(
            item for item in seed.edges if item.is_effective(AS_OF.date())
        ),
        memory_context=_memory(),
    )


def _evidence_id(
    research_input: SectorResearchInput,
    suffix: str,
) -> str:
    return next(
        item.entry.evidence_id
        for item in build_sector_research_evidence(research_input)
        if item.entry.evidence_id.endswith(suffix)
    )


def _response(research_input: SectorResearchInput) -> JsonObject:
    trend_id = _evidence_id(research_input, ":market:return_20d")
    macro_id = _evidence_id(research_input, ":macro:rates:FEDFUNDS")
    sensitivity_id = _evidence_id(research_input, ":sensitivity:FEDFUNDS")
    claims: list[JsonObject] = [
        {
            "claim_path": "claims[0]",
            "claim_text": (
                "Sector return_20d was 0.12."
                if research_input.sector_snapshot.status
                is not SectorCapabilityStatus.PARTIAL
                else "Partial limited-universe return_20d Evidence reports 0.12."
            ),
            "category": "trend",
            "evidence_ids": [trend_id],
            "numeric_literals": [],
            "confidence": 0.8,
        },
        {
            "claim_path": "claims[1]",
            "claim_text": "Rates were rising while growth was adverse.",
            "category": "macro_environment",
            "evidence_ids": [macro_id],
            "numeric_literals": [],
            "confidence": 0.7,
        },
        {
            "claim_path": "claims[2]",
            "claim_text": (
                "The -0.62 correlation is a historical association, not causality."
            ),
            "category": "macro_sensitivity",
            "evidence_ids": [sensitivity_id],
            "numeric_literals": [],
            "confidence": 0.7,
        },
    ]
    if research_input.anomaly_events:
        claims.append(
            {
                "claim_path": "claims[3]",
                "claim_text": (
                    "The NVIDIA AI Infrastructure propagation candidate remains "
                    "uncertain and does not confirm beneficiary impact."
                ),
                "category": "anomalies",
                "evidence_ids": [f"event:{research_input.anomaly_events[0].event_id}"],
                "numeric_literals": [],
                "confidence": 0.6,
            }
        )
    return cast(
        JsonObject,
        {
            "claims": claims,
            "cycle_assessment": {
                "phase": "uncertain",
                "confidence": 0.5,
                "supporting_claim_paths": ["claims[0]", "claims[1]"],
                "uncertainty": (
                    "Strong Sector state conflicts with adverse Macro context."
                ),
            },
            "uncertainties": ["Historical Memory is unavailable."],
        },
    )


def _run(
    research_input: SectorResearchInput,
    response: JsonObject | None = None,
) -> tuple[FixedGateway, object]:
    gateway = FixedGateway(response or _response(research_input))
    result = SectorResearchAgent(
        gateway,
        SectorResearchPromptLoader(PROMPT_ROOT),
    ).run(
        run_id="sector-run-v1",
        model_name="fake-sector-model",
        research_input=research_input,
    )
    return gateway, result


def test_sector_agent_is_claim_first_and_uses_compact_projection() -> None:
    """Accepted output uses direct Evidence without dumping source snapshots."""

    research_input = _research_input()
    gateway, untyped = _run(research_input)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert len(result.output.claims) == 4
    assert all(
        item.evidence_ids and not item.upstream_claim_ids
        for item in result.output.claims
    )
    assert gateway.payload is not None
    assert "sector_snapshot" not in gateway.payload
    assert "macro_snapshot" not in gateway.payload
    assert "evidence_manifest" in gateway.payload


def test_exact_numeric_hallucination_is_quarantined() -> None:
    """An unsupported number remains rejected while valid Claims survive."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        {
            "claim_path": "claims[4]",
            "claim_text": "Sector return was 99.9.",
            "category": "trend",
            "evidence_ids": [_evidence_id(research_input, ":market:return_20d")],
            "numeric_literals": [],
            "confidence": 0.9,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert (
        result.output.rejected_claims[0].reason == "numeric_literal_not_grounded:99.9"
    )
    assert all("99.9" not in item.claim_text for item in result.output.claims)


def test_macro_correlation_cannot_be_promoted_to_causality() -> None:
    """Citation correctness cannot turn historical association into causality."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[2]["claim_text"] = "The -0.62 correlation causes Sector weakness."

    _, untyped = _run(research_input, response)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.output.rejected_claims[0].reason == (
        "historical_association_misstated_as_causality"
    )


def test_partial_proxy_requires_explicit_degradation() -> None:
    """PARTIAL State and benchmark proxy remain visible in accepted research."""

    research_input = _research_input(partial=True)
    _, untyped = _run(research_input)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert "benchmark_mapping:partial" in result.output.missing_data
    assert "Partial" in result.output.claims[0].claim_text
    assert result.output.uncertainties


def test_propagation_candidate_cannot_become_confirmed_benefit() -> None:
    """Graph-grounded candidate interpretation remains explicitly uncertain."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3]["claim_text"] = "AMD will benefit from this propagation event."

    _, untyped = _run(research_input, response)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert "HIGH Sector Radar event was omitted" in result.error.message


def test_no_radar_event_cannot_create_catalyst() -> None:
    """A fluent output cannot invent a catalyst when Radar produced none."""

    research_input = _research_input(with_event=False)
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        {
            "claim_path": "claims[3]",
            "claim_text": "A catalyst may emerge.",
            "category": "catalysts",
            "evidence_ids": [_evidence_id(research_input, ":market:return_20d")],
            "numeric_literals": [],
            "confidence": 0.4,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert all(
        item.category is not SectorClaimCategory.CATALYSTS
        for item in result.output.claims
    )
    assert result.output.rejected_claims[0].reason == "catalyst_requires_upstream_event"


def test_input_rejects_future_or_misaligned_pit_context() -> None:
    """Day35 composes existing PIT contracts instead of accepting mixed cutoffs."""

    research_input = _research_input()
    event = research_input.anomaly_events[0].model_copy(
        update={"as_of": AS_OF + timedelta(minutes=1)}
    )
    with pytest.raises(ValueError, match="share research_as_of"):
        research_input.model_copy(update={"anomaly_events": (event,)}).model_validate(
            research_input.model_copy(update={"anomaly_events": (event,)}).model_dump()
        )


def test_prompt_is_versioned_and_preserves_research_boundaries() -> None:
    """The central Prompt states numeric, proxy, causality, graph, and trade rules."""

    prompt = SectorResearchPromptLoader(PROMPT_ROOT).load()

    assert prompt.version == "sector_research_prompt_v1"
    assert "historical association" in prompt.system_prompt
    assert "PARTIAL" in prompt.system_prompt
    assert "propagation candidate" in prompt.system_prompt
    assert "target price" in prompt.system_prompt
    assert '"claim_intent":' not in prompt.system_prompt


@pytest.mark.parametrize(
    ("evidence_ids", "reason"),
    [
        ([], "missing_direct_upstream_evidence"),
        (["event:unknown"], "unknown_direct_upstream_evidence"),
    ],
)
def test_invalid_upstream_binding_is_quarantined(
    evidence_ids: list[str],
    reason: str,
) -> None:
    """Claims cannot bypass the invocation-local direct Evidence namespace."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        cast(
            JsonObject,
            {
                "claim_path": "claims[4]",
                "claim_text": "An unsupported upstream statement.",
                "category": "risks",
                "evidence_ids": evidence_ids,
                "numeric_literals": [],
                "confidence": 0.4,
            },
        )
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.output.rejected_claims[-1].reason == reason


def test_prohibited_trading_claim_is_quarantined() -> None:
    """Sector interpretation cannot become a trade, order, or target price."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        {
            "claim_path": "claims[4]",
            "claim_text": "DeepInsight recommends buying the Sector now.",
            "category": "catalysts",
            "evidence_ids": [f"event:{research_input.anomaly_events[0].event_id}"],
            "numeric_literals": [],
            "confidence": 0.9,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.output.rejected_claims[-1].reason == "prohibited_claim_intent"


def test_minimum_valid_claims_remains_fail_closed() -> None:
    """Quarantine cannot turn an evidence-empty response into success."""

    research_input = _research_input(with_event=False)
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    del claims[2]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert "minimum is 3" in result.error.message


def test_llm_cannot_add_canonical_graph_relationship() -> None:
    """The output schema has no graph mutation channel."""

    research_input = _research_input()
    response = _response(research_input)
    response["new_graph_relations"] = ["NVDA causes HBM demand"]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert "new_graph_relations" in result.error.message


def test_only_selected_validated_claims_are_written_to_memory() -> None:
    """Memory receives structured Claim units with lineage, never full prose."""

    research_input = _research_input()
    gateway = FixedGateway(_response(research_input))
    memory = RecordingMemory()
    result = SectorResearchAgent(
        gateway,
        SectorResearchPromptLoader(PROMPT_ROOT),
        memory,
    ).run(
        run_id="sector-memory-run-v1",
        model_name="fake-sector-model",
        research_input=research_input,
    )

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert len(memory.requests) == 2
    assert {item.namespace_key for item in memory.requests} == {
        "SECTOR:SEMICONDUCTORS_AI",
        "CHAIN:NVIDIA_AI_INFRA",
    }
    assert all("source_claim_ids" in item.summary_text for item in memory.requests)
    assert all("source_event_ids" in item.summary_text for item in memory.requests)
    assert all("Sector return_20d" not in item.summary_text for item in memory.requests)


def test_existing_fake_llm_gateway_contract_is_supported(tmp_path: Path) -> None:
    """Day35 reuses the production structured Gateway with an offline Fake."""

    research_input = _research_input()
    database = DuckDBDatabase(tmp_path / "sector-agent.duckdb")
    database.bootstrap()
    provider = FakeLLMProvider(_response(research_input))
    gateway = LLMGateway(LLMCacheRepository(database), provider=provider)

    result = SectorResearchAgent(
        gateway,
        SectorResearchPromptLoader(PROMPT_ROOT),
    ).run(
        run_id="sector-gateway-run-v1",
        model_name="fake-sector-model",
        research_input=research_input,
    )

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.llm_run_metadata is not None
    assert result.llm_run_metadata.provider == "fake"
    assert len(provider.calls) == 1
    assert provider.calls[0].response_schema is not None


def test_sector_and_chain_memory_enters_direct_evidence_projection() -> None:
    """An attributable PIT-safe Memory item is exposed through its exact ID."""

    research_input = _research_input()
    memory_item = ResearchContextMemory(
        memory_id="memory-sector-thesis-v1",
        section=ResearchContextSection.PRIOR_RESEARCH,
        memory_level=MemoryLevel.L3,
        namespace_key="SECTOR:SEMICONDUCTORS_AI",
        market=MarketScope.US,
        memory_type="sector_research_cycle",
        summary_text="Prior validated cycle assessment remained uncertain.",
        effective_ts=AS_OF - timedelta(days=1),
        importance_score=0.8,
        retrieval_score=0.9,
        retrieval_reason="semantic_relevance",
        source=SourceReference(
            document_id="sector:prior:claim:1",
            excerpt_ref="sector:prior:claim:1",
            provider="sector_research_agent:v1",
        ),
        created_by="sector_research_agent_v1",
    )
    metadata = research_input.memory_context.retrieval_metadata.model_copy(
        update={
            "candidate_count": 1,
            "eligible_count": 1,
            "result_count": 1,
            "section_counts": {
                section: (1 if section is ResearchContextSection.PRIOR_RESEARCH else 0)
                for section in ResearchContextSection
            },
            "status": RetrievalStatus.COMPLETE,
            "no_relevant_memory": False,
        }
    )
    context = research_input.memory_context.model_copy(
        update={
            "prior_research": [memory_item],
            "retrieval_metadata": metadata,
            "missing_context": [
                item
                for item in research_input.memory_context.missing_context
                if item.section is not ResearchContextSection.PRIOR_RESEARCH
            ],
        }
    )
    with_memory = SectorResearchInput.model_validate(
        {
            **research_input.model_dump(mode="python"),
            "memory_context": context,
        }
    )

    projected = build_sector_research_evidence(with_memory)

    item = next(
        value
        for value in projected
        if value.entry.evidence_id == "memory-sector-thesis-v1"
    )
    assert item.kind.value == "memory"
    assert item.entry.source.document_id == "sector:prior:claim:1"
