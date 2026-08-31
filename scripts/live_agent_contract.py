"""Run the seven pre-Risk Agent contracts on one fixed Data bundle snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from src.agents import (
    ANALYST_ORDER,
    BearManagerAgent,
    BullManagerAgent,
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    ResearchManagerAgent,
    RiskManagerAgent,
    SentimentAnalystAgent,
    TechnicalTextAnalystAgent,
)
from src.agents.base import BaseAgent
from src.agents.contracts import (
    AgentExecutionResult,
    AgentInvocation,
    ResearchTaskRequest,
)
from src.agents.coordinator import (
    _context_for_contract,
    _contract_json,
    _parse_analyst_output,
    _sector_context_usage,
    _versioned_output,
)
from src.agents.input_contracts import (
    AgentInputProjector,
    BearManagerInputV1,
    BullManagerInputV1,
    ResearchManagerInputV1,
    RiskManagerInputV1,
)
from src.core import LLMProviderName, load_settings
from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import AgentName, AgentStatus, MemoryLevel, ReportMarketScope
from src.models.types import JsonObject
from src.repositories.records import AgentRunRecord, LLMCacheRecord
from src.schemas.agents import (
    AgentContext,
    AgentRequest,
    AnalystOutput,
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    ResearchManagerRequest,
    ResearchManagerResponse,
    RiskManagerRequest,
)
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse
from src.schemas.research_data import ResearchDataBundle
from src.schemas.sector_context import SectorContextBundle
from src.services import LLMGateway, build_configured_llm_provider

_AGENT_CLASSES: dict[AgentName, type[BaseAgent]] = {
    AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystAgent,
    AgentName.TECHNICAL_TEXT_ANALYST: TechnicalTextAnalystAgent,
    AgentName.SENTIMENT_ANALYST: SentimentAnalystAgent,
    AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystAgent,
    AgentName.RESEARCH_MANAGER: ResearchManagerAgent,
    AgentName.BULL_MANAGER: BullManagerAgent,
    AgentName.BEAR_MANAGER: BearManagerAgent,
}
_RISK_AGENT_CLASS: type[BaseAgent] = RiskManagerAgent


class _MemoryCache:
    """Process-local cache that cannot mix this run with prior live output."""

    def __init__(self) -> None:
        self.records: dict[str, LLMCacheRecord] = {}

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        return self.records.get(cache_key)

    def put(self, record: LLMCacheRecord) -> None:
        self.records[record.cache_key] = record


class _NoRuntimeMemory:
    """Reject retrieval because the fixed Memory bundle is already explicit."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        del request
        raise RuntimeError("fixed Agent contract run forbids runtime Memory retrieval")


