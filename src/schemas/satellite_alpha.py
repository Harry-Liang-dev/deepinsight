"""Versioned Satellite Alpha research-descriptor contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.enums import AgentName, Market, SectorAnomalyType, SectorId
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonScalar
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSectionName, ResearchStateSnapshot
from src.schemas.temporal import TemporalMetadata, require_utc_aware

if TYPE_CHECKING:
    from src.schemas.sector_context import SectorContextBundle


class SatelliteAlphaUsage(StrEnum):
    """Intended research use, never a selection or timing decision."""

    SELECTION = "selection"
    TIMING = "timing"
    BOTH = "both"


class SatelliteAlphaComparisonScope(StrEnum):
    """Descriptive comparison frame without ranking or normalization."""

    MARKET = "market"
    SECTOR = "sector"
    INDUSTRY_CHAIN = "industry_chain"
    PEER_GROUP = "peer_group"
    ASSET_TIME_SERIES = "asset_time_series"


class SatelliteAlphaCoverageStatus(StrEnum):
    """Truthful availability states; absence is never numeric zero."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    EMPTY_VALID = "empty_valid"
    MISSING_INPUT = "missing_input"
    NOT_RESEARCHED = "not_researched"
    NOT_AVAILABLE_AT_SOURCE_RUN = "not_available_at_source_run"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_HISTORY = "requires_history"
    UNSUPPORTED = "unsupported"


class SatelliteAlphaDefinitionStatus(StrEnum):
    """Implementation maturity of one ontology definition."""

    IMPLEMENTED = "implemented"
    SCHEMA_READY = "schema_ready"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class SatelliteAlphaValueType(StrEnum):
    """Supported descriptor shapes; complex semantics need not be scalar."""

    CATEGORICAL = "categorical"
    NUMERIC = "numeric"
    MULTI_COMPONENT = "multi_component"


class SatelliteAlphaFamily(StrEnum):
    """Closed Day45 Selection and Timing ontology families."""

    CHAIN_BENEFIT_ELASTICITY = "chain_benefit_elasticity"
    EXPECTATION_REVISION = "expectation_revision"
    LOGIC_CERTAINTY = "logic_certainty"
    RISK_BURDEN = "risk_burden"
    EVIDENCE_STRENGTH = "evidence_strength"
    SECTOR_CHAIN_ALIGNMENT = "sector_chain_alignment"
    RESEARCH_DISAGREEMENT = "research_disagreement"
    STATE_TRANSITION = "state_transition"
    EXPECTATION_REVISION_VELOCITY = "expectation_revision_velocity"
    EVENT_WINDOW = "event_window"
    THESIS_UPGRADE_DOWNGRADE = "thesis_upgrade_downgrade"
    RISK_ESCALATION = "risk_escalation"
    EVIDENCE_CONFIRMATION = "evidence_confirmation"
    CATALYST_PROXIMITY = "catalyst_proximity"


class ExpectationRevisionDirection(StrEnum):
    """Finite expectation-change vocabulary, not a score."""

    UPGRADE = "upgrade"
    UNCHANGED = "unchanged"
    DOWNGRADE = "downgrade"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"


class ExpectationRevisionSubtype(StrEnum):
    """Research dimensions on which an expectation may change."""

    EARNINGS = "earnings"
    ORDER = "order"
    DEMAND = "demand"
    CAPACITY = "capacity"
    MARGIN = "margin"
    CAPEX = "capex"
    GUIDANCE = "guidance"


class LogicCertaintyStage(StrEnum):
    """Versioned evidence-progress vocabulary; values are not probabilities."""

    RUMOR = "rumor"
    EARLY_SIGNAL = "early_signal"
    EXPECTATION_FORMING = "expectation_forming"
    ORDER_EXPECTATION = "order_expectation"
    ORDER_CONFIRMED = "order_confirmed"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    REVENUE_REALIZED = "revenue_realized"
    REPEATED_VALIDATION = "repeated_validation"
    INVALIDATED = "invalidated"
    UNCERTAIN = "uncertain"


class SectorChainAlignmentState(StrEnum):
    """Alignment semantics that do not equate context presence with support."""

    POSITIVE_ALIGNMENT = "positive_alignment"
    NEGATIVE_ALIGNMENT = "negative_alignment"
    MIXED = "mixed"
    WEAK_RELATION = "weak_relation"
    UNCERTAIN = "uncertain"


class ResearchDisagreementState(StrEnum):
    """Structured debate dispositions without private model reasoning."""

    CONSENSUS_POSITIVE = "consensus_positive"
    CONSENSUS_NEGATIVE = "consensus_negative"
    HIGH_DISAGREEMENT = "high_disagreement"
    RISK_DOMINANT = "risk_dominant"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"


