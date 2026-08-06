"""Run one opt-in SEC-to-Qwen Phase One report acceptance through FastAPI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openai import OpenAI
from pydantic import SecretStr

from src.adapters import SECEDGARAdapter
from src.agents import (
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
from src.agents.base import BaseAgent
from src.api import create_app
from src.api.services import (
    ApiServices,
    EmptySnapshotQueryService,
    InProcessReportTaskService,
)
from src.core import AppEnvironment, AppSettings, OpenAISettings, StorageSettings
from src.memory import MemoryService
from src.models.enums import AgentName, MarketScope, ReportMarketScope, ReportType
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.operators import FundamentalFeatureOperator, TechnicalFeatureOperator
from src.orchestration import ResearchReportPipeline, ResearchWorkflowService
from src.reports import STANDARD_SECTION_NAMES, ReportAssembler
from src.repositories import (
    AgentRunRepository,
    DocumentRepository,
    DuckDBDatabase,
    FaissVectorRepository,
    IngestionJobRepository,
    InstrumentRepository,
    LLMCacheRepository,
    MarketDataRepository,
    MemoryItemRepository,
    ReportRepository,
    SourceRegistryRecord,
    SourceRegistryRepository,
)
from src.schemas import GenerateReportRequest, ResearchReport
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    LLMGateway,
    OpenAIEmbeddingService,
    OpenAIProvider,
    RawTextStore,
)
from src.services.llm_provider import LLMProviderError, LLMProviderResult

_ASSET_ID = AssetId("US:AAPL")
_CIK = "0000320193"
_DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LiveAcceptanceError(RuntimeError):
    """Safe terminal failure for the manual live acceptance."""


class _DiagnosticOpenAIProvider(OpenAIProvider):
    """Capture already-sanitized provider diagnostics for this manual run."""

    provider_name = "dashscope_qwen_compatible"
    last_error: LLMProviderError | None = None

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> LLMProviderResult:
        try:
            return super().invoke_json(model, system_prompt, input_payload)
        except LLMProviderError as exc:
            self.last_error = exc
            raise


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise LiveAcceptanceError(f"缺少必需环境变量 {name}")
    return value


def _environment_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise LiveAcceptanceError(f"{name} 必须是 true 或 false")


def _data_root() -> Path:
    configured = os.getenv("DEEPINSIGHT_LIVE_ROOT", "").strip()
    if configured:
        return Path(configured)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("data") / "live_acceptance" / stamp


def _agent_registry(
    *,
    database: DuckDBDatabase,
    memory: MemoryService,
    settings: OpenAISettings,
    qwen_client: OpenAI,
    enable_thinking: bool,
) -> tuple[dict[AgentName, BaseAgent], _DiagnosticOpenAIProvider]:
    prompt_root = Path(__file__).resolve().parents[1] / "config" / "prompts"
    prompts = PromptLoader(prompt_root)
    runs = AgentRunRepository(database)
    cache = LLMCacheRepository(database)
    provider = _DiagnosticOpenAIProvider(
        settings,
        request_extra_body={"enable_thinking": enable_thinking},
        client=qwen_client,
    )
    classes: dict[AgentName, type[BaseAgent]] = {
        AgentName.FUNDAMENTAL_ANALYST: FundamentalAnalystAgent,
        AgentName.TECHNICAL_TEXT_ANALYST: TechnicalTextAnalystAgent,
        AgentName.SENTIMENT_ANALYST: SentimentAnalystAgent,
        AgentName.NEWS_EVENT_ANALYST: NewsEventAnalystAgent,
        AgentName.RESEARCH_MANAGER: ResearchManagerAgent,
        AgentName.BULL_MANAGER: BullManagerAgent,
        AgentName.BEAR_MANAGER: BearManagerAgent,
        AgentName.RISK_MANAGER: RiskManagerAgent,
    }
    registry = {
        name: agent_type(
            LLMGateway(cache, settings, provider=provider),
            memory,
            prompts,
            runs,
        )
        for name, agent_type in classes.items()
    }
    return registry, provider


def _build_application(
    root: Path,
    api_key: str,
    sec_user_agent: str,
) -> tuple[FastAPI, DuckDBDatabase, _DiagnosticOpenAIProvider]:
    root.mkdir(parents=True, exist_ok=False)
    qwen_model = os.getenv("DASHSCOPE_MODEL", "qwen3.6-flash").strip()
    enable_thinking = _environment_bool(
        "DASHSCOPE_ENABLE_THINKING",
        default=False,
    )
    qwen_base_url = os.getenv(
        "DASHSCOPE_BASE_URL",
        _DEFAULT_QWEN_BASE_URL,
    ).strip()
    embedding_model = os.getenv(
        "DASHSCOPE_EMBEDDING_MODEL",
        "text-embedding-v4",
    ).strip()
    embedding_base_url = os.getenv(
        "DASHSCOPE_EMBEDDING_BASE_URL",
        _DEFAULT_EMBEDDING_BASE_URL,
    ).strip()
    openai_settings = OpenAISettings(
        api_key=SecretStr(api_key),
        model_default=qwen_model,
        embedding_model=embedding_model,
        timeout_seconds=90,
        max_retries=0,
        store_remote=False,
    )
    settings = AppSettings(
        env=AppEnvironment.DEVELOPMENT,
        storage=StorageSettings(
            duckdb_path=root / "duckdb" / "platform.duckdb",
            faiss_root=root / "faiss",
            snapshot_root=root / "snapshots",
            backup_root=root / "backups",
        ),
        openai=openai_settings,
    )
    database = DuckDBDatabase(settings.storage.duckdb_path)
    database.bootstrap()
    SourceRegistryRepository(database).upsert(
        SourceRegistryRecord(
            source_id="sec_edgar",
            source_name="SEC EDGAR",
            market_scope=MarketScope.US,
            source_type="filing",
            auth_mode="identified_public",
            base_url="https://data.sec.gov",
            notes="Official public disclosure source; SEC Fair Access applies.",
        )
    )

    qwen_client = OpenAI(
        api_key=api_key,
        base_url=qwen_base_url,
        timeout=90,
        max_retries=0,
    )
    embedding_client = OpenAI(
        api_key=api_key,
        base_url=embedding_base_url,
        timeout=90,
        max_retries=0,
    )
    embedder = OpenAIEmbeddingService(
        openai_settings,
        dimension=256,
        batch_size=10,
        client=embedding_client,
    )
    vectors = FaissVectorRepository(
        settings.storage.faiss_root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    documents = DocumentRepository(database)
    market_data = MarketDataRepository(database)
    memory = MemoryService(
        MemoryItemRepository(database),
        vectors,
        embedder,
    )
    chunker = DocumentChunker(
        chunk_size=12_000,
        overlap=500,
        embedding_model=embedder.model_name,
        embedding_dim=embedder.dimension,
        faiss_namespace="docs_v1",
    )
    ingestion = DataIngestionService(
        instruments=InstrumentRepository(database),
        market_data=market_data,
        documents=documents,
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(root / "raw"),
        chunker=chunker,
    )
    provider = SECEDGARAdapter(
        user_agent=sec_user_agent,
        cik_by_asset={str(_ASSET_ID): _CIK},
        max_documents=1,
    )
    registry, diagnostic_provider = _agent_registry(
        database=database,
        memory=memory,
        settings=openai_settings,
        qwen_client=qwen_client,
        enable_thinking=enable_thinking,
    )
    reports = ReportRepository(database)
    workflow = ResearchWorkflowService(
        provider=provider,
        ingestion=ingestion,
        market_data=market_data,
        documents=documents,
        document_indexer=DocumentEmbeddingService(
            documents,
            vectors,
            embedder,
        ),
        memory=memory,
        fundamental_features=FundamentalFeatureOperator(),
        technical_features=TechnicalFeatureOperator(),
        coordinator=ResearchCoordinator(registry),
        report_pipeline=ResearchReportPipeline(
            ReportAssembler(),
            reports,
            memory,
        ),
        model_name=qwen_model,
        document_lookback_days=370,
        evidence_chunks_per_document=2,
    )
    services = ApiServices(
        report_tasks=InProcessReportTaskService(workflow),
        reports=reports,
        memory=memory,
        snapshots=EmptySnapshotQueryService(),
    )
    return (
        create_app(settings=settings, services=services),
        database,
        diagnostic_provider,
    )


def _failure_diagnostics(
    database: DuckDBDatabase,
    provider: _DiagnosticOpenAIProvider,
    *,
    model: str,
    enable_thinking: bool,
) -> dict[str, object]:
    with database.connection() as connection:
        ingestion = connection.execute("""
            SELECT status, rows_written, error_message
            FROM ingestion_jobs
            ORDER BY created_at DESC
            LIMIT 1
            """).fetchone()
        agent_runs = connection.execute("""
            SELECT agent_name, status, error_message
            FROM agent_runs
            ORDER BY started_at
            """).fetchall()
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM instruments),
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM document_chunks),
                (SELECT count(*) FROM agent_runs),
                (SELECT count(*) FROM reports)
            """).fetchone()
    diagnostic: dict[str, object] = {
        "llm_request": {
            "model": model,
            "enable_thinking": enable_thinking,
        },
        "stage_counts": {
            "instruments": counts[0] if counts else 0,
            "text_documents": counts[1] if counts else 0,
            "document_chunks": counts[2] if counts else 0,
            "agent_runs": counts[3] if counts else 0,
            "reports": counts[4] if counts else 0,
        },
        "ingestion": (
            None
            if ingestion is None
            else {
                "status": ingestion[0],
                "rows_written": ingestion[1],
                "error_message": ingestion[2],
            }
        ),
        "agent_runs": [
            {
                "agent_name": row[0],
                "status": row[1],
                "error_message": row[2],
            }
            for row in agent_runs
        ],
    }
    error = provider.last_error
    if error is not None:
        diagnostic["provider_error"] = {
            key: value
            for key, value in {
                "error_code": error.code,
                "message": str(error),
                "status_code": error.provider_status_code,
                "provider_code": error.provider_code,
                "provider_type": error.provider_type,
                "provider_param": error.provider_param,
                "provider_message": error.provider_message,
                "endpoint": error.provider_endpoint,
                "request_id": error.provider_request_id,
            }.items()
            if value is not None
        }
    return diagnostic


