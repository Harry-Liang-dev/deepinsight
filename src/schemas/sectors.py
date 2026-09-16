"""Versioned Sector Ontology and hierarchical research-scope contracts."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import (
    AnomalyDirection,
    EventSeverity,
    MacroCycleDirection,
    OntologyStatus,
    ResearchScopeType,
    SectorAnomalyStatus,
    SectorAnomalyType,
    SectorCapabilityStatus,
    SectorEdgeType,
    SectorId,
    SectorMembershipRole,
    SectorNodeType,
)
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.research_data import DataQualityStatus
from src.schemas.temporal import (
    TemporalAccessMode,
    TemporalMetadata,
    is_usable_at,
    validate_temporal_access,
)

_CHAIN_ID = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SCOPE_PREFIX = {
    ResearchScopeType.GLOBAL: "GLOBAL:",
    ResearchScopeType.MACRO: "MACRO:",
    ResearchScopeType.SECTOR: "SECTOR:",
    ResearchScopeType.INDUSTRY_CHAIN: "CHAIN:",
    ResearchScopeType.ASSET: "ASSET:",
    ResearchScopeType.RESEARCH_EPISODE: "EPISODE:",
}


class TemporalOntologyModel(DomainModel):
    """Base contract using inclusive start and exclusive optional end dates."""

    valid_from: date
    valid_to: date | None = None
    version: str = Field(min_length=1, max_length=64)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        """Require a stable machine-readable version token."""

        if not _VERSION.fullmatch(value):
            raise ValueError("invalid ontology version")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Require a non-empty half-open temporal interval."""

        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self

    def is_effective(self, as_of: date) -> bool:
        """Return whether this revision is effective on one date."""

        return is_usable_at(
            TemporalMetadata(
                effective_from=self.valid_from,
                effective_to=self.valid_to,
            ),
            datetime.combine(as_of, time.max, tzinfo=UTC),
        )


class SectorDefinition(DomainModel):
    """One stable first-level Sector Ontology v1 definition."""

    sector_id: SectorId
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(default="sector_ontology_v1", min_length=1)


class SectorOntology(DomainModel):
    """Versioned complete first-level research Sector list."""

    version: str = Field(default="sector_ontology_v1", min_length=1)
    sectors: tuple[SectorDefinition, ...]

    @model_validator(mode="after")
    def validate_unique_sectors(self) -> Self:
        """Reject duplicate IDs or display names."""

        ids = [item.sector_id for item in self.sectors]
        names = [item.name.casefold() for item in self.sectors]
        if len(ids) != len(set(ids)):
            raise ValueError("sector IDs must be unique")
        if len(names) != len(set(names)):
            raise ValueError("sector names must be unique")
        return self


class IndustryChainDefinition(TemporalOntologyModel):
    """Dynamic, versioned research chain associated with one Sector."""

    chain_id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    sector_id: SectorId
    description: str = Field(min_length=1, max_length=1000)
    status: OntologyStatus

    @field_validator("chain_id")
    @classmethod
    def validate_chain_id(cls, value: str) -> str:
        """Require a stable uppercase chain identifier."""

        if not _CHAIN_ID.fullmatch(value):
            raise ValueError("invalid chain_id")
        return value


