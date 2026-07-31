"""Deterministic offline composition for local demos and end-to-end tests."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import cast

from fastapi import FastAPI

from src.adapters import FakeProviderAdapter
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
from src.core.settings import (
    AppEnvironment,
    AppSettings,
    OpenAISettings,
    StorageSettings,
)
from src.memory import MemoryService
from src.models.enums import AgentName, MemoryLevel, ReportMarketScope, ReportType
from src.models.identifiers import AssetId
from src.models.types import JsonObject, JsonValue
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
)
from src.schemas import GenerateReportRequest, MemoryWriteRequest, SourceReference
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    FakeEmbeddingService,
    FakeLLMProvider,
    LLMGateway,
    LLMProviderError,
    RawTextStore,
)

OFFLINE_NOW = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)
OFFLINE_ASSET_ID = AssetId("US:AAPL")
OFFLINE_DOCUMENT_ID = "offline-doc-aapl"
OFFLINE_DOCUMENT_TEXT = (
    "Revenue increased in the reported period while management described "
    "stable demand and acknowledged valuation and execution uncertainty."
)
OFFLINE_MEMORY_TEXT = (
    "Policy conditions remained restrictive during the evidence window."
)
OFFLINE_QUERY_TEXT = "Research evidence for US:AAPL through 2026-07-31"
OFFLINE_REPORT_MEMORY_TEXT = (
    "Research synthesis: Growth remained positive while valuation risk "
    "required caution. Narrative risk score: 0.50. This conclusion is "
    "research analysis only. Risk review: Valuation remained elevated. "
    "Demand may slow."
)
OFFLINE_EMBEDDING_MODEL = "offline-fake-embedding-v1"
OFFLINE_EMBEDDING_DIMENSION = 3


def offline_report_request() -> GenerateReportRequest:
    """Return the fixed single-asset request used by the offline demo."""

    return GenerateReportRequest(
        report_date=OFFLINE_NOW.date(),
        market_scope=ReportMarketScope.US,
        report_type=ReportType.SINGLE_ASSET,
        asset_ids=[OFFLINE_ASSET_ID],
        language="en",
        include_sections=list(STANDARD_SECTION_NAMES),
    )


def create_offline_application(
    data_root: Path,
    *,
    llm_error: LLMProviderError | None = None,
) -> FastAPI:
    """Create a complete local API using only fixed data and fake providers.

    Args:
        data_root: Isolated root for DuckDB, FAISS, and raw fixture data.
        llm_error: Optional deterministic provider failure for tests.

    Returns:
        A fully wired FastAPI application with no network dependencies.
    """

    settings = AppSettings(
        env=AppEnvironment.TEST,
        storage=StorageSettings(
            duckdb_path=data_root / "duckdb" / "platform.duckdb",
            faiss_root=data_root / "faiss",
            snapshot_root=data_root / "snapshots",
            backup_root=data_root / "backups",
        ),
        openai=OpenAISettings(model_default="offline-fake-model"),
    )
    database = DuckDBDatabase(settings.storage.duckdb_path)
    database.bootstrap()

    normalizer = DataNormalizer()
    chunker = DocumentChunker(
        chunk_size=1000,
        overlap=0,
        embedding_model=OFFLINE_EMBEDDING_MODEL,
        embedding_dim=OFFLINE_EMBEDDING_DIMENSION,
        faiss_namespace="docs_v1",
    )
    provider = _provider()
    normalized_document = normalizer.normalize_document(
        provider.provider_name,
        _document_record(),
        received_at=OFFLINE_NOW,
    )
    fixture_chunks = chunker.chunk(
        normalized_document.record,
        normalized_document.raw_text,
        created_at=OFFLINE_NOW,
    )
    if len(fixture_chunks) != 1:
        raise RuntimeError("offline fixture must produce exactly one chunk")
    citation = SourceReference(
        document_id=OFFLINE_DOCUMENT_ID,
        excerpt_ref=fixture_chunks[0].chunk_id,
    )

    embedder = FakeEmbeddingService(
        {
            OFFLINE_DOCUMENT_TEXT: [1.0, 0.0, 0.0],
            OFFLINE_MEMORY_TEXT: [0.9, 0.1, 0.0],
            OFFLINE_QUERY_TEXT: [0.9, 0.1, 0.0],
            OFFLINE_REPORT_MEMORY_TEXT: [0.8, 0.2, 0.0],
        },
        model_name=OFFLINE_EMBEDDING_MODEL,
    )
    vectors = FaissVectorRepository(
        settings.storage.faiss_root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    documents = DocumentRepository(database)
    market_data = MarketDataRepository(database)
    memory_ids = count(1)
    memory = MemoryService(
        MemoryItemRepository(database),
        vectors,
        embedder,
        clock=lambda: OFFLINE_NOW,
        memory_id_factory=lambda: f"mem_demo_{next(memory_ids)}",
    )
    memory.write(
        MemoryWriteRequest(
            memory_level=MemoryLevel.L1,
            namespace_key="US",
            asset_id=OFFLINE_ASSET_ID,
            effective_ts=OFFLINE_NOW,
            memory_type="macro_event",
            importance_score=0.8,
            summary_text=OFFLINE_MEMORY_TEXT,
            source_ref_json=SourceReference(provider="offline_fixture"),
            created_by="offline_fixture",
        )
    )

    ingestion_ids = count(1)
    ingestion = DataIngestionService(
        instruments=InstrumentRepository(database),
        market_data=market_data,
        documents=documents,
        jobs=IngestionJobRepository(database),
        normalizer=normalizer,
        raw_text_store=RawTextStore(data_root / "raw"),
        chunker=chunker,
        clock=lambda: OFFLINE_NOW,
        job_id_factory=lambda: f"ingestion_demo_{next(ingestion_ids)}",
    )
    document_indexer = DocumentEmbeddingService(documents, vectors, embedder)
    coordinator = _coordinator(
        database,
        memory,
        citation,
        settings,
        llm_error=llm_error,
    )
    reports = ReportRepository(database)
    report_pipeline = ResearchReportPipeline(
        ReportAssembler(),
        reports,
        memory,
    )
    report_ids = count(1)
    task_ids = count(1)
    workflow = ResearchWorkflowService(
        provider=provider,
        ingestion=ingestion,
        market_data=market_data,
        documents=documents,
        document_indexer=document_indexer,
        memory=memory,
        fundamental_features=FundamentalFeatureOperator(),
        technical_features=TechnicalFeatureOperator(),
        coordinator=coordinator,
        report_pipeline=report_pipeline,
        model_name=settings.openai.model_default,
        clock=lambda: OFFLINE_NOW,
        report_id_factory=lambda: f"rep_demo_{next(report_ids)}",
        task_id_factory=lambda: f"task_demo_{next(task_ids)}",
    )
    job_ids = count(1)
    services = ApiServices(
        report_tasks=InProcessReportTaskService(
            workflow,
            job_id_factory=lambda: f"job_demo_{next(job_ids)}",
        ),
        reports=reports,
        memory=memory,
        snapshots=EmptySnapshotQueryService(),
    )
    return create_app(settings=settings, services=services)


def _provider() -> FakeProviderAdapter:
    return FakeProviderAdapter(
        instruments=[
            {
                "asset_id": str(OFFLINE_ASSET_ID),
                "market": "US",
                "exchange_code": "NASDAQ",
                "company_name": "Offline Example Corp.",
                "currency": "USD",
            }
        ],
        eod_bars=[
            {
                "asset_id": str(OFFLINE_ASSET_ID),
                "market": "US",
                "trade_date": OFFLINE_NOW.date().isoformat(),
                "open": 208.0,
                "high": 212.0,
                "low": 207.0,
                "close": 210.5,
                "volume": 1_000_000,
            }
        ],
        documents=[_document_record()],
    )


def _document_record() -> JsonObject:
    return {
        "document_id": OFFLINE_DOCUMENT_ID,
        "asset_id": str(OFFLINE_ASSET_ID),
        "market": "US",
        "doc_type": "filing",
        "title": "Offline Form 10-Q",
        "raw_text": OFFLINE_DOCUMENT_TEXT,
        "source_url": "https://example.test/offline-10q",
        "publish_ts": OFFLINE_NOW.isoformat(),
    }


def _coordinator(
    database: DuckDBDatabase,
    memory: MemoryService,
    citation: SourceReference,
    settings: AppSettings,
    *,
    llm_error: LLMProviderError | None,
) -> ResearchCoordinator:
    responses = _agent_responses(citation)
    prompt_root = Path(__file__).resolve().parents[2] / "config" / "prompts"
    prompts = PromptLoader(prompt_root)
    run_logger = AgentRunRepository(database)
    cache = LLMCacheRepository(database)
    agent_classes: dict[AgentName, type[BaseAgent]] = {
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
        agent_name: agent_class(
            LLMGateway(
                cache,
                settings.openai,
                provider=FakeLLMProvider(
                    responses[agent_name],
                    error=llm_error,
                ),
            ),
            memory,
            prompts,
            run_logger,
            clock=lambda: OFFLINE_NOW,
        )
        for agent_name, agent_class in agent_classes.items()
    }
    return ResearchCoordinator(registry)


def _agent_responses(
    source: SourceReference,
) -> dict[AgentName, JsonObject]:
    citation = cast(
        list[JsonValue],
        [source.model_dump(mode="json")],
    )
    return {
        AgentName.FUNDAMENTAL_ANALYST: {
            "agent_name": "fundamental_analyst",
            "status": "ok",
            "analysis": {
                "quality_score": 0.8,
                "growth_score": 0.7,
                "valuation_score": 0.5,
                "key_points": ["Revenue evidence was reviewed."],
                "risk_points": ["Valuation evidence remains limited."],
                "uncertainties": ["Historical fundamentals were unavailable."],
                "supporting_citations": citation,
            },
        },
        AgentName.TECHNICAL_TEXT_ANALYST: _analyst_response(
            AgentName.TECHNICAL_TEXT_ANALYST,
            "The latest normalized close was available.",
            "Long technical history was unavailable.",
            citation,
        ),
        AgentName.SENTIMENT_ANALYST: _analyst_response(
            AgentName.SENTIMENT_ANALYST,
            "The supplied document tone was stable.",
            "The sentiment sample was limited.",
            citation,
        ),
        AgentName.NEWS_EVENT_ANALYST: _analyst_response(
            AgentName.NEWS_EVENT_ANALYST,
            "No adverse event was stated in the supplied filing.",
            "Later events may not be represented.",
            citation,
        ),
        AgentName.RESEARCH_MANAGER: {
            "agent_name": "research_manager",
            "status": "ok",
            "analysis": {
                "summary_points": [
                    "Growth remained positive while valuation risk required caution."
                ],
                "conflicts": [
                    "Constructive operating evidence was offset by limited history."
                ],
                "uncertainties": ["Only fixed offline evidence was supplied."],
                "supporting_citations": citation,
            },
        },
        AgentName.BULL_MANAGER: {
            "bull_thesis": ["Growth remained positive."],
            "conditions_required": ["Demand remains stable."],
            "invalidators": ["Revenue contracts."],
            "confidence": 0.6,
        },
        AgentName.BEAR_MANAGER: {
            "bear_thesis": ["Valuation remained elevated."],
            "conditions_required": ["Growth slows."],
            "invalidators": ["Growth accelerates."],
            "confidence": 0.5,
        },
        AgentName.RISK_MANAGER: {
            "confirmed_risks": ["Valuation remained elevated."],
            "scenario_risks": ["Demand may slow."],
            "watch_items": ["Revenue growth requires monitoring."],
            "narrative_risk_score": 0.5,
        },
    }


def _analyst_response(
    agent_name: AgentName,
    key_point: str,
    risk_point: str,
    citation: list[JsonValue],
) -> JsonObject:
    return {
        "agent_name": agent_name.value,
        "status": "ok",
        "analysis": {
            "key_points": [key_point],
            "risk_points": [risk_point],
            "uncertainties": ["Evidence coverage was limited."],
            "supporting_citations": citation,
        },
    }
