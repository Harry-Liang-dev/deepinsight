"""Real-provider execution of fixed live Agent Benchmark scenarios."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from src.agents import REQUIRED_AGENTS, ResearchTaskRequest, ResearchTaskResult
from src.live_benchmark.fingerprint import live_case_fingerprint
from src.live_benchmark.loader import LoadedLiveSnapshot
from src.models.enums import AgentName, AgentStatus, ReportType, TaskStatus
from src.reports import STANDARD_SECTION_NAMES, ReportAssembler, ReportAssemblyInput
from src.schemas.common import SourceReference
from src.schemas.evaluation import (
    EvaluationEvidenceItem,
    EvaluationInput,
    EvaluationResult,
)
from src.schemas.live_benchmark import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunResult,
    LiveCaseResult,
    MaterializedLiveScenario,
)
from src.schemas.reports import GenerateReportRequest, ResearchReport


class AgentCoordinator(Protocol):
    """Existing coordinator surface required by the live runner."""

    def run(self, request: ResearchTaskRequest) -> ResearchTaskResult:
        """Execute the fixed eight-Agent chain."""
        ...


class EvaluationService(Protocol):
    """Existing report evaluation surface required by the live runner."""

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        """Return one persisted EvaluationResult."""
        ...


class LiveAgentBenchmarkRunner:
    """Measure existing Agents and prompts without changing their behavior."""

    def __init__(
        self,
        coordinator: AgentCoordinator,
        assembler: ReportAssembler,
        evaluation_factory: Callable[[str], EvaluationService],
    ) -> None:
        """Bind only existing production Agent/report/evaluation boundaries."""

        self._coordinator = coordinator
        self._assembler = assembler
        self._evaluation_factory = evaluation_factory

    def run(
        self,
        loaded: LoadedLiveSnapshot,
        scenarios: list[MaterializedLiveScenario],
        config: LiveBenchmarkConfig,
    ) -> LiveBenchmarkRunResult:
        """Run all fixed cases and retain failures as Benchmark observations."""

        if not config.provider_real or not config.judge_real:
            raise ValueError("live Agent Benchmark requires real provider metadata")
        cases = [self._run_case(item, loaded.sha256, config) for item in scenarios]
        fingerprints = {item.case_id: item.input_fingerprint for item in cases}
        completed = sum(item.status == "completed" for item in cases)
        return LiveBenchmarkRunResult(
            run_id=config.run_id,
            dataset_version=loaded.snapshot.dataset_version,
            snapshot_id=loaded.snapshot.snapshot_id,
            snapshot_sha256=loaded.sha256,
            market_coverage=loaded.snapshot.market_coverage,
            coverage_limitations=loaded.snapshot.coverage_limitations,
            config=config,
            case_input_fingerprints=fingerprints,
            cases=cases,
            completed_cases=completed,
            failed_cases=len(cases) - completed,
        )

    def _run_case(
        self,
        scenario: MaterializedLiveScenario,
        snapshot_sha256: str,
        config: LiveBenchmarkConfig,
    ) -> LiveCaseResult:
        fingerprint = live_case_fingerprint(scenario, config, snapshot_sha256)
        task_id = f"{config.run_id}:{scenario.case_id}"
        report_id = f"report:{task_id}"
        agent_result = self._coordinator.run(
            ResearchTaskRequest(
                task_id=task_id,
                report_id=report_id,
                model_name=config.model_name,
                input_context=scenario.context,
            )
        )
        statuses = _agent_statuses(agent_result)
        success_rate = sum(
            value == AgentStatus.OK.value for value in statuses.values()
        ) / len(REQUIRED_AGENTS)
        if agent_result.status is AgentStatus.ERROR:
            return LiveCaseResult(
                case_id=scenario.case_id,
                scenario=scenario.scenario,
                input_fingerprint=fingerprint,
                status="failed",
                agent_statuses=statuses,
                agent_success_rate=success_rate,
                agent_result=agent_result.model_dump(mode="json"),
                error_code="agent_pipeline_failed",
            )
        try:
            report = self._assemble(report_id, scenario, agent_result)
            evaluation = self._evaluation_factory(scenario.case_id).evaluate(
                EvaluationInput(
                    report=report,
                    evidence_items=[
                        EvaluationEvidenceItem(
                            evidence_id=source.evidence_id,
                            source_ref=SourceReference(
                                document_id=source.document_id,
                                excerpt_ref=source.chunk_id,
                                provider=source.provider,
                                source_url=source.source_locator,
                            ),
                            text=source.text,
                            published_at=source.published_at,
                        )
                        for source in scenario.evidence_by_id.values()
                    ],
                    known_missing_data=scenario.known_missing_data,
                    ruleset_version=config.evaluation_ruleset_version,
                )
            )
        except Exception:
            return LiveCaseResult(
                case_id=scenario.case_id,
                scenario=scenario.scenario,
                input_fingerprint=fingerprint,
                status="failed",
                agent_statuses=statuses,
                agent_success_rate=success_rate,
                agent_result=agent_result.model_dump(mode="json"),
                error_code="report_or_evaluation_failed",
            )
        return LiveCaseResult(
            case_id=scenario.case_id,
            scenario=scenario.scenario,
            input_fingerprint=fingerprint,
            status="completed",
            agent_statuses=statuses,
            agent_success_rate=success_rate,
            agent_result=agent_result.model_dump(mode="json"),
            report=report,
            evaluation=evaluation,
        )

    def _assemble(
        self,
        report_id: str,
        scenario: MaterializedLiveScenario,
        agent_result: ResearchTaskResult,
    ) -> ResearchReport:
        return self._assembler.assemble(
            ReportAssemblyInput(
                report_id=report_id,
                request=GenerateReportRequest(
                    report_date=scenario.context.report_date,
                    market_scope=scenario.context.market_scope,
                    report_type=ReportType.SINGLE_ASSET,
                    asset_ids=[scenario.context.asset_id],
                    language="en",
                    include_sections=list(STANDARD_SECTION_NAMES),
                ),
                input_context=scenario.context,
                agent_result=agent_result,
                created_at=datetime.now(UTC),
            ),
            status=TaskStatus.COMPLETED,
        )


def _agent_statuses(result: ResearchTaskResult) -> dict[AgentName, str]:
    values = dict(result.analyst_results)
    managers = {
        AgentName.RESEARCH_MANAGER: result.research_manager,
        AgentName.BULL_MANAGER: result.bull_manager,
        AgentName.BEAR_MANAGER: result.bear_manager,
        AgentName.RISK_MANAGER: result.risk_manager,
    }
    statuses: dict[AgentName, str] = {}
    for name in REQUIRED_AGENTS:
        analyst = values.get(name)
        manager = managers.get(name)
        if analyst is not None:
            statuses[name] = analyst.status.value
        elif manager is not None:
            statuses[name] = manager.status.value
        else:
            statuses[name] = "not_run"
    return statuses
