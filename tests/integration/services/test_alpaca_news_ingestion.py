"""Offline Alpaca News to documents/chunks/events/DuckDB integration."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import Request

import pytest

from src.adapters import AlpacaAdapter
from src.adapters.http import ProviderHTTPResponse
from src.models.enums import IngestionJobType
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
NOW = datetime(2026, 8, 10, 20, tzinfo=UTC)


class _Transport:
    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del request, timeout
        return ProviderHTTPResponse(
            200,
            {},
            json.dumps(
                {
                    "news": [
                        {
                            "id": 1,
                            "headline": "Attributed headline",
                            "summary": "Attributed summary for offline ingestion.",
                            "author": "Reporter",
                            "created_at": "2026-08-09T12:00:00Z",
                            "updated_at": "2026-08-09T13:00:00Z",
                            "url": "https://publisher.test/1",
                            "source": "Benzinga",
                            "symbols": ["AAPL"],
                        }
                    ],
                    "next_page_token": None,
                }
            ).encode(),
        )


def test_news_becomes_canonical_evidence_document_chunk_and_event(
    tmp_path: Path,
) -> None:
    database = DuckDBDatabase(tmp_path / "news.duckdb")
    database.bootstrap()
    service = DataIngestionService(
        instruments=InstrumentRepository(database),
        market_data=MarketDataRepository(database),
        documents=DocumentRepository(database),
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(tmp_path / "raw"),
        chunker=DocumentChunker(
            chunk_size=100,
            overlap=10,
            embedding_model="fixture",
            embedding_dim=3,
            faiss_namespace="news_fixture",
        ),
        clock=lambda: NOW,
        job_id_factory=lambda: "news-job",
    )
    adapter = AlpacaAdapter(
        api_key_id="fixture-id",
        api_secret_key="fixture-secret",
        http_transport=_Transport(),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    job = service.run(
        adapter,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=("US:AAPL",),
            document_start_date=date(2026, 8, 9),
            document_end_date=date(2026, 8, 9),
        ),
    )

    market = MarketDataRepository(database)
    news = market.list_news_evidence(
        AssetId("US:AAPL"),
        start_at=datetime(2026, 8, 9, tzinfo=UTC),
        as_of=NOW,
    )
    events = market.list_corporate_events(
        AssetId("US:AAPL"),
        start_at=datetime(2026, 8, 9, tzinfo=UTC),
        as_of=NOW,
    )
    documents = DocumentRepository(database)
    assert job.rows_written == 4
    assert [record.news_id for record in news] == ["1"]
    assert [record.event_type for record in events] == ["other"]
    assert documents.get_document("alpaca-news-1") is not None
    assert len(documents.list_chunks("alpaca-news-1")) == 1
