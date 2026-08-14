"""Offline end-to-end persistence and Bundle coverage for closure data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.models.enums import DocumentType, EventSeverity, Market, MarketScope
from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    InstrumentRepository,
    MarketDataRepository,
)
from src.schemas.documents import TextDocumentRecord
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    FundamentalRecord,
    InstrumentRecord,
    MacroObservationRecord,
    NewsEvidenceRecord,
    SentimentEvidenceRecord,
    SentimentSnapshotRecord,
)
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    ResearchDataBundleRequest,
)
from src.services import ResearchDataBundleService

pytestmark = pytest.mark.integration
AS_OF = datetime(2026, 8, 10, 20, tzinfo=UTC)


def test_all_closure_capabilities_flow_from_duckdb_to_bundle(tmp_path: Path) -> None:
    database = DuckDBDatabase(tmp_path / "closure.duckdb")
    database.bootstrap()
    instruments = InstrumentRepository(database)
    market = MarketDataRepository(database)
    documents = DocumentRepository(database)
    instruments.upsert(
        InstrumentRecord(
            asset_id=AssetId("US:AAPL"),
            market=Market.US,
            ticker="AAPL",
            exchange_code="NASDAQ",
            company_name="Apple Inc.",
            currency="USD",
            source_primary="sec_edgar",
        )
    )
    for asset_id, multiplier in (
        ("US:AAPL", 1.2),
        ("US:SPY", 1.0),
        ("US:QQQ", 1.1),
        ("US:XLK", 1.15),
    ):
        for index in range(61):
            market.upsert_eod_bar(
                EodBarRecord(
                    asset_id=AssetId(asset_id),
                    trade_date=date(2026, 6, 11) + timedelta(days=index),
                    open=(100 + index) * multiplier,
                    high=(101 + index) * multiplier,
                    low=(99 + index) * multiplier,
                    close=(100 + index) * multiplier,
                    volume=1_000 + index,
                    feed_identity="iex",
                    coverage_scope=(
                        "IEX single-exchange US equity feed; not consolidated SIP"
                    ),
                    source_id="alpaca_market_data",
                    ingestion_ts=AS_OF - timedelta(hours=1),
                )
            )
    market.upsert_fundamental(
        FundamentalRecord(
            asset_id=AssetId("US:AAPL"),
            fiscal_period_end=date(2026, 6, 30),
            report_type="annual",
            revenue=1000,
            net_income=100,
            eps_basic=6,
            total_assets=2000,
            total_liabilities=1000,
            shareholders_equity=1000,
            operating_cash_flow=120,
            shares_outstanding=100,
            filing_url="https://www.sec.gov/Archives/example",
            filing_date=date(2026, 8, 1),
            accepted_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
            source_id="sec_edgar",
            ingestion_ts=AS_OF - timedelta(hours=1),
        )
    )
    for index, series in enumerate(
        (
            "FEDFUNDS",
            "DGS2",
            "DGS10",
            "T10Y2Y",
            "CPIAUCSL",
            "PCEPILFE",
            "UNRATE",
            "PAYEMS",
            "GDP",
            "INDPRO",
            "VIXCLS",
            "BAMLH0A0HYM2",
        )
    ):
        market.upsert_macro_observation(
            MacroObservationRecord(
                series_key=series,
                region_code=MarketScope.US,
                observation_date=date(2026, 8, 1),
                indicator_name=series,
                value=float(index),
                unit="index",
                frequency="Daily",
                realtime_start=date(2026, 8, 5),
                realtime_end=date(2026, 8, 5),
                source_locator=f"fred:series:{series}:vintage:2026-08-05",
                source_id="fred",
                ingestion_ts=AS_OF - timedelta(hours=1),
            )
        )
    market.upsert_sentiment_snapshot(
        SentimentSnapshotRecord(
            asset_id=AssetId("US:AAPL"),
            as_of=AS_OF - timedelta(hours=2),
            provider="stocktwits_mcp",
            score=70,
            label="BULLISH",
            message_volume_score=46,
            message_volume_label="NORMAL",
            source_timestamp=AS_OF - timedelta(hours=2),
            quality="current_community_signal",
            source_locator="stocktwits:symbol:AAPL:current",
            ingestion_ts=AS_OF - timedelta(hours=1),
        )
    )
    market.upsert_sentiment_evidence(
        SentimentEvidenceRecord(
            message_id="123",
            asset_id=AssetId("US:AAPL"),
            created_at=AS_OF - timedelta(hours=3),
            text="Community opinion only.",
            declared_sentiment="Bullish",
            source="stocktwits_mcp",
            source_locator="https://stocktwits.com/message/123",
            ingestion_ts=AS_OF - timedelta(hours=1),
        )
    )
    market.upsert_news_evidence(
        NewsEvidenceRecord(
            news_id="news-1",
            asset_id=AssetId("US:AAPL"),
            headline="Attributed headline",
            summary="Attributed summary",
            author="Reporter",
            created_at=AS_OF - timedelta(days=1),
            updated_at=AS_OF - timedelta(days=1),
            source_url="https://publisher.test/news-1",
            provider="alpaca_market_data",
            original_source="Benzinga",
            source_locator="alpaca:news:news-1",
            ingestion_ts=AS_OF - timedelta(hours=1),
        )
    )
    documents.upsert_document(
        TextDocumentRecord(
            document_id="sec-filing-1",
            asset_id=AssetId("US:AAPL"),
            market=MarketScope.US,
            doc_type=DocumentType.FILING,
            title="Apple 10-Q",
            publish_ts=datetime(2026, 8, 1, 12, tzinfo=UTC),
            source_id="sec_edgar",
            source_url="https://www.sec.gov/Archives/example",
            metadata_json={"provider_locator": "sec:accession:1"},
            created_at=AS_OF - timedelta(hours=1),
        )
    )
    market.upsert_corporate_event(
        CorporateEventRecord(
            event_id="event-1",
            asset_id=AssetId("US:AAPL"),
            market=Market.US,
            event_date=AS_OF - timedelta(days=1),
            event_type="filing",
            severity=EventSeverity.LOW,
            title="10-Q filed",
            source_document_id="sec-filing-1",
            source_id="sec_edgar",
            has_document=True,
        )
    )

    bundle = ResearchDataBundleService(
        instruments=instruments,
        market_data=market,
        documents=documents,
    ).build(
        ResearchDataBundleRequest(
            asset_id=AssetId("US:AAPL"),
            as_of=AS_OF,
            window_start=date(2026, 6, 1),
            window_end=date(2026, 8, 10),
            dataset_version="closure-fixture-v1",
            requested_capabilities=tuple(DataCapability),
        )
    )

    for section in (
        bundle.valuation,
        bundle.market_context,
        bundle.industry_sector_context,
        bundle.macro_indicators,
        bundle.news_evidence,
        bundle.sentiment_evidence,
        bundle.filings,
        bundle.corporate_events,
    ):
        assert section.status in {
            DataAvailabilityStatus.PRESENT,
            DataAvailabilityStatus.PARTIAL,
        }
        assert section.items
        assert all(item.source.provider_locator for item in section.items)
        assert all(item.effective_at <= AS_OF for item in section.items)
    assert bundle.valuation.items[0].parent_evidence_ids
    macro_paths = {item.field_path for item in bundle.macro_indicators.items}
    assert {
        "macro_indicators.fed_funds",
        "macro_indicators.yield_2y",
        "macro_indicators.yield_10y",
        "macro_indicators.yield_spread_10y2y",
        "macro_indicators.cpi",
        "macro_indicators.core_pce",
        "macro_indicators.unemployment",
        "macro_indicators.payrolls",
        "macro_indicators.gdp",
        "macro_indicators.industrial_production",
        "macro_indicators.vix",
        "macro_indicators.high_yield_spread",
    } <= macro_paths
    assert all(
        item.parent_evidence_ids
        for item in bundle.macro_indicators.items
        if item.transformation_name == "macro_snapshot"
    )
    assert {item.field_path for item in bundle.news_evidence.items} >= {
        "news_evidence.headline",
        "news_evidence.summary",
    }
    assert {
        item.source.retention_class for item in bundle.sentiment_evidence.items
    } <= {"community_sentiment_only", "derived_normalized_facts"}
    coverage = next(
        item for item in bundle.ohlcv.items if item.field_path == "ohlcv.coverage_scope"
    )
    assert "not consolidated SIP" in str(coverage.value)
