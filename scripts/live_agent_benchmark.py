"""Run the fixed-input Agent Benchmark with a real configured LLM and Judge."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from src.agents import (
    REQUIRED_AGENTS,
    BearManagerAgent,
    BullManagerAgent,
    FundamentalAnalystAgent,
    NewsEventAnalystAgent,
    PromptLoader,
    ResearchCoordinator,
    ResearchManagerAgent,
    RiskManagerAgent,
    SentimentAnalystAgent,
    TechnicalTextAnalystAgent,
)
from src.core import load_settings
from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    LLMReportJudge,
    ReportEvaluationService,
)
from src.live_benchmark import (
    LiveAgentBenchmarkRunner,
    LiveBenchmarkComparator,
    LiveBenchmarkWriter,
    LiveSnapshotLoader,
    materialize_scenarios,
)
from src.models.enums import AgentName
from src.models.types import JsonObject
from src.reports import ReportAssembler
from src.repositories import (
    AgentRunRepository,
    DuckDBDatabase,
    EvaluationRepository,
    LLMCacheRepository,
)
from src.schemas.live_benchmark import (
    LiveBenchmarkConfig,
    LiveBenchmarkRunResult,
)
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse
from src.services import LLMGateway, build_configured_llm_provider


class _SnapshotMemoryBoundary:
    """No-network Memory boundary; contexts already contain fixed Memory results."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Reject unexpected retrieval so benchmark input cannot drift."""

        del request
        raise RuntimeError("live Agent Benchmark forbids runtime Memory retrieval")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("benchmarks/live_agent/v1/snapshot.yaml"),
    )
    parser.add_argument(
        "--checksum",
        type=Path,
        default=Path("benchmarks/live_agent/v1/snapshot.sha256"),
    )
    parser.add_argument("--prompt-root", type=Path, default=Path("config/prompts"))
    parser.add_argument("--rules-root", type=Path, default=Path("config/evaluation"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/live_agent_benchmark")
    )
    parser.add_argument("--model")
    parser.add_argument("--baseline", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute all six cases or fail closed without a Fake fallback."""

    arguments = _parser().parse_args(argv)
    try:
        loaded = LiveSnapshotLoader(arguments.snapshot, arguments.checksum).load()
        scenarios = materialize_scenarios(loaded)
        settings = load_settings()
        configured = build_configured_llm_provider(settings)
        model = arguments.model or configured.model_default
        prompt_loader = PromptLoader(arguments.prompt_root)
        prompts = {name: prompt_loader.load(name) for name in REQUIRED_AGENTS}
        prompt_versions = {name: prompt.version for name, prompt in prompts.items()}
        prompt_sha256 = {
            name: hashlib.sha256(prompt.system_prompt.encode("utf-8")).hexdigest()
            for name, prompt in prompts.items()
        }
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"live_agent_{stamp}_{uuid4().hex[:8]}"
        config = LiveBenchmarkConfig(
            run_id=run_id,
            provider=configured.provider_name.value,
            provider_real=True,
            judge_real=True,
            model_name=model,
            prompt_versions=prompt_versions,
            prompt_sha256=prompt_sha256,
            inference_parameters=_inference_parameters(configured.settings),
            evaluation_ruleset_version="report_quality_v1",
            generated_at=datetime.now(UTC),
        )
        runtime_root = arguments.output_root / ".runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        database = DuckDBDatabase(runtime_root / f"{run_id}.duckdb")
        database.bootstrap()
        gateway = LLMGateway(
            LLMCacheRepository(database),
            provider=configured.provider,
        )
        memory = _SnapshotMemoryBoundary()
        logger = AgentRunRepository(database)
        agents = {
            AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.TECHNICAL_TEXT_ANALYST: TechnicalTextAnalystAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.SENTIMENT_ANALYST: SentimentAnalystAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.RESEARCH_MANAGER: ResearchManagerAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.BULL_MANAGER: BullManagerAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.BEAR_MANAGER: BearManagerAgent(
                gateway, memory, prompt_loader, logger
            ),
            AgentName.RISK_MANAGER: RiskManagerAgent(
                gateway, memory, prompt_loader, logger
            ),
        }

        def evaluation_factory(case_id: str) -> ReportEvaluationService:
            return ReportEvaluationService(
                EvaluationRuleLoader(arguments.rules_root),
                DeterministicReportEvaluator(),
                LLMReportJudge(gateway, model),
                EvaluationRepository(database),
                evaluation_id_factory=lambda: f"eval:{run_id}:{case_id}",
            )

        result = LiveAgentBenchmarkRunner(
            ResearchCoordinator(agents),
            ReportAssembler(),
            evaluation_factory,
        ).run(loaded, scenarios, config)
        output = LiveBenchmarkWriter().write(result, scenarios, arguments.output_root)
        comparison_path = None
        if arguments.baseline is not None:
            baseline = LiveBenchmarkRunResult.model_validate_json(
                arguments.baseline.read_text(encoding="utf-8")
            )
            comparison = LiveBenchmarkComparator().compare(baseline, result)
            comparison_path = output / "comparison.json"
            LiveBenchmarkWriter.write_comparison(comparison, comparison_path)
        print(
            json.dumps(
                {
                    "status": "ok" if result.failed_cases == 0 else "partial",
                    "run_id": result.run_id,
                    "dataset_version": result.dataset_version,
                    "provider": result.config.provider,
                    "model": result.config.model_name,
                    "completed_cases": result.completed_cases,
                    "failed_cases": result.failed_cases,
                    "output": str(output),
                    "comparison": (
                        str(comparison_path) if comparison_path is not None else None
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.failed_cases == 0 else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "live_agent_benchmark_failed",
                    "message": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def _inference_parameters(settings: object) -> JsonObject:
    return cast(
        JsonObject,
        {
            key: value
            for key, value in {
                "timeout_seconds": getattr(settings, "timeout_seconds", None),
                "max_retries": getattr(settings, "max_retries", None),
                "store_remote": getattr(settings, "store_remote", None),
                "enable_thinking": getattr(settings, "enable_thinking", None),
            }.items()
            if value is not None
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
