"""Fixed Phase One multi-Agent research coordination."""

from __future__ import annotations

import json
from typing import cast

from pydantic import ValidationError

from src.agents.base import BaseAgent
from src.agents.contracts import (
    AgentExecutionResult,
    AgentInvocation,
    ResearchTaskRequest,
    ResearchTaskResult,
)
from src.agents.evidence import ManifestContract, build_role_evidence_manifest
from src.agents.input_contracts import (
    AgentInputBaseV1,
    AgentInputProjector,
    BearManagerInputV1,
    BullManagerInputV1,
    ManagerResearchContextV1,
    ResearchManagerInputV1,
    RiskManagerInputV1,
    VersionedUpstreamOutputV1,
)
from src.models.enums import AgentName, AgentStatus
from src.models.types import JsonObject
from src.schemas.agents import (
    AgentContext,
    AgentRequest,
    AnalystOutput,
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    ClaimEvidenceBinding,
    FundamentalAnalystResponse,
    ResearchManagerRequest,
    ResearchManagerResponse,
    RiskManagerRequest,
)
from src.schemas.research_data import DataCapability

ANALYST_ORDER = (
    AgentName.FUNDAMENTAL_ANALYST,
    AgentName.TECHNICAL_TEXT_ANALYST,
    AgentName.SENTIMENT_ANALYST,
    AgentName.NEWS_EVENT_ANALYST,
)

_DOCUMENT_CAPABILITIES_BY_ROLE = {
    AgentName.FUNDAMENTAL_ANALYST: {DataCapability.FILINGS},
    AgentName.TECHNICAL_TEXT_ANALYST: set(),
    AgentName.SENTIMENT_ANALYST: set(),
    AgentName.NEWS_EVENT_ANALYST: {
        DataCapability.FILINGS,
        DataCapability.NEWS_EVIDENCE,
    },
    AgentName.RESEARCH_MANAGER: {
        DataCapability.FILINGS,
        DataCapability.NEWS_EVIDENCE,
    },
    AgentName.BULL_MANAGER: {
        DataCapability.FILINGS,
        DataCapability.NEWS_EVIDENCE,
    },
    AgentName.BEAR_MANAGER: {
        DataCapability.FILINGS,
        DataCapability.NEWS_EVIDENCE,
    },
    AgentName.RISK_MANAGER: {
        DataCapability.FILINGS,
        DataCapability.NEWS_EVIDENCE,
    },
}

REQUIRED_AGENTS = (
    *ANALYST_ORDER,
    AgentName.RESEARCH_MANAGER,
    AgentName.BULL_MANAGER,
    AgentName.BEAR_MANAGER,
    AgentName.RISK_MANAGER,
)


class CoordinatorConfigurationError(ValueError):
    """Raised when the fixed Phase One Agent registry is incomplete."""


