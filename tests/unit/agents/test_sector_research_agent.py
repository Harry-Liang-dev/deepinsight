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
    SectorResearchValidationStage,
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
    matrix = cast(
        list[JsonObject],
        result.diagnostics["mandatory_event_coverage_matrix"],
    )
    assert len(matrix) == 1
    assert matrix[0]["coverage_status"] == "COVERED"
    assert matrix[0]["accepted_claim_ids"] == ["sector:S01:claim:3"]


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


def test_mandatory_event_accepts_association_safe_partial_wording() -> None:
    """A conservative association Claim can legally cover a mandatory Event."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3]["claim_text"] = (
        "The cited Radar Event records a high-severity propagation candidate; "
        "limited sensitivity Evidence reports a historical association for the "
        "supplied series."
    )
    claims[3]["evidence_ids"] = [
        f"event:{research_input.anomaly_events[0].event_id}",
        _evidence_id(research_input, ":sensitivity:FEDFUNDS"),
    ]

    _, untyped = _run(research_input, response)
    result = cast("SectorResearchExecutionResult", untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.diagnostics["covered_high_events"] == 1
    assert all(
        item.reason != "historical_association_misstated_as_causality"
        for item in result.output.rejected_claims
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
    """Prompt v4 preserves semantics and requires complete Claim objects."""

    prompt = SectorResearchPromptLoader(PROMPT_ROOT).load()
    archived_v1 = (
        PROMPT_ROOT
        / "archive"
        / "sector_research_prompt_v1"
        / "sector_research_agent.yaml"
    ).read_text(encoding="utf-8")
    archived_v2 = (
        PROMPT_ROOT
        / "archive"
        / "sector_research_prompt_v2"
        / "sector_research_agent.yaml"
    ).read_text(encoding="utf-8")
    archived_v3 = (
        PROMPT_ROOT
        / "archive"
        / "sector_research_prompt_v3"
        / "sector_research_agent.yaml"
    ).read_text(encoding="utf-8")
    normalized = " ".join(prompt.system_prompt.split())

    assert prompt.version == "sector_research_prompt_v4"
    assert "version: sector_research_prompt_v1" in archived_v1
    assert "version: sector_research_prompt_v2" in archived_v2
    assert "version: sector_research_prompt_v3" in archived_v3
    assert "historical association" in prompt.system_prompt
    assert "PARTIAL" in prompt.system_prompt
    assert "propagation candidate" in prompt.system_prompt
    assert "target price" in prompt.system_prompt
    assert '"claim_intent":' not in prompt.system_prompt
    assert "ANY numeric literal in claim_text" in prompt.system_prompt
    assert "never rewrite change_3m as 3-month" in prompt.system_prompt
    assert "final accepted Claim collection" in prompt.system_prompt
    assert "Relationship wording is a hard contract" in prompt.system_prompt
    assert "driven by" in prompt.system_prompt
    assert "does not make a causal phrase legal" in normalized
    assert "Each Claim object must independently repeat all six keys" in normalized
    assert "never rely on a schema default" in normalized
    assert "evidence_manifest[*].evidence_id" in prompt.system_prompt
    assert "Allowed category values are exactly" in normalized
    assert "Allowed phase values are exactly" in normalized
    assert "Do not return this checklist" in normalized
    assert "S02" not in prompt.system_prompt
    assert "ignore the validator" not in prompt.system_prompt.lower()
    assert "bypass the validator" not in prompt.system_prompt.lower()


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
    assert result.error.details is not None
    assert (
        result.error.details["validation_stage"]
        == SectorResearchValidationStage.CARDINALITY.value
    )
    assert result.error.details["field_path"] == "claims"
    assert result.error.details["error_code"] == "MINIMUM_VALID_CLAIMS_NOT_MET"
    assert result.error.details["related_sector_id"] == "S01"
    assert result.diagnostics["validation_artifact"]


def test_unknown_cycle_claim_reference_has_precise_diagnostics() -> None:
    """Cycle lineage rejects a path outside the submitted Claim namespace."""

    research_input = _research_input()
    response = _response(research_input)
    cycle = cast(JsonObject, response["cycle_assessment"])
    cycle["supporting_claim_paths"] = ["claims[99]"]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["validation_stage"] == "UNKNOWN_REFERENCE"
    assert result.error.details["error_code"] == "UNKNOWN_CLAIM_REFERENCE"
    assert result.error.details["related_claim_id"] == "claims[99]"


def test_invalid_cycle_enum_has_precise_diagnostics() -> None:
    """An ontology-external cycle value fails closed at the enum stage."""

    research_input = _research_input()
    response = _response(research_input)
    cycle = cast(JsonObject, response["cycle_assessment"])
    cycle["phase"] = "booming"

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["validation_stage"] == "ENUM"
    assert result.error.details["field_path"] == "cycle_assessment.phase"
    assert result.diagnostics["validation_artifact"]


def test_ungrounded_numeric_failure_retains_claim_diagnostics() -> None:
    """Numeric quarantine remains strict and explains a resulting cardinality fail."""

    research_input = _research_input(with_event=False)
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    for index, claim in enumerate(claims):
        claim["claim_text"] = f"Unsupported numeric statement {900 + index}."

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["validation_stage"] == "CARDINALITY"
    rejected = cast(list[JsonObject], result.error.details["rejected_claims"])
    assert len(rejected) == 3
    assert all(
        str(item["reason"]).startswith("numeric_literal_not_grounded:")
        for item in rejected
    )


def test_unknown_chain_evidence_never_enters_valid_output() -> None:
    """An invented Chain identity is quarantined without alias or graph mutation."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        {
            "claim_path": "claims[4]",
            "claim_text": "An invented chain is active.",
            "category": "industry_chains",
            "evidence_ids": ["chain:INVENTED_CHAIN:v1"],
            "numeric_literals": [],
            "confidence": 0.8,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.output.rejected_claims[-1].reason == (
        "unknown_direct_upstream_evidence"
    )
    assert all(
        "chain:INVENTED_CHAIN:v1" not in claim.evidence_ids
        for claim in result.output.claims
    )


