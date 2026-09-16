"""Deterministic ResearchState history comparison and Timing projection."""

from __future__ import annotations

import hashlib
import json

from src.schemas.memory import MemorySearchResult
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import (
    ResearchStateFeature,
    ResearchStateSection,
    ResearchStateSectionName,
    ResearchStateSectionStatus,
    ResearchStateSnapshot,
)
from src.schemas.research_state_transition import (
    CatalystProximity,
    EventWindowPosition,
    EvidenceTransitionStatus,
    ExpectationChangeOrder,
    ResearchStateTransition,
    ResearchStateTransitionDirection,
    ResearchStateValueChange,
    RiskTransitionStatus,
    ThesisTransitionStatus,
    TimingEventKind,
    TimingEventReference,
    TimingSatelliteBuildInput,
)
from src.schemas.satellite_alpha import (
    LogicCertaintyStage,
    SatelliteAlphaComparisonScope,
    SatelliteAlphaComponent,
    SatelliteAlphaCoverageStatus,
    SatelliteAlphaFamily,
    SatelliteAlphaObservation,
    SatelliteAlphaUsage,
)
from src.schemas.temporal import (
    TemporalMetadata,
    TemporalSourceKind,
    validate_temporal_access,
)
from src.services.satellite_alpha import build_satellite_alpha_registry_v1

_TRANSITION_VERSION = "research_state_transition_v1"
_COMPARISON_VERSION = "research_state_comparison_v1"
_TIMING_TRANSFORM_VERSION = "timing_satellite_transform_v1"
_SECONDS_PER_DAY = 86_400.0
_EVENT_WINDOW_DAYS = 1.0
_EVENT_CONTEXT_DAYS = 30.0
_CATALYST_IMMINENT_DAYS = 7.0
_CATALYST_NEAR_TERM_DAYS = 30.0
_CATALYST_MEDIUM_TERM_DAYS = 90.0

_LOGIC_ORDER = {
    LogicCertaintyStage.RUMOR.value: 0,
    LogicCertaintyStage.EARLY_SIGNAL.value: 1,
    LogicCertaintyStage.EXPECTATION_FORMING.value: 2,
    LogicCertaintyStage.ORDER_EXPECTATION.value: 3,
    LogicCertaintyStage.ORDER_CONFIRMED.value: 4,
    LogicCertaintyStage.DELIVERY_CONFIRMED.value: 5,
    LogicCertaintyStage.REVENUE_REALIZED.value: 6,
    LogicCertaintyStage.REPEATED_VALIDATION.value: 7,
    LogicCertaintyStage.INVALIDATED.value: -1,
    LogicCertaintyStage.UNCERTAIN.value: 0,
}
_THESIS_ORDER = {
    "invalidated": -2,
    "negative": -1,
    "uncertain": 0,
    "neutral": 0,
    "positive": 1,
}
_TIMING_FAMILIES = (
    SatelliteAlphaFamily.STATE_TRANSITION,
    SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY,
    SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE,
    SatelliteAlphaFamily.RISK_ESCALATION,
    SatelliteAlphaFamily.EVIDENCE_CONFIRMATION,
    SatelliteAlphaFamily.EVENT_WINDOW,
    SatelliteAlphaFamily.CATALYST_PROXIMITY,
)


class ResearchStateTransitionBuildError(ValueError):
    """Raised when ordered frozen State inputs cannot form a transition."""


