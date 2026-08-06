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
from src.core import AppSettings, load_settings
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
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    LLMGateway,
    OpenAIEmbeddingService,
    OpenAIProvider,
    RawTextStore,
)


def build_report_worker(settings: AppSettings | None = None) -> ReportWorker:
    """Build the only process authorized to execute report workflows."""

    resolved = settings or load_settings()
    provider_settings = resolved.providers
    if provider_settings.sec_user_agent is None:
        raise RuntimeError("SEC Provider user agent is not configured")
    if not provider_settings.sec_cik_map:
        raise RuntimeError("SEC Provider CIK map is not configured")
    if resolved.openai.api_key is None:
        raise RuntimeError("OpenAI API key is not configured")

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
        raw_text_store=RawTextStore(resolved.storage.raw_root),
        chunker=chunker,
    )
    workflow = ResearchWorkflowService(
        provider=SECEDGARAdapter(
            user_agent=provider_settings.sec_user_agent,
            cik_by_asset=provider_settings.sec_cik_map,
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
        coordinator=_coordinator(database, memory, resolved),
        report_pipeline=ResearchReportPipeline(
            ReportAssembler(),
            ReportRepository(database),
            memory,
        ),
        model_name=resolved.openai.model_default,
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
    settings: AppSettings,
) -> ResearchCoordinator:
    prompt_root = Path(__file__).resolve().parents[2] / "config" / "prompts"
    prompts = PromptLoader(prompt_root)
    runs = AgentRunRepository(database)
    cache = LLMCacheRepository(database)
    provider = OpenAIProvider(settings.openai)
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
            LLMGateway(cache, settings.openai, provider=provider),
            memory,
            prompts,
            runs,
        )
        for name, agent_type in classes.items()
    }
    return ResearchCoordinator(registry)
