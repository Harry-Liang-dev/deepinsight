"""Offline SEC Company Facts ingestion and bundle integration tests."""

from __future__ import annotations

import json
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
from src.schemas import (
    DataAvailabilityStatus,
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
NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
FILING_ROOT = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/"


class _SECXBRLFixtureTransport:
    """Serve fixed official-format SEC JSON without external access."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        del timeout
        self.requests.append(request.full_url)
        if request.full_url == SUBMISSIONS_URL:
            payload: object = {
                "name": "Apple Inc.",
                "tickers": ["AAPL"],
                "exchanges": ["Nasdaq"],
                "filings": {"recent": {}},
            }
        elif request.full_url == COMPANY_FACTS_URL:
            facts = {
                "RevenueFromContractWithCustomerExcludingAssessedTax": 94.0,
                "GrossProfit": 44.0,
                "OperatingIncomeLoss": 30.0,
                "NetIncomeLoss": 24.0,
            }
            us_gaap: dict[str, object] = {
                concept: {"units": {"USD": [_fact(value)]}}
                for concept, value in facts.items()
            }
            us_gaap["EarningsPerShareBasic"] = {"units": {"USD/shares": [_fact(1.55)]}}
            payload = {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": {"us-gaap": us_gaap},
            }
        else:
            raise AssertionError(f"unexpected fixture URL: {request.full_url}")
        return ProviderHTTPResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )


def _fact(value: float) -> dict[str, object]:
    return {
        "start": "2026-03-29",
        "end": "2026-06-27",
        "val": value,
        "accn": "0000320193-26-000001",
        "fy": 2026,
        "fp": "Q3",
        "form": "10-Q",
        "filed": "2026-08-01",
    }


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


def test_sec_xbrl_ingests_idempotently_and_builds_bundle(tmp_path: Path) -> None:
    """Company Facts reaches DuckDB and a deterministic attributable bundle."""

    database = DuckDBDatabase(tmp_path / "sec-xbrl.duckdb")
    database.bootstrap()
    transport = _SECXBRLFixtureTransport()
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
        iter(("xbrl-job-1", "xbrl-job-2")),
    )
    request = IngestionRequest(
        job_type=IngestionJobType.INCREMENTAL,
        asset_ids=("US:AAPL",),
        fundamental_start_date=date(2026, 7, 1),
        fundamental_end_date=date(2026, 8, 7),
    )

    first = service.run(adapter, request)
    second = service.run(adapter, request)

    assert first.status == TaskStatus.COMPLETED.value
    assert first.rows_written == 2
    assert second.rows_written == first.rows_written
    market_data = MarketDataRepository(database)
    fundamental = market_data.get_fundamental(
        AssetId("US:AAPL"),
        date(2026, 6, 27),
        "10-Q",
    )
    assert fundamental is not None
    assert fundamental.revenue == 94.0
    assert fundamental.eps_basic == 1.55
    assert fundamental.filing_url == FILING_ROOT
    assert fundamental.source_id == "sec_edgar"
    listed_fundamentals = market_data.list_fundamentals(
        AssetId("US:AAPL"),
        end_date=date(2026, 8, 7),
    )
    assert len(listed_fundamentals) == 1

    bundle_service = ResearchDataBundleService(
        instruments=InstrumentRepository(database),
        market_data=market_data,
    )
    bundle_request = ResearchDataBundleRequest(
        asset_id=AssetId("US:AAPL"),
        as_of=NOW,
        window_start=date(2026, 1, 1),
        window_end=date(2026, 8, 7),
        dataset_version="sec_xbrl_offline_v1",
        snapshot_id="fixture-snapshot",
    )
    first_bundle = bundle_service.build(bundle_request)
    second_bundle = bundle_service.build(bundle_request)

    assert first_bundle == second_bundle
    assert first_bundle.fundamentals.status is DataAvailabilityStatus.PARTIAL
    assert first_bundle.fundamentals.available_field_count == 8
    assert {item.field_path for item in first_bundle.fundamentals.items} >= {
        "fundamentals.gross_margin",
        "fundamentals.operating_margin",
        "fundamentals.net_margin",
    }
    assert len(first_bundle.fundamentals.items) == 8
    assert {item.source.provider_name for item in first_bundle.fundamentals.items} == {
        "sec_edgar"
    }
    raw_items = [
        item
        for item in first_bundle.fundamentals.items
        if item.transformation_name is None
    ]
    assert {item.source.provider_locator for item in raw_items} == {FILING_ROOT}
    assert all(
        item.parent_evidence_ids
        for item in first_bundle.fundamentals.items
        if item.transformation_name == "fundamental_features"
    )
    assert first_bundle.macro_indicators.status is DataAvailabilityStatus.NOT_APPLICABLE
    snapshot = first_bundle.model_dump(mode="json", exclude_none=True)
    _assert_no_none(snapshot)

    with database.connection() as connection:
        counts = connection.execute("""
            SELECT
                (SELECT count(*) FROM instruments),
                (SELECT count(*) FROM fundamentals),
                (SELECT count(*) FROM ingestion_jobs)
            """).fetchone()
    assert counts == (1, 1, 2)
    assert transport.requests == [
        SUBMISSIONS_URL,
        COMPANY_FACTS_URL,
        COMPANY_FACTS_URL,
    ]


def _assert_no_none(value: object) -> None:
    if isinstance(value, dict):
        assert all(item is not None for item in value.values())
        for item in value.values():
            _assert_no_none(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_none(item)
