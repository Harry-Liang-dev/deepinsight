"""Additive strict AnalystResult, plan, messages and synthesis contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from src.models.enums import AgentName
from src.schemas.research_v2_shared import Clock, Frozen, Reference, Text, reference

CoverageStatus = Literal[
    "COMPLETE", "PARTIAL", "MISSING_INPUT", "NOT_RESEARCHED", "NOT_APPLICABLE", "FAILED"
]
RequestStatus = Literal[
    "OPEN",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "RESOLVED",
    "UNRESOLVED",
    "FAILED",
    "CANCELLED",
]


class Coverage(Frozen):
    """Disposition for one plan-requested asset, role and capability."""

    scope_id: Text
    role: Text
    capability: Text
    status: CoverageStatus
    reason: Text
    required: bool
    missing_items: tuple[Text, ...]
    applicability_rule: Reference | None
    evidence_refs: tuple[Reference, ...]

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        for item in self.evidence_refs:
            item.require("EVIDENCE")
        if self.status == "NOT_APPLICABLE" and not self.applicability_rule:
            raise ValueError("APPLICABILITY_PROOF_REQUIRED")
        if self.applicability_rule:
            self.applicability_rule.require("DEFINITION")
        if self.status == "COMPLETE" and (self.missing_items or not self.evidence_refs):
            raise ValueError("EMPTY_OR_INCOMPLETE_COVERAGE")
        if self.status == "PARTIAL" and not self.missing_items:
            raise ValueError("PARTIAL_GAPS_REQUIRED")
        return self


class Confidence(Frozen):
    """Uncalibrated confidence with attributable support."""

    level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    meaning: Literal["UNCALIBRATED_RESEARCH_CONFIDENCE_NOT_RETURN_PROBABILITY"]
    reason: Text
    support: tuple[Reference, ...]


class Statement(Frozen):
    """A Claim-backed fact or separately typed research inference."""

    id: Text
    kind: Literal["FACT", "ANALYTICAL_INFERENCE", "HYPOTHESIS", "UNCERTAINTY"]
    text: Text
    support: tuple[Reference, ...]
    counter_evidence: tuple[Reference, ...]
    confidence: Confidence

    @model_validator(mode="after")
    def fact_support(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        if self.kind == "FACT":
            if not self.support:
                raise ValueError("UNSUPPORTED_FACT")
            for r in self.support:
                r.require("CLAIM")
        for r in self.counter_evidence:
            r.require("EVIDENCE")
        return self


class QuantitativeFact(Frozen):
    """Exact numeric Claim, unit/basis and validator receipt."""

    claim: Reference
    value: float
    unit: Text
    period_basis: Text
    grounding_receipt: Reference
    operand_refs: tuple[Reference, ...]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.claim.require("CLAIM")
        self.grounding_receipt.require("RECEIPT")
        return self


class Question(Frozen):
    """A tracked research question with original resolution requirements."""

    id: Text
    text: Text
    owner: Text
    status: RequestStatus
    subject_refs: tuple[Reference, ...]
    required_resolution: Text
    resolution_refs: tuple[Reference, ...]
    reason: Text


class Trigger(Frozen):
    """Attributable mechanism and observable trigger, or explicit unknown."""

    statement: Statement
    mechanism: Text
    horizon: str | None
    observable_trigger: str | None
    unknown_reason: str | None
    dependencies: tuple[Reference, ...]

    @model_validator(mode="after")
    def unknown(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        if (
            self.horizon is None or self.observable_trigger is None
        ) and not self.unknown_reason:
            raise ValueError("UNKNOWN_TRIGGER_REASON_REQUIRED")
        return self


class Contradiction(Frozen):
    """Fact comparability or hypothesis disagreement with separate disposition."""

    id: Text
    kind: Literal[
        "COMPARABLE_FACT_CONFLICT",
        "INCOMPARABLE_CONTEXT",
        "INSUFFICIENT_CONTEXT",
        "HYPOTHESIS_DISAGREEMENT",
    ]
    left: Reference
    right: Reference
    comparability_receipt: Reference | None
    status: Literal["OPEN", "RESOLVED", "UNRESOLVED"]
    reason: Text
    resolution_refs: tuple[Reference, ...]

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        ns = "HYPOTHESIS" if self.kind == "HYPOTHESIS_DISAGREEMENT" else "CLAIM"
        self.left.require(ns)
        self.right.require(ns)
        if self.comparability_receipt:
            self.comparability_receipt.require("RECEIPT")
        if self.kind != "HYPOTHESIS_DISAGREEMENT" and not self.comparability_receipt:
            raise ValueError("COMPARABILITY_RECEIPT_REQUIRED")
        if self.status == "RESOLVED" and not self.resolution_refs:
            raise ValueError("CONTRADICTION_RESOLUTION_PROOF")
        return self


class SlotDisposition(Frozen):
    """Explicit completion or missingness for a result field."""

    status: CoverageStatus
    reason: Text


class SlotDispositions(Frozen):
    """Full frozen Analyst field census."""

    findings: SlotDisposition
    claims: SlotDisposition
    evidence_refs: SlotDisposition
    quantitative_facts: SlotDisposition
    hypotheses: SlotDisposition
    risks: SlotDisposition
    catalysts: SlotDisposition
    contradictions: SlotDisposition
    uncertainties: SlotDisposition
    open_questions: SlotDisposition
    followup_requests: SlotDisposition
    dependencies: SlotDisposition


class AnalystResult(Frozen):
    """Strict v2 Analyst output consuming an exact State revision."""

    schema_version: Literal["analyst_result_v2"]
    result_id: Text
    run_id: Text
    episode: Reference
    plan: Reference
    participant: Text
    scope_id: Text
    research_as_of: Clock
    generated_at: Clock
    read_state: Reference
    model: Reference
    prompt: Reference
    producer_build: Reference
    coverage: tuple[Coverage, ...]
    slot_dispositions: SlotDispositions
    findings: tuple[Statement, ...]
    claims: tuple[Reference, ...]
    evidence_refs: tuple[Reference, ...]
    quantitative_facts: tuple[QuantitativeFact, ...]
    hypotheses: tuple[Statement, ...]
    risks: tuple[Trigger, ...]
    catalysts: tuple[Trigger, ...]
    contradictions: tuple[Contradiction, ...]
    uncertainties: tuple[Statement, ...]
    open_questions: tuple[Question, ...]
    followup_requests: tuple[Reference, ...]
    confidence: Confidence
    dependencies: tuple[Reference, ...]

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        for name, ns in [
            ("episode", "EPISODE"),
            ("plan", "PLAN"),
            ("read_state", "STATE"),
            ("model", "MODEL"),
            ("prompt", "PROMPT"),
            ("producer_build", "BUILD"),
        ]:
            getattr(self, name).require(ns)
        if self.generated_at < self.research_as_of:
            raise ValueError("RESULT_CHRONOLOGY")
        for items, ns in [
            (self.claims, "CLAIM"),
            (self.evidence_refs, "EVIDENCE"),
            (self.followup_requests, "MESSAGE"),
        ]:
            for item in items:
                item.require(ns)
        for name in SlotDispositions.model_fields:
            if (
                not getattr(self, name)
                and getattr(self.slot_dispositions, name).status == "COMPLETE"
            ):
                raise ValueError("EMPTY_COMPLETE_SLOT:" + name)
        if any(s.kind != "HYPOTHESIS" for s in self.hypotheses) or any(
            s.kind != "UNCERTAINTY" for s in self.uncertainties
        ):
            raise ValueError("STATEMENT_SLOT_KIND")
        if not self.coverage:
            raise ValueError("RESULT_COVERAGE_REQUIRED")
        return self

    @property
    def reference(self) -> Reference:
        """Bind the result without introducing a second Claim namespace."""
        return reference("RECEIPT", self.result_id, "analyst_result_v2", self)


class CollaborationMessage(Frozen):
    """Versioned request/response retaining original acceptance conditions."""

    schema_version: Literal["research_collaboration_message_v1"]
    message_id: Text
    kind: Literal[
        "EVIDENCE_REQUEST",
        "FOLLOWUP_REQUEST",
        "HYPOTHESIS_CHALLENGE",
        "CONTRADICTION_NOTICE",
        "DEPENDENCY_REQUEST",
        "RESOLUTION",
    ]
    run_id: Text
    episode: Reference
    state_revision: Reference
    sender: Text
    recipient: Text
    created_at: Clock
    deadline: Clock
    priority: Annotated[int, Field(ge=0)]
    idempotency_key: Text
    causal_requests: tuple[Reference, ...]
    subject_refs: tuple[Reference, ...]
    purpose: Text
    acceptance_conditions: tuple[Text, ...]
    budget_ref: Reference
    resolution_status: Literal["RESOLVED", "UNRESOLVED", "FAILED", "CANCELLED"] | None
    resolution_evidence: tuple[Reference, ...]
    validation_receipt: Reference | None

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.episode.require("EPISODE")
        self.state_revision.require("STATE")
        self.budget_ref.require("DEFINITION")
        for r in self.causal_requests:
            r.require("MESSAGE")
        for r in self.resolution_evidence:
            r.require("EVIDENCE", "CLAIM")
        if self.validation_receipt:
            self.validation_receipt.require("RECEIPT")
        if self.deadline < self.created_at:
            raise ValueError("INVALID_DEADLINE")
        if self.kind == "RESOLUTION":
            if not self.causal_requests or self.resolution_status is None:
                raise ValueError("RESOLUTION_CAUSAL_REQUEST_REQUIRED")
            if self.resolution_status == "RESOLVED" and (
                not self.resolution_evidence or not self.validation_receipt
            ):
                raise ValueError("FABRICATED_RESOLUTION")
        elif (
            self.resolution_status is not None
            or self.resolution_evidence
            or self.validation_receipt
        ):
            raise ValueError("REQUEST_CANNOT_ASSERT_RESOLUTION")
        elif not self.acceptance_conditions:
            raise ValueError("REQUEST_CONDITIONS_REQUIRED")
        return self

    @property
    def reference(self) -> Reference:
        """Content identity includes original acceptance conditions."""
        return reference(
            "MESSAGE", self.message_id, "research_collaboration_message_v1", self
        )


class Scenario(Frozen):
    """Structured thesis case whose financial facts must remain Claim-backed."""

    status: CoverageStatus
    reason: Text
    statements: tuple[Statement, ...]
    assumptions: tuple[Statement, ...]
    mechanisms: tuple[Statement, ...]
    major_evidence: tuple[Reference, ...]
    opposing_evidence: tuple[Reference, ...]
    contradictions: tuple[Contradiction, ...]
    uncertainties: tuple[Statement, ...]
    catalysts: tuple[Trigger, ...]
    risk_triggers: tuple[Trigger, ...]
    open_questions: tuple[Question, ...]
    thesis_change_conditions: tuple[Trigger, ...]

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        for r in (*self.major_evidence, *self.opposing_evidence):
            r.require("EVIDENCE")
        if self.status == "COMPLETE" and (
            not self.statements
            or not self.major_evidence
            or self.open_questions
            or any(c.status != "RESOLVED" for c in self.contradictions)
        ):
            raise ValueError("INCOMPLETE_SCENARIO")
        return self


class SynthesisState(Frozen):
    """Three revision-bound cases with traceable upstream dependencies."""

    schema_version: Literal["research_synthesis_state_v2"]
    run_id: Text
    state_revision: Reference
    research_as_of: Clock
    generated_at: Clock
    base_case: Scenario
    bull_case: Scenario
    bear_case: Scenario
    dependencies: tuple[Reference, ...]

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        self.state_revision.require("STATE")
        if self.generated_at < self.research_as_of:
            raise ValueError("SYNTHESIS_CHRONOLOGY")
        return self


class Budgets(Frozen):
    """Finite offline limits; no live capability is implicitly granted."""

    max_rounds: Annotated[int, Field(ge=1)]
    max_messages: Annotated[int, Field(ge=1)]
    max_followups: Annotated[int, Field(ge=0)]
    max_retries_per_request: Annotated[int, Field(ge=0)]
    max_provider_calls: Literal[0]
    max_llm_calls: Literal[0]
    max_llm_tokens: Literal[0]
    max_tool_calls: Literal[0]
    max_wall_seconds: Annotated[float, Field(gt=0)]

    @property
    def reference(self) -> Reference:
        """Explicit finite offline policy, never an executable live default."""
        return reference("DEFINITION", "offline-collaboration-budget", "1.0.0", self)


class AuthorizedPilotBudgets(Frozen):
    """Additive one-shot real-inference budget; offline Budgets stay unchanged."""

    authorization_sha256: Literal[
        "11478f49550a350a99e19e76040ba92b1df9b7b1cf00b1b5651a793a48de32a0"
    ]
    max_rounds: Literal[2] = 2
    max_messages: Literal[12] = 12
    max_followups: Literal[2] = 2
    max_retries_per_request: Literal[1] = 1
    max_provider_calls: Literal[0] = 0
    max_llm_calls: Literal[12] = 12
    max_llm_tokens: Literal[12000000] = 12000000
    max_tool_calls: Literal[0] = 0
    max_wall_seconds: Annotated[float, Field(ge=1200, le=1200)] = 1200.0

    @property
    def reference(self) -> Reference:
        """Reference does not replace the independently verified execution grant."""
        return reference(
            "DEFINITION", "authorized-retained-pilot-budget", "1.0.0", self
        )


class G90PilotBudgets(Frozen):
    """Independent two-call G90 scope, never an alias for a historical grant."""

    experiment: Literal["G90_REAL_RESEARCH_V2_ADMISSION_AND_MEMORY"]
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_rounds: Literal[1] = 1
    max_messages: Literal[2] = 2
    max_followups: Literal[0] = 0
    max_retries_per_request: Literal[0] = 0
    max_provider_calls: Literal[0] = 0
    max_llm_calls: Literal[2] = 2
    max_llm_tokens: Literal[1989760] = 1989760
    max_tool_calls: Literal[0] = 0
    max_wall_seconds: Annotated[float, Field(ge=180, le=180)] = 180.0

    @property
    def reference(self) -> Reference:
        """Bind exact scope; actual dispatch still requires the original meter."""
        return reference("DEFINITION", "g90-two-call-budget", "1.0.0", self)


class G91PilotBudgets(Frozen):
    """Independent two-call G91 scope, never an alias for a historical grant."""

    experiment: Literal["G91_TYPED_SEMANTIC_ADMISSION_AND_REAL_MEMORY"]
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_rounds: Literal[1] = 1
    max_messages: Literal[2] = 2
    max_followups: Literal[0] = 0
    max_retries_per_request: Literal[0] = 0
    max_provider_calls: Literal[0] = 0
    max_llm_calls: Literal[2] = 2
    max_llm_tokens: Literal[1989760] = 1989760
    max_tool_calls: Literal[0] = 0
    max_wall_seconds: Annotated[float, Field(ge=180, le=180)] = 180.0

    @property
    def reference(self) -> Reference:
        """Bind exact scope; actual dispatch still requires the original meter."""
        return reference("DEFINITION", "g91-two-call-budget", "1.0.0", self)


class G97PilotBudgets(Frozen):
    """Independent two-call G97 scope, never an alias for a historical grant."""

    experiment: Literal["G97_AVGO_REAL_SPECIALIST_INCREMENTAL_RESEARCH"]
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_rounds: Literal[1] = 1
    max_messages: Literal[2] = 2
    max_followups: Literal[0] = 0
    max_retries_per_request: Literal[0] = 0
    max_provider_calls: Literal[0] = 0
    max_llm_calls: Literal[2] = 2
    max_llm_tokens: Literal[1989760] = 1989760
    max_tool_calls: Literal[0] = 0
    max_wall_seconds: Annotated[float, Field(ge=180, le=180)] = 180.0

    @property
    def reference(self) -> Reference:
        """Bind exact scope; actual dispatch still requires the original meter."""
        return reference("DEFINITION", "g97-two-call-budget", "1.0.0", self)


class RequestedSlot(Frozen):
    """Prospectively registered capability and applicability requirement."""

    scope_id: Text
    role: Text
    capability: Text
    required: bool
    applicable: bool
    applicability_rule: Reference
    reason: Text

    @property
    def key(self) -> tuple[str, str, str]:
        """Validate the exact typed field and namespace invariants."""
        return self.scope_id, self.role, self.capability


class ResearchPlan(Frozen):
    """Complete immutable population, cutoff, permissions and budget binding."""

    schema_version: Literal["research_plan_v2"]
    plan_id: Text
    run_id: Text
    episode: Reference
    research_as_of: Clock
    requested_assets: tuple[Text, ...]
    requested_roles: tuple[Text, ...]
    required_capabilities: tuple[Text, ...]
    slots: tuple[RequestedSlot, ...]
    budgets: (
        Budgets
        | AuthorizedPilotBudgets
        | G90PilotBudgets
        | G91PilotBudgets
        | G97PilotBudgets
    )
    source_permissions: tuple[Reference, ...]
    model: Reference
    prompt: Reference
    producer_build: Reference
    input_snapshots: tuple[Reference, ...]
    registered_at: Clock

    @model_validator(mode="after")
    def validity(self) -> Self:
        """Validate the exact typed field and namespace invariants."""
        roles = {r.value for r in AgentName} | {"sector_research"}
        if (
            not self.requested_assets
            or not self.requested_roles
            or not self.required_capabilities
            or set(self.requested_roles) - roles
        ):
            raise ValueError("UNREGISTERED_PLAN_POPULATION")
        expected = {
            (a, r, c)
            for a in self.requested_assets
            for r in self.requested_roles
            for c in self.required_capabilities
        }
        if {s.key for s in self.slots} != expected or len(self.slots) != len(expected):
            raise ValueError("INCOMPLETE_PLAN_CENSUS")
        if self.registered_at > self.research_as_of:
            raise ValueError("LATE_PLAN_REGISTRATION")
        self.episode.require("EPISODE")
        self.model.require("MODEL")
        self.prompt.require("PROMPT")
        self.producer_build.require("BUILD")
        for s in self.slots:
            s.applicability_rule.require("DEFINITION")
        for p in self.source_permissions:
            p.require("DEFINITION")
        return self

    @property
    def reference(self) -> Reference:
        """Immutable registration identity binds complete population and config."""
        return reference("PLAN", self.plan_id, "research_plan_v2", self)


class SectorEntity(Frozen):
    """Frozen Sector interface binding; membership is not company economics."""

    entity: Reference
    scope_id: Text
    kind: Literal["COMPANY", "SECTOR", "INDUSTRY_CHAIN", "PRODUCT", "INPUT"]
    identity_authority: Reference

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Require an explicit entity and identity authority namespace."""
        self.entity.require("SECTOR_ENTITY")
        self.identity_authority.require("RECEIPT")
        return self