class ResearchStateTransitionBuilder:
    """Build transitions and existing Timing Satellite observations without LLMs."""

    def __init__(self) -> None:
        """Load the canonical Day45 definitions once."""

        registry = build_satellite_alpha_registry_v1()
        self._definitions = {item.family: item for item in registry.definitions}

    def select_predecessor(
        self,
        current_state: ResearchStateSnapshot,
        historical_states: tuple[ResearchStateSnapshot, ...],
    ) -> ResearchStateSnapshot | None:
        """Select the nearest strictly earlier PIT-valid State for one asset."""

        self._validate_state_at_own_cutoff(current_state)
        eligible: list[ResearchStateSnapshot] = []
        for state in historical_states:
            if state.asset_id != current_state.asset_id:
                continue
            self._validate_state_at_own_cutoff(state)
            if state.research_as_of == current_state.research_as_of:
                raise ResearchStateTransitionBuildError(
                    "same-time ResearchState is not a valid predecessor"
                )
            validate_temporal_access(
                TemporalMetadata(as_of=state.research_as_of),
                current_state.research_as_of,
            )
            eligible.append(state)
        if not eligible:
            return None
        return max(
            eligible,
            key=lambda item: (item.research_as_of, item.research_state_id),
        )

    def build_transition(
        self,
        inputs: TimingSatelliteBuildInput,
    ) -> ResearchStateTransition | None:
        """Compare the current State with its deterministic predecessor."""

        self._validate_external_inputs(inputs)
        current = inputs.current_state
        previous = self.select_predecessor(current, inputs.historical_states)
        if previous is None:
            return None

        previous_episode = self._episode_for(previous, inputs.historical_episodes)
        current_episode = inputs.current_episode
        changed_dimensions = self._changed_dimensions(previous, current)
        logic_from = self._semantic_value(previous, "satellite.logic_certainty")
        logic_to = self._semantic_value(current, "satellite.logic_certainty")
        direction = self._logic_direction(logic_from, logic_to)
        expectation_changes = self._expectation_changes(previous, current)
        thesis_change = self._thesis_change(previous, current)
        risk_changes = self._risk_changes(previous, current)
        catalyst_changes = self._prefixed_changes(
            previous,
            current,
            "satellite.catalyst.",
            "changed",
        )
        evidence_changes = self._evidence_changes(previous, current)

        missing: list[str] = []
        if logic_from is None or logic_to is None:
            missing.append("both States require a structured logic stage")
        coverage = (
            SatelliteAlphaCoverageStatus.AVAILABLE
            if not missing
            else SatelliteAlphaCoverageStatus.PARTIAL
        )
        claims, evidence = self._provenance(
            previous,
            current,
            (
                *expectation_changes,
                *risk_changes,
                *catalyst_changes,
                *evidence_changes,
            ),
        )
        event_ids = tuple(sorted(item.event_id for item in inputs.events))
        memory_ids = self._used_memory_ids(inputs.retrieved_memories, current)
        artifacts = tuple(
            sorted(
                {
                    previous.research_state_id,
                    current.research_state_id,
                    *memory_ids,
                }
            )
        )
        candidate = {
            "asset_id": str(current.asset_id),
            "previous_state_id": previous.research_state_id,
            "current_state_id": current.research_state_id,
            "previous_episode_id": (
                previous_episode.episode_id if previous_episode else None
            ),
            "current_episode_id": (
                current_episode.episode_id if current_episode else None
            ),
            "previous_as_of": previous.research_as_of.isoformat(),
            "current_as_of": current.research_as_of.isoformat(),
            "changed_dimensions": tuple(item.value for item in changed_dimensions),
            "direction": direction.value,
            "logic_stage_from": logic_from,
            "logic_stage_to": logic_to,
            "expectation_changes": self._json_changes(expectation_changes),
            "thesis_change": thesis_change.value if thesis_change else None,
            "risk_changes": self._json_changes(risk_changes),
            "catalyst_changes": self._json_changes(catalyst_changes),
            "evidence_changes": self._json_changes(evidence_changes),
            "source_claim_ids": claims,
            "source_event_ids": event_ids,
            "source_evidence_ids": evidence,
            "source_artifact_ids": artifacts,
            "coverage_status": coverage.value,
            "missing_reasons": tuple(missing),
            "transition_version": _TRANSITION_VERSION,
            "comparison_version": _COMPARISON_VERSION,
        }
        transition_id = "research_state_transition_" + _digest(candidate)
        return ResearchStateTransition(
            transition_id=transition_id,
            asset_id=current.asset_id,
            previous_state_id=previous.research_state_id,
            current_state_id=current.research_state_id,
            previous_episode_id=(
                previous_episode.episode_id if previous_episode else None
            ),
            current_episode_id=current_episode.episode_id if current_episode else None,
            previous_as_of=previous.research_as_of,
            current_as_of=current.research_as_of,
            changed_dimensions=changed_dimensions,
            direction=direction,
            logic_stage_from=logic_from,
            logic_stage_to=logic_to,
            expectation_changes=expectation_changes,
            thesis_change=thesis_change,
            risk_changes=risk_changes,
            catalyst_changes=catalyst_changes,
            evidence_changes=evidence_changes,
            source_claim_ids=claims,
            source_event_ids=event_ids,
            source_evidence_ids=evidence,
            source_artifact_ids=artifacts,
            coverage_status=coverage,
            missing_reasons=tuple(missing),
            available_at=inputs.available_at,
            created_at=inputs.created_at,
        )

    def build_timing(
        self,
        inputs: TimingSatelliteBuildInput,
    ) -> tuple[SatelliteAlphaObservation, ...]:
        """Return one truthful existing Observation for every Timing family."""

        self._validate_external_inputs(inputs)
        transition = self.build_transition(inputs)
        builders = {
            SatelliteAlphaFamily.STATE_TRANSITION: self._state_observation,
            SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY: (
                self._velocity_observation
            ),
            SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE: self._thesis_observation,
            SatelliteAlphaFamily.RISK_ESCALATION: self._risk_observation,
            SatelliteAlphaFamily.EVIDENCE_CONFIRMATION: self._evidence_observation,
            SatelliteAlphaFamily.EVENT_WINDOW: self._event_observation,
            SatelliteAlphaFamily.CATALYST_PROXIMITY: self._catalyst_observation,
        }
        return tuple(
            builders[family](inputs, transition) for family in _TIMING_FAMILIES
        )

    @staticmethod
    def _validate_state_at_own_cutoff(state: ResearchStateSnapshot) -> None:
        for section in _sections(state):
            for feature in section.features:
                validate_temporal_access(
                    TemporalMetadata(
                        event_time=feature.as_of,
                        available_at=feature.available_at or feature.as_of,
                    ),
                    state.research_as_of,
                )

    def _validate_external_inputs(self, inputs: TimingSatelliteBuildInput) -> None:
        cutoff = inputs.current_state.research_as_of
        for event in inputs.events:
            validate_temporal_access(
                TemporalMetadata(
                    source_kind=TemporalSourceKind.RESEARCH_EVIDENCE,
                    event_time=event.event_time,
                    available_at=event.available_at,
                ),
                cutoff,
            )
            if event.outcome_available_at is not None:
                validate_temporal_access(
                    TemporalMetadata(
                        source_kind=TemporalSourceKind.RESEARCH_EVIDENCE,
                        event_time=event.event_time,
                        available_at=event.outcome_available_at,
                    ),
                    cutoff,
                )
                if cutoff < event.event_time:
                    raise ResearchStateTransitionBuildError(
                        "post-event outcome cannot enter a pre-event observation"
                    )
        for memory in inputs.retrieved_memories:
            available_at = memory.available_at
            if available_at is None and memory.metadata is not None:
                available_at = memory.metadata.temporal.available_at
            validate_temporal_access(
                TemporalMetadata(
                    source_kind=TemporalSourceKind.MEMORY,
                    available_at=available_at,
                    effective_from=memory.effective_ts,
                ),
                cutoff,
            )

    def _state_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        if transition is None:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.STATE_TRANSITION,
                SatelliteAlphaCoverageStatus.REQUIRES_HISTORY,
                "nearest strictly earlier PIT ResearchState is unavailable",
            )
        if transition.logic_stage_from is None or transition.logic_stage_to is None:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.STATE_TRANSITION,
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                "both States require a structured logic stage",
                transition,
            )
        component = self._component_from_feature_names(
            "transition_direction",
            transition.direction.value,
            (transition.logic_stage_from, transition.logic_stage_to),
            ("event_state::satellite.logic_certainty",),
            transition,
        )
        return self._observation(
            inputs,
            SatelliteAlphaFamily.STATE_TRANSITION,
            transition.direction.value,
            (component,),
            SatelliteAlphaCoverageStatus.AVAILABLE,
            (),
            transition,
        )

    def _velocity_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        ordered = self._ordered_asset_history(inputs)
        if len(ordered) < 2:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY,
                SatelliteAlphaCoverageStatus.REQUIRES_HISTORY,
                "at least two PIT-valid expectation States are required",
                transition,
            )
        numeric = [
            (
                state,
                self._numeric_feature(state, "satellite.expectation_revision.value"),
            )
            for state in ordered
        ]
        if numeric[-1][1] is None or numeric[-2][1] is None:
            direction = self._semantic_value(
                ordered[-1], "satellite.expectation_revision.direction"
            )
            if direction is None:
                return self._missing_observation(
                    inputs,
                    SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY,
                    SatelliteAlphaCoverageStatus.MISSING_INPUT,
                    "grounded numeric expectation or categorical direction is absent",
                    transition,
                )
            component = self._feature_component(
                "direction",
                direction,
                ordered[-1],
                "satellite.expectation_revision.direction",
            )
            return self._observation(
                inputs,
                SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY,
                direction,
                (component,),
                SatelliteAlphaCoverageStatus.PARTIAL,
                ("numeric delta and elapsed-time rate are not grounded",),
                transition,
            )

        earlier_state, earlier_feature = numeric[-2]
        current_state, current_feature = numeric[-1]
        assert earlier_feature is not None and current_feature is not None
        elapsed_days = (
            current_state.research_as_of - earlier_state.research_as_of
        ).total_seconds() / _SECONDS_PER_DAY
        earlier_value = earlier_feature.value
        current_value = current_feature.value
        assert isinstance(earlier_value, (int, float)) and not isinstance(
            earlier_value, bool
        )
        assert isinstance(current_value, (int, float)) and not isinstance(
            current_value, bool
        )
        delta = float(current_value) - float(earlier_value)
        rate = delta / elapsed_days
        direction = (
            "upgrade" if delta > 0 else "downgrade" if delta < 0 else "unchanged"
        )
        refs = ("thesis_state::satellite.expectation_revision.value",)
        components = [
            self._component_from_features(
                "direction", direction, (earlier_feature, current_feature), refs
            ),
            self._numeric_component(
                "delta",
                delta,
                "expectation_unit",
                "absolute_change",
                refs,
                (earlier_feature, current_feature),
            ),
            self._numeric_component(
                "change_rate",
                rate,
                "expectation_unit_per_day",
                "calendar_day_rate",
                refs,
                (earlier_feature, current_feature),
            ),
        ]
        coverage = SatelliteAlphaCoverageStatus.PARTIAL
        missing: tuple[str, ...] = (
            "two points establish direction/rate but not acceleration or deceleration",
        )
        if len(numeric) >= 3 and numeric[-3][1] is not None:
            oldest_state, oldest_feature = numeric[-3]
            assert oldest_feature is not None
            oldest_value = oldest_feature.value
            assert isinstance(oldest_value, (int, float)) and not isinstance(
                oldest_value, bool
            )
            prior_elapsed = (
                earlier_state.research_as_of - oldest_state.research_as_of
            ).total_seconds() / _SECONDS_PER_DAY
            prior_rate = (float(earlier_value) - float(oldest_value)) / prior_elapsed
            rate_change = rate - prior_rate
            second_order = (
                ExpectationChangeOrder.ACCELERATING
                if abs(rate) > abs(prior_rate)
                else (
                    ExpectationChangeOrder.DECELERATING
                    if abs(rate) < abs(prior_rate)
                    else ExpectationChangeOrder.STEADY
                )
            )
            three = (oldest_feature, earlier_feature, current_feature)
            components.extend(
                (
                    self._component_from_features(
                        "second_order_change", second_order.value, three, refs
                    ),
                    self._numeric_component(
                        "change_rate_delta",
                        rate_change,
                        "expectation_unit_per_day_squared",
                        "calendar_day_rate_change",
                        refs,
                        three,
                    ),
                )
            )
            coverage = SatelliteAlphaCoverageStatus.AVAILABLE
            missing = ()
        return self._observation(
            inputs,
            SatelliteAlphaFamily.EXPECTATION_REVISION_VELOCITY,
            direction,
            tuple(components),
            coverage,
            missing,
            transition,
        )

    def _thesis_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        if transition is None:
            return self._history_or_source_missing(
                inputs, SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE
            )
        if transition.thesis_change is None:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE,
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                "comparable structured thesis disposition is absent",
                transition,
            )
        component = self._component_from_feature_names(
            "thesis_change",
            transition.thesis_change.value,
            (),
            ("thesis_state::satellite.thesis.disposition",),
            transition,
        )
        return self._observation(
            inputs,
            SatelliteAlphaFamily.THESIS_UPGRADE_DOWNGRADE,
            transition.thesis_change.value,
            (component,),
            SatelliteAlphaCoverageStatus.AVAILABLE,
            (),
            transition,
        )

    def _risk_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        if transition is None:
            return self._history_or_source_missing(
                inputs, SatelliteAlphaFamily.RISK_ESCALATION
            )
        if not transition.risk_changes:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.RISK_ESCALATION,
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                "comparable structured risk components are absent",
                transition,
            )
        components = tuple(
            self._component_from_change(item, transition)
            for item in transition.risk_changes
        )
        statuses = {item.classification for item in transition.risk_changes}
        value = (
            next(iter(statuses))
            if len(statuses) == 1
            else RiskTransitionStatus.MIXED.value
        )
        return self._observation(
            inputs,
            SatelliteAlphaFamily.RISK_ESCALATION,
            value,
            components,
            SatelliteAlphaCoverageStatus.AVAILABLE,
            (),
            transition,
        )

    def _evidence_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        if transition is None:
            return self._history_or_source_missing(
                inputs, SatelliteAlphaFamily.EVIDENCE_CONFIRMATION
            )
        if not transition.evidence_changes:
            return self._missing_observation(
                inputs,
                SatelliteAlphaFamily.EVIDENCE_CONFIRMATION,
                SatelliteAlphaCoverageStatus.MISSING_INPUT,
                "prior hypothesis to later distinct Evidence linkage is absent",
                transition,
            )
        components = tuple(
            self._component_from_change(item, transition)
            for item in transition.evidence_changes
        )
        statuses = {item.classification for item in transition.evidence_changes}
        value = (
            next(iter(statuses))
            if len(statuses) == 1
            else EvidenceTransitionStatus.MIXED.value
        )
        partial = EvidenceTransitionStatus.UNRESOLVED.value in statuses
        return self._observation(
            inputs,
            SatelliteAlphaFamily.EVIDENCE_CONFIRMATION,
            value,
            components,
            (
                SatelliteAlphaCoverageStatus.PARTIAL
                if partial
                else SatelliteAlphaCoverageStatus.AVAILABLE
            ),
            (
                ("later Evidence is not distinct from the prior hypothesis Evidence",)
                if partial
                else ()
            ),
            transition,
        )

    def _event_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        events = tuple(
            item for item in inputs.events if item.kind is TimingEventKind.EVENT
        )
        if not events:
            return self._source_event_missing(
                inputs, SatelliteAlphaFamily.EVENT_WINDOW, transition
            )
        event = min(
            events,
            key=lambda item: (
                abs(
                    (
                        item.event_time - inputs.current_state.research_as_of
                    ).total_seconds()
                ),
                item.event_id,
            ),
        )
        days = (
            event.event_time - inputs.current_state.research_as_of
        ).total_seconds() / _SECONDS_PER_DAY
        if days > _EVENT_CONTEXT_DAYS or days < -_EVENT_CONTEXT_DAYS:
            position = EventWindowPosition.OUTSIDE_WINDOW
        elif days > _EVENT_WINDOW_DAYS:
            position = EventWindowPosition.PRE_EVENT
        elif days >= -_EVENT_WINDOW_DAYS:
            position = EventWindowPosition.EVENT_WINDOW
        else:
            position = EventWindowPosition.POST_EVENT
        components = (
            self._event_component("window_position", position.value, event),
            self._event_numeric_component("distance_to_event_days", days, event),
        )
        return self._observation(
            inputs,
            SatelliteAlphaFamily.EVENT_WINDOW,
            position.value,
            components,
            SatelliteAlphaCoverageStatus.AVAILABLE,
            (),
            transition,
            event_ids=(event.event_id,),
        )

    def _catalyst_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        catalysts = tuple(
            item
            for item in inputs.events
            if item.kind is TimingEventKind.CATALYST
            and item.event_time >= inputs.current_state.research_as_of
        )
        if not catalysts:
            return self._source_event_missing(
                inputs, SatelliteAlphaFamily.CATALYST_PROXIMITY, transition
            )
        catalyst = min(catalysts, key=lambda item: (item.event_time, item.event_id))
        days = (
            catalyst.event_time - inputs.current_state.research_as_of
        ).total_seconds() / _SECONDS_PER_DAY
        proximity = (
            CatalystProximity.IMMINENT
            if days <= _CATALYST_IMMINENT_DAYS
            else (
                CatalystProximity.NEAR_TERM
                if days <= _CATALYST_NEAR_TERM_DAYS
                else (
                    CatalystProximity.MEDIUM_TERM
                    if days <= _CATALYST_MEDIUM_TERM_DAYS
                    else CatalystProximity.DISTANT
                )
            )
        )
        components = (
            self._event_component("proximity", proximity.value, catalyst),
            self._event_numeric_component("distance_to_catalyst_days", days, catalyst),
        )
        return self._observation(
            inputs,
            SatelliteAlphaFamily.CATALYST_PROXIMITY,
            proximity.value,
            components,
            SatelliteAlphaCoverageStatus.AVAILABLE,
            (),
            transition,
            event_ids=(catalyst.event_id,),
        )

    def _observation(
        self,
        inputs: TimingSatelliteBuildInput,
        family: SatelliteAlphaFamily,
        value: str | None,
        components: tuple[SatelliteAlphaComponent, ...],
        coverage: SatelliteAlphaCoverageStatus,
        missing: tuple[str, ...],
        transition: ResearchStateTransition | None,
        *,
        event_ids: tuple[str, ...] = (),
    ) -> SatelliteAlphaObservation:
        definition = self._definitions[family]
        current = inputs.current_state
        claims = tuple(
            sorted({ref for item in components for ref in item.source_claim_ids})
        )
        evidence = tuple(
            sorted({ref for item in components for ref in item.source_evidence_ids})
        )
        feature_refs = tuple(
            sorted(
                {ref for item in components for ref in item.source_state_feature_refs}
            )
        )
        memory_ids = self._used_memory_ids(inputs.retrieved_memories, current)
        artifacts = tuple(
            sorted(
                {
                    current.research_state_id,
                    *(transition.source_artifact_ids if transition else ()),
                    *memory_ids,
                    *(ref for item in components for ref in item.source_artifact_ids),
                }
            )
        )
        candidate = {
            "family": family.value,
            "asset_id": str(current.asset_id),
            "research_as_of": current.research_as_of.isoformat(),
            "value": value,
            "components": [item.model_dump(mode="json") for item in components],
            "coverage": coverage.value,
            "missing": missing,
            "current_state_id": current.research_state_id,
            "previous_state_id": transition.previous_state_id if transition else None,
            "transition_id": transition.transition_id if transition else None,
            "episode_id": (
                inputs.current_episode.episode_id if inputs.current_episode else None
            ),
            "event_ids": event_ids,
            "artifacts": artifacts,
            "definition_version": definition.definition_version,
            "transform_version": _TIMING_TRANSFORM_VERSION,
        }
        return SatelliteAlphaObservation(
            observation_id="satellite_alpha_" + _digest(candidate),
            satellite_alpha_id=family,
            asset_id=current.asset_id,
            market=current.asset_id.market,
            chain_ids=tuple(
                sorted(
                    scope.removeprefix("CHAIN:")
                    for scope in current.hierarchy.industry_chain_scope_ids
                )
            ),
            research_as_of=current.research_as_of,
            available_at=inputs.available_at,
            usage=(
                SatelliteAlphaUsage.TIMING
                if definition.usage is not SatelliteAlphaUsage.BOTH
                else SatelliteAlphaUsage.BOTH
            ),
            value=value,
            value_components=components,
            quality=self._quality(coverage),
            coverage_status=coverage,
            comparison_scope=SatelliteAlphaComparisonScope.ASSET_TIME_SERIES,
            missing_reasons=missing,
            source_research_state_id=current.research_state_id,
            previous_research_state_id=(
                transition.previous_state_id if transition else None
            ),
            source_transition_id=transition.transition_id if transition else None,
            source_episode_id=(
                inputs.current_episode.episode_id if inputs.current_episode else None
            ),
            source_state_feature_refs=feature_refs,
            source_claim_ids=claims,
            source_event_ids=event_ids,
            source_evidence_ids=evidence,
            source_artifact_ids=artifacts,
            data_snapshot_id=current.lineage.data_snapshot_id,
            definition_version=definition.definition_version,
            transform_version=_TIMING_TRANSFORM_VERSION,
            created_at=inputs.created_at,
        )

    def _missing_observation(
        self,
        inputs: TimingSatelliteBuildInput,
        family: SatelliteAlphaFamily,
        coverage: SatelliteAlphaCoverageStatus,
        reason: str,
        transition: ResearchStateTransition | None = None,
    ) -> SatelliteAlphaObservation:
        return self._observation(
            inputs, family, None, (), coverage, (reason,), transition
        )

    def _history_or_source_missing(
        self, inputs: TimingSatelliteBuildInput, family: SatelliteAlphaFamily
    ) -> SatelliteAlphaObservation:
        definition = self._definitions[family]
        statuses = tuple(
            getattr(inputs.current_state, name.value).status
            for name in definition.source_dimensions
        )
        coverage = (
            SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
            if statuses
            and all(
                item is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
                for item in statuses
            )
            else SatelliteAlphaCoverageStatus.REQUIRES_HISTORY
        )
        reason = (
            "structured source semantics were not available at the source run"
            if coverage is SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
            else "nearest strictly earlier PIT ResearchState is unavailable"
        )
        return self._missing_observation(inputs, family, coverage, reason)

    def _source_event_missing(
        self,
        inputs: TimingSatelliteBuildInput,
        family: SatelliteAlphaFamily,
        transition: ResearchStateTransition | None,
    ) -> SatelliteAlphaObservation:
        status = inputs.current_state.event_state.status
        coverage = (
            SatelliteAlphaCoverageStatus.NOT_AVAILABLE_AT_SOURCE_RUN
            if status is ResearchStateSectionStatus.NOT_AVAILABLE_AT_SOURCE_RUN
            else SatelliteAlphaCoverageStatus.MISSING_INPUT
        )
        return self._missing_observation(
            inputs,
            family,
            coverage,
            "canonical PIT-visible event identity and timestamp are unavailable",
            transition,
        )

    @staticmethod
    def _quality(coverage: SatelliteAlphaCoverageStatus) -> DataQualityStatus:
        return (
            DataQualityStatus.PASS
            if coverage
            in {
                SatelliteAlphaCoverageStatus.AVAILABLE,
                SatelliteAlphaCoverageStatus.PARTIAL,
            }
            else DataQualityStatus.UNKNOWN
        )

    @staticmethod
    def _episode_for(
        state: ResearchStateSnapshot, episodes: tuple[ResearchEpisode, ...]
    ) -> ResearchEpisode | None:
        return next(
            (
                item
                for item in episodes
                if item.research_state_id == state.research_state_id
            ),
            None,
        )

    def _ordered_asset_history(
        self, inputs: TimingSatelliteBuildInput
    ) -> tuple[ResearchStateSnapshot, ...]:
        current = inputs.current_state
        prior = [
            item
            for item in inputs.historical_states
            if item.asset_id == current.asset_id
        ]
        for item in prior:
            if item.research_as_of == current.research_as_of:
                raise ResearchStateTransitionBuildError(
                    "same-time ResearchState is not a valid predecessor"
                )
            validate_temporal_access(
                TemporalMetadata(as_of=item.research_as_of), current.research_as_of
            )
            self._validate_state_at_own_cutoff(item)
        return tuple(
            sorted(
                (*prior, current),
                key=lambda item: (item.research_as_of, item.research_state_id),
            )
        )

    @staticmethod
    def _semantic_value(state: ResearchStateSnapshot, name: str) -> str | None:
        found = _find_feature(state, name)
        return (
            found[1].value
            if found is not None and isinstance(found[1].value, str)
            else None
        )

    @staticmethod
    def _numeric_feature(
        state: ResearchStateSnapshot, name: str
    ) -> ResearchStateFeature | None:
        found = _find_feature(state, name)
        if (
            found is None
            or isinstance(found[1].value, bool)
            or not isinstance(found[1].value, (int, float))
        ):
            return None
        return found[1]

    @staticmethod
    def _logic_direction(
        previous: str | None, current: str | None
    ) -> ResearchStateTransitionDirection:
        if (
            previous is None
            or current is None
            or previous not in _LOGIC_ORDER
            or current not in _LOGIC_ORDER
        ):
            return ResearchStateTransitionDirection.UNKNOWN
        if previous == current:
            return ResearchStateTransitionDirection.UNCHANGED
        if current == LogicCertaintyStage.INVALIDATED.value:
            return ResearchStateTransitionDirection.DOWNGRADE
        if _LOGIC_ORDER[current] > _LOGIC_ORDER[previous]:
            return ResearchStateTransitionDirection.UPGRADE
        if _LOGIC_ORDER[current] < _LOGIC_ORDER[previous]:
            return ResearchStateTransitionDirection.DOWNGRADE
        return ResearchStateTransitionDirection.MIXED

    def _expectation_changes(
        self, previous: ResearchStateSnapshot, current: ResearchStateSnapshot
    ) -> tuple[ResearchStateValueChange, ...]:
        return self._named_changes(
            previous,
            current,
            (
                "satellite.expectation_revision.direction",
                "satellite.expectation_revision.value",
            ),
            "changed",
        )

    def _thesis_change(
        self, previous: ResearchStateSnapshot, current: ResearchStateSnapshot
    ) -> ThesisTransitionStatus | None:
        before = self._semantic_value(previous, "satellite.thesis.disposition")
        after = self._semantic_value(current, "satellite.thesis.disposition")
        if (
            before is None
            or after is None
            or before not in _THESIS_ORDER
            or after not in _THESIS_ORDER
        ):
            return None
        if after == "invalidated":
            return ThesisTransitionStatus.INVALIDATED
        if _THESIS_ORDER[after] > _THESIS_ORDER[before]:
            return ThesisTransitionStatus.UPGRADED
        if _THESIS_ORDER[after] < _THESIS_ORDER[before]:
            return ThesisTransitionStatus.DOWNGRADED
        if before == after:
            return ThesisTransitionStatus.UNCHANGED
        return ThesisTransitionStatus.UNCERTAIN

    def _risk_changes(
        self, previous: ResearchStateSnapshot, current: ResearchStateSnapshot
    ) -> tuple[ResearchStateValueChange, ...]:
        if previous.risk_state.status not in {
            ResearchStateSectionStatus.PRESENT,
            ResearchStateSectionStatus.PARTIAL,
        } or current.risk_state.status not in {
            ResearchStateSectionStatus.PRESENT,
            ResearchStateSectionStatus.PARTIAL,
        }:
            return ()
        before = {
            feature.feature_name: feature
            for feature in previous.risk_state.features
            if feature.feature_name.startswith("satellite.risk.")
        }
        after = {
            feature.feature_name: feature
            for feature in current.risk_state.features
            if feature.feature_name.startswith("satellite.risk.")
        }
        changes: list[ResearchStateValueChange] = []
        for name in sorted(set(before) | set(after)):
            left, right = before.get(name), after.get(name)
            if left is None and right is not None:
                classification = RiskTransitionStatus.NEW_RISK.value
            elif right is None:
                classification = RiskTransitionStatus.UNCERTAIN.value
            elif right.value == "resolved":
                classification = RiskTransitionStatus.RESOLVED.value
            elif right.value == "escalating":
                classification = RiskTransitionStatus.ESCALATING.value
            elif right.value == "deescalating":
                classification = RiskTransitionStatus.DEESCALATING.value
            elif left is not None and left.value == right.value:
                classification = RiskTransitionStatus.STABLE.value
            else:
                classification = RiskTransitionStatus.UNCERTAIN.value
            changes.append(
                self._make_change(
                    name,
                    left,
                    right,
                    classification,
                    ResearchStateSectionName.RISK,
                    previous,
                    current,
                )
            )
        return tuple(changes)

    def _evidence_changes(
        self, previous: ResearchStateSnapshot, current: ResearchStateSnapshot
    ) -> tuple[ResearchStateValueChange, ...]:
        before = _prefixed_feature_map(previous, "satellite.hypothesis.")
        after = _prefixed_feature_map(current, "satellite.hypothesis.")
        changes: list[ResearchStateValueChange] = []
        allowed = {item.value for item in EvidenceTransitionStatus}
        for name in sorted(set(before) & set(after)):
            left_section, left = before[name]
            right_section, right = after[name]
            status = (
                str(right.value)
                if right.value in allowed
                else EvidenceTransitionStatus.UNRESOLVED.value
            )
            if not (set(right.source_evidence_ids) - set(left.source_evidence_ids)):
                status = EvidenceTransitionStatus.UNRESOLVED.value
            changes.append(
                self._make_change(
                    name,
                    left,
                    right,
                    status,
                    right_section,
                    previous,
                    current,
                    left_section,
                )
            )
        return tuple(changes)

    def _prefixed_changes(
        self,
        previous: ResearchStateSnapshot,
        current: ResearchStateSnapshot,
        prefix: str,
        classification: str,
    ) -> tuple[ResearchStateValueChange, ...]:
        before = _prefixed_feature_map(previous, prefix)
        after = _prefixed_feature_map(current, prefix)
        changes = []
        for name in sorted(set(before) & set(after)):
            left_section, left = before[name]
            right_section, right = after[name]
            if left.value != right.value:
                changes.append(
                    self._make_change(
                        name,
                        left,
                        right,
                        classification,
                        right_section,
                        previous,
                        current,
                        left_section,
                    )
                )
        return tuple(changes)

    def _named_changes(
        self,
        previous: ResearchStateSnapshot,
        current: ResearchStateSnapshot,
        names: tuple[str, ...],
        classification: str,
    ) -> tuple[ResearchStateValueChange, ...]:
        changes = []
        for name in names:
            left_found, right_found = _find_feature(previous, name), _find_feature(
                current, name
            )
            if left_found is None or right_found is None:
                continue
            left_section, left = left_found
            right_section, right = right_found
            if not _compatible(left, right):
                continue
            changes.append(
                self._make_change(
                    name,
                    left,
                    right,
                    classification if left.value != right.value else "unchanged",
                    right_section,
                    previous,
                    current,
                    left_section,
                )
            )
        return tuple(changes)

    @staticmethod
    def _make_change(
        name: str,
        left: ResearchStateFeature | None,
        right: ResearchStateFeature | None,
        classification: str,
        section: ResearchStateSectionName,
        previous: ResearchStateSnapshot,
        current: ResearchStateSnapshot,
        left_section: ResearchStateSectionName | None = None,
    ) -> ResearchStateValueChange:
        features = tuple(item for item in (left, right) if item is not None)
        refs = tuple(
            dict.fromkeys(
                (
                    f"{(left_section or section).value}::{name}",
                    f"{section.value}::{name}",
                )
            )
        )
        return ResearchStateValueChange(
            change_key=name,
            previous_value=left.value if left else None,
            current_value=right.value if right else None,
            classification=classification,
            source_state_feature_refs=refs,
            source_claim_ids=tuple(
                sorted({ref for item in features for ref in item.source_claim_ids})
            ),
            source_evidence_ids=tuple(
                sorted({ref for item in features for ref in item.source_evidence_ids})
            ),
            source_artifact_ids=(previous.research_state_id, current.research_state_id),
        )

    @staticmethod
    def _changed_dimensions(
        previous: ResearchStateSnapshot, current: ResearchStateSnapshot
    ) -> tuple[ResearchStateSectionName, ...]:
        changed = []
        for name in ResearchStateSectionName:
            left = {
                item.feature_name: item
                for item in getattr(previous, name.value).features
            }
            right = {
                item.feature_name: item
                for item in getattr(current, name.value).features
            }
            common_changed = any(
                _compatible(left[key], right[key])
                and left[key].value != right[key].value
                for key in set(left) & set(right)
            )
            if common_changed or set(left) != set(right):
                changed.append(name)
        return tuple(changed)

    @staticmethod
    def _provenance(
        previous: ResearchStateSnapshot,
        current: ResearchStateSnapshot,
        changes: tuple[ResearchStateValueChange, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        logic_features = tuple(
            item[1]
            for state in (previous, current)
            if (item := _find_feature(state, "satellite.logic_certainty")) is not None
        )
        claims = tuple(
            sorted(
                {ref for feature in logic_features for ref in feature.source_claim_ids}
                | {ref for change in changes for ref in change.source_claim_ids}
            )
        )
        evidence = tuple(
            sorted(
                {
                    ref
                    for feature in logic_features
                    for ref in feature.source_evidence_ids
                }
                | {ref for change in changes for ref in change.source_evidence_ids}
            )
        )
        return claims, evidence

    @staticmethod
    def _json_changes(
        changes: tuple[ResearchStateValueChange, ...],
    ) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in changes]

    @staticmethod
    def _used_memory_ids(
        memories: tuple[MemorySearchResult, ...], state: ResearchStateSnapshot
    ) -> tuple[str, ...]:
        state_claims = {
            claim
            for section in _sections(state)
            for feature in section.features
            for claim in feature.source_claim_ids
        }
        return tuple(
            sorted(
                memory.memory_id
                for memory in memories
                if memory.metadata is not None
                and set(memory.metadata.source_claim_ids) & state_claims
            )
        )

    @staticmethod
    def _component_from_change(
        change: ResearchStateValueChange, transition: ResearchStateTransition
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=_safe_component_name(change.change_key),
            value=change.classification,
            source_state_feature_refs=change.source_state_feature_refs,
            source_claim_ids=change.source_claim_ids,
            source_evidence_ids=change.source_evidence_ids,
            source_artifact_ids=tuple(
                sorted({*change.source_artifact_ids, transition.transition_id})
            ),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )

    @staticmethod
    def _component_from_feature_names(
        name: str,
        value: str,
        raw_values: tuple[str, ...],
        refs: tuple[str, ...],
        transition: ResearchStateTransition,
    ) -> SatelliteAlphaComponent:
        del raw_values
        return SatelliteAlphaComponent(
            component_name=name,
            value=value,
            source_state_feature_refs=refs,
            source_claim_ids=transition.source_claim_ids,
            source_evidence_ids=transition.source_evidence_ids,
            source_artifact_ids=(transition.transition_id,),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )

    @staticmethod
    def _component_from_features(
        name: str,
        value: str,
        features: tuple[ResearchStateFeature, ...],
        refs: tuple[str, ...],
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=name,
            value=value,
            source_state_feature_refs=refs,
            source_claim_ids=tuple(
                sorted({ref for item in features for ref in item.source_claim_ids})
            ),
            source_evidence_ids=tuple(
                sorted({ref for item in features for ref in item.source_evidence_ids})
            ),
            source_artifact_ids=tuple(
                sorted({ref for item in features for ref in item.source_artifact_ids})
            ),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )

    def _feature_component(
        self, name: str, value: str, state: ResearchStateSnapshot, feature_name: str
    ) -> SatelliteAlphaComponent:
        found = _find_feature(state, feature_name)
        assert found is not None
        section, feature = found
        return self._component_from_features(
            name, value, (feature,), (f"{section.value}::{feature_name}",)
        )

    @staticmethod
    def _numeric_component(
        name: str,
        value: float,
        unit: str,
        scale: str,
        refs: tuple[str, ...],
        features: tuple[ResearchStateFeature, ...],
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=name,
            value=value,
            unit=unit,
            scale=scale,
            source_state_feature_refs=refs,
            source_claim_ids=tuple(
                sorted({ref for item in features for ref in item.source_claim_ids})
            ),
            source_evidence_ids=tuple(
                sorted({ref for item in features for ref in item.source_evidence_ids})
            ),
            source_artifact_ids=tuple(
                sorted({ref for item in features for ref in item.source_artifact_ids})
            ),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )

    @staticmethod
    def _event_component(
        name: str, value: str, event: TimingEventReference
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=name,
            value=value,
            source_state_feature_refs=(event.source_state_feature_ref,),
            source_claim_ids=event.source_claim_ids,
            source_evidence_ids=event.source_evidence_ids,
            source_artifact_ids=(event.event_id,),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )

    @staticmethod
    def _event_numeric_component(
        name: str, value: float, event: TimingEventReference
    ) -> SatelliteAlphaComponent:
        return SatelliteAlphaComponent(
            component_name=name,
            value=value,
            unit="calendar_day",
            scale="signed_distance",
            source_state_feature_refs=(event.source_state_feature_ref,),
            source_claim_ids=event.source_claim_ids,
            source_evidence_ids=event.source_evidence_ids,
            source_artifact_ids=(event.event_id,),
            transform_version=_TIMING_TRANSFORM_VERSION,
        )


def _sections(state: ResearchStateSnapshot) -> tuple[ResearchStateSection, ...]:
    return tuple(getattr(state, name.value) for name in ResearchStateSectionName)


def _find_feature(
    state: ResearchStateSnapshot, feature_name: str
) -> tuple[ResearchStateSectionName, ResearchStateFeature] | None:
    return next(
        (
            (section.section_name, feature)
            for section in _sections(state)
            for feature in section.features
            if feature.feature_name == feature_name
        ),
        None,
    )


def _prefixed_feature_map(
    state: ResearchStateSnapshot, prefix: str
) -> dict[str, tuple[ResearchStateSectionName, ResearchStateFeature]]:
    return {
        feature.feature_name: (section.section_name, feature)
        for section in _sections(state)
        for feature in section.features
        if feature.feature_name.startswith(prefix)
    }


def _compatible(previous: ResearchStateFeature, current: ResearchStateFeature) -> bool:
    return (
        previous.feature_type,
        previous.feature_version,
        previous.transform_name,
        previous.transform_version,
    ) == (
        current.feature_type,
        current.feature_version,
        current.transform_name,
        current.transform_version,
    )


def _safe_component_name(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "_" for character in value.lower()
    ).strip("_")
    return normalized[-80:] if len(normalized) > 80 else normalized


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:24]
