"""Versioned, least-privilege input contracts for the fixed eight Agents.

The contracts in this module project existing Data- and Memory-owned bundles
into Agent-owned views. They are intentionally side-effect free: no contract
or projector can access a Provider, Repository, DuckDB, FAISS, or an LLM.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final, Literal, Self, cast

from pydantic import Field, model_validator

from src.memory.contracts import (
    MissingContext,
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextSection,
    RetrievalMetadata,
)
from src.models.enums import AgentName, AgentStatus, Market
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    MissingData,
    ResearchDataBundle,
    ResearchDataSection,
    ResearchEvidenceItem,
)
from src.schemas.sector_context import SectorContextBundle, SectorRoleContext
from src.services.sector_context import SectorContextProjector

type InputSchemaVersion = Literal["agent_input_v1"]
type OutputSchemaVersion = Literal["agent_output_v1", "agent_output_v2"]

AGENT_INPUT_SCHEMA_VERSION: Final[InputSchemaVersion] = "agent_input_v1"
AGENT_OUTPUT_SCHEMA_VERSION: Final[OutputSchemaVersion] = "agent_output_v2"

# The canonical ResearchDataBundle remains complete and auditable.  Agent views
# carry only a deterministic, field-balanced projection so a long observation
# history cannot turn one structured LLM request into an unbounded payload.
_AGENT_EVIDENCE_LIMITS: Final[dict[DataCapability, int]] = {
    DataCapability.ASSET_IDENTITY: 16,
    DataCapability.MARKET_CONTEXT: 24,
    DataCapability.OHLCV: 64,
    DataCapability.TECHNICAL_FEATURES: 32,
    DataCapability.FUNDAMENTALS: 64,
    DataCapability.VALUATION: 16,
    DataCapability.CORPORATE_EVENTS: 24,
    DataCapability.FILINGS: 8,
    DataCapability.MACRO_INDICATORS: 36,
    DataCapability.INDUSTRY_SECTOR_CONTEXT: 16,
    DataCapability.NEWS_EVIDENCE: 60,
    DataCapability.SENTIMENT_EVIDENCE: 64,
}


def _require_unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class AgentInputRequirement(DomainModel):
    """One row in the fixed eight-Agent input requirement matrix."""

    agent: AgentName
    required_data: tuple[DataCapability, ...]
    optional_data: tuple[DataCapability, ...]
    required_memory: tuple[ResearchContextSection, ...]
    optional_memory: tuple[ResearchContextSection, ...]
    required_upstream_outputs: tuple[AgentName, ...]
    missing_data_behavior: str = Field(min_length=1)
    degradation_behavior: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_requirement_sets(self) -> Self:
        """Keep required and optional capabilities unique and disjoint."""

        _require_unique(self.required_data, "required data")
        _require_unique(self.optional_data, "optional data")
        _require_unique(self.required_memory, "required Memory")
        _require_unique(self.optional_memory, "optional Memory")
        _require_unique(self.required_upstream_outputs, "required upstream outputs")
        if set(self.required_data) & set(self.optional_data):
            raise ValueError("required and optional data must be disjoint")
        if set(self.required_memory) & set(self.optional_memory):
            raise ValueError("required and optional Memory must be disjoint")
        return self


_ANALYSTS = (
    AgentName.FUNDAMENTAL_ANALYST,
    AgentName.TECHNICAL_TEXT_ANALYST,
    AgentName.SENTIMENT_ANALYST,
    AgentName.NEWS_EVENT_ANALYST,
)

_ALL_MEMORY_SECTIONS = tuple(ResearchContextSection)

AGENT_INPUT_MATRIX: tuple[AgentInputRequirement, ...] = (
    AgentInputRequirement(
        agent=AgentName.FUNDAMENTAL_ANALYST,
        required_data=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.FUNDAMENTALS,
            DataCapability.FILINGS,
        ),
        optional_data=(
            DataCapability.VALUATION,
            DataCapability.CORPORATE_EVENTS,
            DataCapability.INDUSTRY_SECTOR_CONTEXT,
            DataCapability.MACRO_INDICATORS,
        ),
        required_memory=(),
        optional_memory=(
            ResearchContextSection.CURRENT_SNAPSHOT,
            ResearchContextSection.ASSET_EVENTS,
            ResearchContextSection.PRIOR_RESEARCH,
            ResearchContextSection.PRIOR_RISK,
        ),
        required_upstream_outputs=(),
        missing_data_behavior=(
            "Disclose every absent statement, period, unit, and valuation input."
        ),
        degradation_behavior=(
            "Use only remaining structured fundamentals or filing evidence, lower "
            "certainty, and never calculate an undisclosed ratio."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.TECHNICAL_TEXT_ANALYST,
        required_data=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.OHLCV,
            DataCapability.TECHNICAL_FEATURES,
        ),
        optional_data=(
            DataCapability.MARKET_CONTEXT,
            DataCapability.INDUSTRY_SECTOR_CONTEXT,
            DataCapability.CORPORATE_EVENTS,
        ),
        required_memory=(),
        optional_memory=(
            ResearchContextSection.CURRENT_SNAPSHOT,
            ResearchContextSection.ASSET_EVENTS,
            ResearchContextSection.HISTORICAL_ANALOGS,
            ResearchContextSection.REGIME_CONTEXT,
        ),
        required_upstream_outputs=(),
        missing_data_behavior=(
            "Disclose insufficient history, stale bars, adjustment gaps, and "
            "missing benchmark coverage separately."
        ),
        degradation_behavior=(
            "Do not form a trend conclusion without attributable deterministic "
            "features and never calculate indicators in the LLM."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.SENTIMENT_ANALYST,
        required_data=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.SENTIMENT_EVIDENCE,
        ),
        optional_data=(
            DataCapability.NEWS_EVIDENCE,
            DataCapability.MARKET_CONTEXT,
        ),
        required_memory=(),
        optional_memory=(
            ResearchContextSection.MACRO_EVENTS,
            ResearchContextSection.ASSET_EVENTS,
            ResearchContextSection.PRIOR_RESEARCH,
        ),
        required_upstream_outputs=(),
        missing_data_behavior=(
            "Disclose sample channel, count, window, language, recency, and "
            "market-coverage limitations."
        ),
        degradation_behavior=(
            "Return unavailable when no attributable sentiment sample exists; "
            "a filing or one news item is not broad investor sentiment."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.NEWS_EVENT_ANALYST,
        required_data=(DataCapability.ASSET_IDENTITY,),
        optional_data=(
            DataCapability.FILINGS,
            DataCapability.CORPORATE_EVENTS,
            DataCapability.NEWS_EVIDENCE,
            DataCapability.MACRO_INDICATORS,
            DataCapability.MARKET_CONTEXT,
        ),
        required_memory=(),
        optional_memory=(
            ResearchContextSection.MACRO_EVENTS,
            ResearchContextSection.ASSET_EVENTS,
            ResearchContextSection.PRIOR_RISK,
        ),
        required_upstream_outputs=(),
        missing_data_behavior=(
            "Disclose which filing, event, news, or policy channels were absent."
        ),
        degradation_behavior=(
            "Require at least one attributable event source and separate confirmed "
            "events, possible impact, and unresolved facts."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.RESEARCH_MANAGER,
        required_data=(DataCapability.ASSET_IDENTITY,),
        optional_data=tuple(
            capability
            for capability in DataCapability
            if capability is not DataCapability.ASSET_IDENTITY
        ),
        required_memory=(),
        optional_memory=_ALL_MEMORY_SECTIONS,
        required_upstream_outputs=_ANALYSTS,
        missing_data_behavior=(
            "Preserve missing, stale, failed, and not-applicable coverage plus every "
            "failed Analyst slot."
        ),
        degradation_behavior=(
            "Synthesize remaining validated Analyst outputs without adding facts; "
            "fail when no Analyst output is usable."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.BULL_MANAGER,
        required_data=(DataCapability.ASSET_IDENTITY,),
        optional_data=tuple(
            capability
            for capability in DataCapability
            if capability is not DataCapability.ASSET_IDENTITY
        ),
        required_memory=(),
        optional_memory=_ALL_MEMORY_SECTIONS,
        required_upstream_outputs=(*_ANALYSTS, AgentName.RESEARCH_MANAGER),
        missing_data_behavior=(
            "Name every unsupported constructive premise and counterevidence gap."
        ),
        degradation_behavior=(
            "Lower confidence and keep the thesis conditional without bypassing "
            "the Research Manager."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.BEAR_MANAGER,
        required_data=(DataCapability.ASSET_IDENTITY,),
        optional_data=tuple(
            capability
            for capability in DataCapability
            if capability is not DataCapability.ASSET_IDENTITY
        ),
        required_memory=(),
        optional_memory=_ALL_MEMORY_SECTIONS,
        required_upstream_outputs=(*_ANALYSTS, AgentName.RESEARCH_MANAGER),
        missing_data_behavior=(
            "Name every unsupported adverse premise, trigger, and invalidator gap."
        ),
        degradation_behavior=(
            "Lower confidence and distinguish confirmed weakness from a scenario; "
            "never present a positive invalidator as a risk fact."
        ),
    ),
    AgentInputRequirement(
        agent=AgentName.RISK_MANAGER,
        required_data=(DataCapability.ASSET_IDENTITY,),
        optional_data=tuple(
            capability
            for capability in DataCapability
            if capability is not DataCapability.ASSET_IDENTITY
        ),
        required_memory=(),
        optional_memory=_ALL_MEMORY_SECTIONS,
        required_upstream_outputs=(
            *_ANALYSTS,
            AgentName.RESEARCH_MANAGER,
            AgentName.BULL_MANAGER,
            AgentName.BEAR_MANAGER,
        ),
        missing_data_behavior=(
            "Treat missing coverage and stale or conflicting evidence as explicit "
            "research risk."
        ),
        degradation_behavior=(
            "Keep scenarios conditional and fail when Research, Bull, or Bear output "
            "is unavailable; never create a new market fact."
        ),
    ),
)


class AgentEpistemicPolicyV1(DomainModel):
    """Machine-enforced reasoning boundaries carried by every Agent input."""

    absence_of_evidence_is_evidence_of_absence: Literal[False] = False
    external_access_allowed: Literal[False] = False
    llm_ratio_calculation_allowed: Literal[False] = False
    unsupported_unit_conversion_allowed: Literal[False] = False
    citation_validation_required: Literal[True] = True


class ResearchScopeV1(DomainModel):
    """Shared point-in-time identity for one projected Agent request."""

    asset_id: AssetId
    market: Market
    as_of: datetime
    window_start: date
    window_end: date
    dataset_version: str = Field(min_length=1)
    data_bundle_id: str = Field(min_length=1)
    data_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_snapshot_id: str | None = None
    memory_snapshot_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Require coherent asset, market, window, and point-in-time bounds."""

        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("Agent as_of must be timezone-aware")
        if self.asset_id.market is not self.market:
            raise ValueError("Agent asset and market must match")
        if self.window_end < self.window_start:
            raise ValueError("Agent window_end cannot precede window_start")
        if self.window_end > self.as_of.date():
            raise ValueError("Agent window cannot extend beyond as_of")
        return self