class _RunCollector:
    """Collect credential-free Agent run metadata without persistence."""

    def __init__(self) -> None:
        self.records: list[AgentRunRecord] = []

    def save(self, record: AgentRunRecord) -> None:
        self.records.append(record)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("data/live_acceptance/20260812T170421Z/research_data_bundle.json"),
    )
    parser.add_argument("--prompt-root", type=Path, default=Path("config/prompts"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_agent_contract")
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--sector-context",
        type=Path,
        help="Optional PIT-aligned SectorContextBundle JSON for Day36 integration.",
    )
    parser.add_argument("--label", default="candidate")
    parser.add_argument(
        "--sentiment-only",
        action="store_true",
        help="Invoke only Sentiment; do not run the remaining Agent chain.",
    )
    parser.add_argument(
        "--include-risk",
        action="store_true",
        help="Run the Risk smoke after the seven pre-Risk roles pass.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run four Analysts, Research, Bull, and Bear without Risk or report."""

    arguments = _parser().parse_args(argv)
    try:
        settings = load_settings()
        if settings.llm.provider is not LLMProviderName.QWEN:
            return _configuration_error("Qwen provider is not selected.")
        if (
            settings.qwen.api_key is None
            or not settings.qwen.api_key.get_secret_value().strip()
        ):
            return _configuration_error("Qwen credential is not configured.")
        configured = build_configured_llm_provider(settings)
        bundle = ResearchDataBundle.model_validate_json(
            arguments.bundle.read_text(encoding="utf-8")
        )
        sector_context = (
            None
            if arguments.sector_context is None
            else SectorContextBundle.model_validate_json(
                arguments.sector_context.read_text(encoding="utf-8")
            )
        )
        if sector_context is not None and (
            sector_context.asset_id != bundle.asset_id
            or sector_context.research_as_of != bundle.as_of
        ):
            return _configuration_error(
                "Sector context must match the fixed asset bundle and cutoff."
            )
        memory_bundle = _empty_memory_bundle(bundle)
        prompt_loader = PromptLoader(arguments.prompt_root)
        selected_roles = (
            (AgentName.SENTIMENT_ANALYST,)
            if arguments.sentiment_only
            else tuple(_AGENT_CLASSES)
        )
        if arguments.include_risk and not arguments.sentiment_only:
            selected_roles = (*selected_roles, AgentName.RISK_MANAGER)
        prompts = {role: prompt_loader.load(role) for role in selected_roles}
        model = arguments.model or configured.model_default
        cache = _MemoryCache()
        gateway = LLMGateway(cache, provider=configured.provider)
        logger = _RunCollector()
        agent_classes = dict(_AGENT_CLASSES)
        if arguments.include_risk and not arguments.sentiment_only:
            agent_classes[AgentName.RISK_MANAGER] = _RISK_AGENT_CLASS
        agents = {
            role: agent_class(
                gateway,
                _NoRuntimeMemory(),
                prompt_loader,
                logger,
            )
            for role, agent_class in agent_classes.items()
            if role in selected_roles
        }
        base_context = AgentContext(
            report_date=bundle.window_end,
            market_scope=ReportMarketScope(bundle.asset_id.market.value),
            asset_id=bundle.asset_id,
            structured_features={
                "fixed_data_bundle_id": bundle.bundle_id,
                "dataset_version": bundle.dataset_version,
            },
        )
        if arguments.sentiment_only:
            results = _run_sentiment_only(
                bundle,
                memory_bundle,
                base_context,
                agents[AgentName.SENTIMENT_ANALYST],
                model,
                sector_context,
            )
        else:
            results = _run_chain(
                bundle,
                memory_bundle,
                base_context,
                agents,
                model,
                include_risk=arguments.include_risk,
                sector_context=sector_context,
            )
        stamp = datetime.now(UTC)
        run_id = f"agent_contract_{stamp.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        summary = {
            "run_id": run_id,
            "label": arguments.label,
            "timestamp": stamp.isoformat(),
            "dataset_version": bundle.dataset_version,
            "data_bundle_id": bundle.bundle_id,
            "sector_context_id": (
                None if sector_context is None else sector_context.context_id
            ),
            "provider": configured.provider_name.value,
            "provider_real": True,
            "judge_real": False,
            "model": model,
            "prompt_versions": {
                role.value: prompt.version for role, prompt in prompts.items()
            },
            "inference_parameters": {
                "timeout_seconds": configured.settings.timeout_seconds,
                "max_retries": configured.settings.max_retries,
                "store_remote": configured.settings.store_remote,
                "enable_thinking": getattr(
                    configured.settings, "enable_thinking", None
                ),
            },
            "agents": {
                role.value: _metrics(result) for role, result in results.items()
            },
        }
        if sector_context is not None:
            usage = _sector_context_usage(
                ResearchTaskRequest(
                    task_id=run_id,
                    model_name=model,
                    input_context=base_context,
                    data_bundle=bundle,
                    context_bundle=memory_bundle,
                    sector_context_bundle=sector_context,
                ),
                results,
            )
            summary["sector_context_usage"] = [
                item.model_dump(mode="json")
                for item in usage
                if item.agent_role in results
            ]
            summary["with_without_sector"] = {
                "without_sector": {
                    "provided_sector_claims": 0,
                    "used_sector_claims": 0,
                    "provided_events": 0,
                    "used_events": 0,
                    "context_chars": 0,
                },
                "with_sector": {
                    "provided_sector_claims": sum(
                        len(item.provided_sector_claim_ids)
                        for item in usage
                        if item.agent_role in results
                    ),
                    "used_sector_claims": sum(
                        len(item.used_sector_claim_ids)
                        for item in usage
                        if item.agent_role in results
                    ),
                    "provided_events": sum(
                        len(item.provided_event_ids)
                        for item in usage
                        if item.agent_role in results
                    ),
                    "used_events": sum(
                        len(item.used_event_ids)
                        for item in usage
                        if item.agent_role in results
                    ),
                    "context_chars": sum(
                        item.serialized_context_chars
                        for item in usage
                        if item.agent_role in results
                    ),
                    "missing_data_items": sum(
                        len(result.missing_data) for result in results.values()
                    ),
                    "accepted_claims": sum(
                        cast(int, _metrics(result)["valid_claims"])
                        for result in results.values()
                    ),
                },
            }
        passed = sum(result.status is AgentStatus.OK for result in results.values())
        summary["passed_agents"] = passed
        summary["failed_agents"] = len(selected_roles) - passed
        output = arguments.output_root / run_id
        output.mkdir(parents=True, exist_ok=False)
        output_file = output / "summary.json"
        output_file.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if passed != len(selected_roles):
            diagnostic = []
            for record in logger.records:
                result = results.get(record.agent_name)
                if result is None or result.status is not AgentStatus.ERROR:
                    continue
                error = result.error
                diagnostic.append(
                    {
                        "agent_name": record.agent_name.value,
                        "validator_error": record.error_message,
                        "error_code": None if error is None else error.code,
                        "safe_error_details": (
                            None if error is None else error.details
                        ),
                    }
                )
            (output / "rejected_outputs.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "status": "ok" if passed == len(selected_roles) else "failed",
                    "run_id": run_id,
                    "passed_agents": passed,
                    "failed_agents": len(selected_roles) - passed,
                    "output": str(output_file),
                },
                sort_keys=True,
            )
        )
        return 0 if passed == len(selected_roles) else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "live_agent_contract_failed",
                    "message": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def _run_chain(
    bundle: ResearchDataBundle,
    memory_bundle: ResearchContextBundle,
    base_context: AgentContext,
    agents: dict[AgentName, BaseAgent],
    model: str,
    *,
    include_risk: bool = False,
    sector_context: SectorContextBundle | None = None,
) -> dict[AgentName, AgentExecutionResult]:
    results: dict[AgentName, AgentExecutionResult] = {}
    analyst_outputs: list[AnalystOutput] = []
    for role in ANALYST_ORDER:
        analyst_contract = AgentInputProjector.analyst(
            bundle, memory_bundle, role, sector_context
        )
        analyst_request = AgentRequest(
            run_id=f"fixed:{role.value}",
            agent_name=role,
            model_name=model,
            input_context=_context_for_contract(base_context, analyst_contract),
            research_contract=_contract_json(analyst_contract),
        )
        result = _invoke(
            agents[role], role, model, analyst_request.model_dump(mode="json")
        )
        results[role] = result
        if result.status is AgentStatus.OK and result.output is not None:
            analyst_outputs.append(_parse_analyst_output(role, result.output))

    slots = tuple(_versioned_output(results[role]) for role in ANALYST_ORDER)
    if not analyst_outputs:
        return results
    research_context = AgentInputProjector.manager_context(
        bundle,
        memory_bundle,
        AgentName.RESEARCH_MANAGER,
        slots,
        sector_context,
    )
    research_contract = ResearchManagerInputV1(context=research_context)
    research_request = ResearchManagerRequest(
        input_context=_context_for_contract(base_context, research_contract),
        analyst_outputs=analyst_outputs,
        research_contract=_contract_json(research_contract),
    )
    research_result = _invoke(
        agents[AgentName.RESEARCH_MANAGER],
        AgentName.RESEARCH_MANAGER,
        model,
        research_request.model_dump(mode="json"),
    )
    results[AgentName.RESEARCH_MANAGER] = research_result
    if research_result.status is not AgentStatus.OK or research_result.output is None:
        return results
    research_response = ResearchManagerResponse.model_validate(research_result.output)
    research_slot = _versioned_output(research_result)

    for role, input_model, request_model in (
        (AgentName.BULL_MANAGER, BullManagerInputV1, BullManagerRequest),
        (AgentName.BEAR_MANAGER, BearManagerInputV1, BearManagerRequest),
    ):
        manager_context = AgentInputProjector.manager_context(
            bundle,
            memory_bundle,
            role,
            slots,
            sector_context,
        )
        manager_contract = input_model(
            context=manager_context,
            research_output=research_slot,
        )
        manager_request = request_model(
            input_context=_context_for_contract(base_context, manager_contract),
            analyst_outputs=analyst_outputs,
            research_summary=research_response.analysis,
            research_contract=_contract_json(manager_contract),
        )
        results[role] = _invoke(
            agents[role], role, model, manager_request.model_dump(mode="json")
        )
    if include_risk and _pre_risk_gate_passed(results):
        bull_result = results[AgentName.BULL_MANAGER]
        bear_result = results[AgentName.BEAR_MANAGER]
        if (
            bull_result.status is AgentStatus.OK
            and bear_result.status is AgentStatus.OK
            and bull_result.output is not None
            and bear_result.output is not None
        ):
            bull_output = BullManagerResponse.model_validate(bull_result.output)
            bear_output = BearManagerResponse.model_validate(bear_result.output)
            risk_context = AgentInputProjector.manager_context(
                bundle,
                memory_bundle,
                AgentName.RISK_MANAGER,
                slots,
                sector_context,
            )
            risk_contract = RiskManagerInputV1(
                context=risk_context,
                research_output=research_slot,
                bull_output=_versioned_output(bull_result),
                bear_output=_versioned_output(bear_result),
            )
            risk_request = RiskManagerRequest(
                input_context=_context_for_contract(base_context, risk_contract),
                analyst_outputs=analyst_outputs,
                research_summary=research_response.analysis,
                bull_output=bull_output,
                bear_output=bear_output,
                research_contract=_contract_json(risk_contract),
            )
            results[AgentName.RISK_MANAGER] = _invoke(
                agents[AgentName.RISK_MANAGER],
                AgentName.RISK_MANAGER,
                model,
                risk_request.model_dump(mode="json"),
            )
    return results


