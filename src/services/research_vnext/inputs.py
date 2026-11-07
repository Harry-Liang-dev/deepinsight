"""Narrow existing-role input projections and honest Sector usage attribution."""

from __future__ import annotations

from collections.abc import Sequence

from src.agents.contracts import AgentExecutionResult
from src.agents.coordinator import ANALYST_ORDER, _parse_analyst_output
from src.memory.vnext import content_sha256
from src.memory.vnext_contracts import ArtifactRef, Frozen, Role
from src.models.enums import AgentName, AgentStatus
from src.schemas.agents import (
    AgentContext,
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    ClaimEvidenceBinding,
    ResearchSummary,
    RiskManagerRequest,
)
from src.schemas.sector_context import SectorContextBundle, SectorRoleContext
from src.services.sector_context import (
    SectorContextProjector,
    build_sector_context_usage,
)


def debate_input(
    role: AgentName,
    context: AgentContext,
    results: Sequence[AgentExecutionResult],
) -> BullManagerRequest | BearManagerRequest:
    """Route real Analyst outputs directly; no invented Research Manager run."""
    if role not in (AgentName.BULL_MANAGER, AgentName.BEAR_MANAGER):
        raise ValueError("DEBATE_ROLE_REQUIRED")
    analysts = []
    seen = set()
    for result in results:
        if result.agent_name not in ANALYST_ORDER or result.agent_name in seen:
            raise ValueError("INVALID_OR_DUPLICATE_ANALYST_PARENT")
        seen.add(result.agent_name)
        if (
            result.status != AgentStatus.OK
            or result.output is None
            or not result.evidence
        ):
            raise ValueError("INVALID_ANALYST_PARENT_NOT_SILENTLY_FILTERED")
        analysts.append(_parse_analyst_output(result.agent_name, result.output))
    cls = BullManagerRequest if role == AgentName.BULL_MANAGER else BearManagerRequest
    return cls(
        input_context=context,
        analyst_outputs=analysts,
        research_summary=ResearchSummary(
            summary_points=[],
            uncertainties=[
                (
                    "G86 direct Analyst route; empty legacy compatibi"
                    "lity field, not Manager synthesis"
                )
            ],
        ),
        research_contract={"schema_version": "g86_direct_analyst_debate_v1"},
    )


class SectorConsumption(Frozen):
    """Citation-backed usage, not a claim that every supplied item was attended."""

    role: Role
    bundle_sha256: str
    provided_claim_ids: tuple[str, ...]
    cited_claim_ids: tuple[str, ...]
    status: str
    economic_benefit_established_by_membership: bool = False


def sector_usage(
    bundle: SectorContextBundle,
    *,
    role: Role,
    accepted_by_role: dict[AgentName, tuple[ClaimEvidenceBinding, ...]],
    trader_citations: tuple[str, ...] = (),
) -> SectorConsumption:
    """Reuse the existing citation ancestry resolver for the original eight."""
    bundle = SectorContextBundle.model_validate_json(bundle.model_dump_json())
    if role == "trader":
        provided = tuple(
            c.claim_id for c in bundle.accepted_claims if c.claim_id is not None
        )
        if not set(trader_citations) <= set(provided):
            raise ValueError("TRADER_SECTOR_REFERENCE_NOT_SUPPLIED")
        used = trader_citations
    else:
        diagnostic = next(
            d
            for d in build_sector_context_usage(bundle, accepted_by_role)
            if d.agent_role == role
        )
        provided, used = (
            diagnostic.provided_sector_claim_ids,
            diagnostic.used_sector_claim_ids,
        )
    return SectorConsumption(
        role=role,
        bundle_sha256=content_sha256(bundle),
        provided_claim_ids=provided,
        cited_claim_ids=used,
        status="CITED_IN_OUTPUT" if used else "SUPPLIED_NOT_CITED",
    )


def sector_projection(
    bundle: SectorContextBundle | None, role: AgentName
) -> SectorRoleContext | None:
    """Pure company research can omit Sector; chain research reuses its projector."""
    return None if bundle is None else SectorContextProjector.for_role(bundle, role)


def require_product_citations(
    cited: tuple[ArtifactRef, ...],
    supplied: tuple[ArtifactRef, ...],
) -> None:
    """A content hash or namespace alone does not authorize new fact usage."""
    if any(ref not in supplied for ref in cited):
        raise ValueError("PRODUCT_NOT_IN_ROLE_INPUT")


def risk_input(
    context: AgentContext,
    results: Sequence[AgentExecutionResult],
    bull: BullManagerResponse,
    bear: BearManagerResponse,
) -> RiskManagerRequest:
    """Pass direct Analysts and both conditional cases without Manager relay."""
    from src.schemas.agents import RiskManagerRequest

    direct = debate_input(AgentName.BULL_MANAGER, context, results)
    return RiskManagerRequest(
        input_context=context,
        analyst_outputs=direct.analyst_outputs,
        research_summary=direct.research_summary,
        bull_output=bull,
        bear_output=bear,
        research_contract={"schema_version": "g86_direct_risk_inputs_v1"},
    )