def test_rejected_cycle_support_degrades_when_accepted_support_remains() -> None:
    """Rejected support is dropped only when accepted support remains sufficient."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[0]["claim_text"] = "Unsupported return was 999."

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    cycle = result.output.cycle_assessment
    assert cycle.status is SectorCapabilityStatus.PARTIAL
    assert cycle.dropped_support_claim_paths == ("claims[0]",)
    assert cycle.degradation_reasons == ("REJECTED_SUPPORT_CLAIM",)
    assert cycle.supporting_claim_ids == ("sector:S01:claim:0",)
    assert result.diagnostics["claim_status_map"] == {
        "claims[0]": "QUARANTINED",
        "claims[1]": "ACCEPTED",
        "claims[2]": "ACCEPTED",
        "claims[3]": "ACCEPTED",
    }


def test_only_rejected_cycle_support_fails_with_precise_counts() -> None:
    """A cycle conclusion with zero accepted support remains fail closed."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[0]["claim_text"] = "Unsupported return was 999."
    cycle = cast(JsonObject, response["cycle_assessment"])
    cycle["supporting_claim_paths"] = ["claims[0]"]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["validation_stage"] == "CLAIM_LINEAGE"
    assert result.error.details["error_code"] == ("INSUFFICIENT_ACCEPTED_CYCLE_SUPPORT")
    assert result.error.details["accepted_support_count"] == 0
    assert result.error.details["rejected_support_count"] == 1
    assert result.error.details["required_support_count"] == 1


