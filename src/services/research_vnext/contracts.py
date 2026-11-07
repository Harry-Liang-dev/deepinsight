"""G86 development extensions around the exact frozen G84 interfaces."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol, Self, TypeVar

from pydantic import Field, model_validator

from src.memory.vnext import content_sha256
from src.memory.vnext_contracts import (
    ArtifactRef,
    Digest,
    Envelope,
    Frozen,
    ResearchReviewDecision,
    Role,
    Text,
    TradeProposal,
)
from src.models.enums import Market
from src.models.identifiers import AssetId
from src.schemas.temporal import require_utc_aware

VERSION = "g86_research_workflow_v1"
T = TypeVar("T", bound=Frozen)


class RetainedReader(Protocol):
    """Trusted composition-root resolver, not a model-controlled source store."""

    def __call__(self, reference: ArtifactRef) -> bytes:
        """Return original retained bytes or raise; do not acquire sources."""
        ...


def resolve(reference: ArtifactRef, reader: RetainedReader) -> bytes:
    """Bind actual bytes to the exact full reference at the trusted boundary."""
    import hashlib

    raw = reader(reference)
    if hashlib.sha256(raw).hexdigest() != reference.sha256_digest:
        raise ValueError("RETAINED_BYTES_MISMATCH")
    return raw


def artifact(record: Envelope) -> ArtifactRef:
    """Reference a generated record at creation, never backdate availability."""
    return ArtifactRef(
        artifact_id=record.record_id,
        sha256_digest=content_sha256(record),
        version=getattr(record, "schema_version", record.mode),
        owner=record.owner,
        available_at=record.created_at,
        observed_at=record.created_at,
        ingested_at=record.created_at,
    )


class ExecutionDisposition(StrEnum):
    """Role-level outcomes; these never replace legacy AgentStatus."""

    EXECUTED = "EXECUTED"
    REUSED = "REUSED"
    SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
    BLOCKED_MISSING_EVIDENCE = "BLOCKED_MISSING_EVIDENCE"
    INVALIDATED_REQUIRES_RESEARCH = "INVALIDATED_REQUIRES_RESEARCH"


class RoleDecision(Frozen):
    """Pre-call policy result, not a dispatch receipt or paid permission."""

    role: Role
    disposition: ExecutionDisposition
    reason: Text
    reusable_result: ArtifactRef | None = None


class ProductReferences(Frozen):
    """Keep independently resolved products separate; no text-to-Claim cast."""

    validated_claims: tuple[ArtifactRef, ...] = ()
    hypotheses: tuple[ArtifactRef, ...] = ()
    research_questions: tuple[ArtifactRef, ...] = ()
    bull_cases: tuple[ArtifactRef, ...] = ()
    bear_cases: tuple[ArtifactRef, ...] = ()
    risk_reviews: tuple[ArtifactRef, ...] = ()
    trade_proposals: tuple[ArtifactRef, ...] = ()
    research_review_decisions: tuple[ArtifactRef, ...] = ()


class MarketDatum(Frozen):
    """A trusted read-only quantitative observation, never Agent prose."""

    schema_version: Literal["g86_market_datum_v1"] = "g86_market_datum_v1"
    asset_id: AssetId
    category: Literal[
        "PRICE_VOLUME",
        "FUND_FLOW",
        "RELATIVE_VALUE",
        "LIQUIDITY",
        "CAPACITY",
        "TREND_VALIDATION",
        "LIMIT_UP_DOWN",
        "CONSECUTIVE_LIMITS",
    ]
    metric: Text
    value: Decimal
    unit: Text
    session: Text
    provider: Text
    basis: Text
    source_kind: Literal["OHLCV", "FUND_FLOW_SOURCE", "QUANT_OPERATOR", "EXCHANGE"]
    source_receipt: ArtifactRef
    operator: ArtifactRef | None = None

    @model_validator(mode="after")
    def authority(self) -> Self:
        """OHLCV does not establish fund flow or exchange limit applicability."""
        if not self.value.is_finite():
            raise ValueError("FINITE_QUANTITY_REQUIRED")
        if self.category == "TREND_VALIDATION" and self.source_kind != "QUANT_OPERATOR":
            raise ValueError("TREND_VALIDATION_AUTHORITY_REQUIRED")
        if self.category == "FUND_FLOW" and self.source_kind != "FUND_FLOW_SOURCE":
            raise ValueError("OHLCV_IS_NOT_FUND_FLOW")
        if self.category in {"LIMIT_UP_DOWN", "CONSECUTIVE_LIMITS"} and (
            self.asset_id.market != Market.CN or self.source_kind != "EXCHANGE"
        ):
            raise ValueError("LIMIT_MARKET_OR_SOURCE_UNPROVEN")
        if self.source_kind == "QUANT_OPERATOR" and self.operator is None:
            raise ValueError("QUANT_OPERATOR_REQUIRED")
        return self


class Coverage(Frozen):
    """A missing quantity is null, including liquidity and capacity screening."""

    status: Literal["AVAILABLE", "MISSING", "NOT_APPLICABLE"]
    measurements: tuple[MarketDatum, ...] = ()
    reason: Text

    @model_validator(mode="after")
    def branch(self) -> Self:
        """Prevent missing or inapplicable states carrying invented values."""
        if (self.status == "AVAILABLE") != bool(self.measurements):
            raise ValueError("MEASUREMENT_STATUS_MISMATCH")
        return self


class QuantResearchContext(Frozen):
    """Resolved Quant context, explicitly not a portfolio or order target."""

    schema_version: Literal["g86_quant_read_context_v1"] = "g86_quant_read_context_v1"
    asset_id: AssetId
    research_as_of: datetime
    factors: tuple[MarketDatum, ...]
    constraint_receipts: tuple[ArtifactRef, ...]
    missing: tuple[Text, ...] = ()
    authority: Literal["READ_ONLY_RESEARCH_NOT_EXECUTION"] = (
        "READ_ONLY_RESEARCH_NOT_EXECUTION"
    )

    @model_validator(mode="after")
    def source_binding(self) -> Self:
        """Keep owner/time/scopes and factor limitations on every value."""
        require_utc_aware(self.research_as_of)
        for factor in self.factors:
            if factor.asset_id != self.asset_id:
                raise ValueError("QUANT_ASSET_MISMATCH")
            for ref in (factor.source_receipt, factor.operator):
                if ref is not None:
                    ref.require_recorded_by(self.research_as_of)
        for ref in self.constraint_receipts:
            ref.require_recorded_by(self.research_as_of)
        return self


TradeAction = Literal[
    "WATCH",
    "PROPOSE_ENTRY",
    "PROPOSE_ADD",
    "PROPOSE_REDUCE",
    "PROPOSE_EXIT",
    "NO_TRADE",
]
ReviewAction = Literal[
    "APPROVE_FOR_QUANT_REVIEW",
    "RETURN_FOR_RESEARCH",
    "REJECT",
    "APPROVE_NO_TRADE",
]


class TraderDraft(Frozen):
    """Logical role output: no sizes, costs, factor values or execution fields."""

    action: TradeAction
    thesis: Text
    invalidation_conditions: tuple[Text, ...] = Field(min_length=1)
    cited_input_ids: tuple[Text, ...]
    uncertainties: tuple[Text, ...]


class TraderProduct(Frozen):
    """Action sidecar preserves G84 TradeProposal unchanged."""

    schema_version: Literal["g86_trader_product_v1"] = "g86_trader_product_v1"
    action: TradeAction
    proposal: TradeProposal
    quant_context: ArtifactRef
    cited_input_ids: tuple[Text, ...]
    uncertainties: tuple[Text, ...]
    memory_read_set: ArtifactRef
    role_work_sha256: Digest
    execution_disposition: Literal["EXECUTED"] = "EXECUTED"
    production_admission: Literal[False] = False

    @model_validator(mode="after")
    def action_binding(self) -> Self:
        """The G84 thesis and G86 action must describe the same proposal."""
        if not self.proposal.thesis.startswith(f"[{self.action}] "):
            raise ValueError("TRADER_ACTION_BINDING_MISMATCH")
        return self


class ReviewDraft(Frozen):
    """Manager judgment remains separate from factual Claim admission."""

    decision: ReviewAction
    reasons: tuple[Text, ...] = Field(min_length=1)
    return_to_roles: tuple[Role, ...] = ()
    cited_input_ids: tuple[Text, ...]


class ReviewProduct(Frozen):
    """Preserve exact business decision alongside frozen G84 transport enum."""

    schema_version: Literal["g86_review_product_v1"] = "g86_review_product_v1"
    decision: ReviewAction
    review: ResearchReviewDecision
    trader_product_sha256: Digest
    memory_read_set: ArtifactRef
    role_work_sha256: Digest
    return_to_roles: tuple[Role, ...]
    execution_disposition: Literal["EXECUTED"] = "EXECUTED"
    production_admission: Literal[False] = False


def trader_reference(product: TraderProduct) -> ArtifactRef:
    """Bind the complete action/readset sidecar as well as the G84 proposal."""
    p = product.proposal
    return ArtifactRef(
        artifact_id="trader-product:" + p.record_id,
        sha256_digest=content_sha256(product),
        version=product.schema_version,
        owner=p.owner,
        available_at=p.created_at,
        observed_at=p.created_at,
        ingested_at=p.created_at,
    )
