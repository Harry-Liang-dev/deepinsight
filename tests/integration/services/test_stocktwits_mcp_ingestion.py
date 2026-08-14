"""Offline Stocktwits MCP Provider-to-Bundle integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.adapters import FakeMCPTransport, StocktwitsSentimentProvider
from src.models.enums import IngestionJobType, Market, TaskStatus
from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
)
from src.schemas.market_data import InstrumentRecord
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    ResearchDataBundleRequest,
)
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    IngestionRequest,
    RawTextStore,
    ResearchDataBundleService,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 10, 22, tzinfo=UTC)


def _provider() -> StocktwitsSentimentProvider:
    results: dict[str, dict[str, object]] = {
        "get_sentiment": {
            "symbol": "AAPL",
            "score": 70,
            "label": "BULLISH",
            "bullish_pct": 75,
            "bearish_pct": 25,
            "updated_at": "2026-08-10T20:00:00Z",
        },
        "get_sentiment_history": {
            "symbol": "AAPL",
            "series": [
                {
                    "time": "2026-08-09T20:00:00Z",
                    "value": 65,
                    "label": "BULLISH",
                }
            ],
        },
        "get_message_volume": {
            "symbol": "AAPL",
            "series": [
                {
                    "timeframe": "now",
                    "normalized_value": 46,
                    "normalized_label": "NORMAL",
                }
            ],
        },
        "get_message_volume_history": {
            "symbol": "AAPL",
            "series": [
                {
                    "time": "2026-08-09T20:00:00Z",
                    "value": 40,
                    "label": "NORMAL",
                }
            ],
        },
        "get_symbol_messages": {
            "messages": [
                {
                    "id": 123,
                    "created_at": "2026-08-10T19:00:00Z",
                    "body": "Community opinion only.",
                    "sentiment": "Bullish",
                }
            ],
            "more": False,
        },
    }
    return StocktwitsSentimentProvider(
        transport=FakeMCPTransport(
            tools=StocktwitsSentimentProvider.required_tools,
            results=results,
        ),
        clock=lambda: datetime(2026, 8, 10, 21, tzinfo=UTC),
    )


def _service(
    database: DuckDBDatabase,
    root: Path,
    job_ids: Iterator[str],
) -> DataIngestionService:
    return DataIngestionService(
        instruments=InstrumentRepository(database),
        market_data=MarketDataRepository(database),
        documents=DocumentRepository(database),
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(root / "raw"),
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


def test_stocktwits_mcp_ingestion_is_idempotent_and_bundle_visible(
    tmp_path: Path,
) -> None:
    database = DuckDBDatabase(tmp_path / "stocktwits.duckdb")
    database.bootstrap()
    instruments = InstrumentRepository(database)
    market_data = MarketDataRepository(database)
    instruments.upsert(
        InstrumentRecord(
            asset_id=AssetId("US:AAPL"),
            market=Market.US,
            ticker="AAPL",
            exchange_code="NASDAQ",
            company_name="Apple Inc.",
            currency="USD",
            source_primary="instrument_registry",
        )
    )
    service = _service(database, tmp_path, iter(("sentiment-1", "sentiment-2")))
    request = IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=("US:AAPL",),
        sentiment_start_date=date(2026, 8, 9),
        sentiment_end_date=date(2026, 8, 10),
    )

    first = service.run(_provider(), request)
    second = service.run(_provider(), request)

    assert first.status == TaskStatus.COMPLETED.value
    assert second.status == TaskStatus.COMPLETED.value
    snapshots = market_data.list_sentiment_snapshots(
        AssetId("US:AAPL"),
        start_at=datetime(2026, 8, 9, tzinfo=UTC),
        as_of=datetime(2026, 8, 10, 23, tzinfo=UTC),
    )
    messages = market_data.list_sentiment_evidence(
        AssetId("US:AAPL"),
        start_at=datetime(2026, 8, 9, tzinfo=UTC),
        as_of=datetime(2026, 8, 10, 23, tzinfo=UTC),
    )
    assert len(snapshots) == 2
    assert len(messages) == 1

    bundle = ResearchDataBundleService(
        instruments=instruments,
        market_data=market_data,
    ).build(
        ResearchDataBundleRequest(
            asset_id=AssetId("US:AAPL"),
            as_of=datetime(2026, 8, 10, 23, tzinfo=UTC),
            window_start=date(2026, 8, 9),
            window_end=date(2026, 8, 10),
            dataset_version="stocktwits-offline-integration-v1",
            requested_capabilities=(
                DataCapability.ASSET_IDENTITY,
                DataCapability.SENTIMENT_EVIDENCE,
            ),
        )
    )

    assert bundle.sentiment_evidence.status is DataAvailabilityStatus.PRESENT
    assert bundle.sentiment_evidence.items
    assert all(
        item.source.provider_name == "stocktwits_mcp"
        for item in bundle.sentiment_evidence.items
    )
    assert {
        item.source.retention_class for item in bundle.sentiment_evidence.items
    } <= {"community_sentiment_only", "derived_normalized_facts"}