class ResearchStateSemanticDimension(StrEnum):
    """Day45 audit dimensions over the frozen State contract."""

    LOGIC_STAGE = "logic_stage"
    EXPECTATION_DIRECTION = "expectation_direction"
    RISK_TAXONOMY = "risk_taxonomy"
    CATALYST = "catalyst"
    INVALIDATOR = "invalidator"
    SECTOR_CHAIN_RELATIONSHIP = "sector_chain_relationship"
    RESEARCH_DISAGREEMENT = "research_disagreement"
    EVENT_TIMING = "event_timing"


class ResearchStateSupportLevel(StrEnum):
    """Honest semantic support available from ResearchState v1."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    MISSING = "missing"


class SatelliteAlphaDefinition(DomainModel):
    """Stable machine-readable definition separate from observations."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    satellite_alpha_id: SatelliteAlphaFamily
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    family: SatelliteAlphaFamily
    usage: SatelliteAlphaUsage
    value_type: SatelliteAlphaValueType
    allowed_values: tuple[str, ...] = ()
    source_dimensions: tuple[ResearchStateSectionName, ...]
    source_state_fields: tuple[str, ...] = ()
    source_claim_roles: tuple[AgentName, ...] = ()
    source_event_types: tuple[SectorAnomalyType, ...] = ()
    comparison_scope: SatelliteAlphaComparisonScope
    missing_semantics: str = Field(min_length=1)
    direction_semantics: str = Field(min_length=1)
    aggregation_semantics: str = Field(min_length=1)
    requires_history: bool = False
    minimum_history_points: int = Field(default=1, ge=1)
    deterministic_transform_version: str = Field(min_length=1)
    definition_version: Literal["satellite_alpha_definition_v1"] = (
        "satellite_alpha_definition_v1"
    )
    status: SatelliteAlphaDefinitionStatus
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC ontology creation time."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        """Keep identity, value vocabulary, and history semantics coherent."""

        if self.satellite_alpha_id is not self.family:
            raise ValueError("Satellite definition family identity is inconsistent")
        groups = (
            self.allowed_values,
            self.source_dimensions,
            self.source_state_fields,
            self.source_claim_roles,
            self.source_event_types,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("Satellite definition values must be unique")
        if self.value_type is SatelliteAlphaValueType.CATEGORICAL:
            if not self.allowed_values:
                raise ValueError(
                    "categorical Satellite definition needs allowed values"
                )
        elif self.allowed_values:
            raise ValueError("only categorical definitions declare allowed values")
        if self.requires_history and self.minimum_history_points < 2:
            raise ValueError("history-required Satellite needs at least two points")
        if not self.requires_history and self.minimum_history_points != 1:
            raise ValueError("single-state Satellite must require exactly one point")
        if (
            self.comparison_scope is SatelliteAlphaComparisonScope.PEER_GROUP
            and self.status is not SatelliteAlphaDefinitionStatus.UNSUPPORTED
        ):
            raise ValueError("PEER_GROUP lacks a supported PIT contract")
        return self


class SatelliteAlphaComponent(DomainModel):
    """One attributable categorical or numeric part of an observation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    component_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    value: JsonScalar
    unit: str | None = Field(default=None, min_length=1)
    scale: str | None = Field(default=None, min_length=1)
    source_state_feature_refs: tuple[str, ...] = Field(min_length=1)
    source_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    transform_version: str = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def reject_execution_value(cls, value: JsonScalar) -> JsonScalar:
        """Reject direct decision semantics at the component boundary."""

        return _reject_execution_semantics(value)

    @model_validator(mode="after")
    def validate_component(self) -> Self:
        """Require section-qualified, attributable, typed component values."""

        groups = (
            self.source_state_feature_refs,
            self.source_claim_ids,
            self.source_evidence_ids,
            self.source_artifact_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("Satellite component provenance must be unique")
        if any("::" not in value for value in self.source_state_feature_refs):
            raise ValueError("Satellite feature references must be section-qualified")
        if not any(
            (self.source_claim_ids, self.source_evidence_ids, self.source_artifact_ids)
        ):
            raise ValueError("Satellite component requires attributable provenance")
        is_number = isinstance(self.value, (int, float)) and not isinstance(
            self.value, bool
        )
        if is_number and (self.unit is None or self.scale is None):
            raise ValueError("numeric Satellite component requires unit and scale")
        if not is_number and (self.unit is not None or self.scale is not None):
            raise ValueError(
                "categorical Satellite component cannot declare numeric scale"
            )
        return self


class SatelliteAlphaObservation(DomainModel):
    """PIT-safe raw research descriptor, never a Factor exposure or signal."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["satellite_alpha_observation_v1"] = (
        "satellite_alpha_observation_v1"
    )
    observation_id: str = Field(pattern=r"^satellite_alpha_[0-9a-f]{24}$")
    satellite_alpha_id: SatelliteAlphaFamily
    asset_id: AssetId
    market: Market
    sector_id: SectorId | None = None
    chain_ids: tuple[str, ...] = ()
    research_as_of: datetime
    available_at: datetime
    usage: SatelliteAlphaUsage
    value: JsonScalar = None
    value_components: tuple[SatelliteAlphaComponent, ...] = ()
    quality: DataQualityStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_status: SatelliteAlphaCoverageStatus
    comparison_scope: SatelliteAlphaComparisonScope
    missing_reasons: tuple[str, ...] = ()
    source_research_state_id: str = Field(pattern=r"^research_state_[0-9a-f]{24}$")
    previous_research_state_id: str | None = Field(
        default=None,
        pattern=r"^research_state_[0-9a-f]{24}$",
    )
    source_transition_id: str | None = Field(
        default=None,
        pattern=r"^research_state_transition_[0-9a-f]{24}$",
    )
    source_episode_id: str | None = Field(
        default=None,
        pattern=r"^research_episode_[0-9a-f]{24}$",
    )
    source_state_feature_refs: tuple[str, ...] = ()
    source_claim_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    source_sector_claim_ids: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    data_snapshot_id: str | None = Field(default=None, min_length=1)
    definition_version: str = Field(min_length=1)
    transform_version: str = Field(min_length=1)
    created_at: datetime

    @field_validator("value")
    @classmethod
    def reject_execution_value(cls, value: JsonScalar) -> JsonScalar:
        """Reject direct decision semantics at the Observation boundary."""

        return _reject_execution_semantics(value)

    @field_validator("research_as_of", "available_at", "created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Require all public Observation clocks to be UTC-aware."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        """Validate identity-independent audit time, coverage, and provenance."""

        if self.market is not self.asset_id.market:
            raise ValueError("Satellite market does not match canonical asset")
        if self.available_at < self.research_as_of:
            raise ValueError("Satellite cannot predate its source ResearchState")
        if self.created_at < self.available_at:
            raise ValueError("Satellite created_at cannot precede availability")
        groups = (
            self.chain_ids,
            self.value_components,
            self.missing_reasons,
            self.source_state_feature_refs,
            self.source_claim_ids,
            self.source_event_ids,
            self.source_sector_claim_ids,
            self.source_evidence_ids,
            self.source_artifact_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("Satellite Observation values must be unique")
        names = tuple(item.component_name for item in self.value_components)
        if len(names) != len(set(names)):
            raise ValueError("Satellite component names must be unique")
        has_content = self.value is not None or bool(self.value_components)
        if self.coverage_status is SatelliteAlphaCoverageStatus.AVAILABLE:
            if not has_content or self.missing_reasons:
                raise ValueError("available Satellite requires complete content")
        elif self.coverage_status is SatelliteAlphaCoverageStatus.PARTIAL:
            if not has_content or not self.missing_reasons:
                raise ValueError("partial Satellite requires content and reasons")
        elif has_content:
            raise ValueError("unavailable Satellite cannot contain a value")
        elif not self.missing_reasons:
            raise ValueError("unavailable Satellite requires an explicit reason")
        is_numeric = isinstance(self.value, (int, float)) and not isinstance(
            self.value, bool
        )
        if is_numeric and not any(
            item.value == self.value
            and isinstance(item.value, (int, float))
            and not isinstance(item.value, bool)
            for item in self.value_components
        ):
            raise ValueError("numeric Satellite scalar requires a grounded component")
        return self

    def temporal_metadata(self) -> TemporalMetadata:
        """Return the existing Unified Temporal Contract adapter."""

        return TemporalMetadata(
            event_time=self.research_as_of,
            available_at=self.available_at,
            as_of=self.research_as_of,
        )


class SatelliteAlphaRegistry(DomainModel):
    """Immutable complete Day45 family ontology."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    schema_version: Literal["satellite_alpha_registry_v1"] = (
        "satellite_alpha_registry_v1"
    )
    registry_version: Literal["satellite_alpha_ontology_v1"] = (
        "satellite_alpha_ontology_v1"
    )
    definitions: tuple[SatelliteAlphaDefinition, ...]

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        """Require exactly one definition for every closed family."""

        identities = tuple(item.satellite_alpha_id for item in self.definitions)
        if len(identities) != len(set(identities)):
            raise ValueError("Satellite definitions must be unique")
        if set(identities) != set(SatelliteAlphaFamily):
            raise ValueError("Satellite registry must cover every v1 family")
        return self