class AgentDataViewV1(DomainModel):
    """Least-privilege structured-data sections visible to one role."""

    sections: tuple[ResearchDataSection, ...]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        """Reject duplicate slots and implicit unavailable-data states."""

        _require_unique(
            tuple(section.capability for section in self.sections),
            "data view capabilities",
        )
        implicit_missing = [
            section.capability.value
            for section in self.sections
            if section.status
            in {
                DataAvailabilityStatus.MISSING,
                DataAvailabilityStatus.PARTIAL,
                DataAvailabilityStatus.STALE,
                DataAvailabilityStatus.FAILED,
            }
            and not section.missing_data
        ]
        if implicit_missing:
            raise ValueError("unavailable Agent data requires explicit missing-data")
        return self

    def section(self, capability: DataCapability) -> ResearchDataSection:
        """Return one visible section or reject access outside the role view."""

        for section in self.sections:
            if section.capability is capability:
                return section
        raise KeyError(f"capability is outside Agent view: {capability.value}")


class AgentMemoryViewV1(DomainModel):
    """Role-filtered Memory items with explicit empty-section records."""

    allowed_sections: tuple[ResearchContextSection, ...]
    items: tuple[ResearchContextMemory, ...]
    missing_context: tuple[MissingContext, ...]
    retrieval_metadata: RetrievalMetadata

    @model_validator(mode="after")
    def validate_memory_view(self) -> Self:
        """Ensure every item and absence record remains inside the role view."""

        _require_unique(self.allowed_sections, "allowed Memory sections")
        allowed = set(self.allowed_sections)
        item_sections = {item.section for item in self.items}
        missing_sections = {item.section for item in self.missing_context}
        if not item_sections <= allowed or not missing_sections <= allowed:
            raise ValueError("Memory item is outside the Agent role view")
        if item_sections & missing_sections:
            raise ValueError("Memory section cannot be present and missing")
        if item_sections | missing_sections != allowed:
            raise ValueError("every allowed Memory section needs presence or absence")
        return self