def _pre_risk_gate_passed(
    results: dict[AgentName, AgentExecutionResult],
) -> bool:
    """Allow Risk only after every one of the seven prerequisite roles passes."""

    return all(
        role in results and results[role].status is AgentStatus.OK
        for role in _AGENT_CLASSES
    )


def _run_sentiment_only(
    bundle: ResearchDataBundle,
    memory_bundle: ResearchContextBundle,
    base_context: AgentContext,
    agent: BaseAgent,
    model: str,
    sector_context: SectorContextBundle | None = None,
) -> dict[AgentName, AgentExecutionResult]:
    """Invoke only Sentiment against the same fixed role projection."""

    role = AgentName.SENTIMENT_ANALYST
    contract = AgentInputProjector.analyst(bundle, memory_bundle, role, sector_context)
    request = AgentRequest(
        run_id=f"fixed:{role.value}",
        agent_name=role,
        model_name=model,
        input_context=_context_for_contract(base_context, contract),
        research_contract=_contract_json(contract),
    )
    return {
        role: _invoke(agent, role, model, request.model_dump(mode="json")),
    }


def _invoke(
    agent: BaseAgent,
    role: AgentName,
    model: str,
    payload: dict[str, object],
) -> AgentExecutionResult:
    return agent.run(
        AgentInvocation(
            run_id=f"fixed:{role.value}",
            model_name=model,
            input_payload=cast(JsonObject, payload),
        )
    )


