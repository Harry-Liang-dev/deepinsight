"""Analyst and manager agent input and output contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.enums import AgentName, AgentStatus, ClaimIntent, ReportMarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject, JsonValue
from src.schemas.common import SourceReference
from src.schemas.documents import RetrievedDocument
from src.schemas.memory import MemorySearchResult

type RoleEvidenceManifestVersion = Literal["role_evidence_manifest_v1"]
type ClaimEvidenceBindingVersion = Literal[
    "claim_evidence_binding_v1", "validated_claim_v1"
]
type RoleEvidenceType = Literal[
    "document",
    "memory",
    "structured_direct",
    "structured_derived",
]
type ClaimDerivationType = Literal["direct_evidence"]
type ClaimType = Literal["factual", "analytical", "downside", "invalidator"]
type ScoreSourceType = Literal["assessment_score", "deterministic_calculation"]


class RoleEvidenceManifestEntry(DomainModel):
    """One exact, citation-allowed Evidence identity visible to one role."""

    evidence_id: str = Field(min_length=1)
    evidence_type: RoleEvidenceType
    source: SourceReference
    as_of: datetime | None = None
    short_description: str = Field(min_length=1)
    numeric_tokens: tuple[str, ...] = ()
    citation_allowed: Literal[True] = True

    @model_validator(mode="after")
    def validate_numeric_tokens(self) -> Self:
        """Require stable, non-empty, unique numeric literals."""

        if any(not token.strip() for token in self.numeric_tokens):
            raise ValueError("Evidence numeric tokens cannot be blank")
        if len(self.numeric_tokens) != len(set(self.numeric_tokens)):
            raise ValueError("Evidence numeric tokens must be unique")
        return self


class RoleEvidenceManifest(DomainModel):
    """The sole citation namespace exposed to one Agent invocation."""

    schema_version: RoleEvidenceManifestVersion = "role_evidence_manifest_v1"
    agent_name: AgentName
    entries: tuple[RoleEvidenceManifestEntry, ...]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        """Reject aliases or duplicate Evidence identities."""

        ids = tuple(entry.evidence_id for entry in self.entries)
        if len(ids) != len(set(ids)):
            raise ValueError("Role Evidence IDs must be unique")
        return self


class ClaimEvidenceBinding(DomainModel):
    """One accepted Claim with exactly one authoritative provenance route.

    Analysts bind directly to canonical Evidence. Managers bind to accepted
    upstream Claims; their citations are inherited recursively for rendering
    and audit rather than revalidated against raw Evidence.
    """

    schema_version: ClaimEvidenceBindingVersion = "validated_claim_v1"
    claim_path: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    numeric_literals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    source_references: tuple[SourceReference, ...] = ()
    derivation_type: ClaimDerivationType = "direct_evidence"
    claim_id: str | None = Field(default=None, min_length=1)
    claim_type: ClaimType | None = None
    claim_intent: ClaimIntent = ClaimIntent.FACT
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["accepted"] = "accepted"

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        """Keep claim bindings deterministic and alias-free."""

        if len(self.numeric_literals) != len(set(self.numeric_literals)):
            raise ValueError("Claim numeric literals must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Claim Evidence IDs must be unique")
        if len(self.upstream_claim_ids) != len(set(self.upstream_claim_ids)):
            raise ValueError("Claim upstream IDs must be unique")
        if bool(self.evidence_ids) == bool(self.upstream_claim_ids):
            raise ValueError(
                "accepted Claim requires exactly one Evidence or upstream route"
            )
        return self

    @classmethod
    def from_legacy_evidence(
        cls,
        **values: object,
    ) -> Self:
        """Explicit compatibility constructor for pre-v2 fixtures only."""

        return cls.model_validate(values)


ValidatedClaim = ClaimEvidenceBinding


class RejectedClaim(DomainModel):
    """Credential-free record for one discarded, invalid Claim object."""

    claim_path: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    numeric_literals: tuple[str, ...] = ()
    status: Literal["rejected"] = "rejected"


class FundamentalScoreMetadata(DomainModel):
    """Provenance metadata for a non-factual normalized assessment score."""

    source_type: ScoreSourceType
    calculation: str | None = None
    evidence_ids: tuple[str, ...] = ()


class FundamentalNormalizedScores(DomainModel):
    """The three normalized scores kept separate from factual Claims."""

    quality_score: float = Field(ge=0.0, le=1.0)
    growth_score: float = Field(ge=0.0, le=1.0)
    valuation_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, FundamentalScoreMetadata] = Field(default_factory=dict)


class FundamentalClaim(ClaimEvidenceBinding):
    """One Fundamental factual or analytical Claim."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^analysis\.(facts|key_points|risk_points)\[\d+\]$",
    )
    claim_type: ClaimType | None = None


