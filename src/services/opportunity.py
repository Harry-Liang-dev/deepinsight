"""Deterministic OpportunityCandidate qualification from frozen research."""

from __future__ import annotations

import hashlib
import json

from src.schemas.opportunity import (
    OpportunityCandidate,
    OpportunityCandidateBuildInput,
    OpportunityCandidateStatus,
    OpportunityType,
    ThesisDirection,
)
from src.schemas.research_data import DataQualityStatus
from src.schemas.satellite_alpha import (
    LogicCertaintyStage,
    ResearchDisagreementState,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SectorChainAlignmentState,
)


class OpportunityCandidateBuilder:
    """Apply transparent eligibility rules without a score or model call."""

    def build(self, inputs: OpportunityCandidateBuildInput) -> OpportunityCandidate:
        """Build one qualification artifact from validated Selection descriptors."""

        state = inputs.research_state
        observations = {
            item.satellite_alpha_id: item for item in inputs.selection_observations
        }
        types: set[OpportunityType] = set()
        reasons: set[str] = set()

        alignment = observations.get(SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT)
        if (
            alignment is not None
            and alignment.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
        ):
            if alignment.value in {
                SectorChainAlignmentState.POSITIVE_ALIGNMENT.value,
                SectorChainAlignmentState.NEGATIVE_ALIGNMENT.value,
                SectorChainAlignmentState.MIXED.value,
            }:
                types.add(OpportunityType.SECTOR_CHAIN)
                reasons.add("qualified_sector_chain_alignment")

        revision = observations.get(SatelliteAlphaFamily.EXPECTATION_REVISION)
        if (
            revision is not None
            and revision.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
        ):
            if revision.value not in {"unchanged", "uncertain", None}:
                types.add(OpportunityType.EXPECTATION_CHANGE)
                reasons.add("qualified_expectation_change")

        logic = observations.get(SatelliteAlphaFamily.LOGIC_CERTAINTY)
        if (
            logic is not None
            and logic.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
        ):
            if logic.value not in {
                LogicCertaintyStage.RUMOR.value,
                LogicCertaintyStage.UNCERTAIN.value,
                None,
            }:
                types.add(OpportunityType.MATERIAL_EVENT)
                reasons.add("qualified_structured_logic_stage")

        disagreement = observations.get(SatelliteAlphaFamily.RESEARCH_DISAGREEMENT)
        if (
            disagreement is not None
            and disagreement.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
        ):
            if disagreement.value not in {
                ResearchDisagreementState.UNCERTAIN.value,
                None,
            }:
                types.add(OpportunityType.RESEARCH_DEBATE)
                reasons.add("qualified_structured_research_debate")

        thesis_features = tuple(
            feature
            for feature in state.thesis_state.features
            if feature.feature_name.startswith("claim.research:")
            and feature.source_claim_ids
        )
        if thesis_features:
            types.add(OpportunityType.MATERIAL_THESIS)
            reasons.add("qualified_accepted_research_thesis")

        material_event_features = tuple(
            feature
            for feature in state.event_state.features
            if feature.feature_name.startswith("claim.news_event_analyst:")
            and feature.source_claim_ids
        )
        if material_event_features:
            types.add(OpportunityType.MATERIAL_EVENT)
            reasons.add("qualified_accepted_asset_event")

        risk = observations.get(SatelliteAlphaFamily.RISK_BURDEN)
        if risk is not None and risk.source_claim_ids:
            types.add(OpportunityType.RISK_RESEARCH)
            reasons.add("qualified_structured_risk_review")

        qualified = bool(types)
        status = (
            OpportunityCandidateStatus.QUALIFIED
            if qualified
            else OpportunityCandidateStatus.INSUFFICIENT_RESEARCH
        )
        source_claim_ids = tuple(
            sorted(
                {
                    claim_id
                    for observation in inputs.selection_observations
                    for claim_id in observation.source_claim_ids
                }
            )
        )
        source_event_ids = tuple(
            sorted(
                {
                    event_id
                    for observation in inputs.selection_observations
                    for event_id in observation.source_event_ids
                }
            )
        )
        source_sector_claim_ids = tuple(
            sorted(
                {
                    claim_id
                    for observation in inputs.selection_observations
                    for claim_id in observation.source_sector_claim_ids
                }
            )
        )
        direction = self._direction(alignment, disagreement)
        logic_stage = (
            LogicCertaintyStage(logic.value)
            if logic is not None
            and logic.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE
            and isinstance(logic.value, str)
            else None
        )
        coverage, missing = self._coverage(inputs.selection_observations, qualified)
        available_at = max(item.available_at for item in inputs.selection_observations)
        sector_ids = {
            item.sector_id
            for item in inputs.selection_observations
            if item.sector_id is not None
        }
        sector_id = next(iter(sector_ids)) if len(sector_ids) == 1 else None
        chain_ids = tuple(
            sorted(
                {
                    chain_id
                    for observation in inputs.selection_observations
                    for chain_id in observation.chain_ids
                }
            )
        )
        observation_ids = tuple(
            sorted(item.observation_id for item in inputs.selection_observations)
        )
        risk_refs = risk.source_claim_ids if risk is not None else ()
        invalidator_refs = tuple(
            sorted(
                {
                    claim_id
                    for feature in state.debate_state.features
                    if ":invalidators:" in feature.feature_name
                    for claim_id in feature.source_claim_ids
                }
            )
        )
        payload = {
            "status": status.value,
            "asset_id": str(state.asset_id),
            "market": state.asset_id.market.value,
            "research_as_of": state.research_as_of.isoformat(),
            "available_at": available_at.isoformat(),
            "sector_id": sector_id.value if sector_id is not None else None,
            "chain_ids": chain_ids,
            "opportunity_types": sorted(item.value for item in types),
            "thesis_direction": direction.value,
            "logic_stage": logic_stage.value if logic_stage is not None else None,
            "satellite_observation_ids": observation_ids,
            "catalyst_refs": (),
            "risk_refs": risk_refs,
            "invalidator_refs": invalidator_refs,
            "source_research_state_id": state.research_state_id,
            "source_episode_id": (
                inputs.source_episode.episode_id if inputs.source_episode else None
            ),
            "source_claim_ids": source_claim_ids,
            "source_event_ids": source_event_ids,
            "source_sector_claim_ids": source_sector_claim_ids,
            "coverage_status": coverage.value,
            "qualification_reasons": sorted(reasons),
            "missing_reasons": missing,
            "candidate_version": "opportunity_candidate_v1",
        }
        candidate_id = (
            "opportunity_"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:24]
        )
        return OpportunityCandidate(
            candidate_id=candidate_id,
            status=status,
            asset_id=state.asset_id,
            market=state.asset_id.market,
            research_as_of=state.research_as_of,
            available_at=available_at,
            sector_id=sector_id,
            chain_ids=chain_ids,
            opportunity_types=tuple(sorted(types, key=lambda item: item.value)),
            thesis_direction=direction,
            logic_stage=logic_stage,
            satellite_observation_ids=observation_ids,
            risk_refs=risk_refs,
            invalidator_refs=invalidator_refs,
            source_research_state_id=state.research_state_id,
            source_episode_id=(
                inputs.source_episode.episode_id if inputs.source_episode else None
            ),
            source_claim_ids=source_claim_ids,
            source_event_ids=source_event_ids,
            source_sector_claim_ids=source_sector_claim_ids,
            coverage_status=coverage,
            quality=(
                DataQualityStatus.WARNING
                if coverage is SatelliteAlphaCoverageStatus.PARTIAL
                else (
                    DataQualityStatus.PASS
                    if coverage is SatelliteAlphaCoverageStatus.AVAILABLE
                    else DataQualityStatus.UNKNOWN
                )
            ),
            qualification_reasons=tuple(sorted(reasons)),
            missing_reasons=missing,
            created_at=inputs.created_at,
        )

    @staticmethod
    def _direction(
        alignment: SatelliteAlphaObservation | None,
        disagreement: SatelliteAlphaObservation | None,
    ) -> ThesisDirection:
        if alignment is not None:
            mapping = {
                SectorChainAlignmentState.POSITIVE_ALIGNMENT.value: (
                    ThesisDirection.POSITIVE
                ),
                SectorChainAlignmentState.NEGATIVE_ALIGNMENT.value: (
                    ThesisDirection.NEGATIVE
                ),
                SectorChainAlignmentState.MIXED.value: ThesisDirection.MIXED,
            }
            if isinstance(alignment.value, str) and alignment.value in mapping:
                return mapping[alignment.value]
        if disagreement is not None:
            mapping = {
                ResearchDisagreementState.CONSENSUS_POSITIVE.value: (
                    ThesisDirection.POSITIVE
                ),
                ResearchDisagreementState.CONSENSUS_NEGATIVE.value: (
                    ThesisDirection.NEGATIVE
                ),
                ResearchDisagreementState.HIGH_DISAGREEMENT.value: (
                    ThesisDirection.MIXED
                ),
                ResearchDisagreementState.RISK_DOMINANT.value: ThesisDirection.NEGATIVE,
                ResearchDisagreementState.MIXED.value: ThesisDirection.MIXED,
            }
            if isinstance(disagreement.value, str) and disagreement.value in mapping:
                return mapping[disagreement.value]
        return ThesisDirection.UNCERTAIN

    @staticmethod
    def _coverage(
        observations: tuple[SatelliteAlphaObservation, ...], qualified: bool
    ) -> tuple[SatelliteAlphaCoverageStatus, tuple[str, ...]]:
        statuses = {item.coverage_status for item in observations}
        if qualified:
            if statuses <= {
                SatelliteAlphaCoverageStatus.AVAILABLE,
                SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
            }:
                return SatelliteAlphaCoverageStatus.AVAILABLE, ()
            return (
                SatelliteAlphaCoverageStatus.PARTIAL,
                ("one or more Selection descriptors have incomplete source coverage",),
            )
        if statuses == {SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN}:
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                ("Selection semantics were unavailable in the source run",),
            )
        if statuses == {SatelliteAlphaCoverageStatus.NOT_APPLICABLE}:
            return (
                SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
                ("Selection semantics do not apply to this source context",),
            )
        return (
            SatelliteAlphaCoverageStatus.MISSING_INPUT,
            ("no rule-based research opportunity could be established",),
        )