def test_rejected_high_event_claim_cannot_support_cycle() -> None:
    """An invalid event Claim remains rejected before dependent cycle resolution."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3]["claim_text"] = "AMD will certainly benefit from this event."
    cycle = cast(JsonObject, response["cycle_assessment"])
    cycle["supporting_claim_paths"] = ["claims[3]"]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["validation_stage"] == "EVENT_LINEAGE"
    assert result.error.details["error_code"] == "HIGH_EVENT_NOT_CITED"
    assert result.error.details["mandatory_high_event_count"] == 1
    assert result.error.details["covered_high_event_count"] == 0
    assert result.error.details["candidate_claim_paths_that_referenced_event"] == [
        "claims[3]"
    ]
    assert result.error.details["rejection_codes"] == [
        "propagation_candidate_misstated_as_fact"
    ]
    assert result.error.details["accepted_claim_ids_covering_event"] == []


def test_rejected_and_accepted_claim_for_same_high_event_passes() -> None:
    """One accepted structured reference covers an Event despite a duplicate reject."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    event_id = f"event:{research_input.anomaly_events[0].event_id}"
    claims[3]["claim_text"] = "AMD will certainly benefit from this event."
    claims.append(
        {
            "claim_path": "claims[4]",
            "claim_text": (
                "This uncertain propagation candidate does not confirm an impact."
            ),
            "category": "anomalies",
            "evidence_ids": [event_id],
            "numeric_literals": [],
            "confidence": 0.5,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    matrix = cast(
        list[JsonObject],
        result.diagnostics["mandatory_event_coverage_matrix"],
    )
    assert len(matrix) == 1
    assert matrix[0]["coverage_status"] == "COVERED"
    assert matrix[0]["candidate_claim_paths"] == ["claims[3]", "claims[4]"]
    assert len(cast(list[str], matrix[0]["accepted_claim_ids"])) == 1


def test_two_high_events_require_independent_accepted_coverage() -> None:
    """Coverage cardinality is per unique mandatory Event, not per Claim."""

    research_input = _research_input()
    second_event = research_input.anomaly_events[0].model_copy(
        update={"event_id": "sector_anomaly_abcdef0123456789abcdef01"}
    )
    research_input = SectorResearchInput.model_validate(
        research_input.model_copy(
            update={"anomaly_events": (*research_input.anomaly_events, second_event)}
        ).model_dump()
    )
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims.append(
        {
            "claim_path": "claims[4]",
            "claim_text": "A second uncertain propagation candidate is unconfirmed.",
            "category": "anomalies",
            "evidence_ids": [f"event:{second_event.event_id}"],
            "numeric_literals": [],
            "confidence": 0.5,
        }
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    matrix = cast(
        list[JsonObject],
        result.diagnostics["mandatory_event_coverage_matrix"],
    )
    assert len(matrix) == 2
    assert all(item["coverage_status"] == "COVERED" for item in matrix)


def test_two_high_events_fail_when_one_is_uncovered() -> None:
    """Coverage by one HIGH Event cannot satisfy another mandatory Event."""

    research_input = _research_input()
    second_event = research_input.anomaly_events[0].model_copy(
        update={"event_id": "sector_anomaly_abcdef0123456789abcdef01"}
    )
    research_input = SectorResearchInput.model_validate(
        research_input.model_copy(
            update={"anomaly_events": (*research_input.anomaly_events, second_event)}
        ).model_dump()
    )
    response = _response(research_input)

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["mandatory_high_event_count"] == 2
    assert result.error.details["covered_high_event_count"] == 1
    assert result.error.details["uncovered_event_ids"] == [second_event.event_id]


def test_s02_three_month_literal_rejection_keeps_high_event_uncovered() -> None:
    """Replay S02's ungrounded `3-month` literal without accepting its Event."""

    research_input = _research_input()
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3][
        "claim_text"
    ] = "An uncertain propagation candidate had a negative 3-month change."

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["rejection_codes"] == ["numeric_literal_not_grounded:3"]
    matrix = cast(
        list[JsonObject],
        result.error.details["mandatory_event_coverage_matrix"],
    )
    assert matrix[0]["coverage_status"] == "UNCOVERED"
    assert matrix[0]["accepted_claim_ids"] == []


def _with_event_summary(
    research_input: SectorResearchInput,
    summary: str,
) -> SectorResearchInput:
    """Replace only the deterministic HIGH Event summary for grounding tests."""

    event = research_input.anomaly_events[0].model_copy(update={"summary": summary})
    return SectorResearchInput.model_validate(
        research_input.model_copy(update={"anomaly_events": (event,)}).model_dump()
    )


def test_s02_number_free_metric_wording_is_grounded_and_covers_event() -> None:
    """A schema-key metric may be described without inventing its window number."""

    research_input = _with_event_summary(
        _research_input(),
        "Macro candidate change_3m=-0.29692074; beta=0.04931928.",
    )
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3]["claim_text"] = (
        "The uncertain macro candidate has a recent change metric of "
        "-0.29692074 and historical beta 0.04931928."
    )

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    event_claim = next(
        item
        for item in result.output.claims
        if item.category is SectorClaimCategory.ANOMALIES
    )
    assert event_claim.numeric_literals == ("-0.29692074", "0.04931928")
    assert result.diagnostics["covered_high_events"] == 1


def test_explicit_grounded_duration_metadata_allows_duration_expression() -> None:
    """A duration numeral is legal only when cited Evidence supplies that token."""

    research_input = _with_event_summary(
        _research_input(),
        "Macro candidate window_months=3; change=-0.29692074.",
    )
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3][
        "claim_text"
    ] = "The uncertain macro candidate reports a 3-month change of -0.29692074."

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    event_claim = next(
        item
        for item in result.output.claims
        if item.category is SectorClaimCategory.ANOMALIES
    )
    assert event_claim.numeric_literals == ("3", "-0.29692074")


