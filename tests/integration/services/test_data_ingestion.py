"""Offline Adapter-to-DuckDB ingestion integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.adapters import FakeProviderAdapter
from src.models.enums import IngestionJobType, TaskStatus
from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
)
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    IngestionRequest,
    IngestionRunError,
    RawTextStore,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
TARGET_DATE = date(2026, 7, 30)


def _provider(*, fail_after_first_instrument: bool = False) -> FakeProviderAdapter:
    return FakeProviderAdapter(
        instruments=[
            {
                "asset_id": "US:AAPL",
                "market": "US",
                "exchange_code": "NASDAQ",
                "company_name": "Apple Inc.",
                "currency": "USD",
            },
            {
                "asset_id": "US:MSFT",
                "market": "US",
                "exchange_code": "NASDAQ",
                "company_name": "Microsoft Corp.",
                "currency": "USD",
            },
        ],
        eod_bars=[
            {
                "asset_id": "US:AAPL",
                "market": "US",
                "trade_date": "2026-07-30",
                "open": 208.0,
                "high": 212.0,
                "low": 207.0,
                "close": 210.5,
                "volume": 1_000_000,
            }
        ],
        documents=[
            {
                "document_id": "doc-aapl-10q",
                "asset_id": "US:AAPL",
                "market": "US",
                "doc_type": "filing",
                "title": "Apple Form 10-Q",
                "raw_text": "abcdefghij",
                "source_url": "https://www.sec.gov/example",
                "publish_ts": "2026-07-30T20:00:00Z",
            }
        ],
        fail_stream="instruments" if fail_after_first_instrument else None,
        fail_after=1,
    )


def _service(
    database: DuckDBDatabase,
    raw_root: Path,
    job_ids: Iterator[str],
) -> DataIngestionService:
    return DataIngestionService(
        instruments=InstrumentRepository(database),
        market_data=MarketDataRepository(database),
        documents=DocumentRepository(database),
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(raw_root),
        chunker=DocumentChunker(
            chunk_size=6,
            overlap=2,
            embedding_model="fixture-embedding",
            embedding_dim=3,
            faiss_namespace="docs_fixture",
        ),
        clock=lambda: NOW,
        job_id_factory=lambda: next(job_ids),
    )


def _request() -> IngestionRequest:
    return IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=("US:AAPL",),
        target_date=TARGET_DATE,
        document_start_date=TARGET_DATE,
        document_end_date=TARGET_DATE,
    )


def test_fake_provider_ingests_normalized_records_idempotently(
    tmp_path: Path,
) -> None:
    """The offline provider completes the full normalized persistence path."""

    database = DuckDBDatabase(tmp_path / "ingestion.duckdb")
    database.bootstrap()
    service = _service(database, tmp_path / "raw", iter(["job-1", "job-2"]))

    first = service.run(_provider(), _request())
    second = service.run(_provider(), _request())

    assert first.status == TaskStatus.COMPLETED.value
    assert first.rows_written == 7
    assert second.rows_written == first.rows_written

    instrument = InstrumentRepository(database).get(AssetId("US:AAPL"))
    bar = MarketDataRepository(database).get_eod_bar(
        AssetId("US:AAPL"),
        TARGET_DATE,
    )
    documents = DocumentRepository(database)
    document = documents.get_document("doc-aapl-10q")
    chunks = documents.list_chunks("doc-aapl-10q")

    assert instrument is not None
    assert instrument.source_primary == "fake"
    assert bar is not None
    assert bar.source_id == "fake"
    assert document is not None
    assert document.raw_text_path is not None
    assert Path(document.raw_text_path).read_text(encoding="utf-8") == "abcdefghij"
    assert [item.chunk_index for item in chunks] == [0, 1]
    assert all(
        item.metadata_json is not None
        and item.metadata_json["embedding_status"] == "pending"
        for item in chunks
    )

    with database.connection() as connection:
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM instruments),
                (SELECT count(*) FROM eod_bars),
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM document_chunks),
                (SELECT count(*) FROM corporate_events)
            """).fetchone()
    assert counts == (2, 1, 1, 2, 1)


def test_partial_provider_failure_records_failed_job_and_committed_rows(
    tmp_path: Path,
) -> None:
    """A stream interruption leaves an explicit failed audit record."""

    database = DuckDBDatabase(tmp_path / "failed.duckdb")
    database.bootstrap()
    jobs = IngestionJobRepository(database)
    service = _service(database, tmp_path / "raw", iter(["failed-job"]))

    with pytest.raises(IngestionRunError) as raised:
        service.run(
            _provider(fail_after_first_instrument=True),
            IngestionRequest(job_type=IngestionJobType.FULL),
        )

    assert raised.value.job_id == "failed-job"
    job = jobs.get("failed-job")
    assert job is not None
    assert job.status == TaskStatus.FAILED.value
    assert job.rows_written == 1
    assert job.finished_at is not None
    assert job.error_message is not None
    assert "configured failure" in job.error_message
    assert InstrumentRepository(database).get(AssetId("US:AAPL")) is not None
    assert InstrumentRepository(database).get(AssetId("US:MSFT")) is None


def test_invalid_provider_record_is_rejected_and_audited(tmp_path: Path) -> None:
    """Malformed provider data fails normalization and records the job error."""

    database = DuckDBDatabase(tmp_path / "invalid.duckdb")
    database.bootstrap()
    jobs = IngestionJobRepository(database)
    service = _service(database, tmp_path / "raw", iter(["invalid-job"]))
    provider = FakeProviderAdapter(
        eod_bars=[
            {
                "asset_id": "US:AAPL",
                "market": "US",
                "trade_date": "2026-07-30",
                "high": 100.0,
                "close": 101.0,
            }
        ]
    )

    with pytest.raises(IngestionRunError):
        service.run(provider, _request())

    job = jobs.get("invalid-job")
    assert job is not None
    assert job.status == TaskStatus.FAILED.value
    assert job.rows_written == 0
    assert job.error_message is not None
    assert "high" in job.error_message
    assert (
        MarketDataRepository(database).get_eod_bar(
            AssetId("US:AAPL"),
            TARGET_DATE,
        )
        is None
    )
