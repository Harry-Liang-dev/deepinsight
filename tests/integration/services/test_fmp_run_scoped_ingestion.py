"""Offline FMP preflight-to-ingestion snapshot reuse integration."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

import pytest

from src.adapters import FinancialModelingPrepAdapter
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
from src.schemas.market_data import InstrumentRecord
from src.services import (
    DataIngestionService,
    DataNormalizer,
    DocumentChunker,
    IngestionRequest,
    RawTextStore,
)

pytestmark = pytest.mark.integration
_AS_OF = datetime(2026, 8, 14, 20, tzinfo=UTC)


class _FMPTransport:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        assert timeout == 7.0
        self.requests.append(request)
        endpoint = urlparse(request.full_url).path.rsplit("/", maxsplit=1)[-1]
        payload: dict[str, object]
        if endpoint == "income-statement":
            payload = {
                "date": "2026-06-27",
                "filingDate": "2026-07-31",
                "acceptedDate": "2026-07-31 06:01:02",
            }
        elif endpoint == "ratios-ttm":
            payload = {
                "grossProfitMarginTTM": 0.48,
                "operatingProfitMarginTTM": 0.33,
                "netProfitMarginTTM": 0.27,
                "debtToEquityRatioTTM": 0.78,
                "currentRatioTTM": 1.0,
                "netIncomePerShareTTM": 8.77,
                "bookValuePerShareTTM": 7.31,
                "priceToEarningsRatioTTM": 34.84,
                "priceToBookRatioTTM": 41.71,
            }
        elif endpoint == "key-metrics-ttm":
            payload = {
                "returnOnEquityTTM": 1.37,
                "returnOnAssetsTTM": 0.33,
                "marketCap": 4_483_462_292_560,
                "earningsYieldTTM": 0.028,
            }
        else:
            payload = {"growthRevenue": -0.015, "growthNetIncome": 0.007}
        return ProviderHTTPResponse(200, {}, json.dumps([payload]).encode())


def test_fmp_preflight_snapshot_is_reused_by_formal_ingestion(tmp_path: Path) -> None:
    """One run acquires once, validates, then persists the same provenance."""

    database = DuckDBDatabase(tmp_path / "fmp.duckdb")
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
    transport = _FMPTransport()
    provider = FinancialModelingPrepAdapter(
        api_key="fixture-secret",
        request_timeout=7.0,
        http_transport=transport,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        research_as_of=_AS_OF,
        acquisition_clock=lambda: _AS_OF,
    )
    start = date(2024, 8, 4)
    end = date(2026, 8, 14)

    preflight = list(provider.fetch_fundamentals_range(["US:AAPL"], start, end))
    assert len(preflight) == 1
    service = DataIngestionService(
        instruments=instruments,
        market_data=market_data,
        documents=DocumentRepository(database),
        jobs=IngestionJobRepository(database),
        normalizer=DataNormalizer(),
        raw_text_store=RawTextStore(tmp_path / "raw"),
        chunker=DocumentChunker(
            chunk_size=100,
            overlap=10,
            embedding_model="fixture",
            embedding_dim=3,
            faiss_namespace="fixture",
        ),
        clock=lambda: _AS_OF,
        job_id_factory=lambda: "fmp-job",
    )
    service.run(
        provider,
        IngestionRequest(
            job_type=IngestionJobType.INCREMENTAL,
            asset_ids=("US:AAPL",),
            fundamental_start_date=start,
            fundamental_end_date=end,
        ),
    )

    stored = market_data.get_fundamental(
        AssetId("US:AAPL"),
        date(2026, 6, 27),
        "TTM_STANDARDIZED",
    )
    assert stored is not None
    assert stored.accepted_at is not None
    assert stored.source_locator == "fmp:stable:standardized-metrics:AAPL"
    assert stored.ingestion_ts is not None
    diagnostics = provider.acquisition_diagnostics()
    assert diagnostics["external_acquisition_count"] == 1
    assert diagnostics["snapshot_reuse_count"] == 1
    assert diagnostics["physical_http_request_count"] == 4
    assert diagnostics["retry_count"] == 0
    snapshot = provider.acquisition_snapshot(
        ("US:AAPL",), start, end, research_as_of=_AS_OF
    )
    assert snapshot is not None
    assert "fixture-secret" not in json.dumps(snapshot.to_payload())