class AgentCoverageManifestV1(DomainModel):
    """Role-level required, optional, missing, and upstream coverage."""

    required_data: tuple[DataCapability, ...]
    optional_data: tuple[DataCapability, ...]
    required_memory: tuple[ResearchContextSection, ...]
    optional_memory: tuple[ResearchContextSection, ...]
    missing_data: tuple[MissingData, ...]
    missing_context: tuple[MissingContext, ...]
    required_upstream_outputs: tuple[AgentName, ...]
    unavailable_upstream_outputs: tuple[AgentName, ...] = ()
    missing_data_behavior: str = Field(min_length=1)
    degradation_behavior: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        """Keep coverage categories non-overlapping and attributable."""

        if set(self.required_data) & set(self.optional_data):
            raise ValueError("coverage data requirements overlap")
        if set(self.required_memory) & set(self.optional_memory):
            raise ValueError("coverage Memory requirements overlap")
        if not set(self.unavailable_upstream_outputs) <= set(
            self.required_upstream_outputs
        ):
            raise ValueError("unavailable upstream output was not required")
        return self


class VersionedUpstreamOutputV1(DomainModel):
    """One explicit successful or unavailable upstream Agent output slot."""

    schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: AgentName
    status: AgentStatus
    output: JsonObject | None = None
    evidence_ids: tuple[str, ...] = ()
    validated_claims: tuple[ClaimEvidenceBinding, ...] = ()
    missing_data: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_status_branch(self) -> Self:
        """Require a payload only for success and an error code only for failure."""

        if self.status is AgentStatus.OK:
            if self.output is None or self.error_code is not None:
                raise ValueError("successful upstream output requires output only")
        elif self.output is not None or not self.error_code:
            raise ValueError("failed upstream output requires an error code only")
        _require_unique(self.evidence_ids, "upstream evidence IDs")
        claim_ids = tuple(
            claim.claim_id for claim in self.validated_claims if claim.claim_id
        )
        if len(claim_ids) != len(self.validated_claims):
            raise ValueError("upstream accepted Claims require stable claim IDs")
        _require_unique(claim_ids, "upstream Claim IDs")
        return self


