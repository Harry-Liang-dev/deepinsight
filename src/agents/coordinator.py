"""Fixed Phase One multi-Agent research coordination."""

from __future__ import annotations

from typing import cast

from pydantic import ValidationError

from src.agents.base import BaseAgent
from src.agents.contracts import (
    AgentExecutionResult,
    AgentInvocation,
    ResearchTaskRequest,
    ResearchTaskResult,
)
from src.models.enums import AgentName, AgentStatus
from src.models.types import JsonObject
from src.schemas.agents import (
    AgentRequest,
    AnalystOutput,
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    FundamentalAnalystResponse,
    ResearchManagerRequest,
    ResearchManagerResponse,
    RiskManagerRequest,
)

ANALYST_ORDER = (
    AgentName.FUNDAMENTAL_ANALYST,
    AgentName.TECHNICAL_TEXT_ANALYST,
    AgentName.SENTIMENT_ANALYST,
    AgentName.NEWS_EVENT_ANALYST,
)

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
            agent_request = AgentRequest(
                run_id=self._run_id(request.task_id, agent_name),
                agent_name=agent_name,
                model_name=request.model_name,
                input_context=request.input_context,
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
        research_request = ResearchManagerRequest(
            input_context=manager_context,
            analyst_outputs=analyst_outputs,
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

        bull_request = BullManagerRequest(
            input_context=manager_context,
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
        )
        bear_request = BearManagerRequest(
            input_context=manager_context,
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
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

        risk_request = RiskManagerRequest(
            input_context=manager_context,
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
            bull_output=bull_output,
            bear_output=bear_output,
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
    def _run_id(task_id: str, agent_name: AgentName) -> str:
        return f"{task_id}:{agent_name.value}"


def _parse_analyst_output(
    agent_name: AgentName,
    output: JsonObject,
) -> AnalystOutput:
    if agent_name is AgentName.FUNDAMENTAL_ANALYST:
        return FundamentalAnalystResponse.model_validate(output)
    from src.schemas.agents import AnalystResponse

    return AnalystResponse.model_validate(output)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