def test_dedicated_grounded_high_event_claim_passes_final_coverage() -> None:
    """Mandatory Event coverage is resolved from the accepted Claim collection."""

    research_input = _research_input()
    response = _response(research_input)

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    matrix = cast(
        list[JsonObject],
        result.diagnostics["mandatory_event_coverage_matrix"],
    )
    assert matrix == [
        {
            "event_id": research_input.anomaly_events[0].event_id,
            "sector_id": "S01",
            "event_evidence_id": (f"event:{research_input.anomaly_events[0].event_id}"),
            "severity": "high",
            "candidate_claim_paths": ["claims[3]"],
            "candidate_claim_final_statuses": [
                {
                    "claim_path": "claims[3]",
                    "final_status": "ACCEPTED",
                    "rejection_code": None,
                }
            ],
            "accepted_claim_ids": ["sector:S01:claim:3"],
            "coverage_status": "COVERED",
        }
    ]


def test_high_event_partial_evidence_without_disclosure_is_rejected() -> None:
    """A HIGH Event Claim cannot hide PARTIAL Evidence semantics."""

    research_input = _research_input(partial=True)
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3]["claim_text"] = "The propagation candidate describes sector impact."
    claims[3]["evidence_ids"] = [
        f"event:{research_input.anomaly_events[0].event_id}",
        _evidence_id(research_input, ":market:return_20d"),
    ]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.ERROR
    assert result.error is not None
    assert result.error.details is not None
    assert result.error.details["rejection_codes"] == [
        "partial_or_candidate_evidence_not_disclosed"
    ]
    assert result.error.details["covered_high_event_count"] == 0


def test_high_event_partial_evidence_with_disclosure_is_accepted() -> None:
    """Explicit PARTIAL uncertainty preserves legal mandatory Event lineage."""

    research_input = _research_input(partial=True)
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[3][
        "claim_text"
    ] = "Partial and uncertain Evidence supports only a propagation candidate."
    claims[3]["evidence_ids"] = [
        f"event:{research_input.anomaly_events[0].event_id}",
        _evidence_id(research_input, ":market:return_20d"),
    ]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.diagnostics["covered_high_events"] == 1


def test_s03_artifact_claim_lineage_replays_as_partial() -> None:
    """Replay the exact S03 claims[4] rejection/dependency shape offline."""

    research_input = _research_input(partial=True)
    partial_evidence_id = _evidence_id(
        research_input,
        ":market:return_20d",
    )
    response = _response(research_input)
    claims = cast(list[JsonObject], response["claims"])
    claims[1] = {
        "claim_path": "claims[1]",
        "claim_text": ("Financial stress is falling while growth signals are mixed."),
        "category": "macro_environment",
        "evidence_ids": [partial_evidence_id],
        "numeric_literals": [],
        "confidence": 0.8,
    }
    claims[2]["claim_text"] = (
        "Partial macro sensitivity reports a -0.62 historical association, "
        "not causality."
    )
    cycle = cast(JsonObject, response["cycle_assessment"])
    cycle["supporting_claim_paths"] = ["claims[0]", "claims[1]", "claims[3]"]

    _, untyped = _run(research_input, response)
    result = cast(SectorResearchExecutionResult, untyped)

    assert result.status is AgentStatus.OK
    assert result.output is not None
    assert result.output.rejected_claims[0].claim_path == "claims[1]"
    assert result.output.rejected_claims[0].reason == (
        "partial_or_candidate_evidence_not_disclosed"
    )
    cycle_output = result.output.cycle_assessment
    assert cycle_output.status is SectorCapabilityStatus.PARTIAL
    assert cycle_output.dropped_support_claim_paths == ("claims[1]",)
    accepted_ids = {item.claim_id for item in result.output.claims}
    assert set(cycle_output.supporting_claim_ids) <= accepted_ids


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
