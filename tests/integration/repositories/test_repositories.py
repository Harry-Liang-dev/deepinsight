"""CRUD and consistency tests for the Phase One Repository layer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.models.enums import (
    AgentName,
    DocumentType,
    EventSeverity,
    IngestionJobType,
    Market,
    MarketScope,
    MemoryLevel,
    ReportMarketScope,
    ReportType,
    TaskStatus,
)
from src.models.identifiers import AssetId
from src.repositories import (
    AgentRunRecord,
    AgentRunRepository,
    DocumentRepository,
    DuckDBDatabase,
    IngestionJobRecord,
    IngestionJobRepository,
    InstrumentRepository,
    LLMCacheRecord,
    LLMCacheRepository,
    MarketDataRepository,
    MemoryItemRecord,
    MemoryItemRepository,
    ReportRepository,
    RepositoryError,
    SourceRegistryRecord,
    SourceRegistryRepository,
)
from src.schemas.common import SourceReference
from src.schemas.documents import DocumentChunkRecord, TextDocumentRecord
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    FundamentalRecord,
    InstrumentRecord,
    MacroObservationRecord,
)
from src.schemas.reports import ReportSection, ResearchReport

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 31, 9, 30)
ASSET_ID = AssetId("US:AAPL")


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return an isolated initialized database."""

    instance = DuckDBDatabase(tmp_path / "repository.duckdb")
    instance.bootstrap()
    return instance


def test_source_instrument_and_market_data_crud(
    database: DuckDBDatabase,
) -> None:
    """Structured repositories round-trip normalized domain records."""

    sources = SourceRegistryRepository(database)
    instruments = InstrumentRepository(database)
    market_data = MarketDataRepository(database)

    source = SourceRegistryRecord(
        source_id="sec_edgar",
        source_name="SEC EDGAR",
        market_scope=MarketScope.US,
        source_type="filing",
        auth_mode="internal",
    )
    sources.upsert(source)
    stored_source = sources.get(source.source_id)
    assert stored_source is not None
    assert stored_source.source_name == "SEC EDGAR"
    assert stored_source.created_at is not None

    instrument = InstrumentRecord(
        asset_id=ASSET_ID,
        market=Market.US,
        ticker="AAPL",
        exchange_code="NASDAQ",
        company_name="Apple Inc.",
        currency="USD",
        source_primary="sec_edgar",
        p2_factor_universe="must-not-be-used",
    )
    instruments.upsert(instrument)
    instruments.upsert(instrument.model_copy(update={"company_name": "Apple"}))
    stored_instrument = instruments.get(ASSET_ID)
    assert stored_instrument is not None
    assert stored_instrument.company_name == "Apple"
    assert stored_instrument.p2_factor_universe is None

    bar = EodBarRecord(
        asset_id=ASSET_ID,
        trade_date=date(2026, 7, 30),
        close=210.5,
        volume=1_000_000,
        source_id="sec_edgar",
        ingestion_ts=NOW,
    )
    market_data.upsert_eod_bar(bar)
    assert market_data.get_eod_bar(ASSET_ID, bar.trade_date) == bar

    fundamental = FundamentalRecord(
        asset_id=ASSET_ID,
        fiscal_period_end=date(2026, 6, 30),
        report_type="quarterly",
        revenue=95_000.0,
        net_income=24_000.0,
        source_id="sec_edgar",
        ingestion_ts=NOW,
    )
    market_data.upsert_fundamental(fundamental)
    assert (
        market_data.get_fundamental(
            ASSET_ID,
            fundamental.fiscal_period_end,
            fundamental.report_type,
        )
        == fundamental
    )

    macro = MacroObservationRecord(
        series_key="FEDFUNDS",
        region_code=MarketScope.US,
        observation_date=date(2026, 7, 1),
        indicator_name="Federal Funds Rate",
        value=4.25,
        unit="percent",
        source_id="fred",
        ingestion_ts=NOW,
    )
    market_data.upsert_macro_observation(macro)
    assert (
        market_data.get_macro_observation(
            macro.series_key,
            macro.observation_date,
        )
        == macro
    )

    event = CorporateEventRecord(
        event_id="event-1",
        asset_id=ASSET_ID,
        market=Market.US,
        event_date=NOW,
        event_type="earnings",
        severity=EventSeverity.HIGH,
        title="Quarterly earnings",
        source_id="sec_edgar",
        tags_json={"topic": "earnings"},
    )
    market_data.upsert_corporate_event(event)
    assert market_data.get_corporate_event(event.event_id) == event
    assert instruments.get(AssetId("US:MSFT")) is None


def test_eod_repository_applies_date_and_ingestion_cutoffs(
    database: DuckDBDatabase,
) -> None:
    """Point-in-time reads exclude out-of-window and future-ingested bars."""

    repository = MarketDataRepository(database)
    first_ingestion = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    second_ingestion = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    for trade_date, ingestion_ts in (
        (date(2026, 8, 4), first_ingestion),
        (date(2026, 8, 5), second_ingestion),
    ):
        repository.upsert_eod_bar(
            EodBarRecord(
                asset_id=ASSET_ID,
                trade_date=trade_date,
                close=200.0,
                source_id="alpaca_market_data",
                ingestion_ts=ingestion_ts,
            )
        )

    visible = repository.list_eod_bars(
        ASSET_ID,
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 5),
        ingested_as_of=first_ingestion,
        limit=10,
    )

    assert [bar.trade_date for bar in visible] == [date(2026, 8, 4)]
    with pytest.raises(ValueError, match="cannot precede"):
        repository.list_eod_bars(
            ASSET_ID,
            start_date=date(2026, 8, 6),
            end_date=date(2026, 8, 5),
        )