class FundamentalClaimAnalysis(DomainModel):
    """Fundamental Claim-first generation output."""

    claims: list[FundamentalClaim] = Field(default_factory=list)
    normalized_scores: FundamentalNormalizedScores
    uncertainties: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_claim_paths(self) -> Self:
        """Reject duplicates while permitting sparse paths for quarantine."""

        paths = [claim.claim_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("Fundamental claim paths must be unique")
        return self


class FundamentalClaimResponse(DomainModel):
    """Schema-constrained Fundamental response before public assembly."""

    agent_name: Literal[AgentName.FUNDAMENTAL_ANALYST] = AgentName.FUNDAMENTAL_ANALYST
    status: AgentStatus
    analysis: FundamentalClaimAnalysis


class FundamentalDraftClaim(DomainModel):
    """Gateway draft Claim shape; strict Evidence validation happens locally."""

    claim_id: str | None = Field(default=None, min_length=1)
    # Keep the gateway draft permissive so one malformed Claim can be
    # quarantined locally instead of aborting the complete collection.
    claim_type: str | None = Field(default=None, min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.FACT
    claim_path: str = Field(
        min_length=1,
        pattern=r"^analysis\.(facts|key_points|risk_points)\[\d+\]$",
    )
    claim_text: str = Field(min_length=1)
    numeric_literals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class FundamentalDraftAnalysis(DomainModel):
    """Loose Gateway wrapper needed to quarantine invalid individual Claims."""

    claims: list[FundamentalDraftClaim] = Field(default_factory=list)
    normalized_scores: FundamentalNormalizedScores
    uncertainties: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonObject] = Field(default_factory=dict)


class FundamentalDraftResponse(DomainModel):
    """Gateway response model before local strict Claim validation."""

    agent_name: Literal[AgentName.FUNDAMENTAL_ANALYST] = AgentName.FUNDAMENTAL_ANALYST
    status: AgentStatus
    analysis: FundamentalDraftAnalysis


class AnalystClaim(ClaimEvidenceBinding):
    """One Analyst business claim as the role's sole generation unit."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^analysis\.(facts|key_points|risk_points)\[\d+\]$",
    )


class AnalystDraftClaim(DomainModel):
    """Permissive Analyst draft for claim-level quarantine."""

    claim_id: str | None = Field(default=None, min_length=1)
    claim_type: str | None = Field(default=None, min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.FACT
    claim_path: str = Field(
        min_length=1,
        pattern=r"^analysis\.(facts|key_points|risk_points)\[\d+\]$",
    )
    claim_text: str = Field(min_length=1)
    numeric_literals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AnalystDraftAnalysis(DomainModel):
    """Loose Analyst generation wrapper."""

    claims: list[AnalystDraftClaim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class TechnicalDraftResponse(DomainModel):
    """Technical draft before Claim quarantine."""

    agent_name: Literal[AgentName.TECHNICAL_TEXT_ANALYST] = (
        AgentName.TECHNICAL_TEXT_ANALYST
    )
    status: AgentStatus
    analysis: AnalystDraftAnalysis


class SentimentDraftResponse(DomainModel):
    """Sentiment draft before Claim quarantine."""

    agent_name: Literal[AgentName.SENTIMENT_ANALYST] = AgentName.SENTIMENT_ANALYST
    status: AgentStatus
    analysis: AnalystDraftAnalysis


class NewsDraftResponse(DomainModel):
    """News/Event draft before Claim quarantine."""

    agent_name: Literal[AgentName.NEWS_EVENT_ANALYST] = AgentName.NEWS_EVENT_ANALYST
    status: AgentStatus
    analysis: AnalystDraftAnalysis


class AnalystClaimAnalysis(DomainModel):
    """Analyst inference shape before deterministic public assembly."""

    claims: list[AnalystClaim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim_paths(self) -> Self:
        """Require unique paths and some useful role output.

        Paths may be sparse after an independently invalid Claim is
        quarantined. The presentation projection deterministically compacts
        them without changing Claim content or provenance.
        """

        paths = [claim.claim_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("Sentiment claim paths must be unique")
        if not self.claims and not self.uncertainties:
            raise ValueError("Analyst output requires claims or explicit uncertainty")
        return self


class TechnicalClaimResponse(DomainModel):
    """Schema-constrained LLM response for the Technical role."""

    agent_name: Literal[AgentName.TECHNICAL_TEXT_ANALYST] = (
        AgentName.TECHNICAL_TEXT_ANALYST
    )
    status: AgentStatus
    analysis: AnalystClaimAnalysis


class NewsClaimResponse(DomainModel):
    """Schema-constrained LLM response for the News/Event role."""

    agent_name: Literal[AgentName.NEWS_EVENT_ANALYST] = AgentName.NEWS_EVENT_ANALYST
    status: AgentStatus
    analysis: AnalystClaimAnalysis


class SentimentClaimResponse(DomainModel):
    """Schema-constrained LLM response for the Sentiment role."""

    agent_name: Literal[AgentName.SENTIMENT_ANALYST] = AgentName.SENTIMENT_ANALYST
    status: AgentStatus
    analysis: AnalystClaimAnalysis


SentimentClaim = AnalystClaim
SentimentClaimAnalysis = AnalystClaimAnalysis


class AgentContext(DomainModel):
    """Evidence and structured features supplied to an agent."""

    report_date: date
    market_scope: ReportMarketScope
    asset_id: AssetId
    structured_features: JsonObject
    structured_evidence: list[SourceReference] = Field(default_factory=list)
    role_evidence_manifest: RoleEvidenceManifest | None = None
    retrieved_memories: list[MemorySearchResult] = Field(default_factory=list)
    retrieved_documents: list[RetrievedDocument] = Field(default_factory=list)


class AgentRequest(DomainModel):
    """Common validated request for a Phase One agent."""

    run_id: str = Field(min_length=1)
    agent_name: AgentName
    model_name: str = Field(min_length=1)
    input_context: AgentContext
    research_contract: JsonObject | None = None


class FundamentalAnalysis(DomainModel):
    """Fundamental analyst output defined by MASTER_SPEC."""

    quality_score: float = Field(ge=0.0, le=1.0)
    growth_score: float = Field(ge=0.0, le=1.0)
    valuation_score: float = Field(ge=0.0, le=1.0)
    facts: list[str] = Field(default_factory=list)
    key_points: list[str]
    risk_points: list[str]
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class FundamentalAnalystResponse(DomainModel):
    """Fundamental analyst response envelope."""

    agent_name: Literal[AgentName.FUNDAMENTAL_ANALYST] = AgentName.FUNDAMENTAL_ANALYST
    status: AgentStatus
    analysis: FundamentalAnalysis


class AnalystAnalysis(DomainModel):
    """Minimum common output for analyst roles without a fixed schema."""

    facts: list[str] = Field(default_factory=list)
    key_points: list[str]
    risk_points: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)


class AnalystResponse(DomainModel):
    """Response envelope for non-fundamental analyst roles."""

    agent_name: Literal[
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    ]
    status: AgentStatus
    analysis: AnalystAnalysis


type AnalystOutput = FundamentalAnalystResponse | AnalystResponse


class ResearchManagerRequest(DomainModel):
    """Research Manager input after all analyst roles complete."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_contract: JsonObject | None = None


class ResearchSummary(DomainModel):
    """Minimum synthesis contract for the Research Manager."""

    summary_points: list[str]
    conflicts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    supporting_citations: list[SourceReference] = Field(default_factory=list)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)


