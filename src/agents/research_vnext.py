"""Opt-in Trader and final-review roles on the existing Agent Gateway boundary.

No execution loop, Provider, Memory store, Claim validator or State builder here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, Protocol, cast

from src.agents.base import AgentGateway
from src.agents.contracts import AgentExecutionResult
from src.agents.evidence import numeric_literals
from src.agents.numeric_grounding import validate_numeric_grounding
from src.memory.contracts import ResearchContextBundle
from src.memory.vnext import MemoryAccessContext, content_sha256, read_set_from_bundle
from src.memory.vnext_contracts import (
    ROLE_STAGES,
    ArtifactRef,
    Envelope,
    MemoryReadSet,
    ResearchMandate,
    ResearchReviewDecision,
    Role,
    Scope,
    TradeProposal,
)
from src.models.compliance import prohibited_narrative_intent
from src.models.enums import AgentName, AgentStatus
from src.models.types import JsonObject
from src.schemas.agents import RoleEvidenceManifestEntry
from src.schemas.common import SourceReference
from src.schemas.research_state import ResearchStateSnapshot
from src.services.research_vnext.contracts import (
    ProductReferences,
    QuantResearchContext,
    RetainedReader,
    ReviewDraft,
    ReviewProduct,
    TraderDraft,
    TraderProduct,
    artifact,
    resolve,
    trader_reference,
)
from src.services.research_vnext.radar import require_mandate

PROMPT_VERSION = "g86_nonexecuting_roles_v1"
TRADER_PROMPT = """You are the non-executing Trader research role.
Consume only resolved current Quant market context, applicable constraints,
conditional Bull/Bear cases and the actual Risk review. Distinguish facts,
hypotheses, questions and missing inputs. Do not invent market factors, holdings,
position costs, cashflows, orders, sizes or system target prices. Do not require
opposite Bull/Bear price directions. Propose WATCH, PROPOSE_ENTRY, PROPOSE_ADD,
PROPOSE_REDUCE, PROPOSE_EXIT or NO_TRADE, with invalidation conditions and exact
supplied input IDs. Missing Quant/constraints supports WATCH or NO_TRADE, not a
fictional numeric proposal. Proposals are research-only; no trading authority.
Return only the supplied TraderDraft schema; no Claims or review authority.
"""
REVIEW_PROMPT = """You are the final Research Manager independent reviewer.
Review the actual Trader proposal and entire supplied research lineage after
Analysts, Bull/Bear and Risk. Do not act as an upstream factual relay. Separate
validated Claims from hypotheses and questions; detect missing evidence,
fragile assumptions, counterevidence and unsupported quantities. Return research
approval for Quant review, return to named upstream specialists, rejection, or
approval of NO_TRADE. Do not fabricate evidence yourself. No review approves
orders, production State, PIT, Quant factors or trading. Return only ReviewDraft.
"""


class RoleValidation(Protocol):
    """Application binds existing original validation receipts, not model claims."""

    def __call__(self, ref: ArtifactRef, role: Role | None, scope: Scope) -> None:
        """Reject unaccepted, wrong-role, wrong-subject or unregistered results."""
        ...


class RoleWork(Envelope):
    """Typed working input; generated dependencies may follow the source cutoff."""

    schema_version: Literal["g86_role_work_v1"] = "g86_role_work_v1"
    mandate: ResearchMandate
    memory_reads: MemoryReadSet
    quant_context: ArtifactRef
    risk_review: ArtifactRef
    products: ProductReferences


def _read_inputs(
    work: RoleWork,
    role: Role,
    access: MemoryAccessContext,
    reader: RetainedReader,
    validate_role: RoleValidation,
    validate_quant: Callable[[QuantResearchContext], None],
) -> tuple[QuantResearchContext, JsonObject]:
    access.require("READ_HISTORY", work.scope)
    reads = work.memory_reads
    if (
        work.owner != access.owner
        or reads.created_at > work.created_at
        or reads.agent_role != role
        or reads.owner != access.owner
        or reads.agent_run_id != work.record_id
        or reads.scope != work.scope
        or reads.research_as_of != work.research_as_of
        or access.role != role
    ):
        raise ValueError("ROLE_MEMORY_INPUT_BINDING")
    require_mandate(
        work.mandate, role=role, scope=work.scope, at=work.created_at, reader=reader
    )
    bundle = ResearchContextBundle.model_validate_json(
        resolve(reads.bundle_ref, reader)
    )
    actual_reads = read_set_from_bundle(
        bundle,
        bundle_ref=reads.bundle_ref,
        memory_refs={r.artifact_id: r for r in reads.memory_refs},
        access=access,
        scope=work.scope,
        agent_run_id=work.record_id,
        record_id=reads.record_id,
        created_at=reads.created_at,
    )
    if actual_reads.sha256 != reads.sha256:
        raise ValueError("ACTUAL_MEMORY_READSET_MISMATCH")
    for ref in (
        *work.source_refs,
        *reads.memory_refs,
        work.quant_context,
        work.risk_review,
    ):
        ref.require_recorded_by(work.created_at)
        resolve(ref, reader)
    validate_role(work.risk_review, AgentName.RISK_MANAGER, work.scope)
    risk = AgentExecutionResult.model_validate_json(resolve(work.risk_review, reader))
    if (
        risk.agent_name != AgentName.RISK_MANAGER
        or risk.status != AgentStatus.OK
        or risk.run_id != work.risk_review.artifact_id
    ):
        raise ValueError("ACTUAL_ACCEPTED_RISK_REQUIRED")
    quant = QuantResearchContext.model_validate_json(
        resolve(work.quant_context, reader)
    )
    if quant.research_as_of != work.research_as_of:
        raise ValueError("QUANT_CUTOFF_MISMATCH")
    if work.scope.scope_id not in {
        "ASSET:" + str(quant.asset_id),
        "ASSET:" + str(quant.asset_id).split(":", 1)[1],
    }:
        raise ValueError("ROLE_QUANT_SCOPE_MISMATCH")
    validate_quant(quant)
    for factor in quant.factors:
        for quant_ref in (factor.source_receipt, factor.operator):
            if quant_ref is not None:
                if quant_ref not in work.source_refs:
                    raise ValueError("QUANT_SOURCE_NOT_BOUND")
                resolve(quant_ref, reader)
    for ref in quant.constraint_receipts:
        if ref not in work.source_refs:
            raise ValueError("QUANT_CONSTRAINT_NOT_BOUND")
        resolve(ref, reader)
    products: dict[str, object] = {}
    for key in type(work.products).model_fields:
        rows = []
        for ref in getattr(work.products, key):
            validate_role(ref, None, work.scope)
            ref.require_recorded_by(work.created_at)
            rows.append(
                dict(
                    reference=ref.model_dump(mode="json"),
                    payload=json.loads(resolve(ref, reader)),
                )
            )
        products[key] = rows
    return quant, cast(
        JsonObject,
        dict(
            scope=work.scope.model_dump(mode="json"),
            risk=risk.model_dump(mode="json"),
            quant=quant.model_dump(mode="json"),
            research_products=products,
            memory_read_set=reads.model_dump(mode="json"),
            memory_context=bundle.model_dump(mode="json"),
        ),
    )


def _ground(texts: tuple[str, ...], quant: QuantResearchContext) -> None:
    entries = tuple(
        RoleEvidenceManifestEntry(
            evidence_id=f.metric,
            evidence_type="structured_derived",
            source=SourceReference(document_id=f.source_receipt.artifact_id),
            short_description=(
                f"{f.metric} = {f.value} {f.unit}; " f"session {f.session}; {f.basis}"
            ),
            numeric_tokens=numeric_literals(str(f.value)),
        )
        for f in quant.factors
    )
    for text in texts:
        if prohibited_narrative_intent(text) is not None:
            raise ValueError("NON_EXECUTING_RESEARCH_REQUIRED")
        if validate_numeric_grounding(text, entries).ungrounded_literals:
            raise ValueError("ROLE_UNSUPPORTED_NUMERIC")


class TraderResearchRole:
    """Logical ninth role; never registers a production AgentName or dispatches."""

    def run(
        self,
        work: RoleWork,
        *,
        model: str,
        gateway: AgentGateway,
        access: MemoryAccessContext,
        reader: RetainedReader,
        validate_role: RoleValidation,
        validate_quant: Callable[[QuantResearchContext], None],
    ) -> TraderProduct:
        """Use existing Gateway once after source, selection and read-set checks."""
        work = RoleWork.model_validate_json(work.model_dump_json())
        quant, payload = _read_inputs(
            work, "trader", access, reader, validate_role, validate_quant
        )
        draft = TraderDraft.model_validate(
            gateway.invoke_json(
                model,
                TRADER_PROMPT,
                payload,
                prompt_version=PROMPT_VERSION,
                schema_version="g86_trader_draft_v1",
                response_model=TraderDraft,
            )
        )
        allowed = {work.risk_review.artifact_id, work.quant_context.artifact_id}
        allowed.update(f.metric for f in quant.factors)
        for field in type(work.products).model_fields:
            allowed.update(r.artifact_id for r in getattr(work.products, field))
        if set(draft.cited_input_ids) - allowed:
            raise ValueError("TRADER_UNKNOWN_INPUT_REFERENCE")
        if draft.action not in {"NO_TRADE", "WATCH"} and (
            not quant.factors or not quant.constraint_receipts or quant.missing
        ):
            raise ValueError("ACTIONABLE_RESEARCH_REQUIRES_QUANT_AND_CONSTRAINTS")
        _ground(
            (draft.thesis, *draft.invalidation_conditions, *draft.uncertainties), quant
        )
        proposal = TradeProposal(
            owner=access.owner,
            record_id="proposal:" + work.record_id,
            revision=1,
            created_at=work.created_at,
            research_as_of=work.research_as_of,
            scope=work.scope,
            source_refs=work.source_refs,
            mandate_sha256=work.mandate.sha256,
            thesis=f"[{draft.action}] {draft.thesis}",
            invalidation_conditions=draft.invalidation_conditions,
            risk_review=work.risk_review,
        )
        return TraderProduct(
            action=draft.action,
            proposal=proposal,
            quant_context=work.quant_context,
            cited_input_ids=draft.cited_input_ids,
            uncertainties=draft.uncertainties,
            memory_read_set=artifact(work.memory_reads),
            role_work_sha256=work.sha256,
        )


class ManagerFinalReviewRole:
    """Final independent research judgment, separate from legacy synthesis."""

    def run(
        self,
        work: RoleWork,
        trader: TraderProduct,
        *,
        working_state: ArtifactRef,
        model: str,
        gateway: AgentGateway,
        access: MemoryAccessContext,
        reader: RetainedReader,
        validate_role: RoleValidation,
        validate_quant: Callable[[QuantResearchContext], None],
    ) -> ReviewProduct:
        """Review actual supplied proposal without State/Quant publication."""
        access.require("REVIEW_FINAL_STATE", work.scope)
        work = RoleWork.model_validate_json(work.model_dump_json())
        trader = TraderProduct.model_validate_json(trader.model_dump_json())
        quant, payload = _read_inputs(
            work,
            AgentName.RESEARCH_MANAGER,
            access,
            reader,
            validate_role,
            validate_quant,
        )
        if (
            trader.proposal.scope != work.scope
            or trader.proposal.research_as_of != work.research_as_of
            or trader.proposal.mandate_sha256 != work.mandate.sha256
            or trader.quant_context != work.quant_context
            or trader.proposal.risk_review != work.risk_review
        ):
            raise ValueError("FINAL_REVIEW_PROPOSAL_BINDING")
        proposal_ref = artifact(trader.proposal)
        resolve(proposal_ref, reader)
        resolve(trader_reference(trader), reader)
        working_state.require_recorded_by(work.created_at)
        state = ResearchStateSnapshot.model_validate_json(
            resolve(working_state, reader)
        )
        if (
            working_state.artifact_id != state.research_state_id
            or state.asset_id != quant.asset_id
            or state.research_as_of > work.research_as_of
        ):
            raise ValueError("FINAL_WORKING_STATE_SCOPE_OR_TIME")
        payload["working_state"] = state.model_dump(mode="json")
        payload["trader_product"] = trader.model_dump(mode="json")
        payload["working_state_ref"] = working_state.model_dump(mode="json")
        draft = ReviewDraft.model_validate(
            gateway.invoke_json(
                model,
                REVIEW_PROMPT,
                payload,
                prompt_version=PROMPT_VERSION,
                schema_version="g86_review_draft_v1",
                response_model=ReviewDraft,
            )
        )
        if draft.decision == "APPROVE_NO_TRADE" and trader.action != "NO_TRADE":
            raise ValueError("NO_TRADE_REVIEW_REQUIRES_NO_TRADE_PROPOSAL")
        if draft.decision == "RETURN_FOR_RESEARCH" and not draft.return_to_roles:
            raise ValueError("UPSTREAM_SPECIALIST_REQUIRED")
        allowed_roles = {r for stage in ROLE_STAGES[:-1] for r in stage}
        if set(draft.return_to_roles) - allowed_roles:
            raise ValueError("MANAGER_MUST_RETURN_TO_SPECIALIST")
        if set(draft.cited_input_ids) - {
            proposal_ref.artifact_id,
            working_state.artifact_id,
            work.risk_review.artifact_id,
        }:
            raise ValueError("REVIEW_UNKNOWN_REFERENCE")
        _ground(draft.reasons, quant)
        mapping: dict[
            str, Literal["APPROVE_RESEARCH", "REVISE", "REJECT", "ABSTAIN"]
        ] = {
            "APPROVE_FOR_QUANT_REVIEW": "APPROVE_RESEARCH",
            "RETURN_FOR_RESEARCH": "REVISE",
            "REJECT": "REJECT",
            "APPROVE_NO_TRADE": "ABSTAIN",
        }
        review = ResearchReviewDecision(
            owner=access.owner,
            record_id="review:" + work.record_id,
            revision=1,
            created_at=work.created_at,
            research_as_of=work.research_as_of,
            scope=work.scope,
            source_refs=work.source_refs,
            proposal=proposal_ref,
            working_state=working_state,
            decision=mapping[draft.decision],
            reasons=draft.reasons,
        )
        return ReviewProduct(
            decision=draft.decision,
            review=review,
            trader_product_sha256=content_sha256(trader),
            memory_read_set=artifact(work.memory_reads),
            role_work_sha256=work.sha256,
            return_to_roles=draft.return_to_roles,
        )