class ResearchCoordinator:
    """Run the fixed eight-Agent research chain without report assembly."""

    def __init__(self, agent_registry: dict[AgentName, BaseAgent]) -> None:
        """Validate and retain the exact Phase One Agent registry.

        Args:
            agent_registry: Mapping containing all and only required Agent roles.

        Raises:
            CoordinatorConfigurationError: If roles are missing or unexpected.
        """

        configured = set(agent_registry)
        required = set(REQUIRED_AGENTS)
        if configured != required:
            missing = sorted(item.value for item in required - configured)
            unexpected = sorted(item.value for item in configured - required)
            raise CoordinatorConfigurationError(
                f"invalid Agent registry; missing={missing}, unexpected={unexpected}"
            )
        self._agents = dict(agent_registry)

    def run(self, request: ResearchTaskRequest) -> ResearchTaskResult:
        """Run Analysts, synthesis, two single-round theses, then risk review.

        Args:
            request: Validated task identity, model, evidence, and Memory query.

        Returns:
            Complete or explicitly degraded Agent collaboration result.
        """

        analyst_results: dict[AgentName, AgentExecutionResult] = {}
        analyst_outputs: list[AnalystOutput] = []
        missing_agents: list[AgentName] = []
        uncertainties: list[str] = []

        for agent_name in ANALYST_ORDER:
            analyst_contract = self._analyst_contract(request, agent_name)
            agent_request = AgentRequest(
                run_id=self._run_id(request.task_id, agent_name),
                agent_name=agent_name,
                model_name=request.model_name,
                input_context=_context_for_contract(
                    request.input_context,
                    analyst_contract,
                ),
                research_contract=_contract_json(analyst_contract),
            )
            result = self._invoke(
                request,
                agent_name,
                cast(JsonObject, agent_request.model_dump(mode="json")),
            )
            analyst_results[agent_name] = result
            if result.status is AgentStatus.OK and result.output is not None:
                try:
                    analyst_outputs.append(
                        _parse_analyst_output(agent_name, result.output)
                    )
                except ValidationError:
                    missing_agents.append(agent_name)
                    uncertainties.append(
                        f"{agent_name.value} output could not enter synthesis."
                    )
            else:
                missing_agents.append(agent_name)
                uncertainties.append(f"{agent_name.value} was unavailable.")

        if not analyst_outputs:
            return ResearchTaskResult(
                task_id=request.task_id,
                status=AgentStatus.ERROR,
                analyst_results=analyst_results,
                missing_agents=missing_agents,
                uncertainties=_unique(uncertainties),
            )

        manager_context = request.input_context.model_copy(deep=True)
        manager_context.structured_features = {
            **manager_context.structured_features,
            "agent_coverage": {
                "completed": [output.agent_name.value for output in analyst_outputs],
                "missing": [agent.value for agent in missing_agents],
            },
        }
        analyst_slots = tuple(
            _versioned_output(analyst_results[role]) for role in ANALYST_ORDER
        )
        research_contract = self._manager_context(
            request,
            AgentName.RESEARCH_MANAGER,
            analyst_slots,
        )
        research_input = (
            None
            if research_contract is None
            else ResearchManagerInputV1(context=research_contract)
        )
        research_request = ResearchManagerRequest(
            input_context=_context_for_contract(manager_context, research_input),
            analyst_outputs=analyst_outputs,
            research_contract=_contract_json(research_input),
        )
        research_result = self._invoke(
            request,
            AgentName.RESEARCH_MANAGER,
            cast(JsonObject, research_request.model_dump(mode="json")),
        )
        if (
            research_result.status is AgentStatus.ERROR
            or research_result.output is None
        ):
            return ResearchTaskResult(
                task_id=request.task_id,
                status=AgentStatus.ERROR,
                analyst_results=analyst_results,
                research_manager=research_result,
                missing_agents=[*missing_agents, AgentName.RESEARCH_MANAGER],
                uncertainties=_unique(
                    [*uncertainties, "Research synthesis was unavailable."]
                ),
            )

        try:
            research_response = ResearchManagerResponse.model_validate(
                research_result.output
            )
        except ValidationError:
            return ResearchTaskResult(
                task_id=request.task_id,
                status=AgentStatus.ERROR,
                analyst_results=analyst_results,
                research_manager=research_result,
                missing_agents=[*missing_agents, AgentName.RESEARCH_MANAGER],
                uncertainties=_unique(
                    [*uncertainties, "Research synthesis was invalid."]
                ),
            )

        research_slot = _versioned_output(research_result)
        bull_contract = self._manager_context(
            request,
            AgentName.BULL_MANAGER,
            analyst_slots,
        )
        bear_contract = self._manager_context(
            request,
            AgentName.BEAR_MANAGER,
            analyst_slots,
        )
        bull_input = (
            None
            if bull_contract is None
            else BullManagerInputV1(
                context=bull_contract,
                research_output=research_slot,
            )
        )
        bear_input = (
            None
            if bear_contract is None
            else BearManagerInputV1(
                context=bear_contract,
                research_output=research_slot,
            )
        )
        bull_request = BullManagerRequest(
            input_context=_context_for_contract(manager_context, bull_input),
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
            research_contract=_contract_json(bull_input),
        )
        bear_request = BearManagerRequest(
            input_context=_context_for_contract(manager_context, bear_input),
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
            research_contract=_contract_json(bear_input),
        )
        bull_result = self._invoke(
            request,
            AgentName.BULL_MANAGER,
            cast(JsonObject, bull_request.model_dump(mode="json")),
        )
        bear_result = self._invoke(
            request,
            AgentName.BEAR_MANAGER,
            cast(JsonObject, bear_request.model_dump(mode="json")),
        )

        if (
            bull_result.status is AgentStatus.ERROR
            or bear_result.status is AgentStatus.ERROR
            or bull_result.output is None
            or bear_result.output is None
        ):
            failed_theses = [
                name
                for name, result in (
                    (AgentName.BULL_MANAGER, bull_result),
                    (AgentName.BEAR_MANAGER, bear_result),
                )
                if result.status is AgentStatus.ERROR
            ]
            return ResearchTaskResult(
                task_id=request.task_id,
                status=AgentStatus.ERROR,
                analyst_results=analyst_results,
                research_manager=research_result,
                bull_manager=bull_result,
                bear_manager=bear_result,
                missing_agents=[*missing_agents, *failed_theses],
                uncertainties=_unique(
                    [*uncertainties, "Two-sided thesis review was incomplete."]
                ),
            )

        try:
            bull_output = BullManagerResponse.model_validate(bull_result.output)
            bear_output = BearManagerResponse.model_validate(bear_result.output)
        except ValidationError:
            return ResearchTaskResult(
                task_id=request.task_id,
                status=AgentStatus.ERROR,
                analyst_results=analyst_results,
                research_manager=research_result,
                bull_manager=bull_result,
                bear_manager=bear_result,
                missing_agents=missing_agents,
                uncertainties=_unique(
                    [*uncertainties, "Two-sided thesis review was invalid."]
                ),
            )

        risk_contract = self._manager_context(
            request,
            AgentName.RISK_MANAGER,
            analyst_slots,
        )
        risk_input = (
            None
            if risk_contract is None
            else RiskManagerInputV1(
                context=risk_contract,
                research_output=research_slot,
                bull_output=_versioned_output(bull_result),
                bear_output=_versioned_output(bear_result),
            )
        )
        risk_request = RiskManagerRequest(
            input_context=_context_for_contract(manager_context, risk_input),
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
            bull_output=bull_output,
            bear_output=bear_output,
            research_contract=_contract_json(risk_input),
        )
        risk_result = self._invoke(
            request,
            AgentName.RISK_MANAGER,
            cast(JsonObject, risk_request.model_dump(mode="json")),
        )
        final_status = risk_result.status
        if final_status is AgentStatus.ERROR:
            missing_agents.append(AgentName.RISK_MANAGER)
            uncertainties.append("Risk review was unavailable.")

        return ResearchTaskResult(
            task_id=request.task_id,
            status=final_status,
            analyst_results=analyst_results,
            research_manager=research_result,
            bull_manager=bull_result,
            bear_manager=bear_result,
            risk_manager=risk_result,
            missing_agents=missing_agents,
            uncertainties=_unique(uncertainties),
        )

    def _invoke(
        self,
        request: ResearchTaskRequest,
        agent_name: AgentName,
        input_payload: JsonObject,
    ) -> AgentExecutionResult:
        return self._agents[agent_name].run(
            AgentInvocation(
                run_id=self._run_id(request.task_id, agent_name),
                report_id=request.report_id,
                model_name=request.model_name,
                input_payload=input_payload,
                memory_query=request.memory_query,
            )
        )

    @staticmethod
    def _analyst_contract(
        request: ResearchTaskRequest,
        agent_name: AgentName,
    ) -> AgentInputBaseV1 | None:
        if request.data_bundle is None or request.context_bundle is None:
            return None
        return AgentInputProjector.analyst(
            request.data_bundle,
            request.context_bundle,
            agent_name,
        )

    @staticmethod
    def _manager_context(
        request: ResearchTaskRequest,
        agent_name: AgentName,
        analyst_outputs: tuple[VersionedUpstreamOutputV1, ...],
    ) -> ManagerResearchContextV1 | None:
        if request.data_bundle is None or request.context_bundle is None:
            return None
        return AgentInputProjector.manager_context(
            request.data_bundle,
            request.context_bundle,
            agent_name,
            analyst_outputs,
        )

    @staticmethod
    def _run_id(task_id: str, agent_name: AgentName) -> str:
        return f"{task_id}:{agent_name.value}"


