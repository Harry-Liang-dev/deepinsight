"""ResearchStateSnapshot v1 contract and pure-builder tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.models.enums import AgentName, ClaimIntent
from src.models.identifiers import AssetId
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.common import SourceReference
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_state import (
    NormalizedResearchFeatureInput,
    ResearchStateBuildInput,
    ResearchStateClaimInput,
    ResearchStateFeature,
    ResearchStateFeatureType,
    ResearchStateMemoryContextInput,
    ResearchStateSectionName,
    ResearchStateSectionStatus,
    ResearchStateSectorContextInput,
)
from src.services.research_state import ResearchStateBuilder, ResearchStateBuildError
from tests.unit.agents.test_input_contracts import AS_OF, _data_bundle
from tests.unit.services.test_sector_context import _aapl_bundle, _aligned_asset_bundles


def _analyst_claim() -> ClaimEvidenceBinding:
    return ClaimEvidenceBinding(
        claim_id="fundamental:claim:0",
        claim_path="analysis.facts[0]",
        claim_text="Attributable fixture fact.",
        evidence_ids=("ev_000000000000000000000005",),
        source_references=(
            SourceReference(
                document_id="fixture-fundamental",
                excerpt_ref="ev_000000000000000000000005",
                provider="fixture_provider",
            ),
        ),
        claim_intent=ClaimIntent.FACT,
    )


def _manager_claim() -> ClaimEvidenceBinding:
    return ClaimEvidenceBinding(
        claim_id="research:claim:0",
        claim_path="analysis.summary_points[0]",
        claim_text="The attributable fixture supports a cautious thesis.",
        upstream_claim_ids=("fundamental:claim:0",),
        source_references=(
            SourceReference(
                document_id="fixture-fundamental",
                excerpt_ref="ev_000000000000000000000005",
                provider="fixture_provider",
            ),
        ),
        claim_intent=ClaimIntent.ANALYTICAL_INFERENCE,
    )


def _claim_inputs() -> tuple[ResearchStateClaimInput, ...]:
    return (
        ResearchStateClaimInput(
            agent_role=AgentName.FUNDAMENTAL_ANALYST,
            agent_run_id="run:fundamental",
            claim=_analyst_claim(),
        ),
        ResearchStateClaimInput(
            agent_role=AgentName.RESEARCH_MANAGER,
            agent_run_id="run:research",
            claim=_manager_claim(),
        ),
    )


def _sector_input() -> ResearchStateSectorContextInput:
    context = _aapl_bundle()
    return ResearchStateSectorContextInput(
        context_id=context.context_id,
        asset_id=context.asset_id,
        sector_id=context.sector_id.value,
        sector_scope_id=context.sector_scope_id,
        research_as_of=context.research_as_of,
        active_chain_ids=context.active_chain_ids,
        cycle_phase=context.cycle_assessment.phase.value,
        cycle_confidence=context.cycle_assessment.confidence,
        cycle_supporting_claim_ids=context.cycle_assessment.supporting_claim_ids,
        accepted_claims=context.accepted_claims,
        macro_claim_ids=tuple(
            claim.claim_id
            for claim in context.accepted_claims
            if claim.claim_id is not None
            and claim.category.value in {"macro_environment", "macro_sensitivity"}
        ),
        sector_snapshot_id=context.sector_snapshot_id,
        macro_snapshot_id=context.macro_snapshot_id,
        context_version=context.sector_context_version,
    )


def test_builder_is_deterministic_immutable_and_does_not_accept_report_prose() -> None:
    """Frozen structured inputs yield a stable State with no report input channel."""

    inputs = ResearchStateBuildInput(
        research_data_bundle=_data_bundle(),
        accepted_claims=_claim_inputs(),
        source_run_id="phase3-fixture",
    )

    first = ResearchStateBuilder().build(inputs)
    second = ResearchStateBuilder().build(inputs)

    assert first == second
    assert first.research_state_id == second.research_state_id
    assert "report" not in ResearchStateBuildInput.model_fields
    assert first.lineage.agent_run_ids == ("run:fundamental", "run:research")
    with pytest.raises(ValidationError, match="frozen"):
        first.asset_id = AssetId("US:NVDA")


def test_phase3_source_without_sector_is_explicitly_not_backfilled() -> None:
    """A pre-Sector source run remains historical rather than using newer context."""

    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            accepted_claims=_claim_inputs(),
            source_run_id="phase3-golden-fixture",
        )
    )

    assert state.sector_state.status is (
        ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )
    assert state.industry_chain_state.status is (
        ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
    )
    assert state.hierarchy.sector_scope_id is None


def test_sector_aware_state_contains_macro_sector_chain_and_asset_hierarchy() -> None:
    """Day36 context completes the hierarchy without ticker-based inference."""

    data, memory = _aligned_asset_bundles()
    sector = _sector_input()
    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=data,
            sector_context=sector,
            memory_context=ResearchStateMemoryContextInput(
                snapshot_id=memory.retrieval_metadata.snapshot_id,
                as_of=memory.retrieval_metadata.as_of,
                status=memory.retrieval_metadata.status.value,
                result_count=memory.retrieval_metadata.result_count,
            ),
            source_run_id="phase4a-aapl-fixture",
        )
    )

    assert state.hierarchy.macro_scope_ids == ("MACRO:US",)
    assert state.hierarchy.sector_scope_id == sector.sector_scope_id
    assert state.hierarchy.industry_chain_scope_ids
    assert state.hierarchy.asset_scope_id == "ASSET:US:AAPL"
    assert state.macro_state.status is ResearchStateSectionStatus.PRESENT
    assert state.sector_state.status is ResearchStateSectionStatus.PRESENT
    assert state.industry_chain_state.status is ResearchStateSectionStatus.PRESENT
    assert state.memory_context_state.status is ResearchStateSectionStatus.PRESENT


def test_manager_claim_recursively_reaches_direct_evidence() -> None:
    """Manager state stores Claim IDs while the validated graph closes at Evidence."""

    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            accepted_claims=_claim_inputs(),
            source_run_id="claim-lineage-fixture",
        )
    )

    thesis = next(
        item
        for item in state.thesis_state.features
        if item.feature_name == "claim.research:claim:0"
    )
    assert thesis.source_claim_ids == ("research:claim:0",)
    assert thesis.source_evidence_ids == ()

    invalid = _manager_claim().model_copy(
        update={"upstream_claim_ids": ("unknown:claim",)}
    )
    with pytest.raises(ResearchStateBuildError, match="unknown upstream"):
        ResearchStateBuilder().build(
            ResearchStateBuildInput(
                research_data_bundle=_data_bundle(),
                accepted_claims=(
                    ResearchStateClaimInput(
                        agent_role=AgentName.RESEARCH_MANAGER,
                        agent_run_id="run:research",
                        claim=invalid,
                    ),
                ),
                source_run_id="open-lineage-fixture",
            )
        )


def test_normalized_state_requires_a_versioned_transform() -> None:
    """Normalized research values cannot be arbitrary unversioned LLM scores."""

    with pytest.raises(ValidationError, match="versioned transform"):
        ResearchStateFeature(
            feature_name="macro_stress",
            value=0.7,
            feature_type=ResearchStateFeatureType.NORMALIZED_RESEARCH_STATE,
            as_of=AS_OF,
            quality=DataQualityStatus.PASS,
            source_evidence_ids=("macro-evidence",),
            feature_version="research_state_feature_v1",
        )

    state = ResearchStateBuilder().build(
        ResearchStateBuildInput(
            research_data_bundle=_data_bundle(),
            accepted_claims=_claim_inputs(),
            normalized_features=(
                NormalizedResearchFeatureInput(
                    section_name=ResearchStateSectionName.MACRO,
                    feature_name="macro_stress",
                    value=0.7,
                    as_of=AS_OF,
                    source_claim_ids=("fundamental:claim:0",),
                    transform_name="bounded_macro_stress",
                    transform_version="v1",
                ),
            ),
            source_run_id="normalized-feature-fixture",
        )
    )
    feature = next(
        item
        for item in state.macro_state.features
        if item.feature_name == "macro_stress"
    )
    assert feature.transform_version == "v1"


def test_future_feature_is_rejected_by_unified_temporal_contract() -> None:
    """ResearchState reuses Day37 PIT rules rather than defining another validator."""

    with pytest.raises(ValidationError, match="future_available"):
        ResearchStateBuilder().build(
            ResearchStateBuildInput(
                research_data_bundle=_data_bundle(),
                accepted_claims=_claim_inputs(),
                normalized_features=(
                    NormalizedResearchFeatureInput(
                        section_name=ResearchStateSectionName.TECHNICAL,
                        feature_name="future_trend_strength",
                        value=0.9,
                        as_of=AS_OF + timedelta(seconds=1),
                        source_claim_ids=("fundamental:claim:0",),
                        transform_name="trend_strength",
                        transform_version="v1",
                    ),
                ),
                source_run_id="future-feature-fixture",
            )
        )


def test_missing_feature_and_section_semantics_are_explicit() -> None:
    """A missing state value cannot masquerade as zero or an empty category."""

    feature = ResearchStateFeature(
        feature_name="pe_ttm",
        value=None,
        feature_type=ResearchStateFeatureType.DETERMINISTIC_NUMERIC,
        as_of=AS_OF,
        quality=DataQualityStatus.UNKNOWN,
        feature_version="research_state_feature_v1",
        missing_reason="No attributable TTM EPS existed at the cutoff.",
    )
    assert feature.value is None
    assert feature.missing_reason
    with pytest.raises(ValidationError, match="requires a reason"):
        ResearchStateFeature(
            feature_name="pe_ttm",
            value=None,
            feature_type=ResearchStateFeatureType.DETERMINISTIC_NUMERIC,
            as_of=AS_OF,
            quality=DataQualityStatus.UNKNOWN,
            feature_version="research_state_feature_v1",
        )
