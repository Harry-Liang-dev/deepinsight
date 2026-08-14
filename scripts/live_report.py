"""Run the fail-closed SEC, Alpaca, Qwen report and evaluation baseline."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scripts import smoke_alpaca as smoke_alpaca
from scripts import smoke_alpaca_context as smoke_alpaca_context
from scripts import smoke_alpaca_news as smoke_alpaca_news
from scripts import smoke_fmp as smoke_fmp
from scripts import smoke_fred as smoke_fred
from scripts import smoke_qwen as smoke_qwen
from scripts import smoke_sec_edgar as smoke_sec_edgar
from scripts import smoke_sec_xbrl as smoke_sec_xbrl
from scripts import smoke_stocktwits as smoke_stocktwits
from src.adapters import (
    AlpacaAdapter,
    FinancialModelingPrepAdapter,
    FREDAdapter,
    SECEDGARAdapter,
    StocktwitsSentimentProvider,
    build_stocktwits_provider,
    stocktwits_authorization_configured,
)
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
from src.core import (
    AppEnvironment,
    AppSettings,
    LLMProviderName,
    load_settings,
)
from src.evaluation import (
    DeterministicReportEvaluator,
    EvaluationRuleLoader,
    LLMReportJudge,
    ReportEvaluationService,
)
from src.memory import MemoryService
from src.models.enums import (
    AgentName,
    IngestionJobType,
    MarketScope,
    ReportMarketScope,
    ReportType,
)
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.operators import FundamentalFeatureOperator, TechnicalFeatureOperator
from src.orchestration import ResearchReportPipeline, ResearchWorkflowService
from src.reports import STANDARD_SECTION_NAMES, ReportAssembler
from src.repositories import (
    AgentRunRepository,
    DocumentRepository,
    DuckDBDatabase,
    EvaluationRepository,
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
from src.schemas import (
    DataAvailabilityStatus,
    DataCapability,
    EvaluationEvidenceItem,
    EvaluationInput,
    GenerateReportRequest,
    ResearchDataBundle,
    ResearchDataBundleRequest,
    ResearchReport,
    SourceReference,
)
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    IngestionRequest,
    LLMGateway,
    LLMProvider,
    QwenEmbeddingService,
    RawTextStore,
    ResearchDataBundleService,
    build_configured_llm_provider,
)
from src.services.llm_provider import LLMProviderError, LLMProviderResult

_ASSET_ID = AssetId("US:AAPL")
_PRICE_ASSET_IDS = ("US:AAPL", "US:SPY", "US:QQQ", "US:XLK")
_SEC_LOOKBACK_DAYS = 740
_CORE_CAPABILITIES = (
    DataCapability.ASSET_IDENTITY,
    DataCapability.FUNDAMENTALS,
    DataCapability.FILINGS,
    DataCapability.OHLCV,
    DataCapability.TECHNICAL_FEATURES,
    DataCapability.SENTIMENT_EVIDENCE,
    DataCapability.NEWS_EVIDENCE,
    DataCapability.CORPORATE_EVENTS,
    DataCapability.MACRO_INDICATORS,
    DataCapability.MARKET_CONTEXT,
    DataCapability.INDUSTRY_SECTOR_CONTEXT,
)
_NUMERIC_TOKEN = re.compile(r"(?<![\w-])[-+]?\d(?:\d|,(?=\d))*(?:\.\d+)?%?(?![\w-])")


class LiveAcceptanceError(RuntimeError):
    """Safe terminal failure for the manual live acceptance."""


class LivePreflightError(LiveAcceptanceError):
    """Hard-stop an invalid live run before any network request."""

    def __init__(self, result: dict[str, object]) -> None:
        """Retain only the secret-free structured preflight result."""

        self.result = result
        super().__init__("INVALID LIVE RUN")


class _DiagnosticProvider:
    """Capture safe errors while delegating to the production Provider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.provider_name = provider.provider_name
        self.last_error: LLMProviderError | None = None

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
    ) -> LLMProviderResult:
        try:
            return self._provider.invoke_json(
                model,
                system_prompt,
                input_payload,
                response_schema=response_schema,
                schema_name=schema_name,
            )
        except LLMProviderError as exc:
            self.last_error = exc
            raise


def _data_root(settings: AppSettings) -> Path:
    if settings.live.root is not None:
        return settings.live.root
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("data") / "live_acceptance" / stamp