class ResearchStateSemanticSupportAudit(DomainModel):
    """One explicit support finding without overstating current State semantics."""

    dimension: ResearchStateSemanticDimension
    current_source: str = Field(min_length=1)
    support_level: ResearchStateSupportLevel
    missing_fields: tuple[str, ...] = ()
    required_action: str = Field(min_length=1)


class SatelliteAlphaBuildInput(DomainModel):
    """Frozen artifacts and audit clocks accepted by the pure mapper."""

    research_state: ResearchStateSnapshot
    source_episode: ResearchEpisode | None = None
    available_at: datetime
    created_at: datetime

    @field_validator("available_at", "created_at")
    @classmethod
    def normalize_build_time(cls, value: datetime) -> datetime:
        """Require explicit UTC mapper clocks."""

        return require_utc_aware(value)

    @model_validator(mode="after")
    def validate_episode_alignment(self) -> Self:
        """Require an optional Episode to close to the exact frozen State."""

        if self.source_episode is not None:
            episode = self.source_episode
            state = self.research_state
            if (
                episode.research_state_id != state.research_state_id
                or episode.asset_id != state.asset_id
                or episode.research_as_of != state.research_as_of
            ):
                raise ValueError("Satellite Episode does not match ResearchState")
            if self.available_at < episode.created_at:
                raise ValueError("Satellite availability cannot predate Episode")
        if self.available_at < self.research_state.research_as_of:
            raise ValueError("Satellite availability cannot predate ResearchState")
        if self.created_at < self.available_at:
            raise ValueError("Satellite created_at cannot precede availability")
        return self


