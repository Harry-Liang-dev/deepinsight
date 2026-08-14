"""Deterministic offline composition for local demos and end-to-end tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

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
)
from src.schemas import GenerateReportRequest, MemoryWriteRequest, SourceReference
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    DocumentEmbeddingService,
    FakeEmbeddingService,
    LLMGateway,
    LLMProviderCapabilities,
    LLMProviderError,
    LLMProviderResult,
    RawTextStore,
    ResearchDataBundleService,
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
    "This report contains research analysis only and does not issue a system "
    "recommendation or execution instruction. Risk review: Valuation remained "
    "elevated. Demand may slow."
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
    instruments = InstrumentRepository(database)
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
        instruments=instruments,
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
        data_bundle_builder=ResearchDataBundleService(
            instruments=instruments,
            market_data=market_data,
        ),
        dataset_version="offline_api_fixture_v1",
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
    settings: AppSettings,
    *,
    llm_error: LLMProviderError | None,
) -> ResearchCoordinator:
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
                provider=_OfflineAgentProvider(agent_name, error=llm_error),
            ),
            memory,
            prompts,
            run_logger,
            clock=lambda: OFFLINE_NOW,
        )
        for agent_name, agent_class in agent_classes.items()
    }
    return ResearchCoordinator(registry)


class _OfflineAgentProvider:
    """Build deterministic v2 Fake output from the role-local manifest."""

    provider_name = "fake"

    def __init__(
        self,
        agent_name: AgentName,
        *,
        error: LLMProviderError | None,
    ) -> None:
        self._agent_name = agent_name
        self._error = error

    @property
    def capabilities(self) -> LLMProviderCapabilities:
        """Expose the same offline capabilities as the standard Fake provider."""

        return LLMProviderCapabilities(
            structured_json=True,
            native_json_schema=True,
            remote_storage_enabled=False,
        )

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        response_schema: JsonObject | None = None,
        schema_name: str = "deepinsight_response",
    ) -> LLMProviderResult:
        """Return one role-correct response citing only manifest Evidence IDs."""

        del system_prompt, response_schema, schema_name
        if self._error is not None:
            raise self._error
        content = _agent_response(self._agent_name, input_payload)
        return LLMProviderResult(
            content=deepcopy(content),
            model=model,
            response_id=f"offline-{self._agent_name.value}",
        )


def _agent_response(agent_name: AgentName, input_payload: JsonObject) -> JsonObject:
    is_analyst = agent_name in {
        AgentName.FUNDAMENTAL_ANALYST,
        AgentName.TECHNICAL_TEXT_ANALYST,
        AgentName.SENTIMENT_ANALYST,
        AgentName.NEWS_EVENT_ANALYST,
    }
    if is_analyst:
        evidence_id, evidence_text = _first_manifest_evidence(input_payload)
        provenance_key = "evidence_ids"
        provenance_id = evidence_id
    else:
        provenance_id, evidence_text = _first_upstream_claim(input_payload)
        provenance_key = "upstream_claim_ids"

    def binding(path: str, text: str) -> JsonObject:
        return {
            "claim_path": path,
            "claim_text": text,
            "numeric_literals": [],
            provenance_key: [provenance_id],
        }

    if agent_name is AgentName.FUNDAMENTAL_ANALYST:
        return {
            "agent_name": "fundamental_analyst",
            "status": "ok",
            "analysis": {
                "quality_score": 0.8,
                "growth_score": 0.7,
                "valuation_score": 0.5,
                "facts": [evidence_text],
                "key_points": ["The supplied evidence supports a bounded review."],
                "risk_points": ["Evidence coverage remains limited."],
                "uncertainties": ["Historical fundamentals were unavailable."],
                "claim_evidence": [
                    binding("analysis.facts[0]", evidence_text),
                    binding(
                        "analysis.key_points[0]",
                        "The supplied evidence supports a bounded review.",
                    ),
                    binding(
                        "analysis.risk_points[0]", "Evidence coverage remains limited."
                    ),
                ],
            },
        }
    if agent_name is AgentName.SENTIMENT_ANALYST:
        return {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "claims": [
                    binding("analysis.facts[0]", evidence_text),
                    binding(
                        "analysis.risk_points[0]",
                        "The supplied sentiment sample has limited coverage.",
                    ),
                ],
                "uncertainties": ["Broader sentiment coverage was unavailable."],
            },
        }
    if agent_name is AgentName.TECHNICAL_TEXT_ANALYST:
        return {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "claims": [
                    binding("analysis.facts[0]", evidence_text),
                    binding(
                        "analysis.risk_points[0]",
                        "Technical evidence coverage remains limited.",
                    ),
                ],
                "uncertainties": ["Long technical history was unavailable."],
            },
        }
    if agent_name is AgentName.NEWS_EVENT_ANALYST:
        return {
            "agent_name": agent_name.value,
            "status": "ok",
            "analysis": {
                "claims": [
                    binding("analysis.facts[0]", evidence_text),
                    binding(
                        "analysis.risk_points[0]",
                        "Event evidence coverage remains limited.",
                    ),
                ],
                "uncertainties": ["Later events may not be represented."],
            },
        }
    if agent_name is AgentName.RESEARCH_MANAGER:
        summary = "Growth remained positive while valuation risk required caution."
        conflict = "Constructive operating evidence was offset by limited history."
        return {
            "agent_name": "research_manager",
            "status": "ok",
            "analysis": {
                "claims": [
                    binding("analysis.summary_points[0]", summary),
                    binding("analysis.conflicts[0]", conflict),
                ],
                "uncertainties": ["Only fixed offline evidence was supplied."],
            },
        }
    if agent_name is AgentName.BULL_MANAGER:
        return {
            "claims": [
                binding("bull_thesis[0]", evidence_text),
                binding("conditions_required[0]", "Demand remains stable."),
                binding("invalidators[0]", "Revenue contracts."),
            ],
            "confidence": 0.6,
        }
    if agent_name is AgentName.BEAR_MANAGER:
        return {
            "claims": [
                binding("bear_thesis[0]", evidence_text),
                binding("conditions_required[0]", "Growth slows."),
                binding("invalidators[0]", "Growth accelerates."),
            ],
            "confidence": 0.5,
        }
    if agent_name is AgentName.RISK_MANAGER:
        confirmed_risk = "Valuation remained elevated."
        return {
            "claims": [
                binding("confirmed_risks[0]", confirmed_risk),
                binding("scenario_risks[0]", "Demand may slow."),
                binding("watch_items[0]", "Revenue growth requires monitoring."),
            ],
            "narrative_risk_score": 0.5,
            "uncertainties": [],
        }
    raise RuntimeError("offline Agent role is unsupported")


def _first_manifest_evidence(input_payload: JsonObject) -> tuple[str, str]:
    context = input_payload.get("input_context")
    if not isinstance(context, dict):
        raise RuntimeError("offline Agent input context is unavailable")
    manifest = context.get("role_evidence_manifest")
    if not isinstance(manifest, dict):
        raise RuntimeError("offline role Evidence manifest is unavailable")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("offline role Evidence manifest is empty")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise RuntimeError("offline role Evidence entry is invalid")
    evidence_id = entry.get("evidence_id")
    description = entry.get("short_description")
    if not isinstance(evidence_id, str) or not isinstance(description, str):
        raise RuntimeError("offline role Evidence entry is incomplete")
    claim_text = description.split(": ", 1)[-1]
    return evidence_id, claim_text


def _first_upstream_claim(input_payload: JsonObject) -> tuple[str, str]:
    contract = input_payload.get("research_contract")
    if not isinstance(contract, dict):
        raise RuntimeError("offline Manager research contract is unavailable")
    claims = contract.get("validated_upstream_claims")
    if not isinstance(claims, list) or not claims:
        raise RuntimeError("offline Manager upstream Claims are unavailable")
    claim = claims[0]
    if not isinstance(claim, dict):
        raise RuntimeError("offline Manager upstream Claim is invalid")
    claim_id = claim.get("claim_id")
    claim_text = claim.get("claim_text")
    if not isinstance(claim_id, str) or not isinstance(claim_text, str):
        raise RuntimeError("offline Manager upstream Claim is incomplete")
    return claim_id, claim_text


def _analyst_response(
    agent_name: AgentName,
    evidence_id: str,
    evidence_text: str,
) -> JsonObject:
    risk_text = "Evidence coverage remains limited."
    return {
        "agent_name": agent_name.value,
        "status": "ok",
        "analysis": {
            "facts": [evidence_text],
            "key_points": ["The supplied evidence supports a bounded review."],
            "risk_points": [risk_text],
            "uncertainties": ["Evidence coverage was limited."],
            "claim_evidence": [
                {
                    "claim_path": "analysis.facts[0]",
                    "claim_text": evidence_text,
                    "numeric_literals": [],
                    "evidence_ids": [evidence_id],
                    "derivation_type": "direct_evidence",
                },
                {
                    "claim_path": "analysis.key_points[0]",
                    "claim_text": "The supplied evidence supports a bounded review.",
                    "numeric_literals": [],
                    "evidence_ids": [evidence_id],
                    "derivation_type": "direct_evidence",
                },
                {
                    "claim_path": "analysis.risk_points[0]",
                    "claim_text": risk_text,
                    "numeric_literals": [],
                    "evidence_ids": [evidence_id],
                    "derivation_type": "direct_evidence",
                },
            ],
        },
    }