def _verify_traceability(
    database: DuckDBDatabase,
    report: ResearchReport,
) -> tuple[int, int]:
    references = {
        (
            reference.document_id,
            reference.excerpt_ref,
            reference.provider,
            reference.source_url,
        )
        for reference in report.source_trace
    }
    traced = 0
    with database.connection() as connection:
        for document_id, excerpt_ref, provider, source_url in references:
            if document_id is not None and excerpt_ref is not None:
                row = connection.execute(
                    """
                    SELECT d.source_url, d.raw_text_path, d.metadata_json
                    FROM text_documents AS d
                    JOIN document_chunks AS c
                      ON c.document_id = d.document_id
                    WHERE d.document_id = ? AND c.chunk_id = ?
                    """,
                    (document_id, excerpt_ref),
                ).fetchone()
                if row is None or not all(row):
                    raise LiveAcceptanceError(
                        f"引用无法追溯：{document_id}/{excerpt_ref}"
                    )
                traced += 1
            elif provider or source_url:
                traced += 1
            else:
                raise LiveAcceptanceError("报告包含空引用")
    return len(references), traced


async def _run() -> dict[str, object]:
    api_key = _required_environment("DASHSCOPE_API_KEY")
    sec_user_agent = _required_environment("SEC_USER_AGENT")
    root = _data_root()
    application, database, diagnostic_provider = _build_application(
        root,
        api_key,
        sec_user_agent,
    )
    qwen_model = os.getenv("DASHSCOPE_MODEL", "qwen3.6-flash").strip()
    enable_thinking = _environment_bool(
        "DASHSCOPE_ENABLE_THINKING",
        default=False,
    )
    request = GenerateReportRequest(
        report_date=datetime.now(UTC).date(),
        market_scope=ReportMarketScope.US,
        report_type=ReportType.SINGLE_ASSET,
        asset_ids=[_ASSET_ID],
        language="en",
        include_sections=list(STANDARD_SECTION_NAMES),
    )
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://live") as client:
        submitted = await client.post(
            "/v1/reports/generate",
            json=request.model_dump(mode="json"),
        )
        submitted.raise_for_status()
        job_id = submitted.json()["job_id"]
        task_response = await client.get(f"/v1/reports/jobs/{job_id}")
        task_response.raise_for_status()
        task = task_response.json()
        if task["status"] != "completed" or not task.get("report_id"):
            raise LiveAcceptanceError(
                "真实报告任务未完成："
                + json.dumps(
                    {
                        "task": task,
                        "diagnostic": _failure_diagnostics(
                            database,
                            diagnostic_provider,
                            model=qwen_model,
                            enable_thinking=enable_thinking,
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        report_response = await client.get(f"/v1/reports/{task['report_id']}")
        report_response.raise_for_status()
        report = ResearchReport.model_validate(report_response.json())

    citation_count, traced_count = _verify_traceability(database, report)
    if citation_count == 0 or traced_count != citation_count:
        raise LiveAcceptanceError("报告引用追溯验收失败")
    output = root / "reports"
    output.mkdir(parents=True, exist_ok=True)
    markdown_path = output / f"{report.report_id}.md"
    json_path = output / f"{report.report_id}.json"
    markdown_path.write_text(report.report_markdown, encoding="utf-8")
    json_path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    with database.connection() as connection:
        agent_run = connection.execute(
            "SELECT run_id FROM agent_runs ORDER BY started_at LIMIT 1"
        ).fetchone()
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM document_chunks),
                (SELECT count(*) FROM agent_runs),
                (SELECT count(*) FROM report_sections),
                (SELECT count(*) FROM memory_items)
            """).fetchone()
    if agent_run is None or counts is None:
        raise LiveAcceptanceError("验收数据库缺少运行记录")
    task_id = str(agent_run[0]).rsplit(":", maxsplit=1)[0]
    return {
        "status": "ok",
        "asset_id": str(_ASSET_ID),
        "provider": "sec_edgar",
        "job_id": job_id,
        "task_id": task_id,
        "report_id": report.report_id,
        "citation_count": citation_count,
        "traced_citation_count": traced_count,
        "database_path": str(root / "duckdb" / "platform.duckdb"),
        "report_markdown_path": str(markdown_path),
        "report_json_path": str(json_path),
        "table_counts": {
            "text_documents": counts[0],
            "document_chunks": counts[1],
            "agent_runs": counts[2],
            "report_sections": counts[3],
            "memory_items": counts[4],
        },
    }


def main() -> int:
    """Run the controlled live acceptance and print safe result metadata."""

    try:
        result = asyncio.run(_run())
    except LiveAcceptanceError as exc:
        code = (
            "configuration_error"
            if str(exc).startswith("缺少必需环境变量")
            else "acceptance_failed"
        )
        print(
            json.dumps(
                {"status": "error", "error_code": code, "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2 if code == "configuration_error" else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "live_pipeline_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
