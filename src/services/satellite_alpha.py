"""Pure Satellite Alpha ontology and ResearchState mapper."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from src.models.enums import AgentName
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_state import (
    ResearchStateFeature,
    ResearchStateSection,
    ResearchStateSectionName,
    ResearchStateSectionStatus,
    ResearchStateSnapshot,
)
from src.schemas.satellite_alpha import (
    ExpectationRevisionDirection,
    LogicCertaintyStage,
    ResearchDisagreementState,
    ResearchStateSemanticDimension,
    ResearchStateSemanticSupportAudit,
    ResearchStateSupportLevel,
    SatelliteAlphaBuildInput,
    SatelliteAlphaComparisonScope,
    SatelliteAlphaComponent,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaDefinition,
    SatelliteAlphaDefinitionStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SatelliteAlphaRegistry,
    SatelliteAlphaUsage,
    SatelliteAlphaValueType,
    SectorChainAlignmentState,
    SelectionSatelliteBuildInput,
)
from src.schemas.temporal import TemporalMetadata, validate_temporal_access

_DEFINITION_VERSION = "satellite_alpha_definition_v1"
_TRANSFORM_VERSION = "satellite_alpha_transform_v1"
_ONTOLOGY_CREATED_AT = datetime(2026, 9, 15, tzinfo=UTC)


def build_satellite_alpha_registry_v1() -> SatelliteAlphaRegistry:
    """Return the complete immutable Day45 ontology registry."""

    definitions = (
        _definition(
            SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY,
            "Chain Benefit Elasticity",
            "Attributable components describing how an asset may participate "
            "in an industry chain.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.MULTI_COMPONENT,
            SatelliteAlphaComparisonScope.INDUSTRY_CHAIN,
            (ResearchStateSectionName.INDUSTRY_CHAIN,),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            missing="Absent component evidence is unknown, never a zero benefit.",
            aggregation=(
                "Components remain separate; no opaque aggregate score is produced."
            ),
        ),
        _definition(
            SatelliteAlphaFamily.EXPECTATION_REVISION,
            "Expectation Revision",
            "Direction and subtype of an accepted structured expectation change.",
            SatelliteAlphaUsage.BOTH,
            SatelliteAlphaValueType.CATEGORICAL,
            SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
            (ResearchStateSectionName.EVENT, ResearchStateSectionName.THESIS),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            allowed=tuple(item.value for item in ExpectationRevisionDirection),
            missing=(
                "No explicit direction is unknown and must not be inferred from prose."
            ),
            direction=(
                "UPGRADE and DOWNGRADE describe research expectation direction, "
                "not trades."
            ),
        ),
        _definition(
            SatelliteAlphaFamily.LOGIC_CERTAINTY,
            "Logic Certainty",
            "Finite evidence-progress stage; the category is not a probability.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.CATEGORICAL,
            SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
            (ResearchStateSectionName.EVENT, ResearchStateSectionName.THESIS),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            allowed=tuple(item.value for item in LogicCertaintyStage),
            missing="Missing structured stage remains unknown.",
        ),
        _definition(
            SatelliteAlphaFamily.RISK_BURDEN,
            "Risk Burden",
            "Structured accepted risk components using the existing Risk Agent "
            "taxonomy.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.MULTI_COMPONENT,
            SatelliteAlphaComparisonScope.MARKET,
            (ResearchStateSectionName.RISK,),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            roles=(AgentName.RISK_MANAGER,),
            missing="Unobserved risk components are missing, not zero risk.",
            aggregation=(
                "Risk components remain decomposed and are not collapsed to a score."
            ),
        ),
        _definition(
            SatelliteAlphaFamily.EVIDENCE_STRENGTH,
            "Evidence Strength",
            "Deterministic coverage of claim, evidence, and artifact lineage in "
            "the frozen State.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.MULTI_COMPONENT,
            SatelliteAlphaComparisonScope.MARKET,
            tuple(ResearchStateSectionName),
            SatelliteAlphaDefinitionStatus.IMPLEMENTED,
            missing="Missing authority or conflict metadata is reported explicitly.",
            aggregation=(
                "Counts are direct inventory components, not an evaluation score."
            ),
        ),
        _definition(
            SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT,
            "Sector-Chain Alignment",
            "Direction of supported asset, sector, and chain research alignment.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.CATEGORICAL,
            SatelliteAlphaComparisonScope.INDUSTRY_CHAIN,
            (ResearchStateSectionName.SECTOR, ResearchStateSectionName.INDUSTRY_CHAIN),
            SatelliteAlphaDefinitionStatus.IMPLEMENTED,
            allowed=tuple(item.value for item in SectorChainAlignmentState),
            missing="Context presence alone never implies positive alignment.",
        ),
        _definition(
            SatelliteAlphaFamily.RESEARCH_DISAGREEMENT,
            "Research Disagreement",
            "Disposition derived only from accepted structured debate claims.",
            SatelliteAlphaUsage.SELECTION,
            SatelliteAlphaValueType.CATEGORICAL,
            SatelliteAlphaComparisonScope.MARKET,
            (ResearchStateSectionName.DEBATE,),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            allowed=tuple(item.value for item in ResearchDisagreementState),
            roles=(
                AgentName.BULL_MANAGER,
                AgentName.BEAR_MANAGER,
                AgentName.RISK_MANAGER,
            ),
            missing="No structured disposition is UNCERTAIN, not agreement.",
        ),
        _history_definition(SatelliteAlphaFamily.STATE_TRANSITION, 2),
        _history_definition(SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY, 3),
        _definition(
            SatelliteAlphaFamily.EVENT_WINDOW,
            "Event Window",
            "Deterministic event timing context when canonical event time is retained.",
            SatelliteAlphaUsage.TIMING,
            SatelliteAlphaValueType.MULTI_COMPONENT,
            SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
            (ResearchStateSectionName.EVENT,),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            missing=(
                "Without canonical event identity and time, the window is unavailable."
            ),
        ),
        _history_definition(SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE, 2),
        _history_definition(SatelliteAlphaFamily.RISK_ESCALATION, 2),
        _history_definition(SatelliteAlphaFamily.EVIDENCE_CONFIRMATION, 2),
        _definition(
            SatelliteAlphaFamily.CATALYST_PROXIMITY,
            "Catalyst Proximity",
            "Distance to a canonical dated catalyst without inferring a schedule.",
            SatelliteAlphaUsage.TIMING,
            SatelliteAlphaValueType.MULTI_COMPONENT,
            SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
            (ResearchStateSectionName.EVENT, ResearchStateSectionName.THESIS),
            SatelliteAlphaDefinitionStatus.PARTIAL,
            missing="Undated or absent catalyst evidence cannot produce proximity.",
        ),
    )
    return SatelliteAlphaRegistry(definitions=definitions)


def research_state_semantic_support_audit_v1() -> (
    tuple[ResearchStateSemanticSupportAudit, ...]
):
    """Audit current State v1 semantics without promoting inferred support."""

    rows = (
        (
            ResearchStateSemanticDimension.LOGIC_STAGE,
            "event_state/thesis_state accepted claims",
            "logic_stage",
        ),
        (
            ResearchStateSemanticDimension.EXPECTATION_DIRECTION,
            "event_state/thesis_state accepted claims",
            "expectation_direction, expectation_subtype",
        ),
        (
            ResearchStateSemanticDimension.RISK_TAXONOMY,
            "risk_state accepted claims",
            "risk_component_type",
        ),
        (
            ResearchStateSemanticDimension.CATALYST,
            "event_state/thesis_state accepted claims",
            "canonical_catalyst_id, catalyst_time",
        ),
        (
            ResearchStateSemanticDimension.INVALIDATOR,
            "debate_state accepted claims",
            "claim_path or invalidator disposition",
        ),
        (
            ResearchStateSemanticDimension.SECTOR_CHAIN_RELATIONSHIP,
            "State hierarchy and sector/chain sections",
            "canonical sector_id, alignment disposition",
        ),
        (
            ResearchStateSemanticDimension.RESEARCH_DISAGREEMENT,
            "debate_state accepted claims",
            "producer role and structured disposition",
        ),
        (
            ResearchStateSemanticDimension.EVENT_TIMING,
            "event_state feature as_of/available_at",
            "canonical source_event_id and event_time",
        ),
    )
    return tuple(
        ResearchStateSemanticSupportAudit(
            dimension=dimension,
            current_source=source,
            support_level=ResearchStateSupportLevel.PARTIAL,
            missing_fields=tuple(part.strip() for part in missing.split(",")),
            required_action=(
                "Retain the already accepted structured semantic in a future "
                "versioned State projection; do not re-score with an LLM."
            ),
        )
        for dimension, source, missing in rows
    )


class SatelliteAlphaMapper:
    """Map one frozen ResearchState into truthful raw research descriptors."""

    def __init__(self, registry: SatelliteAlphaRegistry | None = None) -> None:
        """Use the canonical v1 registry unless an explicit registry is supplied."""

        self._registry = registry or build_satellite_alpha_registry_v1()

    def build(
        self, inputs: SatelliteAlphaBuildInput
    ) -> tuple[SatelliteAlphaObservation, ...]:
        """Build observations without LLM, Provider, report, or prose parsing."""

        state = inputs.research_state
        self._validate_state_features(state)
        return tuple(
            self._build_one(definition, inputs, selection_context=None)
            for definition in self._registry.definitions
        )

    def build_selection(
        self, inputs: SelectionSatelliteBuildInput
    ) -> tuple[SatelliteAlphaObservation, ...]:
        """Build only Selection-capable descriptors from frozen context."""

        state = inputs.research_state
        self._validate_state_features(state)
        return tuple(
            self._build_one(definition, inputs, inputs)
            for definition in self._registry.definitions
            if definition.usage
            in {SatelliteAlphaUsage.SELECTION, SatelliteAlphaUsage.BOTH}
        )

    def _build_one(
        self,
        definition: SatelliteAlphaDefinition,
        inputs: SatelliteAlphaBuildInput,
        selection_context: SelectionSatelliteBuildInput | None,
    ) -> SatelliteAlphaObservation:
        state = inputs.research_state
        value: str | None = None
        components: tuple[SatelliteAlphaComponent, ...] = ()
        missing: tuple[str, ...]
        coverage: SatelliteAlphaCoverageStatus

        if definition.requires_history:
            coverage = SatelliteAlphaCoverageStatus.REQUIRES_HISTORY
            missing = (
                f"requires {definition.minimum_history_points} PIT ResearchState "
                "snapshots; use the deterministic history builder",
            )
        elif definition.family is SatelliteAlphaFamily.EVIDENCE_STRENGTH:
            components = self._evidence_components(state)
            if components:
                coverage = SatelliteAlphaCoverageStatus.PARTIAL
                missing = (
                    "source authority classification is not retained in "
                    "ResearchState v1",
                    "evidence conflict disposition is not retained in ResearchState v1",
                )
            else:
                coverage = SatelliteAlphaCoverageStatus.EMPTY_VALID
                missing = ("frozen State contains no attributable available features",)
        elif definition.family is SatelliteAlphaFamily.CHAIN_BENEFIT_ELASTICITY:
            coverage, components, missing = self._chain_binding(state)
        elif definition.family is SatelliteAlphaFamily.SECTOR_CHAIN_ALIGNMENT:
            coverage, value, components, missing = self._sector_alignment(state)
        elif definition.family is SatelliteAlphaFamily.RISK_BURDEN:
            coverage, components, missing = self._risk_burden(state)
        elif definition.family is SatelliteAlphaFamily.RESEARCH_DISAGREEMENT:
            coverage, value, components, missing = self._research_disagreement(state)
        elif definition.family is SatelliteAlphaFamily.EXPECTATION_REVISION:
            coverage, value, components, missing = self._expectation_revision(state)
        elif definition.family is SatelliteAlphaFamily.LOGIC_CERTAINTY:
            coverage, value, components, missing = self._logic_certainty(state)
        elif definition.family is SatelliteAlphaFamily.EVENT_WINDOW:
            coverage, components, missing = self._section_inventory(
                state,
                state.event_state,
                "accepted_event_context_count",
                "canonical event identity and event time are not retained in "
                "ResearchState v1",
            )
        else:
            coverage = self._source_coverage(state, definition.source_dimensions)
            missing = (
                "required structured semantic field is absent from ResearchState v1",
            )

        refs = tuple(
            sorted(
                {ref for item in components for ref in item.source_state_feature_refs}
            )
        )
        claims = tuple(
            sorted({ref for item in components for ref in item.source_claim_ids})
        )
        evidence = tuple(
            sorted({ref for item in components for ref in item.source_evidence_ids})
        )
        artifacts = tuple(
            sorted(
                {
                    state.research_state_id,
                    *(ref for item in components for ref in item.source_artifact_ids),
                }
            )
        )
        sector_lineage = {
            claim_id
            for section in (state.macro_state, state.sector_state)
            for feature in section.features
            for claim_id in feature.source_claim_ids
        }
        sector_claims = tuple(sorted(set(claims) & sector_lineage))
        event_ids: tuple[str, ...] = ()
        sector_id = None
        if selection_context is not None:
            sector_id = selection_context.sector_id
            related_events = tuple(
                event
                for event in selection_context.sector_events
                if set(event.chain_ids) & set(self._chain_ids(state))
                or set(event.supporting_sector_claim_ids) & set(sector_claims)
            )
            event_ids = tuple(sorted(event.event_id for event in related_events))
            sector_claims = tuple(
                sorted(
                    {
                        *sector_claims,
                        *(
                            claim_id
                            for event in related_events
                            for claim_id in event.supporting_sector_claim_ids
                        ),
                    }
                )
            )
            if selection_context.sector_context_id is not None:
                artifacts = tuple(
                    sorted({*artifacts, selection_context.sector_context_id})
                )
        candidate = {
            "satellite_alpha_id": definition.satellite_alpha_id.value,
            "asset_id": str(state.asset_id),
            "market": state.asset_id.market.value,
            "sector_id": sector_id.value if sector_id is not None else None,
            "chain_ids": self._chain_ids(state),
            "research_as_of": state.research_as_of.isoformat(),
            "available_at": inputs.available_at.isoformat(),
            "usage": definition.usage.value,
            "value": value,
            "value_components": [item.model_dump(mode="json") for item in components],
            "coverage_status": coverage.value,
            "comparison_scope": definition.comparison_scope.value,
            "source_research_state_id": state.research_state_id,
            "source_episode_id": (
                inputs.source_episode.episode_id if inputs.source_episode else None
            ),
            "source_state_feature_refs": refs,
            "source_claim_ids": claims,
            "source_event_ids": event_ids,
            "source_sector_claim_ids": sector_claims,
            "source_evidence_ids": evidence,
            "source_artifact_ids": artifacts,
            "data_snapshot_id": state.lineage.data_snapshot_id,
            "definition_version": definition.definition_version,
            "transform_version": definition.deterministic_transform_version,
        }
        observation_id = (
            "satellite_alpha_"
            + hashlib.sha256(
                json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:24]
        )
        return SatelliteAlphaObservation(
            observation_id=observation_id,
            satellite_alpha_id=definition.satellite_alpha_id,
            asset_id=state.asset_id,
            market=state.asset_id.market,
            sector_id=sector_id,
            chain_ids=self._chain_ids(state),
            research_as_of=state.research_as_of,
            available_at=inputs.available_at,
            usage=definition.usage,
            value=value,
            value_components=components,
            quality=(
                DataQualityStatus.PASS
                if components or value is not None
                else DataQualityStatus.UNKNOWN
            ),
            coverage_status=coverage,
            comparison_scope=definition.comparison_scope,
            missing_reasons=missing,
            source_research_state_id=state.research_state_id,
            source_episode_id=(
                inputs.source_episode.episode_id if inputs.source_episode else None
            ),
            source_state_feature_refs=refs,
            source_claim_ids=claims,
            source_event_ids=event_ids,
            source_sector_claim_ids=sector_claims,
            source_evidence_ids=evidence,
            source_artifact_ids=artifacts,
            data_snapshot_id=state.lineage.data_snapshot_id,
            definition_version=definition.definition_version,
            transform_version=definition.deterministic_transform_version,
            created_at=inputs.created_at,
        )

    @staticmethod
    def _validate_state_features(state: ResearchStateSnapshot) -> None:
        for section in _sections(state):
            for feature in section.features:
                validate_temporal_access(
                    TemporalMetadata(
                        event_time=feature.as_of,
                        available_at=feature.available_at or feature.as_of,
                    ),
                    state.research_as_of,
                )

    def _evidence_components(
        self, state: ResearchStateSnapshot
    ) -> tuple[SatelliteAlphaComponent, ...]:
        features = tuple(
            (section.section_name, feature)
            for section in _sections(state)
            for feature in section.features
            if feature.value is not None
        )
        specifications = (
            ("attributable_feature_count", features),
            (
                "claim_backed_feature_count",
                tuple(item for item in features if item[1].source_claim_ids),
            ),
            (
                "evidence_backed_feature_count",
                tuple(item for item in features if item[1].source_evidence_ids),
            ),
            (
                "artifact_backed_feature_count",
                tuple(item for item in features if item[1].source_artifact_ids),
            ),
        )
        return tuple(
            self._count_component(name, selected)
            for name, selected in specifications
            if selected
        )

    def _chain_binding(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        if (
            state.industry_chain_state.status
            is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
        ):
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                (),
                ("industry-chain semantics did not exist at the source run",),
            )
        if not state.hierarchy.industry_chain_scope_ids:
            return (
                SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
                (),
                ("asset had no PIT-valid industry-chain scope",),
            )
        component_names = (
            "business_binding_depth",
            "revenue_exposure",
            "incremental_revenue_potential",
            "incremental_earnings_potential",
            "capacity_readiness",
            "competitive_position",
            "evidence_quality",
        )
        exact = tuple(
            (
                name,
                self._find_feature(
                    (state.industry_chain_state,),
                    f"satellite.chain_benefit.{name}",
                ),
            )
            for name in component_names
        )
        exact_components = tuple(
            self._categorical_component(name, feature)
            for name, feature in exact
            if feature is not None and isinstance(feature[1].value, (str, bool))
        )
        if exact_components:
            absent = tuple(
                name
                for name, feature in exact
                if feature is None or not isinstance(feature[1].value, (str, bool))
            )
            if absent:
                return (
                    SatelliteAlphaCoverageStatus.PARTIAL,
                    exact_components,
                    (f"missing chain benefit components: {', '.join(absent)}",),
                )
            return SatelliteAlphaCoverageStatus.AVAILABLE, exact_components, ()
        selected = tuple(
            (ResearchStateSectionName.INDUSTRY_CHAIN, item)
            for item in state.industry_chain_state.features
            if item.value is not None
        )
        if not selected:
            return (
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                (),
                ("no attributable chain binding component is retained",),
            )
        component = self._count_component("chain_context_feature_count", selected)
        return (
            SatelliteAlphaCoverageStatus.PARTIAL,
            (component,),
            (
                "revenue exposure, incremental potential, capacity readiness, "
                "competitive position, and evidence quality are unavailable",
            ),
        )

    def _sector_alignment(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        str | None,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        if (
            state.sector_state.status
            is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
        ):
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                None,
                (),
                ("sector semantics did not exist at the source run",),
            )
        if (
            not state.hierarchy.sector_scope_id
            or not state.hierarchy.industry_chain_scope_ids
        ):
            return (
                SatelliteAlphaCoverageStatus.NOT_APPLICABLE,
                None,
                (),
                ("both PIT-valid sector and industry-chain scopes are required",),
            )
        exact = self._find_feature(
            (state.sector_state, state.industry_chain_state),
            "satellite.sector_chain_alignment",
        )
        if exact is not None and isinstance(exact[1].value, str):
            try:
                alignment = SectorChainAlignmentState(exact[1].value)
            except ValueError:
                return (
                    SatelliteAlphaCoverageStatus.MISSING_INPUT,
                    None,
                    (),
                    ("structured sector-chain alignment value is outside v1",),
                )
            return (
                SatelliteAlphaCoverageStatus.AVAILABLE,
                alignment.value,
                (self._categorical_component("alignment", exact),),
                (),
            )
        selected = tuple(
            (section.section_name, item)
            for section in (state.sector_state, state.industry_chain_state)
            for item in section.features
            if item.value is not None
        )
        if not selected:
            return (
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                None,
                (),
                ("sector-chain relationship evidence is absent",),
            )
        component = self._count_component("relationship_context_count", selected)
        return (
            SatelliteAlphaCoverageStatus.PARTIAL,
            SectorChainAlignmentState.UNCERTAIN.value,
            (component,),
            (
                "directional alignment disposition is not retained; context "
                "presence is not positive alignment",
            ),
        )

    def _expectation_revision(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        str | None,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        direction_feature = self._find_feature(
            (state.event_state, state.thesis_state),
            "satellite.expectation_revision.direction",
        )
        if direction_feature is None or not isinstance(direction_feature[1].value, str):
            return (
                self._source_coverage(
                    state,
                    (ResearchStateSectionName.EVENT, ResearchStateSectionName.THESIS),
                ),
                None,
                (),
                ("structured expectation direction is absent from the source State",),
            )
        try:
            direction = ExpectationRevisionDirection(direction_feature[1].value)
        except ValueError:
            return (
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                None,
                (),
                ("structured expectation direction is outside vocabulary v1",),
            )
        components = [self._categorical_component("direction", direction_feature)]
        subtype_feature = self._find_feature(
            (state.event_state, state.thesis_state),
            "satellite.expectation_revision.subtype",
        )
        if subtype_feature is not None and isinstance(subtype_feature[1].value, str):
            components.append(self._categorical_component("subtype", subtype_feature))
        return (
            SatelliteAlphaCoverageStatus.AVAILABLE,
            direction.value,
            tuple(components),
            (),
        )

    def _logic_certainty(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        str | None,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        feature = self._find_feature(
            (state.event_state, state.thesis_state),
            "satellite.logic_certainty",
        )
        if feature is None or not isinstance(feature[1].value, str):
            return (
                self._source_coverage(
                    state,
                    (ResearchStateSectionName.EVENT, ResearchStateSectionName.THESIS),
                ),
                None,
                (),
                ("structured logic stage is absent from the source State",),
            )
        try:
            stage = LogicCertaintyStage(feature[1].value)
        except ValueError:
            return (
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                None,
                (),
                ("structured logic stage is outside vocabulary v1",),
            )
        return (
            SatelliteAlphaCoverageStatus.AVAILABLE,
            stage.value,
            (self._categorical_component("logic_stage", feature),),
            (),
        )

    def _risk_burden(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        section = state.risk_state
        if section.status is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN:
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                (),
                ("structured Risk Agent claims did not exist at the source run",),
            )
        categories = (
            ("confirmed_risk_count", "claim.risk:confirmed_risks:"),
            ("scenario_risk_count", "claim.risk:scenario_risks:"),
            ("watch_item_count", "claim.risk:watch_items:"),
        )
        components = tuple(
            self._count_component(
                name,
                tuple(
                    (section.section_name, feature)
                    for feature in section.features
                    if feature.feature_name.startswith(prefix)
                ),
            )
            for name, prefix in categories
            if any(
                feature.feature_name.startswith(prefix) for feature in section.features
            )
        )
        if not components:
            return (
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                (),
                (section.missing_reason or "structured Risk Agent paths are absent",),
            )
        return (
            SatelliteAlphaCoverageStatus.PARTIAL,
            components,
            (
                "fine-grained customer, capacity, competition, regulation, and "
                "geopolitical risk categories are not retained in State v1",
            ),
        )

    def _research_disagreement(self, state: ResearchStateSnapshot) -> tuple[
        SatelliteAlphaCoverageStatus,
        str | None,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        section = state.debate_state
        if section.status is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN:
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                None,
                (),
                ("structured Bull/Bear claims did not exist at the source run",),
            )
        exact = self._find_feature(
            (section,),
            "satellite.research_disagreement",
        )
        if exact is not None and isinstance(exact[1].value, str):
            try:
                disposition = ResearchDisagreementState(exact[1].value)
            except ValueError:
                return (
                    SatelliteAlphaCoverageStatus.MISSING_INPUT,
                    None,
                    (),
                    ("structured disagreement is outside vocabulary v1",),
                )
            return (
                SatelliteAlphaCoverageStatus.AVAILABLE,
                disposition.value,
                (self._categorical_component("disposition", exact),),
                (),
            )
        bull = tuple(
            (section.section_name, feature)
            for feature in section.features
            if feature.feature_name.startswith("claim.bull:")
        )
        bear = tuple(
            (section.section_name, feature)
            for feature in section.features
            if feature.feature_name.startswith("claim.bear:")
        )
        components = tuple(
            self._count_component(name, selected)
            for name, selected in (
                ("bull_claim_count", bull),
                ("bear_claim_count", bear),
            )
            if selected
        )
        if bull and bear:
            return (
                SatelliteAlphaCoverageStatus.PARTIAL,
                ResearchDisagreementState.MIXED.value,
                components,
                (
                    "Bull and Bear paths are both present, but State v1 does not "
                    "retain an explicit disagreement disposition",
                ),
            )
        if components:
            return (
                SatelliteAlphaCoverageStatus.PARTIAL,
                ResearchDisagreementState.UNCERTAIN.value,
                components,
                ("both structured Bull and Bear dispositions are required",),
            )
        return (
            SatelliteAlphaCoverageStatus.NOT_RESEARCHED,
            None,
            (),
            (section.missing_reason or "structured debate was not researched",),
        )

    @staticmethod
    def _find_feature(
        sections: tuple[ResearchStateSection, ...], feature_name: str
    ) -> tuple[ResearchStateSectionName, ResearchStateFeature] | None:
        return next(
            (
                (section.section_name, feature)
                for section in sections
                for feature in section.features
                if feature.feature_name == feature_name
            ),
            None,
        )

    @staticmethod
    def _categorical_component(
        component_name: str,
        source: tuple[ResearchStateSectionName, ResearchStateFeature],
    ) -> SatelliteAlphaComponent:
        section_name, feature = source
        if feature.value is None or isinstance(feature.value, (int, float)):
            raise ValueError("categorical Satellite source feature is invalid")
        return SatelliteAlphaComponent(
            component_name=component_name,
            value=feature.value,
            source_state_feature_refs=(
                f"{section_name.value}::{feature.feature_name}",
            ),
            source_claim_ids=feature.source_claim_ids,
            source_evidence_ids=feature.source_evidence_ids,
            source_artifact_ids=feature.source_artifact_ids,
            transform_version=_TRANSFORM_VERSION,
        )

    def _section_inventory(
        self,
        state: ResearchStateSnapshot,
        section: ResearchStateSection,
        component_name: str,
        reason: str,
    ) -> tuple[
        SatelliteAlphaCoverageStatus,
        tuple[SatelliteAlphaComponent, ...],
        tuple[str, ...],
    ]:
        if section.status is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN:
            return (
                SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN,
                (),
                (f"{section.section_name.value} did not exist at the source run",),
            )
        selected = tuple(
            (section.section_name, item)
            for item in section.features
            if item.value is not None
        )
        if not selected:
            return (
                SatelliteAlphaCoverageStatus.NOT_RESEARCHED,
                (),
                (section.missing_reason or "source section was not researched",),
            )
        return (
            SatelliteAlphaCoverageStatus.PARTIAL,
            (self._count_component(component_name, selected),),
            (reason,),
        )

    @staticmethod
    def _source_coverage(
        state: ResearchStateSnapshot, names: tuple[ResearchStateSectionName, ...]
    ) -> SatelliteAlphaCoverageStatus:
        statuses = tuple(getattr(state, name.value).status for name in names)
        if statuses and all(
            item is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
            for item in statuses
        ):
            return SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
        return SatelliteAlphaCoverageStatus.MISSING_INPUT

    @staticmethod
    def _count_component(
        name: str,
        selected: tuple[tuple[ResearchStateSectionName, ResearchStateFeature], ...],
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=name,
            value=len(selected),
            unit="count",
            scale="integer_count",
            source_state_feature_refs=tuple(
                sorted(
                    f"{section.value}::{feature.feature_name}"
                    for section, feature in selected
                )
            ),
            source_claim_ids=tuple(
                sorted(
                    {ref for _, feature in selected for ref in feature.source_claim_ids}
                )
            ),
            source_evidence_ids=tuple(
                sorted(
                    {
                        ref
                        for _, feature in selected
                        for ref in feature.source_evidence_ids
                    }
                )
            ),
            source_artifact_ids=tuple(
                sorted(
                    {
                        ref
                        for _, feature in selected
                        for ref in feature.source_artifact_ids
                    }
                )
            ),
            transform_version=_TRANSFORM_VERSION,
        )

    @staticmethod
    def _chain_ids(state: ResearchStateSnapshot) -> tuple[str, ...]:
        return tuple(
            sorted(
                scope.removeprefix("CHAIN:")
                for scope in state.hierarchy.industry_chain_scope_ids
            )
        )


def _sections(state: ResearchStateSnapshot) -> tuple[ResearchStateSection, ...]:
    return tuple(getattr(state, name.value) for name in ResearchStateSectionName)


def _definition(
    family: SatelliteAlphaFamily,
    name: str,
    description: str,
    usage: SatelliteAlphaUsage,
    value_type: SatelliteAlphaValueType,
    comparison_scope: SatelliteAlphaComparisonScope,
    dimensions: tuple[ResearchStateSectionName, ...],
    status: SatelliteAlphaDefinitionStatus,
    *,
    allowed: tuple[str, ...] = (),
    roles: tuple[AgentName, ...] = (),
    missing: str = "Missing inputs remain missing and are never encoded as zero.",
    direction: str = "Direction is descriptive research semantics, not a trade signal.",
    aggregation: str = (
        "No cross-sectional ranking, normalization, or portfolio aggregation."
    ),
) -> SatelliteAlphaDefinition:
    return SatelliteAlphaDefinition(
        satellite_alpha_id=family,
        name=name,
        description=description,
        family=family,
        usage=usage,
        value_type=value_type,
        allowed_values=allowed,
        source_dimensions=dimensions,
        source_state_fields=tuple(name.value for name in dimensions),
        source_claim_roles=roles,
        comparison_scope=comparison_scope,
        missing_semantics=missing,
        direction_semantics=direction,
        aggregation_semantics=aggregation,
        deterministic_transform_version=_TRANSFORM_VERSION,
        status=status,
        created_at=_ONTOLOGY_CREATED_AT,
    )


def _history_definition(
    family: SatelliteAlphaFamily, points: int
) -> SatelliteAlphaDefinition:
    title = family.value.replace("_", " ").title()
    dimensions = {
        SatelliteAlphaFamily.STATE_TRANSITION: tuple(ResearchStateSectionName),
        SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY: (
            ResearchStateSectionName.EVENT,
            ResearchStateSectionName.THESIS,
        ),
        SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE: (
            ResearchStateSectionName.THESIS,
        ),
        SatelliteAlphaFamily.RISK_ESCALATION: (ResearchStateSectionName.RISK,),
        SatelliteAlphaFamily.EVIDENCE_CONFIRMATION: tuple(ResearchStateSectionName),
    }[family]
    return SatelliteAlphaDefinition(
        satellite_alpha_id=family,
        name=title,
        description=(
            f"Versioned {title.lower()} semantics across ordered frozen "
            "ResearchState snapshots."
        ),
        family=family,
        usage=SatelliteAlphaUsage.TIMING,
        value_type=SatelliteAlphaValueType.MULTI_COMPONENT,
        source_dimensions=dimensions,
        source_state_fields=tuple(item.value for item in dimensions),
        comparison_scope=SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
        missing_semantics=(
            "A single State is insufficient; absence is not stable state."
        ),
        direction_semantics=(
            "Direction describes research-state change, not a timing signal."
        ),
        aggregation_semantics=(
            "Only a future deterministic ordered-history transform may derive "
            "this family."
        ),
        requires_history=True,
        minimum_history_points=points,
        deterministic_transform_version=_TRANSFORM_VERSION,
        status=SatelliteAlphaDefinitionStatus.IMPLEMENTED,
        created_at=_ONTOLOGY_CREATED_AT,
    )