class SectorMembership(TemporalOntologyModel):
    """Point-in-time asset membership and economic-chain role."""

    asset_id: AssetId
    sector_id: SectorId
    chain_ids: tuple[str, ...] = ()
    role: SectorMembershipRole
    weight: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("chain_ids")
    @classmethod
    def validate_chain_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique canonical chain identifiers."""

        if len(values) != len({str(value) for value in values}):
            raise ValueError("chain_ids must be unique")
        if any(not _CHAIN_ID.fullmatch(value) for value in values):
            raise ValueError("invalid membership chain_id")
        return values


class ResearchScopeDefinition(TemporalOntologyModel):
    """One node in the unified Macro-to-Episode scope hierarchy."""

    scope_type: ResearchScopeType
    scope_id: str = Field(min_length=3, max_length=160)
    parent_scope_id: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_scope_identity(self) -> Self:
        """Require canonical prefixes and a root-only null parent."""

        if not self.scope_id.startswith(_SCOPE_PREFIX[self.scope_type]):
            raise ValueError("scope_id prefix does not match scope_type")
        if self.scope_type is ResearchScopeType.GLOBAL:
            if self.parent_scope_id is not None:
                raise ValueError("GLOBAL scope cannot have a parent")
        elif self.parent_scope_id is None:
            raise ValueError("non-GLOBAL scope requires parent_scope_id")
        if self.scope_id == self.parent_scope_id:
            raise ValueError("scope cannot parent itself")
        return self


class SectorNode(TemporalOntologyModel):
    """Versioned node in the minimal DuckDB Sector knowledge graph."""

    node_id: str = Field(min_length=3, max_length=160)
    node_type: SectorNodeType
    name: str = Field(min_length=1, max_length=160)
    sector_id: SectorId | None = None
    chain_id: str | None = None
    asset_id: AssetId | None = None
    description: str | None = Field(default=None, max_length=1000)
    status: OntologyStatus = OntologyStatus.ACTIVE
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_typed_identity(self) -> Self:
        """Require the canonical identity field for each node type."""

        if self.node_type is SectorNodeType.SECTOR:
            if self.sector_id is None or self.chain_id is not None or self.asset_id:
                raise ValueError("sector node requires only sector_id")
        elif self.node_type is SectorNodeType.INDUSTRY_CHAIN:
            if self.chain_id is None or self.sector_id is None or self.asset_id:
                raise ValueError("industry-chain node requires chain_id and sector_id")
            if not _CHAIN_ID.fullmatch(self.chain_id):
                raise ValueError("invalid node chain_id")
        elif self.asset_id is None or self.chain_id is not None:
            raise ValueError("asset node requires asset_id and no chain_id")
        return self


class SectorEdge(TemporalOntologyModel):
    """Versioned directed relationship between two known Sector nodes."""

    edge_id: str = Field(min_length=3, max_length=200)
    source_node_id: str = Field(min_length=3, max_length=160)
    target_node_id: str = Field(min_length=3, max_length=160)
    edge_type: SectorEdgeType
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        """Reject reflexive graph edges."""

        if self.source_node_id == self.target_node_id:
            raise ValueError("sector edge cannot be reflexive")
        return self


class SectorOntologySeed(DomainModel):
    """Small, explicitly non-exhaustive fixture for ontology validation."""

    ontology: SectorOntology
    chains: tuple[IndustryChainDefinition, ...]
    memberships: tuple[SectorMembership, ...]
    scopes: tuple[ResearchScopeDefinition, ...]
    nodes: tuple[SectorNode, ...]
    edges: tuple[SectorEdge, ...]


class SectorBenchmarkCandidate(DomainModel):
    """Optional US benchmark candidates that require live market validation."""

    sector_id: SectorId
    candidate_ids: tuple[AssetId, ...] = ()
    expected_status: SectorCapabilityStatus
    source: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=64)

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidate_ids(cls, values: tuple[AssetId, ...]) -> tuple[AssetId, ...]:
        """Require unique canonical US candidate identifiers."""

        if len(values) != len({str(value) for value in values}):
            raise ValueError("benchmark candidate IDs must be unique")
        if any(not str(value).startswith("US:") for value in values):
            raise ValueError("Sector benchmark candidates must use US asset IDs")
        return values

    @model_validator(mode="after")
    def validate_expected_status(self) -> Self:
        """Represent intentionally unmapped sectors without placeholder tickers."""

        if self.expected_status is SectorCapabilityStatus.MISSING:
            if self.candidate_ids:
                raise ValueError("missing candidate mapping cannot contain tickers")
        elif not self.candidate_ids:
            raise ValueError("candidate mapping requires at least one ticker")
        return self


class SectorBenchmarkMapping(TemporalOntologyModel):
    """Point-in-time mapping containing only market-validated benchmarks."""

    sector_id: SectorId
    benchmark_ids: tuple[AssetId, ...] = ()
    status: SectorCapabilityStatus
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        """Keep status consistent with the validated benchmark set."""

        if len(self.benchmark_ids) != len({str(value) for value in self.benchmark_ids}):
            raise ValueError("benchmark IDs must be unique")
        if self.status is SectorCapabilityStatus.AVAILABLE and not self.benchmark_ids:
            raise ValueError("available benchmark mapping requires a benchmark")
        if self.status is SectorCapabilityStatus.PARTIAL and not self.benchmark_ids:
            raise ValueError("partial benchmark mapping requires a benchmark")
        if self.status is SectorCapabilityStatus.MISSING and self.benchmark_ids:
            raise ValueError("missing benchmark mapping cannot contain a benchmark")
        return self


class SectorUniverseCoverage(DomainModel):
    """Deterministic coverage diagnostics for one universe snapshot."""

    membership_count: int = Field(ge=0)
    classified_asset_count: int = Field(ge=0)
    benchmark_count: int = Field(ge=0)
    classification_ratio: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """Reject impossible classified-asset counts."""

        if self.classified_asset_count > self.membership_count:
            raise ValueError("classified assets cannot exceed memberships")
        return self


class SectorUniverseSnapshot(DomainModel):
    """Immutable point-in-time research universe for one first-level Sector."""

    snapshot_id: str = Field(pattern=r"^sector_universe_[0-9a-f]{24}$")
    sector_id: SectorId
    as_of: date
    asset_ids: tuple[AssetId, ...]
    benchmark_ids: tuple[AssetId, ...] = ()
    membership_version: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=200)
    coverage: SectorUniverseCoverage
    quality: DataQualityStatus

    @model_validator(mode="after")
    def validate_unique_assets(self) -> Self:
        """Require stable unique asset and benchmark identities."""

        if len(self.asset_ids) != len({str(value) for value in self.asset_ids}):
            raise ValueError("Sector universe asset IDs must be unique")
        if len(self.benchmark_ids) != len({str(value) for value in self.benchmark_ids}):
            raise ValueError("Sector universe benchmark IDs must be unique")
        if self.coverage.membership_count != len(self.asset_ids):
            raise ValueError("coverage membership count must match asset IDs")
        if self.coverage.benchmark_count != len(self.benchmark_ids):
            raise ValueError("coverage benchmark count must match benchmark IDs")
        return self


class CoveredSectorMetric(DomainModel):
    """One deterministic Sector metric with explicit sample coverage."""

    value: float | None = None
    coverage_count: int = Field(ge=0)
    universe_count: int = Field(ge=0)
    status: SectorCapabilityStatus

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        """Keep availability, value, and sample counts semantically aligned."""

        if self.coverage_count > self.universe_count:
            raise ValueError("metric coverage cannot exceed universe count")
        if self.status is SectorCapabilityStatus.AVAILABLE and self.value is None:
            raise ValueError("available metric requires a value")
        if self.status is SectorCapabilityStatus.MISSING:
            if self.value is not None or self.coverage_count:
                raise ValueError("missing metric cannot contain a value or coverage")
        return self


class SectorMarketState(DomainModel):
    """Deterministic constituent and benchmark price state."""

    return_1d: CoveredSectorMetric
    return_5d: CoveredSectorMetric
    return_20d: CoveredSectorMetric
    return_60d: CoveredSectorMetric
    excess_return_vs_market: CoveredSectorMetric
    excess_return_vs_sector_benchmark: CoveredSectorMetric
    realized_vol_20d: CoveredSectorMetric
    realized_vol_60d: CoveredSectorMetric
    max_drawdown_60d: CoveredSectorMetric


class SectorBreadthState(DomainModel):
    """Cross-sectional market breadth with sample-size disclosure."""

    pct_above_sma20: CoveredSectorMetric
    pct_above_sma60: CoveredSectorMetric
    pct_positive_5d: CoveredSectorMetric
    pct_positive_20d: CoveredSectorMetric
    advance_decline_ratio: CoveredSectorMetric
    median_return_5d: CoveredSectorMetric
    median_return_20d: CoveredSectorMetric
    return_dispersion_20d: CoveredSectorMetric
    leader_count: CoveredSectorMetric
    laggard_count: CoveredSectorMetric


class SectorFundamentalState(DomainModel):
    """Cross-sectional standardized fundamental breadth."""

    median_revenue_yoy: CoveredSectorMetric
    median_net_income_yoy: CoveredSectorMetric
    median_gross_margin: CoveredSectorMetric
    median_roe: CoveredSectorMetric
    median_roa: CoveredSectorMetric
    positive_revenue_growth_ratio: CoveredSectorMetric
    positive_net_income_growth_ratio: CoveredSectorMetric


class SectorValuationState(DomainModel):
    """Cross-sectional valuation state without market-cap averaging."""

    median_pe: CoveredSectorMetric
    median_pb: CoveredSectorMetric


class SectorResearchCoverage(DomainModel):
    """Top-level input coverage for one Sector state calculation."""

    universe_count: int = Field(ge=0)
    market_coverage_count: int = Field(ge=0)
    fundamental_coverage_count: int = Field(ge=0)
    benchmark_coverage_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_top_level_counts(self) -> Self:
        """Reject coverage counts larger than the constituent universe."""

        if self.market_coverage_count > self.universe_count:
            raise ValueError("market coverage cannot exceed universe count")
        if self.fundamental_coverage_count > self.universe_count:
            raise ValueError("fundamental coverage cannot exceed universe count")
        return self


class SectorResearchSnapshot(DomainModel):
    """Immutable deterministic SectorResearchSnapshot v1."""

    snapshot_id: str = Field(pattern=r"^sector_research_[0-9a-f]{24}$")
    sector_id: SectorId
    as_of: date
    market_state: SectorMarketState
    breadth_state: SectorBreadthState
    fundamental_state: SectorFundamentalState
    valuation_state: SectorValuationState
    coverage: SectorResearchCoverage
    source_ids: tuple[str, ...]
    feature_version: str = Field(min_length=1, max_length=64)
    status: SectorCapabilityStatus

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, non-empty canonical source identities."""

        if any(not value.strip() for value in values):
            raise ValueError("Sector research source IDs cannot be empty")
        if len(values) != len(set(values)):
            raise ValueError("Sector research source IDs must be unique")
        return values