class ManagerDraftClaim(DomainModel):
    """Permissive Manager draft validated claim-by-claim after generation."""

    claim_id: str | None = Field(default=None, min_length=1)
    claim_type: str | None = Field(default=None, min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.ANALYTICAL_INFERENCE
    claim_path: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    upstream_claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    numeric_literals: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ResearchManagerDraftClaim(ManagerDraftClaim):
    """One Research Manager synthesis Claim."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^analysis\.(summary_points|conflicts)\[\d+\]$",
    )


class RiskManagerDraftClaim(ManagerDraftClaim):
    """One Risk Manager review Claim."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^(confirmed_risks|scenario_risks|watch_items)\[\d+\]$",
    )


class ManagerClaim(ClaimEvidenceBinding):
    """Accepted Manager Claim whose facts derive only from upstream Claims."""

    claim_intent: ClaimIntent = ClaimIntent.ANALYTICAL_INFERENCE


class ResearchManagerDraftAnalysis(DomainModel):
    """Claim-first Research Manager generation shape."""

    claims: list[ResearchManagerDraftClaim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ResearchManagerDraftResponse(DomainModel):
    """Gateway response before Research Manager Claim quarantine."""

    agent_name: Literal[AgentName.RESEARCH_MANAGER] = AgentName.RESEARCH_MANAGER
    status: AgentStatus
    analysis: ResearchManagerDraftAnalysis


class ResearchManagerResponse(DomainModel):
    """Research Manager response envelope."""

    agent_name: Literal[AgentName.RESEARCH_MANAGER] = AgentName.RESEARCH_MANAGER
    status: AgentStatus
    analysis: ResearchSummary


class BullManagerRequest(DomainModel):
    """Bull Manager evidence and Research Manager synthesis."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary
    research_contract: JsonObject | None = None


class BullManagerResponse(DomainModel):
    """Constructive thesis output defined by MASTER_SPEC."""

    bull_thesis: list[str]
    conditions_required: list[str]
    invalidators: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class BullClaim(ManagerClaim):
    """One Bull business claim as the role's sole generation unit."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^(bull_thesis|conditions_required|invalidators)\[\d+\]$",
    )