def _preflight(settings: AppSettings) -> dict[str, object]:
    """Return a secret-free hard-gate result without network access."""

    provider = settings.llm.provider
    qwen_secret = settings.qwen.api_key
    qwen_configured = bool(
        qwen_secret is not None and qwen_secret.get_secret_value().strip()
    )
    sec_user_agent = settings.providers.sec_user_agent
    sec_identity = bool(sec_user_agent is not None and sec_user_agent.strip())
    sec_resolved = bool(settings.providers.sec_cik_map.get(str(_ASSET_ID)))
    alpaca_key = settings.providers.alpaca_api_key_id
    alpaca_secret = settings.providers.alpaca_api_secret_key
    alpaca_configured = bool(
        alpaca_key is not None
        and alpaca_key.get_secret_value().strip()
        and alpaca_secret is not None
        and alpaca_secret.get_secret_value().strip()
    )
    fred_secret = settings.providers.fred_api_key
    fred_configured = bool(
        fred_secret is not None and fred_secret.get_secret_value().strip()
    )
    fmp_secret = settings.providers.fmp_api_key
    fmp_configured = bool(
        settings.providers.fmp_enabled
        and fmp_secret is not None
        and fmp_secret.get_secret_value().strip()
    )
    stocktwits_enabled = settings.providers.stocktwits_mcp_enabled
    stocktwits_authorized = (
        stocktwits_authorization_configured(settings.providers)
        if stocktwits_enabled
        else False
    )
    live = settings.live
    dataset_configured = bool(
        live.dataset_version
        and live.as_of_date
        and live.data_start
        and live.data_end
        and live.data_start <= live.data_end <= live.as_of_date
    )
    passed = all(
        (
            provider is LLMProviderName.QWEN,
            qwen_configured,
            bool(settings.qwen.model_default.strip()),
            sec_identity,
            sec_resolved,
            alpaca_configured,
            fred_configured,
            fmp_configured,
            stocktwits_enabled,
            stocktwits_authorized,
            dataset_configured,
        )
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "mode": "live",
        "llm": {
            "provider": provider.value,
            "model": settings.qwen.model_default,
            "credential": "configured" if qwen_configured else "missing",
            "real": provider is LLMProviderName.QWEN and qwen_configured,
            "e2e_max_retries": live.llm_max_retries,
        },
        "sec": {
            "configured": sec_identity,
            "asset_resolved": sec_resolved,
            "asset_id": str(_ASSET_ID),
        },
        "alpaca": {
            "configured": alpaca_configured,
            "asset_resolved": True,
        },
        "fred": {
            "configured": fred_configured,
            "series_count": len(FREDAdapter.DEFAULT_SERIES),
        },
        "fmp": {
            "enabled": settings.providers.fmp_enabled,
            "credential": "configured" if fmp_configured else "missing",
            "asset_resolved": True,
        },
        "stocktwits": {
            "enabled": stocktwits_enabled,
            "provider_status": (
                "CONFIGURED"
                if stocktwits_enabled and stocktwits_authorized
                else "NOT_CONFIGURED" if stocktwits_enabled else "DISABLED"
            ),
            "authorization": (
                "configured"
                if stocktwits_authorized
                else "authorization required" if stocktwits_enabled else "disabled"
            ),
        },
        "fake": {"llm": False, "judge": False},
        "dataset_version": live.dataset_version or "missing",
        "as_of_date": (
            live.as_of_date.isoformat() if live.as_of_date is not None else "missing"
        ),
        "data_window": {
            "start": (
                live.data_start.isoformat()
                if live.data_start is not None
                else "missing"
            ),
            "end": (
                live.data_end.isoformat() if live.data_end is not None else "missing"
            ),
        },
    }


def _agent_registry(
    *,
    database: DuckDBDatabase,
    memory: MemoryService,
    settings: AppSettings,
) -> tuple[dict[AgentName, BaseAgent], _DiagnosticProvider]:
    prompt_root = Path(__file__).resolve().parents[1] / "config" / "prompts"
    prompts = PromptLoader(prompt_root)
    runs = AgentRunRepository(database)
    cache = LLMCacheRepository(database)
    provider = _DiagnosticProvider(build_configured_llm_provider(settings).provider)
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
            LLMGateway(cache, provider=provider),
            memory,
            prompts,
            runs,
        )
        for name, agent_type in classes.items()
    }
    return registry, provider