class AgentInputBaseV1(DomainModel):
    """Shared version, evidence, coverage, and policy fields for an Agent."""

    schema_version: InputSchemaVersion = AGENT_INPUT_SCHEMA_VERSION
    expected_output_schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: AgentName
    scope: ResearchScopeV1
    data: AgentDataViewV1
    memory: AgentMemoryViewV1
    coverage: AgentCoverageManifestV1
    data_evidence_index: dict[str, ResearchEvidenceItem]
    memory_evidence_index: dict[str, ResearchContextMemory]
    sector_context: SectorRoleContext | None = None
    epistemic_policy: AgentEpistemicPolicyV1 = Field(
        default_factory=AgentEpistemicPolicyV1
    )

    @model_validator(mode="after")
    def validate_common_input(self) -> Self:
        """Enforce role requirements, evidence identity, and temporal safety."""

        requirement = _requirement(self.agent_name)
        expected_data = set(requirement.required_data) | set(requirement.optional_data)
        actual_data = {section.capability for section in self.data.sections}
        if actual_data != expected_data:
            raise ValueError("Agent data view does not match its role matrix")
        expected_memory = set(requirement.required_memory) | set(
            requirement.optional_memory
        )
        if set(self.memory.allowed_sections) != expected_memory:
            raise ValueError("Agent Memory view does not match its role matrix")
        if self.coverage.required_data != requirement.required_data:
            raise ValueError("Agent required-data coverage does not match matrix")
        if self.coverage.optional_data != requirement.optional_data:
            raise ValueError("Agent optional-data coverage does not match matrix")
        if self.coverage.required_memory != requirement.required_memory:
            raise ValueError("Agent required-Memory coverage does not match matrix")
        if self.coverage.optional_memory != requirement.optional_memory:
            raise ValueError("Agent optional-Memory coverage does not match matrix")
        if self.coverage.required_upstream_outputs != (
            requirement.required_upstream_outputs
        ):
            raise ValueError("Agent upstream coverage does not match matrix")

        required_sections = {
            section.capability: section
            for section in self.data.sections
            if section.capability in requirement.required_data
        }
        if any(
            section.status is DataAvailabilityStatus.NOT_APPLICABLE
            for section in required_sections.values()
        ):
            raise ValueError("required Agent data cannot be not-applicable")
        expected_missing_data = tuple(
            item for section in self.data.sections for item in section.missing_data
        )
        if self.coverage.missing_data != expected_missing_data:
            raise ValueError("coverage must preserve role-visible missing data")
        if self.coverage.missing_context != self.memory.missing_context:
            raise ValueError("coverage must preserve role-visible missing Memory")

        data_items = {
            item.evidence_id: item
            for section in self.data.sections
            for item in section.items
        }
        if self.data_evidence_index != data_items:
            raise ValueError("data evidence index must exactly match the role view")
        memory_items = {item.memory_id: item for item in self.memory.items}
        if self.memory_evidence_index != memory_items:
            raise ValueError("Memory evidence index must exactly match the role view")
        if any(item.effective_at > self.scope.as_of for item in data_items.values()):
            raise ValueError("future structured evidence cannot enter Agent input")
        if any(item.effective_ts > self.scope.as_of for item in memory_items.values()):
            raise ValueError("future Memory cannot enter Agent input")
        if self.sector_context is not None:
            if self.sector_context.agent_role is not self.agent_name:
                raise ValueError("Sector context projection has the wrong Agent role")
            if self.sector_context.asset_id != self.scope.asset_id:
                raise ValueError("Sector context asset does not match Agent scope")
            if self.sector_context.research_as_of != self.scope.as_of:
                raise ValueError("Sector context cutoff does not match Agent scope")
        return self

    def resolve_data_evidence(self, evidence_id: str) -> ResearchEvidenceItem:
        """Resolve one structured Evidence ID within this role's visible index."""

        try:
            return self.data_evidence_index[evidence_id]
        except KeyError:
            raise KeyError(f"unknown role-visible Evidence ID: {evidence_id}") from None

    def resolve_memory_evidence(self, memory_id: str) -> ResearchContextMemory:
        """Resolve one Memory ID within this role's visible index."""

        try:
            return self.memory_evidence_index[memory_id]
        except KeyError:
            raise KeyError(f"unknown role-visible Memory ID: {memory_id}") from None