def _parse_analyst_output(
    agent_name: AgentName,
    output: JsonObject,
) -> AnalystOutput:
    output = _downstream_claim_projection(output)
    if agent_name is AgentName.FUNDAMENTAL_ANALYST:
        return FundamentalAnalystResponse.model_validate(output)
    from src.schemas.agents import AnalystResponse

    return AnalystResponse.model_validate(output)


def _downstream_claim_projection(output: JsonObject) -> JsonObject:
    """Remove producer diagnostics before an output enters another Agent."""

    projected = cast(JsonObject, json.loads(json.dumps(output)))
    owner = projected.get("analysis")
    if isinstance(owner, dict):
        metadata = owner.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("rejected_claims", None)
    else:
        metadata = projected.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("rejected_claims", None)
    return projected


def _context_for_contract(
    context: AgentContext,
    contract: ManifestContract | None,
) -> AgentContext:
    if contract is None:
        return context
    role_context = (
        contract if isinstance(contract, AgentInputBaseV1) else contract.context
    )
    if not isinstance(contract, AgentInputBaseV1):
        return context.model_copy(
            update={
                "structured_evidence": [],
                "retrieved_documents": [],
                "role_evidence_manifest": None,
            },
            deep=True,
        )
    references = [
        item.to_source_reference() for item in role_context.data_evidence_index.values()
    ]
    visible_document_keys = {
        item.source.normalized_record_key
        for section in role_context.data.sections
        if section.capability
        in _DOCUMENT_CAPABILITIES_BY_ROLE.get(role_context.agent_name, set())
        for item in section.items
    }
    document_capabilities = _DOCUMENT_CAPABILITIES_BY_ROLE.get(
        role_context.agent_name, set()
    )
    documents = (
        list(context.retrieved_documents)
        if document_capabilities and not visible_document_keys
        else [
            document
            for document in context.retrieved_documents
            if any(
                document.document_id == key or document.document_id.endswith(f"-{key}")
                for key in visible_document_keys
            )
        ]
    )
    projected = context.model_copy(
        update={
            "structured_evidence": references,
            "retrieved_documents": documents,
        },
        deep=True,
    )
    manifest = build_role_evidence_manifest(projected, contract)
    document_ids = {
        entry.evidence_id
        for entry in manifest.entries
        if entry.evidence_type == "document"
    }
    return projected.model_copy(
        update={
            "role_evidence_manifest": manifest,
            "structured_evidence": [entry.source for entry in manifest.entries],
            "retrieved_documents": [
                document
                for document in projected.retrieved_documents
                if (document.chunk_id or document.document_id) in document_ids
            ],
        },
        deep=True,
    )