class SelectionSectorEventReference(DomainModel):
    """Compact PIT projection of one existing Sector/Radar event reference."""

    event_id: str = Field(min_length=1)
    available_at: datetime
    chain_ids: tuple[str, ...] = ()
    supporting_sector_claim_ids: tuple[str, ...] = ()

    @field_validator("available_at")
    @classmethod
    def normalize_available_at(cls, value: datetime) -> datetime:
        """Require an explicit UTC event availability time."""

        return require_utc_aware(value)


class SelectionSatelliteBuildInput(SatelliteAlphaBuildInput):
    """Day46 frozen Selection inputs without a second Claim representation."""

    sector_id: SectorId | None = None
    sector_context_id: str | None = Field(default=None, min_length=1)
    sector_events: tuple[SelectionSectorEventReference, ...] = ()

    @model_validator(mode="after")
    def validate_sector_context(self) -> Self:
        """Require optional Sector context to be the State's source context."""

        state = self.research_state
        if bool(self.sector_id) != bool(self.sector_context_id):
            raise ValueError("Selection Sector identity must be complete")
        if (
            state.lineage.sector_context_id is not None
            and self.sector_context_id is not None
            and state.lineage.sector_context_id != self.sector_context_id
        ):
            raise ValueError("Selection Sector context identity does not match State")
        event_ids = tuple(item.event_id for item in self.sector_events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Selection Sector event identities must be unique")
        for event in self.sector_events:
            if event.available_at > state.research_as_of:
                raise ValueError("Selection Sector event is unavailable at cutoff")
        return self

    @classmethod
    def from_sector_context(
        cls,
        *,
        base: SatelliteAlphaBuildInput,
        sector_context: SectorContextBundle,
    ) -> Self:
        """Project the existing Day36 context without embedding its payload."""

        if sector_context.asset_id != base.research_state.asset_id:
            raise ValueError("Selection Sector context asset does not match State")
        if sector_context.research_as_of != base.research_state.research_as_of:
            raise ValueError("Selection Sector context cutoff does not match State")
        return cls(
            **base.model_dump(),
            sector_id=sector_context.sector_id,
            sector_context_id=sector_context.context_id,
            sector_events=tuple(
                SelectionSectorEventReference(
                    event_id=event.event_id,
                    available_at=event.available_at,
                    chain_ids=event.chain_ids,
                    supporting_sector_claim_ids=event.supporting_sector_claim_ids,
                )
                for event in sector_context.active_events
            ),
        )


def _reject_execution_semantics(value: JsonScalar) -> JsonScalar:
    if isinstance(value, str) and value.strip().lower() in {
        "buy",
        "sell",
        "long",
        "short",
    }:
        raise ValueError("Satellite Alpha cannot contain a trading decision")
    return value
