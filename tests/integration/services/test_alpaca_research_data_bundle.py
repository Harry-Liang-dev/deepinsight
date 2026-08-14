"""Offline Alpaca-to-ResearchDataBundle technical capability tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.request import Request

import pytest

from src.adapters import AlpacaAdapter
from src.adapters.http import ProviderHTTPResponse
from src.models.enums import IngestionJobType, Market
from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
)
from src.schemas import (
    DataAvailabilityStatus,
    DataCapability,
    DataQualityStatus,
    FreshnessStatus,
    InstrumentRecord,
    MissingDataReason,
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

ASSET_ID = AssetId("US:AAPL")
INGESTED_AT = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
AS_OF = datetime(2026, 8, 9, 23, 59, tzinfo=UTC)


class _FixtureTransport:
    """Return repeated official-format bar pages without network access."""

    def __init__(self, body: str, request_count: int) -> None:
        self._bodies = [body] * request_count
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request)
        return ProviderHTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
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
        clock=lambda: INGESTED_AT,
        job_id_factory=lambda: next(job_ids),
    )


def _trading_dates(end_date: date, count: int) -> list[date]:
    dates: list[date] = []
    cursor = end_date
    while len(dates) < count:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(dates)


def _bar_payload(dates: list[date]) -> str:
    bars = []
    for index, trade_date in enumerate(dates):
        close = 100.0 + index
        bars.append(
            {
                "t": datetime.combine(trade_date, time(4), tzinfo=UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "o": close - 0.5,
                "h": close + 1.0,
                "l": close - 1.0,
                "c": close,
                "v": 1_000_000 + index,
                "vw": close + 0.1,
            }
        )
    return json.dumps({"bars": {"AAPL": bars}, "next_page_token": None})


def test_alpaca_bars_reach_attributable_technical_bundle_idempotently(
    tmp_path: Path,
) -> None:
    """One offline flow covers Adapter, normalization, DuckDB, and Bundle."""

    database = DuckDBDatabase(tmp_path / "alpaca-bundle.duckdb")
    database.bootstrap()
    instruments = InstrumentRepository(database)
    instruments.upsert(
        InstrumentRecord(
            asset_id=ASSET_ID,
            market=Market.US,
            ticker="AAPL",
            exchange_code="NASDAQ",
            company_name="Apple Inc.",
            currency="USD",
            source_primary="sec_edgar",
        )
    )
    dates = _trading_dates(date(2026, 8, 7), 62)
    transport = _FixtureTransport(_bar_payload(dates), request_count=2)
    adapter = AlpacaAdapter(
        api_key_id="fixture-key-id",
        api_secret_key="fixture-secret",
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    ingestion = _service(
        database,
        tmp_path / "raw",
        iter(("bundle-job-1", "bundle-job-2")),
    )
    ingestion_request = IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=(str(ASSET_ID),),
        eod_start_date=dates[0],
        eod_end_date=dates[-1],
    )

    first_job = ingestion.run(adapter, ingestion_request)
    second_job = ingestion.run(adapter, ingestion_request)

    assert first_job.rows_written == 62
    assert second_job.rows_written == 62
    market_data = MarketDataRepository(database)
    stored = market_data.list_eod_bars(
        ASSET_ID,
        start_date=dates[0],
        end_date=dates[-1],
        ingested_as_of=AS_OF,
        limit=100,
    )
    assert len(stored) == 62
    assert (
        market_data.list_eod_bars(
            ASSET_ID,
            start_date=dates[0],
            end_date=dates[-1],
            ingested_as_of=INGESTED_AT - timedelta(seconds=1),
            limit=100,
        )
        == []
    )

    builder = ResearchDataBundleService(
        instruments=instruments,
        market_data=market_data,
    )
    request = ResearchDataBundleRequest(
        asset_id=ASSET_ID,
        as_of=AS_OF,
        window_start=dates[0],
        window_end=dates[-1],
        dataset_version="alpaca_technical_offline_v1",
        requested_capabilities=(
            DataCapability.ASSET_IDENTITY,
            DataCapability.OHLCV,
            DataCapability.TECHNICAL_FEATURES,
        ),
    )

    first_bundle = builder.build(request)
    second_bundle = builder.build(request)

    assert first_bundle == second_bundle
    assert first_bundle.ohlcv.status is DataAvailabilityStatus.PARTIAL
    assert first_bundle.ohlcv.freshness.status is FreshnessStatus.FRESH
    assert first_bundle.ohlcv.quality.status is DataQualityStatus.WARNING
    assert first_bundle.ohlcv.available_field_count == 8
    assert len(first_bundle.ohlcv.items) == 62 * 6 + 2
    assert {item.field_path for item in first_bundle.ohlcv.missing_data} == {
        "ohlcv.adj_close",
        "ohlcv.turnover",
    }
    assert all(
        item.reason_code is MissingDataReason.NO_OBSERVATION
        for item in first_bundle.ohlcv.missing_data
    )
    assert {item.source.provider_name for item in first_bundle.ohlcv.items} == {
        "alpaca_market_data"
    }
    assert {item.source.source_url for item in first_bundle.ohlcv.items} == {
        "https://data.alpaca.markets/v2/stocks/bars"
    }

    technical = first_bundle.technical_features
    assert technical.status is DataAvailabilityStatus.PARTIAL
    assert technical.quality.status is DataQualityStatus.WARNING
    assert technical.available_field_count == 17
    by_path = {item.field_path: item for item in technical.items}
    assert len(by_path["technical_features.sma_20"].parent_evidence_ids) == 20
    assert len(by_path["technical_features.sma_60"].parent_evidence_ids) == 60
    assert len(by_path["technical_features.return_20d"].parent_evidence_ids) == 2
    assert len(by_path["technical_features.rsi_14"].parent_evidence_ids) == 15
    assert len(by_path["technical_features.atr_14"].parent_evidence_ids) == 45
    assert len(by_path["technical_features.volume_ratio_20d"].parent_evidence_ids) == 20
    assert len(by_path["technical_features.trend_label"].parent_evidence_ids) == 2
    assert all(item.transformation_version == "1.0" for item in technical.items)
    snapshot = first_bundle.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(snapshot, sort_keys=True)
    assert '"o"' not in serialized
    assert '"vw"' not in serialized

    with database.connection() as connection:
        counts = connection.execute(
            "SELECT count(*), count(distinct source_id) FROM eod_bars"
        ).fetchone()
    assert counts == (62, 1)
    assert len(transport.requests) == 2