def _empty_memory_bundle(bundle: ResearchDataBundle) -> ResearchContextBundle:
    missing = [
        MissingContext(
            section=section,
            reason=MissingContextReason.NO_RELEVANT_MEMORY,
            detail="The fixed contract snapshot does not include Memory items.",
            requested_levels=list(MemoryLevel),
        )
        for section in ResearchContextSection
    ]
    metadata = RetrievalMetadata(
        query_id="fixed-agent-contract-memory-v1",
        query_text="fixed Agent contract context",
        as_of=bundle.as_of,
        market=bundle.asset_id.market,
        asset_id=bundle.asset_id,
        namespace_keys=[str(bundle.asset_id)],
        requested_levels=list(MemoryLevel),
        min_importance_score=0.0,
        top_k_per_section=1,
        snapshot_id="fixed-empty-memory-v1",
        candidate_count=0,
        eligible_count=0,
        result_count=0,
        excluded_future_count=0,
        excluded_namespace_count=0,
        excluded_asset_count=0,
        excluded_market_count=0,
        excluded_importance_count=0,
        excluded_expired_count=0,
        excluded_current_report_count=0,
        section_counts={section: 0 for section in ResearchContextSection},
        status=RetrievalStatus.EMPTY,
        no_relevant_memory=True,
    )
    return ResearchContextBundle(
        current_snapshot=[],
        macro_events=[],
        asset_events=[],
        prior_research=[],
        prior_risk=[],
        historical_analogs=[],
        regime_context=[],
        retrieval_metadata=metadata,
        missing_context=missing,
    )


def _metrics(result: AgentExecutionResult) -> JsonObject:
    bindings: list[JsonObject] = []
    if result.output is not None:
        owner: JsonObject = result.output
        analysis = result.output.get("analysis")
        if isinstance(analysis, dict):
            owner = analysis
        raw = owner.get("claim_evidence")
        if isinstance(raw, list):
            bindings = [item for item in raw if isinstance(item, dict)]
    numeric_claims = sum(bool(item.get("numeric_literals")) for item in bindings)
    return {
        "status": result.status.value,
        "claims": len(bindings),
        "valid_claims": len(bindings),
        "claims_with_binding": len(bindings),
        "rejected_claims": len(result.rejected_claims),
        "numeric_claims": numeric_claims,
        "grounded_numeric_claims": (
            numeric_claims if result.status is AgentStatus.OK else 0
        ),
        "invalid_citations": int(
            result.error is not None and "cited evidence absent" in result.error.message
        ),
        "schema_validation_errors": int(
            result.error is not None and result.error.code == "schema_validation"
        ),
        "unbound_claims": int(
            result.error is not None and "bindings do not match" in result.error.message
        ),
        "initial_attempt": "failed" if result.repair_attempted else "passed",
        "repair_attempt": (
            "not_run"
            if not result.repair_attempted
            else ("passed" if result.status is AgentStatus.OK else "failed")
        ),
        "structured_output_attempts": result.structured_output_attempts,
        "error_code": None if result.error is None else result.error.code,
        "error_message": None if result.error is None else result.error.message,
    }


def _configuration_error(message: str) -> int:
    print(
        json.dumps(
            {
                "status": "not_configured",
                "error_code": "qwen_not_configured",
                "message": message,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