def _build_application(
    root: Path,
    settings: AppSettings,
) -> tuple[
    FastAPI,
    DuckDBDatabase,
    _DiagnosticProvider,
    DataIngestionService,
    SECEDGARAdapter,
    AlpacaAdapter,
    FREDAdapter,
    FinancialModelingPrepAdapter,
    StocktwitsSentimentProvider | None,
    ResearchDataBundleService,
]:
    root.mkdir(parents=True, exist_ok=False)
    runtime_settings = settings.model_copy(
        update={
            "env": AppEnvironment.DEVELOPMENT,
            "qwen": settings.qwen.model_copy(
                update={"max_retries": settings.live.llm_max_retries}
            ),
            "storage": settings.storage.model_copy(
                update={
                    "duckdb_path": root / "duckdb" / "platform.duckdb",
                    "faiss_root": root / "faiss",
                    "snapshot_root": root / "snapshots",
                    "backup_root": root / "backups",
                    "raw_root": root / "raw",
                }
            ),
        }
    )
    sec_user_agent = runtime_settings.providers.sec_user_agent
    if sec_user_agent is None:
        raise LiveAcceptanceError("SEC User-Agent unexpectedly missing after preflight")
    cik = runtime_settings.providers.sec_cik_map.get(str(_ASSET_ID))
    if cik is None:
        raise LiveAcceptanceError(
            "SEC asset mapping unexpectedly missing after preflight"
        )
    if (
        runtime_settings.live.as_of_date is None
        or runtime_settings.live.data_start is None
    ):
        raise LiveAcceptanceError(
            "live data window unexpectedly missing after preflight"
        )
    database = DuckDBDatabase(runtime_settings.storage.duckdb_path)
    database.bootstrap()
    SourceRegistryRepository(database).upsert(
        SourceRegistryRecord(
            source_id="financial_modeling_prep",
            source_name="Financial Modeling Prep",
            market_scope=MarketScope.US,
            source_type="standardized_fundamentals",
            auth_mode="api_key",
            base_url=runtime_settings.providers.fmp_base_url,
            notes=(
                "Standardized TTM metrics; SEC remains the filing and raw fact "
                "authority."
            ),
        )
    )
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
    SourceRegistryRepository(database).upsert(
        SourceRegistryRecord(
            source_id="fred",
            source_name="FRED / ALFRED",
            market_scope=MarketScope.US,
            source_type="macro",
            auth_mode="api_key",
            base_url="https://api.stlouisfed.org/fred",
            notes="Official vintage-aware US macro observations.",
        )
    )
    if runtime_settings.providers.stocktwits_mcp_enabled:
        SourceRegistryRepository(database).upsert(
            SourceRegistryRecord(
                source_id="stocktwits_mcp",
                source_name="Stocktwits Remote MCP",
                market_scope=MarketScope.US,
                source_type="community_sentiment",
                auth_mode="oauth_account",
                base_url=runtime_settings.providers.stocktwits_mcp_url,
                notes=(
                    "Community sentiment evidence only; not verified financial facts."
                ),
            )
        )
    SourceRegistryRepository(database).upsert(
        SourceRegistryRecord(
            source_id="alpaca_market_data",
            source_name="Alpaca Market Data",
            market_scope=MarketScope.US,
            source_type="market",
            auth_mode="api_key",
            base_url=runtime_settings.providers.alpaca_api_base_url,
            notes="Historical 1Day bars; configured feed and adjustment.",
        )
    )

    embedder = QwenEmbeddingService(
        runtime_settings.qwen,
        dimension=runtime_settings.qwen.embedding_dimension,
        batch_size=runtime_settings.qwen.embedding_batch_size,
    )
    vectors = FaissVectorRepository(
        runtime_settings.storage.faiss_root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    documents = DocumentRepository(database)
    market_data = MarketDataRepository(database)
    instruments = InstrumentRepository(database)
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
        instruments=instruments,
        market_data=market_data,
        documents=documents,
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(root / "raw"),
        chunker=chunker,
    )
    provider = SECEDGARAdapter(
        user_agent=sec_user_agent,
        cik_by_asset={str(_ASSET_ID): cik},
        max_documents=1,
    )
    alpaca_key = runtime_settings.providers.alpaca_api_key_id
    alpaca_secret = runtime_settings.providers.alpaca_api_secret_key
    if alpaca_key is None or alpaca_secret is None:
        raise LiveAcceptanceError(
            "Alpaca credentials unexpectedly missing after preflight"
        )
    dataset_version = runtime_settings.live.dataset_version
    if dataset_version is None:
        raise LiveAcceptanceError(
            "Live dataset version unexpectedly missing after preflight"
        )
    alpaca = AlpacaAdapter(
        api_key_id=alpaca_key.get_secret_value(),
        api_secret_key=alpaca_secret.get_secret_value(),
        api_base_url=runtime_settings.providers.alpaca_api_base_url,
        user_agent=runtime_settings.providers.alpaca_user_agent,
        request_timeout=runtime_settings.providers.alpaca_request_timeout_seconds,
        max_retries=runtime_settings.providers.alpaca_max_retries,
        requests_per_minute=runtime_settings.providers.alpaca_requests_per_minute,
        backoff_base_seconds=(runtime_settings.providers.alpaca_backoff_base_seconds),
        max_backoff_seconds=runtime_settings.providers.alpaca_max_backoff_seconds,
        feed=runtime_settings.providers.alpaca_feed,
        adjustment=runtime_settings.providers.alpaca_adjustment,
        page_limit=runtime_settings.providers.alpaca_page_limit,
        max_pages=runtime_settings.providers.alpaca_max_pages,
    )
    stocktwits = (
        build_stocktwits_provider(runtime_settings.providers)
        if runtime_settings.providers.stocktwits_mcp_enabled
        else None
    )
    fred_secret = runtime_settings.providers.fred_api_key
    if fred_secret is None:
        raise LiveAcceptanceError(
            "FRED credential unexpectedly missing after preflight"
        )
    fred = FREDAdapter(
        api_key=fred_secret.get_secret_value(),
        user_agent=runtime_settings.providers.fred_user_agent,
        request_timeout=runtime_settings.providers.fred_request_timeout_seconds,
        max_retries=runtime_settings.providers.fred_max_retries,
        requests_per_second=runtime_settings.providers.fred_requests_per_second,
        backoff_base_seconds=runtime_settings.providers.fred_backoff_base_seconds,
        max_backoff_seconds=runtime_settings.providers.fred_max_backoff_seconds,
    )
    fmp_secret = runtime_settings.providers.fmp_api_key
    if not runtime_settings.providers.fmp_enabled or fmp_secret is None:
        raise LiveAcceptanceError(
            "FMP unexpectedly disabled or missing after preflight"
        )
    fmp = FinancialModelingPrepAdapter(
        api_key=fmp_secret.get_secret_value(),
        base_url=runtime_settings.providers.fmp_base_url,
        user_agent=runtime_settings.providers.fmp_user_agent,
        request_timeout=runtime_settings.providers.fmp_request_timeout_seconds,
        max_retries=runtime_settings.providers.fmp_max_retries,
        requests_per_second=runtime_settings.providers.fmp_requests_per_second,
    )
    registry, diagnostic_provider = _agent_registry(
        database=database,
        memory=memory,
        settings=runtime_settings,
    )
    reports = ReportRepository(database)
    data_bundle_builder = ResearchDataBundleService(
        instruments=instruments,
        market_data=market_data,
        documents=documents,
    )
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
        model_name=runtime_settings.qwen.model_default,
        data_bundle_builder=data_bundle_builder,
        dataset_version=dataset_version,
        document_lookback_days=_SEC_LOOKBACK_DAYS,
        evidence_chunks_per_document=2,
    )
    services = ApiServices(
        report_tasks=InProcessReportTaskService(workflow),
        reports=reports,
        memory=memory,
        snapshots=EmptySnapshotQueryService(),
    )
    return (
        create_app(settings=runtime_settings, services=services),
        database,
        diagnostic_provider,
        ingestion,
        provider,
        alpaca,
        fred,
        fmp,
        stocktwits,
        data_bundle_builder,
    )