def _contract_json(model: object | None) -> JsonObject | None:
    if model is None:
        return None
    if not hasattr(model, "model_dump"):
        raise TypeError("Agent contract must be a Pydantic domain model")
    return cast(JsonObject, model.model_dump(mode="json"))


def _versioned_output(result: AgentExecutionResult) -> VersionedUpstreamOutputV1:
    output = (
        None if result.output is None else _downstream_claim_projection(result.output)
    )
    evidence_ids = tuple(
        dict.fromkeys(
            citation.excerpt_ref or citation.document_id or citation.provider or ""
            for link in result.evidence
            for citation in link.citations
            if citation.excerpt_ref or citation.document_id or citation.provider
        )
    )
    validated_claims = _validated_claims(result)
    return VersionedUpstreamOutputV1(
        agent_name=result.agent_name,
        status=result.status,
        output=output,
        evidence_ids=evidence_ids,
        validated_claims=validated_claims,
        missing_data=tuple(result.missing_data),
        uncertainties=tuple(result.uncertainties),
        error_code=None if result.error is None else result.error.code,
    )


def _validated_claims(
    result: AgentExecutionResult,
) -> tuple[ClaimEvidenceBinding, ...]:
    """Read the authoritative accepted Claim collection from one result."""

    if result.output is None:
        return ()
    owner = result.output.get("analysis")
    if not isinstance(owner, dict):
        owner = result.output
    raw = owner.get("claim_evidence")
    if not isinstance(raw, list):
        return ()
    return tuple(
        ClaimEvidenceBinding.model_validate(item)
        for item in raw
        if isinstance(item, dict)
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