class MacroSeriesCycleSignal(DomainModel):
    """One point-in-time macro series direction used by a Sector cycle state."""

    series_id: str = Field(min_length=1)
    transformation: str = Field(min_length=1)
    latest_observation_date: date
    latest_value: float
    change_3m: float | None = None
    change_12m: float | None = None
    direction: MacroCycleDirection
    source_id: str = Field(min_length=1)


class MacroCycleDimensionState(DomainModel):
    """Deterministic direction summary for one macro dimension."""

    direction: MacroCycleDirection
    signals: tuple[MacroSeriesCycleSignal, ...]
    coverage_count: int = Field(ge=0)
    expected_count: int = Field(ge=1)
    status: SectorCapabilityStatus

    @model_validator(mode="after")
    def validate_dimension_coverage(self) -> Self:
        """Keep dimension coverage consistent with its series signals."""

        if self.coverage_count != len(self.signals):
            raise ValueError("macro dimension coverage must match signals")
        if self.coverage_count > self.expected_count:
            raise ValueError("macro dimension coverage exceeds expected series")
        return self


class SectorCycleState(DomainModel):
    """Five-dimensional deterministic macro-cycle context for one Sector."""

    sector_id: SectorId
    as_of: date
    rates: MacroCycleDimensionState
    inflation: MacroCycleDimensionState
    labor: MacroCycleDimensionState
    growth: MacroCycleDimensionState
    financial_stress: MacroCycleDimensionState
    sector_momentum: CoveredSectorMetric
    source_ids: tuple[str, ...]
    feature_version: str = Field(min_length=1)
    status: SectorCapabilityStatus