class SectorEdge(Frozen):
    """Typed edge context only; no automatic propagation into accepted Claims."""

    edge: Reference
    source: Reference
    target: Reference
    kind: Literal[
        "SUPPLIER_CUSTOMER",
        "MEMBERSHIP",
        "INPUT_DEPENDENCY",
        "EVENT_PROPAGATION_CANDIDATE",
    ]
    evidence_class: Literal["SOURCE_OBSERVED", "CURATED_ONTOLOGY", "HYPOTHESIS"]
    mechanism: Text
    valid_from: Clock | None
    valid_through: Clock | None
    unknown_time_reason: str | None
    support: tuple[Reference, ...]
    confidence: Confidence

    @model_validator(mode="after")
    def namespaces(self) -> Self:
        """Unknown or inverted validity never becomes a known temporal interval."""
        self.edge.require("SECTOR_EDGE")
        self.source.require("SECTOR_ENTITY")
        self.target.require("SECTOR_ENTITY")
        if (
            self.valid_from is None or self.valid_through is None
        ) and not self.unknown_time_reason:
            raise ValueError("UNKNOWN_EDGE_TIME_REASON")
        if (
            self.valid_from
            and self.valid_through
            and self.valid_from > self.valid_through
        ):
            raise ValueError("EDGE_TIME_INTERVAL")
        return self


class SectorResult(Frozen):
    """Interface compatibility for later W3 integration, not a new Sector Agent."""

    schema_version: Literal["sector_research_result_v2"]
    analyst_result: AnalystResult
    entities: tuple[SectorEntity, ...]
    edges: tuple[SectorEdge, ...]
    supply_chain_dependencies: tuple[Reference, ...]
    sector_events: tuple[Reference, ...]
    cross_company_propagation: tuple[Statement, ...]
    provided_to_companies: tuple[Reference, ...]
    consumed_by_companies: tuple[Reference, ...]
