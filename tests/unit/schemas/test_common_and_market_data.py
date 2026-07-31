"""Tests for common and normalized market data schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import EventSeverity, Market, MarketScope, TaskStatus
from src.models.identifiers import AssetId
from src.schemas.common import ErrorInfo, SourceReference, TaskStatusResponse
from src.schemas.market_data import (
    CorporateEventRecord,
    EodBarRecord,
    FundamentalRecord,
    InstrumentRecord,
    MacroObservationRecord,
    RawDataRecord,
)

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def test_raw_record_accepts_json_payload() -> None:
    """Raw provider data should preserve typed JSON payloads."""
    record = RawDataRecord(
        source_id="sec_edgar",
        market_scope=MarketScope.US,
        object_type="filing",
        payload={"form": "10-Q", "accepted": True},
        received_at=NOW,
    )

    assert record.payload["form"] == "10-Q"
    assert record.source_record_id is None


def test_instrument_matches_asset_market_and_phase_two_defaults() -> None:
    """Instrument identity should match its canonical market."""
    instrument = InstrumentRecord(
        asset_id=AssetId("US:AAPL"),
        market=Market.US,
        ticker="AAPL",
        exchange_code="NASDAQ",
        source_primary="wind_wds",
    )

    assert instrument.asset_id.market is Market.US
    assert instrument.p2_factor_universe is None
    assert instrument.p2_strategy_bucket is None
    assert instrument.p2_router_group is None


def test_instrument_rejects_market_mismatch() -> None:
    """A canonical identifier cannot be attached to another market."""
    with pytest.raises(ValidationError, match="market"):
        InstrumentRecord(
            asset_id=AssetId("US:AAPL"),
            market=Market.CN,
            ticker="AAPL",
            exchange_code="NASDAQ",
            source_primary="wind_wds",
        )


def test_instrument_rejects_invalid_listing_date_order() -> None:
    """Delisting cannot precede listing."""
    with pytest.raises(ValidationError, match="delisted_date"):
        InstrumentRecord(
            asset_id=AssetId("HK:0700.HK"),
            market=Market.HK,
            ticker="0700",
            exchange_code="HKEX",
            source_primary="wind_wds",
            listed_date=date(2020, 1, 1),
            delisted_date=date(2019, 1, 1),
        )


def test_corporate_event_validates_asset_market() -> None:
    """Issuer events should preserve asset and source traceability."""
    event = CorporateEventRecord(
        event_id="event-1",
        asset_id=AssetId("CN:600519.SH"),
        market=Market.CN,
        event_date=NOW,
        event_type="earnings",
        severity=EventSeverity.HIGH,
        title="Earnings release",
        source_id="sse",
    )

    assert event.asset_id is not None
    assert event.asset_id.market is Market.CN


def test_normalized_numeric_records_use_typed_dates_and_sources() -> None:
    """EOD, fundamental, and macro records should share traceable types."""
    bar = EodBarRecord(
        asset_id=AssetId("US:AAPL"),
        trade_date=date(2026, 7, 23),
        close=215.0,
        source_id="alpaca_market_data",
        ingestion_ts=NOW,
    )
    fundamental = FundamentalRecord(
        asset_id=AssetId("US:AAPL"),
        fiscal_period_end=date(2026, 6, 30),
        report_type="quarterly",
        revenue=100.0,
        source_id="sec_edgar",
        ingestion_ts=NOW,
    )
    macro = MacroObservationRecord(
        series_key="FEDFUNDS",
        region_code=MarketScope.US,
        observation_date=date(2026, 7, 1),
        indicator_name="Federal Funds Effective Rate",
        value=4.0,
        source_id="fred",
        ingestion_ts=NOW,
    )

    assert bar.trade_date == date(2026, 7, 23)
    assert fundamental.p2_factor_blob_json is None
    assert macro.p2_regime_feature_json is None


def test_source_reference_requires_a_locator() -> None:
    """An empty source reference cannot support a research claim."""
    with pytest.raises(ValidationError, match="source reference"):
        SourceReference()


def test_task_status_supports_structured_errors() -> None:
    """Failed jobs should carry a typed error payload."""
    task = TaskStatusResponse(
        job_id="job-1",
        status=TaskStatus.FAILED,
        error=ErrorInfo(code="provider_error", message="Provider unavailable"),
    )

    assert task.error is not None
    assert task.error.retryable is False


def test_domain_models_reject_unknown_fields() -> None:
    """Cross-module contracts should reject silently misspelled fields."""
    with pytest.raises(ValidationError, match="extra"):
        RawDataRecord.model_validate(
            {
                "source_id": "fred",
                "market_scope": MarketScope.US,
                "object_type": "macro",
                "payload": {},
                "received_at": NOW,
                "unexpected": True,
            }
        )