def _failure_diagnostics(
    database: DuckDBDatabase,
    provider: _DiagnosticProvider,
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


def _bundle_capability_summary(
    bundle: ResearchDataBundle,
) -> dict[str, dict[str, object]]:
    """Return a credential-free projection audit for every capability."""

    summary: dict[str, dict[str, object]] = {}
    for capability in DataCapability:
        section = getattr(bundle, capability.value)
        source_identities = sorted(
            {item.source.provider_name for item in section.items}
        )
        record_count = len(
            {item.source.normalized_record_key for item in section.items}
        )
        point_in_time_safe = all(
            item.effective_at <= bundle.as_of and item.observed_at <= bundle.as_of
            for item in section.items
        )
        summary[capability.value] = {
            "status": section.status.value,
            "sources": source_identities,
            "record_count": record_count,
            "evidence_count": len(section.items),
            "as_of": section.as_of.isoformat(),
            "latest_timestamp": (
                max(item.effective_at for item in section.items).isoformat()
                if section.items
                else None
            ),
            "freshness": section.freshness.status.value,
            "data_quality": section.quality.status.value,
            "point_in_time_safe": point_in_time_safe,
            "missing_data_count": len(section.missing_data),
        }
    return summary


def _verify_core_bundle(
    bundle: ResearchDataBundle,
    summary: dict[str, dict[str, object]],
) -> None:
    """Fail before Agents when an implemented core capability is not projected."""

    available_states = {
        DataAvailabilityStatus.PRESENT.value,
        DataAvailabilityStatus.PARTIAL.value,
        DataAvailabilityStatus.STALE.value,
    }
    missing = [
        capability.value
        for capability in _CORE_CAPABILITIES
        if summary[capability.value]["status"] not in available_states
        or not summary[capability.value]["evidence_count"]
        or not summary[capability.value]["point_in_time_safe"]
    ]
    if missing:
        raise LiveAcceptanceError(
            "ResearchDataBundle core capability gate failed: " + ", ".join(missing)
        )
    if (
        bundle.valuation.status is DataAvailabilityStatus.MISSING
        and bundle.fundamentals.items
        and bundle.ohlcv.items
    ):
        raise LiveAcceptanceError(
            "ResearchDataBundle valuation remained missing despite live inputs"
        )


def _structured_references(bundle: ResearchDataBundle) -> list[SourceReference]:
    """Collect the canonical structured citation bridge for one Bundle."""

    return [
        item.to_source_reference()
        for capability in DataCapability
        for item in getattr(bundle, capability.value).items
    ]


def _verify_traceability(
    database: DuckDBDatabase,
    report: ResearchReport,
    *,
    structured_references: list[SourceReference] | None = None,
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
    structured = {
        (
            reference.document_id,
            reference.excerpt_ref,
            reference.provider,
            reference.source_url,
        )
        for reference in (structured_references or [])
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
                if (
                    row is None
                    and (
                        document_id,
                        excerpt_ref,
                        provider,
                        source_url,
                    )
                    in structured
                ):
                    traced += 1
                    continue
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


def _evaluation_evidence(
    database: DuckDBDatabase,
    report: ResearchReport,
    *,
    alpaca_base_url: str,
    data_bundle: ResearchDataBundle | None = None,
) -> list[EvaluationEvidenceItem]:
    """Build exact persisted document and price evidence for evaluation."""

    documents = DocumentRepository(database)
    market_data = MarketDataRepository(database)
    items: list[EvaluationEvidenceItem] = []
    for document in documents.list_documents(
        _ASSET_ID,
        end_date=report.report_date,
    ):
        for chunk in documents.list_chunks(document.document_id):
            items.append(
                EvaluationEvidenceItem(
                    evidence_id=f"document:{chunk.chunk_id}",
                    source_ref=SourceReference(
                        document_id=document.document_id,
                        excerpt_ref=chunk.chunk_id,
                        provider=document.source_id,
                        source_url=document.source_url,
                    ),
                    text=chunk.chunk_text,
                    published_at=document.publish_ts,
                )
            )
    for bar in market_data.list_eod_bars(
        _ASSET_ID,
        end_date=report.report_date,
        limit=10_000,
    ):
        locator = f"{bar.asset_id}:{bar.trade_date.isoformat()}"
        values = {
            "asset_id": str(bar.asset_id),
            "trade_date": bar.trade_date.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "vwap": bar.vwap,
            "source_id": bar.source_id,
        }
        items.append(
            EvaluationEvidenceItem(
                evidence_id=f"price:{locator}",
                source_ref=SourceReference(
                    excerpt_ref=locator,
                    provider=bar.source_id,
                    source_url=(f"{alpaca_base_url.rstrip('/')}/v2/stocks/bars"),
                ),
                text=json.dumps(
                    values,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                published_at=datetime.combine(
                    bar.trade_date,
                    time.min,
                    tzinfo=UTC,
                ),
            )
        )
    if data_bundle is not None:
        for capability in DataCapability:
            for evidence in getattr(data_bundle, capability.value).items:
                text_value = " ".join(
                    str(value)
                    for value in (
                        evidence.field_path,
                        evidence.value,
                        evidence.unit,
                        evidence.currency,
                    )
                    if value is not None
                )
                items.append(
                    EvaluationEvidenceItem(
                        evidence_id=f"structured:{evidence.evidence_id}",
                        source_ref=evidence.to_source_reference(),
                        text=text_value,
                        published_at=evidence.effective_at,
                    )
                )
    return items


def _known_missing_data(report: ResearchReport) -> list[str]:
    """Collect explicit report uncertainties without inventing disclosures."""

    missing: list[str] = []
    for raw_section in report.report_json.values():
        if not isinstance(raw_section, dict):
            continue
        uncertainties = raw_section.get("uncertainties")
        if isinstance(uncertainties, list):
            missing.extend(
                item.strip()
                for item in uncertainties
                if isinstance(item, str) and item.strip()
            )
    return list(dict.fromkeys(missing))


def _agent_run_manifest_rows(database: DuckDBDatabase) -> list[tuple[object, ...]]:
    """Read manifest fields using the canonical persisted column names."""

    with database.connection() as connection:
        return connection.execute("""
            SELECT run_id, agent_name, prompt_template_ver, retrieved_context_json
            FROM agent_runs
            ORDER BY started_at
            """).fetchall()


def _ungrounded_numeric_claims(
    report: ResearchReport,
    evidence: list[EvaluationEvidenceItem],
) -> tuple[int, list[dict[str, object]]]:
    """List every numeric report statement not copied from cited evidence."""

    failures: list[dict[str, object]] = []
    total = 0
    for section_name, raw_section in report.report_json.items():
        if not isinstance(raw_section, dict):
            continue
        for category in ("facts", "inferences", "risk_warnings"):
            statements = raw_section.get(category)
            if not isinstance(statements, list):
                continue
            for raw_statement in statements:
                if not isinstance(raw_statement, dict):
                    continue
                claim = raw_statement.get("text")
                if not isinstance(claim, str):
                    continue
                tokens = _NUMERIC_TOKEN.findall(claim)
                if not tokens:
                    continue
                total += 1
                raw_citations = raw_statement.get("citations")
                citations = (
                    [
                        SourceReference.model_validate(item)
                        for item in raw_citations
                        if isinstance(item, dict)
                    ]
                    if isinstance(raw_citations, list)
                    else []
                )
                matched = [
                    item
                    for citation in citations
                    for item in evidence
                    if _source_matches(citation, item.source_ref)
                ]
                evidence_text = " ".join(item.text for item in matched)
                unsupported = [token for token in tokens if token not in evidence_text]
                if unsupported:
                    failures.append(
                        {
                            "section": section_name,
                            "claim": claim,
                            "source_id": [item.evidence_id for item in matched] or None,
                            "failure_reason": (
                                "numeric tokens absent from cited evidence: "
                                + ", ".join(unsupported)
                            ),
                        }
                    )
    return total, failures


def _source_matches(expected: SourceReference, actual: SourceReference) -> bool:
    values = (
        (expected.document_id, actual.document_id),
        (expected.excerpt_ref, actual.excerpt_ref),
        (expected.provider, actual.provider),
        (expected.source_url, actual.source_url),
    )
    return all(value is None or value == candidate for value, candidate in values)


async def _run() -> dict[str, object]:
    settings = load_settings()
    preflight = _preflight(settings)
    if preflight["status"] != "PASS":
        raise LivePreflightError(preflight)
    assert settings.live.as_of_date is not None
    assert settings.live.data_start is not None
    assert settings.live.data_end is not None
    sec_start = settings.live.data_end - timedelta(days=_SEC_LOOKBACK_DAYS)
    if smoke_sec_edgar.main(
        [
            "--asset-id",
            str(_ASSET_ID),
            "--start-date",
            sec_start.isoformat(),
            "--end-date",
            settings.live.data_end.isoformat(),
        ]
    ):
        raise LiveAcceptanceError("SEC live smoke failed")
    if smoke_sec_xbrl.main(
        [
            "--asset-id",
            str(_ASSET_ID),
            "--start-date",
            sec_start.isoformat(),
            "--end-date",
            settings.live.data_end.isoformat(),
        ]
    ):
        raise LiveAcceptanceError("SEC Company Facts live smoke failed")
    if smoke_fmp.main(
        [
            "--asset-id",
            str(_ASSET_ID),
            "--end-date",
            settings.live.data_end.isoformat(),
        ]
    ):
        raise LiveAcceptanceError("FMP standardized fundamentals live smoke failed")
    if smoke_alpaca.main(
        [
            "--start-date",
            settings.live.data_start.isoformat(),
            "--end-date",
            settings.live.data_end.isoformat(),
        ]
    ):
        raise LiveAcceptanceError("Alpaca live smoke failed")
    if smoke_alpaca_context.main([]):
        raise LiveAcceptanceError("Alpaca benchmark context live smoke failed")
    if smoke_alpaca_news.main([]):
        raise LiveAcceptanceError("Alpaca News live smoke failed")
    if smoke_fred.main([]):
        raise LiveAcceptanceError("FRED live smoke failed")
    if smoke_stocktwits.main([]):
        raise LiveAcceptanceError("Stocktwits live smoke failed")
    if smoke_qwen.main([]):
        raise LiveAcceptanceError("Qwen live smoke failed")
    root = _data_root(settings)
    (
        application,
        database,
        diagnostic_provider,
        ingestion,
        sec,
        alpaca,
        fred,
        fmp,
        stocktwits,
        data_bundle_builder,
    ) = _build_application(root, settings)
    sec_job = ingestion.run(
        sec,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=(str(_ASSET_ID),),
            fundamental_start_date=sec_start,
            fundamental_end_date=settings.live.data_end,
            document_start_date=sec_start,
            document_end_date=settings.live.data_end,
        ),
    )
    fmp_job = ingestion.run(
        fmp,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=(str(_ASSET_ID),),
            fundamental_start_date=sec_start,
            fundamental_end_date=settings.live.data_end,
        ),
    )
    price_job = ingestion.run(
        alpaca,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=_PRICE_ASSET_IDS,
            eod_start_date=settings.live.data_start,
            eod_end_date=settings.live.data_end,
        ),
    )
    news_start = max(
        settings.live.data_start,
        settings.live.data_end - timedelta(days=14),
    )
    news_job = ingestion.run(
        alpaca,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=(str(_ASSET_ID),),
            document_start_date=news_start,
            document_end_date=settings.live.data_end,
        ),
    )
    macro_start = min(
        settings.live.data_start,
        settings.live.data_end - timedelta(days=400),
    )
    macro_job = ingestion.run(
        fred,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            macro_series_ids=FREDAdapter.DEFAULT_SERIES,
            macro_start_date=macro_start,
            macro_end_date=settings.live.data_end,
            macro_as_of=settings.live.data_end,
        ),
    )
    sentiment_job = (
        ingestion.run(
            stocktwits,
            IngestionRequest(
                job_type=IngestionJobType.INCREMENTAL,
                asset_ids=(str(_ASSET_ID),),
                sentiment_start_date=settings.live.data_start,
                sentiment_end_date=settings.live.data_end,
            ),
        )
        if stocktwits is not None
        else None
    )
    as_of = datetime.combine(settings.live.as_of_date, time.max, tzinfo=UTC)
    data_bundle = data_bundle_builder.build(
        ResearchDataBundleRequest(
            asset_id=_ASSET_ID,
            as_of=as_of,
            window_start=settings.live.data_start,
            window_end=settings.live.as_of_date,
            dataset_version=settings.live.dataset_version or "missing",
            requested_capabilities=tuple(DataCapability),
        )
    )
    capability_summary = _bundle_capability_summary(data_bundle)
    _verify_core_bundle(data_bundle, capability_summary)
    bundle_path = root / "research_data_bundle.json"
    bundle_path.write_text(data_bundle.model_dump_json(indent=2), encoding="utf-8")
    bundle_summary_path = root / "research_data_bundle_summary.json"
    bundle_summary_path.write_text(
        json.dumps(
            capability_summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    qwen_model = settings.qwen.model_default
    enable_thinking = settings.qwen.enable_thinking
    request = GenerateReportRequest(
        report_date=settings.live.as_of_date,
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

    structured_references = _structured_references(data_bundle)
    citation_count, traced_count = _verify_traceability(
        database,
        report,
        structured_references=structured_references,
    )
    if citation_count == 0 or traced_count != citation_count:
        raise LiveAcceptanceError("报告引用追溯验收失败")
    evidence = _evaluation_evidence(
        database,
        report,
        alpaca_base_url=settings.providers.alpaca_api_base_url,
        data_bundle=data_bundle,
    )
    evaluation = ReportEvaluationService(
        EvaluationRuleLoader(
            Path(__file__).resolve().parents[1] / "config" / "evaluation"
        ),
        DeterministicReportEvaluator(),
        LLMReportJudge(
            LLMGateway(
                LLMCacheRepository(database),
                provider=diagnostic_provider,
            ),
            qwen_model,
        ),
        EvaluationRepository(database),
    ).evaluate(
        EvaluationInput(
            report=report,
            evidence_items=evidence,
            known_missing_data=_known_missing_data(report),
            ruleset_version=settings.live.evaluation_rules_version,
        )
    )
    total_numeric, ungrounded = _ungrounded_numeric_claims(report, evidence)
    numeric_check = next(
        check
        for check in evaluation.deterministic_checks
        if check.check_id == "numeric_grounding"
    )
    output = root / "reports"
    output.mkdir(parents=True, exist_ok=True)
    markdown_path = output / f"{report.report_id}.md"
    json_path = output / f"{report.report_id}.json"
    markdown_path.write_text(report.report_markdown, encoding="utf-8")
    json_path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    evaluation_path = output / f"{report.report_id}.evaluation.json"
    evaluation_path.write_text(
        evaluation.model_dump_json(indent=2),
        encoding="utf-8",
    )
    agent_runs = _agent_run_manifest_rows(database)
    with database.connection() as connection:
        ingestion_jobs = connection.execute("""
            SELECT job_id, source_id, status
            FROM ingestion_jobs
            ORDER BY created_at
            """).fetchall()
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM document_chunks),
                (SELECT count(*) FROM agent_runs),
                (SELECT count(*) FROM report_sections),
                (SELECT count(*) FROM memory_items),
                (SELECT count(*) FROM eod_bars),
                (SELECT count(*) FROM sentiment_snapshots),
                (SELECT count(*) FROM sentiment_evidence),
                (SELECT count(*) FROM fundamentals),
                (SELECT count(*) FROM macro_series),
                (SELECT count(*) FROM news_evidence),
                (SELECT count(*) FROM corporate_events)
            """).fetchone()
    if not agent_runs or counts is None:
        raise LiveAcceptanceError("验收数据库缺少运行记录")
    task_id = str(agent_runs[0][0]).rsplit(":", maxsplit=1)[0]
    sec_jobs = [str(row[0]) for row in ingestion_jobs if row[1] == "sec_edgar"]
    if not sec_jobs:
        raise LiveAcceptanceError("验收数据库缺少 SEC ingestion snapshot")
    memory_ids: set[str] = set()
    for row in agent_runs:
        context = json.loads(str(row[3]))
        memories = context.get("memories")
        if isinstance(memories, list):
            memory_ids.update(
                str(item["memory_id"])
                for item in memories
                if isinstance(item, dict) and item.get("memory_id")
            )
    prompt_versions = {str(row[1]): str(row[2]) for row in agent_runs}
    run_id = root.name
    manifest = {
        "run_id": run_id,
        "run_type": "live_e2e_baseline",
        "asset_id": str(_ASSET_ID),
        "dataset_version": settings.live.dataset_version,
        "as_of_date": settings.live.as_of_date.isoformat(),
        "data_window": {
            "start": settings.live.data_start.isoformat(),
            "end": settings.live.data_end.isoformat(),
        },
        "ingestion_snapshots": {
            "sec": [sec_job.job_id, *sec_jobs],
            "fmp": fmp_job.job_id,
            "price": price_job.job_id,
            "news": news_job.job_id,
            "macro": macro_job.job_id,
            "sentiment": sentiment_job.job_id if sentiment_job is not None else None,
        },
        "llm": {
            "provider": settings.llm.provider.value,
            "model": qwen_model,
            "real": True,
            "max_retries": settings.live.llm_max_retries,
        },
        "judge": {
            "provider": settings.llm.provider.value,
            "model": qwen_model,
            "real": True,
            "max_retries": settings.live.llm_max_retries,
        },
        "providers": {
            "sec": {"real": True, "status": "success"},
            "fmp": {"real": True, "status": "success"},
            "alpaca": {"real": True, "status": "success"},
            "fred": {"real": True, "status": "success"},
            "stocktwits": {
                "real": sentiment_job is not None,
                "status": "success" if sentiment_job is not None else "disabled",
            },
        },
        "fake_llm": False,
        "fake_judge": False,
        "prompt_versions": prompt_versions,
        "evaluation_rules_version": settings.live.evaluation_rules_version,
        "report_id": report.report_id,
        "agent_run_ids": [str(row[0]) for row in agent_runs],
        "source_references": [
            reference.model_dump(mode="json") for reference in report.source_trace
        ],
        "evaluation_id": evaluation.evaluation_id,
        "research_data_bundle": {
            "bundle_id": data_bundle.bundle_id,
            "input_fingerprint": data_bundle.input_fingerprint,
            "artifact_path": str(bundle_path),
            "summary_path": str(bundle_summary_path),
            "capabilities": capability_summary,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    manifest_path = root / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "run_id": run_id,
        "asset_id": str(_ASSET_ID),
        "dataset_version": settings.live.dataset_version,
        "provider": "sec_edgar",
        "fundamental_metrics_provider": "financial_modeling_prep",
        "price_provider": "alpaca_market_data",
        "sec_ingestion_snapshot_ids": sec_jobs,
        "fmp_ingestion_snapshot_id": fmp_job.job_id,
        "price_ingestion_snapshot_id": price_job.job_id,
        "news_ingestion_snapshot_id": news_job.job_id,
        "macro_ingestion_snapshot_id": macro_job.job_id,
        "sentiment_ingestion_snapshot_id": (
            sentiment_job.job_id if sentiment_job is not None else None
        ),
        "job_id": job_id,
        "task_id": task_id,
        "report_id": report.report_id,
        "citation_count": citation_count,
        "traced_citation_count": traced_count,
        "database_path": str(root / "duckdb" / "platform.duckdb"),
        "report_markdown_path": str(markdown_path),
        "report_json_path": str(json_path),
        "evaluation_path": str(evaluation_path),
        "manifest_path": str(manifest_path),
        "research_data_bundle_path": str(bundle_path),
        "research_data_bundle_summary_path": str(bundle_summary_path),
        "research_data_capabilities": capability_summary,
        "evaluation": {
            "evaluation_id": evaluation.evaluation_id,
            "overall_score": evaluation.overall_score,
            "dimensions": {
                item.dimension.value: item.score for item in evaluation.dimensions
            },
            "numeric_grounding": numeric_check.score,
            "total_numeric_claims": total_numeric,
            "grounded_numeric_claims": total_numeric - len(ungrounded),
            "ungrounded_numeric_claim_count": len(ungrounded),
            "ungrounded_numeric_claims": ungrounded,
        },
        "memory_retrieval_count": len(memory_ids),
        "table_counts": {
            "text_documents": counts[0],
            "document_chunks": counts[1],
            "agent_runs": counts[2],
            "report_sections": counts[3],
            "memory_items": counts[4],
            "eod_bars": counts[5],
            "sentiment_snapshots": counts[6],
            "sentiment_evidence": counts[7],
            "fundamentals": counts[8],
            "macro_series": counts[9],
            "news_evidence": counts[10],
            "corporate_events": counts[11],
        },
    }


def main() -> int:
    """Run the controlled live acceptance and print safe result metadata."""

    try:
        result = asyncio.run(_run())
    except LivePreflightError as exc:
        print(
            json.dumps(
                {
                    "status": "INVALID LIVE RUN",
                    "preflight": exc.result,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
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
