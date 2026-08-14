"""Offline SEC EDGAR Adapter-to-DuckDB integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import Request

import pytest

from src.adapters import SECEDGARAdapter
from src.adapters.http import ProviderHTTPResponse
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
    RawTextStore,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019326000001/aapl-20260627.htm"
)


class _SECFixtureTransport:
    """Serve fixed official-format HTTP responses."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def send(
        self,
        request: Request,
        timeout: float,
    ) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request.full_url)
        if request.full_url == SUBMISSIONS_URL:
            body = """
            {
              "name": "Apple Inc.",
              "tickers": ["AAPL"],
              "exchanges": ["Nasdaq"],
              "filings": {"recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "filingDate": ["2026-08-01"],
                "acceptanceDateTime": ["20260801123000"],
                "form": ["10-Q"],
                "primaryDocument": ["aapl-20260627.htm"]
              }}
            }
            """
        elif request.full_url == FILING_URL:
            body = (
                "<html><body><h1>Apple 10-Q</h1>"
                "<p>Revenue disclosed in filing.</p></body></html>"
            )
        else:
            raise AssertionError(f"unexpected fixture URL: {request.full_url}")
        return ProviderHTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=body.encode(),
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
            chunk_size=100,
            overlap=10,
            embedding_model="fixture-embedding",
            embedding_dim=3,
            faiss_namespace="docs_fixture",
        ),
        clock=lambda: NOW,
        job_id_factory=lambda: next(job_ids),
    )


def test_sec_adapter_ingests_traceable_documents_idempotently(
    tmp_path: Path,
) -> None:
    """Official-format responses normalize and upsert without network."""

    database = DuckDBDatabase(tmp_path / "sec.duckdb")
    database.bootstrap()
    transport = _SECFixtureTransport()
    adapter = SECEDGARAdapter(
        user_agent="DeepInsight test@example.com",
        cik_by_asset={"US:AAPL": "320193"},
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    service = _service(
        database,
        tmp_path / "raw",
        iter(["sec-job-1", "sec-job-2"]),
    )
    request = IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=("US:AAPL",),
        document_start_date=date(2026, 7, 1),
        document_end_date=date(2026, 8, 2),
    )

    first = service.run(adapter, request)
    second = service.run(adapter, request)

    assert first.status == TaskStatus.COMPLETED.value
    assert first.rows_written == 4
    assert second.rows_written == first.rows_written
    instrument = InstrumentRepository(database).get(AssetId("US:AAPL"))
    assert instrument is not None
    assert instrument.source_primary == "sec_edgar"

    documents = DocumentRepository(database)
    document = documents.get_document("sec-0000320193-000032019326000001")
    assert document is not None
    assert document.source_id == "sec_edgar"
    assert document.source_url == FILING_URL
    assert document.publish_ts is not None
    assert document.metadata_json is not None
    assert document.metadata_json["provider_locator"] == (
        "sec:accession:0000320193-26-000001"
    )
    assert document.raw_text_path is not None
    assert Path(document.raw_text_path).read_text(encoding="utf-8") == (
        "Apple 10-Q Revenue disclosed in filing."
    )
    chunks = documents.list_chunks(document.document_id)
    assert len(chunks) == 1
    assert chunks[0].document_id == document.document_id

    with database.connection() as connection:
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM instruments),
                (SELECT count(*) FROM text_documents),
                (SELECT count(*) FROM document_chunks),
                (SELECT count(*) FROM corporate_events),
                (SELECT count(*) FROM ingestion_jobs)
            """).fetchone()
    assert counts == (1, 1, 1, 1, 2)
    assert transport.requests == [
        SUBMISSIONS_URL,
        FILING_URL,
        FILING_URL,
    ]