def test_document_repository_round_trip(database: DuckDBDatabase) -> None:
    """Document metadata and ordered chunk mappings round-trip."""

    repository = DocumentRepository(database)
    document = TextDocumentRecord(
        document_id="doc-1",
        asset_id=ASSET_ID,
        market=MarketScope.US,
        doc_type=DocumentType.FILING,
        title="10-Q",
        language="en",
        source_id="sec_edgar",
        metadata_json={"form": "10-Q"},
        created_at=NOW,
    )
    repository.upsert_document(document)

    chunk_two = DocumentChunkRecord(
        chunk_id="chunk-2",
        document_id=document.document_id,
        asset_id=ASSET_ID,
        market=MarketScope.US,
        chunk_index=2,
        chunk_text="Second chunk",
        embedding_model="embedding-model",
        embedding_dim=3,
        faiss_namespace="docs-v1",
        faiss_vector_id=2,
        created_at=NOW,
    )
    chunk_one = chunk_two.model_copy(
        update={
            "chunk_id": "chunk-1",
            "chunk_index": 1,
            "chunk_text": "First chunk",
            "faiss_vector_id": 1,
        }
    )
    repository.upsert_chunk(chunk_two)
    repository.upsert_chunk(chunk_one)

    assert repository.get_document(document.document_id) == document
    assert [item.chunk_id for item in repository.list_chunks(document.document_id)] == [
        "chunk-1",
        "chunk-2",
    ]


def test_memory_repository_crud_and_duplicate_error(
    database: DuckDBDatabase,
) -> None:
    """Memory sidecars round-trip and duplicate identifiers are rejected."""

    repository = MemoryItemRepository(database)
    record = MemoryItemRecord(
        memory_id="memory-1",
        memory_level=MemoryLevel.L2,
        namespace_key="US:AAPL",
        asset_id=ASSET_ID,
        effective_ts=NOW,
        memory_type="issuer_event",
        importance_score=0.9,
        summary_text="Guidance changed.",
        source_ref=SourceReference(document_id="doc-1"),
        embedding_model="embedding-model",
        embedding_dim=3,
        faiss_namespace="memory-L2-v1",
        faiss_vector_id=7,
        created_by="system",
    )

    repository.insert(record)
    stored = repository.get(record.memory_id)
    assert stored is not None
    assert stored.source_ref == record.source_ref
    assert stored.created_at is not None

    with pytest.raises(RepositoryError):
        repository.insert(record)


def test_run_cache_and_ingestion_job_crud(
    database: DuckDBDatabase,
) -> None:
    """Operational repositories persist and update explicit lifecycle state."""

    run_repository = AgentRunRepository(database)
    run = AgentRunRecord(
        run_id="run-1",
        agent_name=AgentName.FUNDAMENTAL_ANALYST,
        agent_role="analyst",
        model_name="replaceable-model",
        prompt_template_ver="v1",
        input_payload={"asset_id": "US:AAPL"},
        status="running",
        started_at=NOW,
    )
    run_repository.save(run)
    run_repository.save(
        run.model_copy(
            update={
                "status": "completed",
                "output_payload": {"quality_score": 0.8},
                "finished_at": NOW,
            }
        )
    )
    stored_run = run_repository.get(run.run_id)
    assert stored_run is not None
    assert stored_run.status == "completed"
    assert stored_run.output_payload == {"quality_score": 0.8}

    cache_repository = LLMCacheRepository(database)
    cache = LLMCacheRecord(
        cache_key="cache-1",
        provider="provider",
        model_name="replaceable-model",
        prompt_hash="hash-1",
        response={"result": "ok"},
    )
    cache_repository.put(cache)
    assert cache_repository.get(cache.cache_key) is not None
    assert cache_repository.get("missing-cache") is None

    jobs = IngestionJobRepository(database)
    job = IngestionJobRecord(
        job_id="job-1",
        source_id="sec_edgar",
        job_type=IngestionJobType.INCREMENTAL,
        market_scope=MarketScope.US,
        status="running",
        target_date=date(2026, 7, 30),
    )
    jobs.save(job)
    jobs.save(job.model_copy(update={"status": "completed", "rows_written": 42}))
    stored_job = jobs.get(job.job_id)
    assert stored_job is not None
    assert stored_job.status == "completed"
    assert stored_job.rows_written == 42


def test_report_and_sections_are_saved_atomically(
    database: DuckDBDatabase,
) -> None:
    """A section failure rolls back both report and section changes."""

    repository = ReportRepository(database)
    citation = SourceReference(document_id="doc-1", excerpt_ref="chunk-1")
    section = ReportSection(
        report_id="report-1",
        section_name="executive_view",
        section_order=1,
        section_markdown="Original section",
        citations=[citation],
    )
    report = ResearchReport(
        report_id="report-1",
        report_date=date(2026, 7, 31),
        market_scope=ReportMarketScope.US,
        report_type=ReportType.SINGLE_ASSET,
        asset_id=ASSET_ID,
        title="Original report",
        final_recommendation="Narrative conclusion",
        report_markdown="# Original report",
        report_json={"executive_view": "Original section"},
        source_trace=[citation],
        sections=[section],
        status=TaskStatus.COMPLETED,
        created_at=NOW,
    )
    repository.save(report)
    assert repository.get(report.report_id) == report

    duplicate_section = section.model_copy(
        update={"section_markdown": "Duplicate primary key"}
    )
    invalid_update = report.model_copy(
        update={
            "title": "Must be rolled back",
            "sections": [section, duplicate_section],
        }
    )
    with pytest.raises(RepositoryError):
        repository.save(invalid_update)

    assert repository.get(report.report_id) == report