class MacroSensitivityEstimate(DomainModel):
    """One univariate monthly Sector-to-macro sensitivity estimate."""

    series_id: str = Field(min_length=1)
    transformation: str = Field(min_length=1)
    beta: float | None = None
    correlation: float | None = Field(default=None, ge=-1.0, le=1.0)
    observation_count: int = Field(ge=0)
    required_count: int = Field(default=24, ge=2)
    window_months: int = Field(default=36, ge=2)
    source_id: str = Field(min_length=1)
    status: SectorCapabilityStatus

    @model_validator(mode="after")
    def validate_estimate(self) -> Self:
        """Require numeric estimates only when the sample gate passes."""

        if self.status is SectorCapabilityStatus.AVAILABLE:
            if self.beta is None or self.correlation is None:
                raise ValueError("available sensitivity requires beta and correlation")
            if self.observation_count < self.required_count:
                raise ValueError("available sensitivity requires enough observations")
        return self


class MacroSensitivity(DomainModel):
    """Versioned collection of point-in-time univariate sensitivities."""

    sector_id: SectorId
    as_of: date
    benchmark_id: AssetId | None = None
    estimates: tuple[MacroSensitivityEstimate, ...]
    window_months: int = Field(default=36, ge=2)
    source_ids: tuple[str, ...]
    feature_version: str = Field(min_length=1)
    status: SectorCapabilityStatus


