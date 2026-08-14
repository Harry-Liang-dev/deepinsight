"""Production single-Worker dependency composition."""

from __future__ import annotations

from pathlib import Path

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
from src.core import AppSettings, LLMProviderName, load_settings
from src.memory import MemoryService
from src.models.enums import AgentName, MarketScope
from src.operators import FundamentalFeatureOperator, TechnicalFeatureOperator
from src.orchestration import (
    RedisReportJobQueue,
    ReportWorker,
    ResearchReportPipeline,
    ResearchWorkflowService,
)
from src.reports import ReportAssembler
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
    ReportJobRepository,
    ReportRepository,
    SourceRegistryRecord,
    SourceRegistryRepository,
)
from src.services import (
    ConfiguredLLMProvider,
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    EmbeddingService,
    LLMGateway,
    OpenAIEmbeddingService,
    QwenEmbeddingService,
    RawTextStore,
    ResearchDataBundleService,
    build_configured_llm_provider,
)


def build_report_worker(settings: AppSettings | None = None) -> ReportWorker:
    """Build the only process authorized to execute report workflows."""

    resolved = settings or load_settings()
    provider_settings = resolved.providers
    llm_runtime = build_configured_llm_provider(resolved)
    if provider_settings.sec_user_agent is None:
        raise RuntimeError("SEC Provider user agent is not configured")
    if not provider_settings.sec_cik_map:
        raise RuntimeError("SEC Provider CIK map is not configured")
    if llm_runtime.settings.api_key is None:
        raise RuntimeError(
            f"{llm_runtime.provider_name.value} API key is not configured"
        )

    database = DuckDBDatabase(resolved.storage.duckdb_path)
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
    embedder: EmbeddingService
    if llm_runtime.provider_name is LLMProviderName.QWEN:
        embedder = QwenEmbeddingService(
            resolved.qwen,
            dimension=resolved.qwen.embedding_dimension,
            batch_size=resolved.qwen.embedding_batch_size,
        )
    else:
        embedder = OpenAIEmbeddingService(
            resolved.openai,
            dimension=resolved.openai.embedding_dimension,
            batch_size=resolved.openai.embedding_batch_size,
        )
    vectors = FaissVectorRepository(
        resolved.storage.faiss_root,
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
        raw_text_store=RawTextStore(resolved.storage.raw_root),
        chunker=chunker,
    )
    workflow = ResearchWorkflowService(
        provider=SECEDGARAdapter(
            user_agent=provider_settings.sec_user_agent,
            cik_by_asset=provider_settings.sec_cik_map,
            request_timeout=(provider_settings.sec_request_timeout_seconds),
            max_retries=provider_settings.sec_max_retries,
            requests_per_second=(provider_settings.sec_requests_per_second),
            backoff_base_seconds=(provider_settings.sec_backoff_base_seconds),
            max_backoff_seconds=(provider_settings.sec_max_backoff_seconds),
            max_documents=provider_settings.sec_max_documents,
        ),
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
        coordinator=_coordinator(database, memory, llm_runtime),
        report_pipeline=ResearchReportPipeline(
            ReportAssembler(),
            ReportRepository(database),
            memory,
        ),
        model_name=llm_runtime.model_default,
        data_bundle_builder=ResearchDataBundleService(
            instruments=instruments,
            market_data=market_data,
        ),
        dataset_version="production_runtime_v1",
        document_lookback_days=370,
        evidence_chunks_per_document=2,
    )
    queue = RedisReportJobQueue(
        resolved.redis.url,
        queue_name=resolved.redis.report_queue_name,
    )
    return ReportWorker(
        ReportJobRepository(database),
        queue,
        workflow,
    )


def _coordinator(
    database: DuckDBDatabase,
    memory: MemoryService,
    llm_runtime: ConfiguredLLMProvider,
) -> ResearchCoordinator:
    prompt_root = Path(__file__).resolve().parents[2] / "config" / "prompts"
    prompts = PromptLoader(prompt_root)
    runs = AgentRunRepository(database)
    cache = LLMCacheRepository(database)
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
            LLMGateway(cache, provider=llm_runtime.provider),
            memory,
            prompts,
            runs,
        )
        for name, agent_type in classes.items()
    }
    return ResearchCoordinator(registry)
