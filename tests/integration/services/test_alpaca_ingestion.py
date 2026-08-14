"""Offline Alpaca Adapter-to-DuckDB EOD ingestion tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import Request

import pytest

from src.adapters import AlpacaAdapter
from src.adapters.http import ProviderHTTPResponse
from src.models.enums import IngestionJobType, MarketScope, TaskStatus
from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
    SourceRegistryRecord,
    SourceRegistryRepository,
)
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    IngestionRequest,
    RawTextStore,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


class _MockHTTPTransport:
    """Return fixed official-format responses without network access."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies = bodies
        self.requests: list[Request] = []

    def send(
        self,
        request: Request,
        timeout: float,
    ) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request)
        return ProviderHTTPResponse(
            status_code=200,
            headers={},
            body=self._bodies.pop(0).encode(),
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


def _request(target_date: date) -> IngestionRequest:
    return IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=("US:AAPL",),
        target_date=target_date,
    )


def test_alpaca_daily_bars_normalize_and_upsert_idempotently(
    tmp_path: Path,
) -> None:
    """Official-format bars should traverse normalization into DuckDB."""

    database = DuckDBDatabase(tmp_path / "alpaca.duckdb")
    database.bootstrap()
    SourceRegistryRepository(database).upsert(
        SourceRegistryRecord(
            source_id="alpaca_market_data",
            source_name="Alpaca Market Data",
            market_scope=MarketScope.US,
            source_type="market",
            auth_mode="api_key",
            base_url="https://data.alpaca.markets",
            notes="Historical 1Day bars; IEX feed; raw adjustment.",
        )
    )
    transport = _MockHTTPTransport(
        [
            """
            {
              "bars": {"AAPL": [{
                "t": "2026-08-03T04:00:00Z",
                "o": 208.1, "h": 211.2, "l": 207.5, "c": 210.4,
                "v": 123456, "vw": 209.9
              }]},
              "next_page_token": null
            }
            """,
            """
            {
              "bars": {"AAPL": [{
                "t": "2026-08-04T04:00:00Z",
                "o": 210.5, "h": 213.0, "l": 209.8, "c": 212.2,
                "v": 234567, "vw": 211.7
              }]},
              "next_page_token": null
            }
            """,
            """
            {
              "bars": {"AAPL": [{
                "t": "2026-08-04T04:00:00Z",
                "o": 210.5, "h": 213.0, "l": 209.8, "c": 212.3,
                "v": 234568, "vw": 211.8
              }]},
              "next_page_token": null
            }
            """,
        ]
    )
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    service = _service(
        database,
        tmp_path / "raw",
        iter(["alpaca-job-1", "alpaca-job-2", "alpaca-job-3"]),
    )

    first = service.run(adapter, _request(date(2026, 8, 3)))
    second = service.run(adapter, _request(date(2026, 8, 4)))
    replay = service.run(adapter, _request(date(2026, 8, 4)))

    assert first.status == TaskStatus.COMPLETED.value
    assert second.status == TaskStatus.COMPLETED.value
    assert replay.status == TaskStatus.COMPLETED.value
    assert (first.rows_written, second.rows_written, replay.rows_written) == (1, 1, 1)

    market_data = MarketDataRepository(database)
    bars = market_data.list_eod_bars(
        AssetId("US:AAPL"),
        end_date=date(2026, 8, 4),
        limit=10,
    )
    assert [bar.trade_date for bar in bars] == [
        date(2026, 8, 3),
        date(2026, 8, 4),
    ]
    assert bars[0].source_id == "alpaca_market_data"
    assert bars[0].adj_close is None
    assert bars[0].turnover is None
    assert bars[1].close == 212.3
    assert bars[1].volume == 234568

    source = SourceRegistryRepository(database).get("alpaca_market_data")
    assert source is not None
    assert source.base_url == "https://data.alpaca.markets"
    with database.connection() as connection:
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM eod_bars),
                (SELECT count(*) FROM ingestion_jobs)
            """).fetchone()
    assert counts == (2, 3)
    assert len(transport.requests) == 3


def test_alpaca_range_uses_one_audited_ingestion_job(
    tmp_path: Path,
) -> None:
    """A bounded live baseline range should traverse the ingestion service."""

    database = DuckDBDatabase(tmp_path / "alpaca-range.duckdb")
    database.bootstrap()
    transport = _MockHTTPTransport(["""
            {
              "bars": {"AAPL": [
                {
                  "t": "2026-08-03T04:00:00Z",
                  "o": 208.1, "h": 211.2, "l": 207.5, "c": 210.4,
                  "v": 123456, "vw": 209.9
                },
                {
                  "t": "2026-08-04T04:00:00Z",
                  "o": 210.5, "h": 213.0, "l": 209.8, "c": 212.2,
                  "v": 234567, "vw": 211.7
                }
              ]},
              "next_page_token": null
            }
            """])
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    service = _service(
        database,
        tmp_path / "raw",
        iter(["alpaca-range-job"]),
    )

    job = service.run(
        adapter,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=("US:AAPL",),
            eod_start_date=date(2026, 8, 3),
            eod_end_date=date(2026, 8, 4),
        ),
    )

    assert job.job_id == "alpaca-range-job"
    assert job.target_date == date(2026, 8, 4)
    assert job.rows_written == 2
    assert len(transport.requests) == 1
    bars = MarketDataRepository(database).list_eod_bars(
        AssetId("US:AAPL"),
        end_date=date(2026, 8, 4),
        limit=10,
    )
    assert [bar.trade_date for bar in bars] == [
        date(2026, 8, 3),
        date(2026, 8, 4),
    ]