class BullClaimResponse(DomainModel):
    """Schema-constrained LLM response before deterministic Bull assembly."""

    claims: list[BullClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim_paths(self) -> Self:
        """Require unique, contiguous paths and a bounded thesis."""

        paths = [claim.claim_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("Bull claim paths must be unique")
        for section in ("bull_thesis", "conditions_required", "invalidators"):
            actual = [
                claim.claim_path
                for claim in self.claims
                if claim.claim_path.startswith(f"{section}[")
            ]
            expected = [f"{section}[{index}]" for index in range(len(actual))]
            if actual != expected:
                raise ValueError("Bull claim paths must be contiguous and ordered")
        if not any(path.startswith("bull_thesis[") for path in paths):
            raise ValueError("Bull output requires at least one thesis claim")
        return self


class BullDraftClaim(ManagerDraftClaim):
    """Permissive Bull Claim before upstream provenance quarantine."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^(bull_thesis|conditions_required|invalidators)\[\d+\]$",
    )


class BullDraftResponse(DomainModel):
    """Loose Bull response before local Claim validation."""

    claims: list[BullDraftClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)


class BearManagerRequest(DomainModel):
    """Bear Manager evidence and Research Manager synthesis."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary
    research_contract: JsonObject | None = None


class BearManagerResponse(DomainModel):
    """Cautious thesis output defined by MASTER_SPEC."""

    bear_thesis: list[str]
    conditions_required: list[str]
    invalidators: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)


class BearClaim(ManagerClaim):
    """One Bear business claim as the role's sole generation unit."""

    claim_path: str = Field(
        min_length=1,
        pattern=r"^(bear_thesis|conditions_required|invalidators)\[\d+\]$",
    )


class BearClaimResponse(DomainModel):
    """Schema-constrained LLM response before deterministic Bear assembly."""

    claims: list[BearClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim_paths(self) -> Self:
        """Require unique paths and at least one bounded thesis.

        Sparse source indexes are allowed because producer-side quarantine may
        remove an invalid Claim before deterministic public assembly.
        """

        paths = [claim.claim_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("Bear claim paths must be unique")
        if not any(path.startswith("bear_thesis[") for path in paths):
            raise ValueError("Bear output requires at least one thesis claim")
        return self


class BearDraftClaim(DomainModel):
    """Gateway draft Bear Claim shape for producer-side quarantine."""

    claim_id: str | None = Field(default=None, min_length=1)
    # Keep the gateway draft permissive so one malformed Claim can be
    # quarantined locally instead of aborting the complete collection.
    claim_type: str | None = Field(default=None, min_length=1)
    claim_intent: ClaimIntent = ClaimIntent.FACT
    claim_path: str = Field(
        min_length=1,
        pattern=r"^(bear_thesis|conditions_required|invalidators)\[\d+\]$",
    )
    claim_text: str = Field(min_length=1)
    numeric_literals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    upstream_claim_ids: tuple[str, ...] = ()
    derivation_type: ClaimDerivationType = "direct_evidence"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class BearDraftResponse(DomainModel):
    """Loose Gateway response before local strict Bear Claim validation."""

    claims: list[BearDraftClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)


class RiskManagerRequest(DomainModel):
    """Risk Manager input after constructive and cautious review."""

    input_context: AgentContext
    analyst_outputs: list[AnalystOutput] = Field(min_length=1)
    research_summary: ResearchSummary
    bull_output: BullManagerResponse
    bear_output: BearManagerResponse
    research_contract: JsonObject | None = None


class RiskManagerResponse(DomainModel):
    """Risk review output defined by MASTER_SPEC."""

    confirmed_risks: list[str]
    scenario_risks: list[str]
    watch_items: list[str]
    narrative_risk_score: float = Field(ge=0.0, le=1.0)
    claim_evidence: list[ClaimEvidenceBinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class RiskManagerDraftResponse(DomainModel):
    """Claim-first Risk Manager response before local quarantine."""

    claims: list[RiskManagerDraftClaim] = Field(default_factory=list)
    narrative_risk_score: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)