class SectorMacroSnapshot(DomainModel):
    """Immutable Day33 connection between macro history and Sector state."""

    snapshot_id: str = Field(pattern=r"^sector_macro_[0-9a-f]{24}$")
    sector_id: SectorId
    as_of: date
    cycle_state: SectorCycleState
    macro_sensitivity: MacroSensitivity
    source_sector_snapshot_id: str = Field(pattern=r"^sector_research_[0-9a-f]{24}$")
    feature_version: str = Field(min_length=1)
    status: SectorCapabilityStatus

    @model_validator(mode="after")
    def validate_sector_identity(self) -> Self:
        """Require both deterministic outputs to describe the same Sector/date."""

        identities = {
            (self.sector_id, self.as_of),
            (self.cycle_state.sector_id, self.cycle_state.as_of),
            (self.macro_sensitivity.sector_id, self.macro_sensitivity.as_of),
        }
        if len(identities) != 1:
            raise ValueError("Sector macro snapshot identities must match")
        return self


class SectorAnomalyEvent(DomainModel):
    """One deterministic, point-in-time-safe Sector Radar event."""

    event_id: str = Field(pattern=r"^sector_anomaly_[0-9a-f]{24}$")
    event_type: SectorAnomalyType
    sector_id: SectorId
    chain_ids: tuple[str, ...] = ()
    source_asset_ids: tuple[AssetId, ...] = ()
    affected_asset_ids: tuple[AssetId, ...] = ()
    direction: AnomalyDirection
    severity: EventSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    event_time: datetime
    published_at: datetime
    available_at: datetime
    ingested_at: datetime
    as_of: datetime
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=2000)
    propagation_hypothesis: str | None = Field(default=None, max_length=2000)
    status: SectorAnomalyStatus
    version: str = Field(default="sector_radar_v1", min_length=1, max_length=64)

    @field_validator("chain_ids")
    @classmethod
    def validate_event_chain_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique canonical Industry Chain identities."""

        if len(values) != len(set(values)) or any(
            not _CHAIN_ID.fullmatch(value) for value in values
        ):
            raise ValueError("invalid or duplicate anomaly chain IDs")
        return values

    @field_validator("source_asset_ids", "affected_asset_ids", "source_evidence_ids")
    @classmethod
    def validate_unique_event_references(
        cls, values: tuple[object, ...]
    ) -> tuple[object, ...]:
        """Reject duplicated assets or Evidence identifiers."""

        if len(values) != len({str(value) for value in values}):
            raise ValueError("anomaly references must be unique")
        return values

    @model_validator(mode="after")
    def validate_event_time_and_status(self) -> Self:
        """Enforce availability cutoffs and propagation semantics."""

        timestamps = (
            self.event_time,
            self.published_at,
            self.available_at,
            self.ingested_at,
            self.as_of,
        )
        if any(
            value.tzinfo is None or value.utcoffset() is None for value in timestamps
        ):
            raise ValueError("anomaly timestamps must be timezone-aware")
        if self.event_time > self.available_at:
            raise ValueError("event_time cannot be later than available_at")
        if self.published_at > self.available_at:
            raise ValueError("published_at cannot be later than available_at")
        validate_temporal_access(
            TemporalMetadata(
                event_time=self.event_time,
                published_at=self.published_at,
                available_at=self.available_at,
                ingested_at=self.ingested_at,
                as_of=self.as_of,
            ),
            self.as_of,
            mode=TemporalAccessMode.LIVE_ACQUISITION,
        )
        if self.status is SectorAnomalyStatus.PROPAGATION_CANDIDATE:
            if self.event_type is not SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION:
                raise ValueError("propagation status requires propagation event type")
            if not self.chain_ids or not self.propagation_hypothesis:
                raise ValueError("propagation candidate requires chain and hypothesis")
        elif self.event_type is SectorAnomalyType.SUPPLY_CHAIN_PROPAGATION:
            raise ValueError("propagation event requires candidate status")
        return self