class FundamentalAnalystInputV1(AgentInputBaseV1):
    """Versioned input for the Fundamental Analyst."""

    agent_name: Literal[AgentName.FUNDAMENTAL_ANALYST] = AgentName.FUNDAMENTAL_ANALYST


class TechnicalTextAnalystInputV1(AgentInputBaseV1):
    """Versioned input for deterministic technical interpretation."""

    agent_name: Literal[AgentName.TECHNICAL_TEXT_ANALYST] = (
        AgentName.TECHNICAL_TEXT_ANALYST
    )


class SentimentAnalystInputV1(AgentInputBaseV1):
    """Versioned input for supplied sentiment-sample interpretation."""

    agent_name: Literal[AgentName.SENTIMENT_ANALYST] = AgentName.SENTIMENT_ANALYST


class NewsEventAnalystInputV1(AgentInputBaseV1):
    """Versioned input for filing, news, policy, and event interpretation."""

    agent_name: Literal[AgentName.NEWS_EVENT_ANALYST] = AgentName.NEWS_EVENT_ANALYST


type AnalystInputV1 = (
    FundamentalAnalystInputV1
    | TechnicalTextAnalystInputV1
    | SentimentAnalystInputV1
    | NewsEventAnalystInputV1
)


class ManagerResearchContextV1(AgentInputBaseV1):
    """Read-only bundle context and all four explicit Analyst output slots."""

    analyst_outputs: tuple[VersionedUpstreamOutputV1, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def validate_analyst_coverage(self) -> Self:
        """Require exactly one slot for each fixed Analyst role."""

        roles = tuple(item.agent_name for item in self.analyst_outputs)
        if len(roles) != len(_ANALYSTS) or set(roles) != set(_ANALYSTS):
            raise ValueError("Manager context requires all four Analyst slots")
        unavailable = tuple(
            item.agent_name
            for item in self.analyst_outputs
            if item.status is not AgentStatus.OK
        )
        if set(self.coverage.unavailable_upstream_outputs) != set(unavailable):
            raise ValueError("Manager coverage must preserve unavailable Analysts")
        return self


class ResearchManagerInputV1(DomainModel):
    """Versioned Research Manager input with no data-access dependency."""

    schema_version: InputSchemaVersion = AGENT_INPUT_SCHEMA_VERSION
    expected_output_schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: Literal[AgentName.RESEARCH_MANAGER] = AgentName.RESEARCH_MANAGER
    context: ManagerResearchContextV1

    @model_validator(mode="after")
    def validate_context_role(self) -> Self:
        """Bind the reusable context to Research Manager requirements."""

        if self.context.agent_name is not AgentName.RESEARCH_MANAGER:
            raise ValueError("Research Manager context has the wrong role")
        if not any(
            item.status is AgentStatus.OK for item in self.context.analyst_outputs
        ):
            raise ValueError("Research Manager requires one usable Analyst output")
        return self


class BullManagerInputV1(DomainModel):
    """Versioned Bull Manager input that cannot bypass research synthesis."""

    schema_version: InputSchemaVersion = AGENT_INPUT_SCHEMA_VERSION
    expected_output_schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: Literal[AgentName.BULL_MANAGER] = AgentName.BULL_MANAGER
    context: ManagerResearchContextV1
    research_output: VersionedUpstreamOutputV1

    @model_validator(mode="after")
    def validate_upstream(self) -> Self:
        """Require the matching context and successful Research output."""

        _require_manager_context(self.context, AgentName.BULL_MANAGER)
        _require_successful_output(self.research_output, AgentName.RESEARCH_MANAGER)
        return self


class BearManagerInputV1(DomainModel):
    """Versioned Bear Manager input that cannot bypass research synthesis."""

    schema_version: InputSchemaVersion = AGENT_INPUT_SCHEMA_VERSION
    expected_output_schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: Literal[AgentName.BEAR_MANAGER] = AgentName.BEAR_MANAGER
    context: ManagerResearchContextV1
    research_output: VersionedUpstreamOutputV1

    @model_validator(mode="after")
    def validate_upstream(self) -> Self:
        """Require the matching context and successful Research output."""

        _require_manager_context(self.context, AgentName.BEAR_MANAGER)
        _require_successful_output(self.research_output, AgentName.RESEARCH_MANAGER)
        return self


class RiskManagerInputV1(DomainModel):
    """Versioned Risk Manager input over the complete validated research chain."""

    schema_version: InputSchemaVersion = AGENT_INPUT_SCHEMA_VERSION
    expected_output_schema_version: OutputSchemaVersion = AGENT_OUTPUT_SCHEMA_VERSION
    agent_name: Literal[AgentName.RISK_MANAGER] = AgentName.RISK_MANAGER
    context: ManagerResearchContextV1
    research_output: VersionedUpstreamOutputV1
    bull_output: VersionedUpstreamOutputV1
    bear_output: VersionedUpstreamOutputV1

    @model_validator(mode="after")
    def validate_upstream(self) -> Self:
        """Require successful Research, Bull, and Bear results by exact role."""

        _require_manager_context(self.context, AgentName.RISK_MANAGER)
        _require_successful_output(self.research_output, AgentName.RESEARCH_MANAGER)
        _require_successful_output(self.bull_output, AgentName.BULL_MANAGER)
        _require_successful_output(self.bear_output, AgentName.BEAR_MANAGER)
        return self


type EightAgentInputV1 = (
    AnalystInputV1
    | ResearchManagerInputV1
    | BullManagerInputV1
    | BearManagerInputV1
    | RiskManagerInputV1
)


class AgentInputProjectionError(ValueError):
    """Raised when Data and Memory bundles cannot form one safe Agent input."""


class AgentInputProjector:
    """Build side-effect-free role views from approved Data and Memory bundles."""

    @staticmethod
    def analyst(
        data_bundle: ResearchDataBundle,
        context_bundle: ResearchContextBundle,
        agent_name: AgentName,
        sector_context_bundle: SectorContextBundle | None = None,
    ) -> AnalystInputV1:
        """Project one of the four Analyst inputs.

        Args:
            data_bundle: Provider-independent structured research evidence.
            context_bundle: Point-in-time Memory context.
            agent_name: One fixed Analyst role.

        Returns:
            A strict role-specific Analyst input.

        Raises:
            AgentInputProjectionError: If the role or bundle identity is invalid.
        """

        if agent_name not in _ANALYSTS:
            raise AgentInputProjectionError("analyst projection requires Analyst role")
        values = _base_input_values(
            data_bundle,
            context_bundle,
            agent_name,
            (),
            sector_context_bundle,
        )
        model_by_role: dict[AgentName, type[AgentInputBaseV1]] = {
            AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystInputV1,
            AgentName.TECHNICAL_TEXT_ANALYST: TechnicalTextAnalystInputV1,
            AgentName.SENTIMENT_ANALYST: SentimentAnalystInputV1,
            AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystInputV1,
        }
        return cast(
            AnalystInputV1,
            model_by_role[agent_name].model_validate(values),
        )

    @staticmethod
    def manager_context(
        data_bundle: ResearchDataBundle,
        context_bundle: ResearchContextBundle,
        agent_name: AgentName,
        analyst_outputs: tuple[VersionedUpstreamOutputV1, ...],
        sector_context_bundle: SectorContextBundle | None = None,
    ) -> ManagerResearchContextV1:
        """Project read-only global context for one Manager role.

        Args:
            data_bundle: Provider-independent structured research evidence.
            context_bundle: Point-in-time Memory context.
            agent_name: Research, Bull, Bear, or Risk Manager.
            analyst_outputs: Exactly four explicit Analyst output slots.

        Returns:
            Strict Manager context preserving failed Analyst coverage.

        Raises:
            AgentInputProjectionError: If the target is not a Manager role.
        """

        manager_roles = {
            AgentName.RESEARCH_MANAGER,
            AgentName.BULL_MANAGER,
            AgentName.BEAR_MANAGER,
            AgentName.RISK_MANAGER,
        }
        if agent_name not in manager_roles:
            raise AgentInputProjectionError("manager projection requires Manager role")
        unavailable = tuple(
            output.agent_name
            for output in analyst_outputs
            if output.status is not AgentStatus.OK
        )
        values = _base_input_values(
            data_bundle,
            context_bundle,
            agent_name,
            unavailable,
            sector_context_bundle,
        )
        values["analyst_outputs"] = analyst_outputs
        return ManagerResearchContextV1.model_validate(values)


def _base_input_values(
    data_bundle: ResearchDataBundle,
    context_bundle: ResearchContextBundle,
    agent_name: AgentName,
    unavailable_upstream: tuple[AgentName, ...],
    sector_context_bundle: SectorContextBundle | None,
) -> dict[str, object]:
    _validate_bundle_alignment(data_bundle, context_bundle)
    requirement = _requirement(agent_name)
    capabilities = (*requirement.required_data, *requirement.optional_data)
    sections = tuple(_project_data_section(data_bundle, item) for item in capabilities)
    memory_sections = (*requirement.required_memory, *requirement.optional_memory)
    memory_items = tuple(
        item
        for section in memory_sections
        for item in context_bundle.items_for_section(section)
    )
    missing_context = tuple(
        item
        for item in context_bundle.missing_context
        if item.section in memory_sections
    )
    missing_data = tuple(item for section in sections for item in section.missing_data)
    scope = ResearchScopeV1(
        asset_id=data_bundle.asset_id,
        market=data_bundle.asset_id.market,
        as_of=data_bundle.as_of,
        window_start=data_bundle.window_start,
        window_end=data_bundle.window_end,
        dataset_version=data_bundle.dataset_version,
        data_bundle_id=data_bundle.bundle_id,
        data_input_fingerprint=data_bundle.input_fingerprint,
        data_snapshot_id=data_bundle.snapshot_id,
        memory_snapshot_id=context_bundle.retrieval_metadata.snapshot_id,
    )
    return {
        "agent_name": agent_name,
        "scope": scope,
        "data": AgentDataViewV1(sections=sections),
        "memory": AgentMemoryViewV1(
            allowed_sections=memory_sections,
            items=memory_items,
            missing_context=missing_context,
            retrieval_metadata=context_bundle.retrieval_metadata,
        ),
        "coverage": AgentCoverageManifestV1(
            required_data=requirement.required_data,
            optional_data=requirement.optional_data,
            required_memory=requirement.required_memory,
            optional_memory=requirement.optional_memory,
            missing_data=missing_data,
            missing_context=missing_context,
            required_upstream_outputs=requirement.required_upstream_outputs,
            unavailable_upstream_outputs=unavailable_upstream,
            missing_data_behavior=requirement.missing_data_behavior,
            degradation_behavior=requirement.degradation_behavior,
        ),
        "data_evidence_index": {
            item.evidence_id: item for section in sections for item in section.items
        },
        "memory_evidence_index": {item.memory_id: item for item in memory_items},
        "sector_context": (
            None
            if sector_context_bundle is None
            else SectorContextProjector.for_role(sector_context_bundle, agent_name)
        ),
    }


def _validate_bundle_alignment(
    data_bundle: ResearchDataBundle,
    context_bundle: ResearchContextBundle,
) -> None:
    metadata = context_bundle.retrieval_metadata
    if metadata.asset_id != data_bundle.asset_id:
        raise AgentInputProjectionError("Data and Memory asset identity must match")
    if metadata.market is not data_bundle.asset_id.market:
        raise AgentInputProjectionError("Data and Memory market must match")
    if metadata.as_of != data_bundle.as_of:
        raise AgentInputProjectionError("Data and Memory as_of must match")


def _data_section(
    bundle: ResearchDataBundle,
    capability: DataCapability,
) -> ResearchDataSection:
    value = getattr(bundle, capability.value)
    if not isinstance(value, ResearchDataSection):
        raise AgentInputProjectionError("ResearchDataBundle capability is invalid")
    return value


def _project_data_section(
    bundle: ResearchDataBundle,
    capability: DataCapability,
) -> ResearchDataSection:
    """Return a bounded field-balanced view without changing the source bundle."""

    section = _data_section(bundle, capability)
    limit = _AGENT_EVIDENCE_LIMITS[capability]
    if len(section.items) <= limit:
        return section

    by_field: dict[str, list[ResearchEvidenceItem]] = {}
    for item in sorted(
        section.items,
        key=lambda value: (
            value.effective_at,
            value.observed_at,
            value.evidence_id,
        ),
        reverse=True,
    ):
        by_field.setdefault(item.field_path, []).append(item)

    selected: list[ResearchEvidenceItem] = []
    depth = 0
    field_names = sorted(by_field)
    while len(selected) < limit:
        added = False
        for field_name in field_names:
            items = by_field[field_name]
            if depth >= len(items):
                continue
            selected.append(items[depth])
            added = True
            if len(selected) == limit:
                break
        if not added:
            break
        depth += 1

    selected.sort(
        key=lambda value: (
            value.effective_at,
            value.field_path,
            value.evidence_id,
        )
    )
    return section.model_copy(update={"items": tuple(selected)})


def _requirement(agent_name: AgentName) -> AgentInputRequirement:
    for requirement in AGENT_INPUT_MATRIX:
        if requirement.agent is agent_name:
            return requirement
    raise ValueError(f"Agent input matrix has no role: {agent_name.value}")


def _require_manager_context(
    context: ManagerResearchContextV1,
    role: AgentName,
) -> None:
    if context.agent_name is not role:
        raise ValueError(f"Manager context must target {role.value}")


def _require_successful_output(
    output: VersionedUpstreamOutputV1,
    role: AgentName,
) -> None:
    if output.agent_name is not role or output.status is not AgentStatus.OK:
        raise ValueError(f"successful {role.value} output is required")
