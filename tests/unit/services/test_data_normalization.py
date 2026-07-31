"""Tests for canonical identifiers and provider-record normalization."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.models.enums import DocumentType, Market
from src.services import (
    AssetIdentifierNormalizer,
    DataNormalizer,
    NormalizationError,
)

NOW = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("symbol", "market", "exchange", "expected"),
    [
        ("600519", "CN", "SSE", "CN:600519.SH"),
        ("SZ000001", "CN", None, "CN:000001.SZ"),
        ("700", "HK", None, "HK:0700.HK"),
        ("aapl", "US", "NASDAQ", "US:AAPL"),
        ("US:BRK.B", "US", None, "US:BRK.B"),
    ],
)
def test_asset_identifier_normalization(
    symbol: str,
    market: str,
    exchange: str | None,
    expected: str,
) -> None:
    """Provider symbols normalize to MASTER_SPEC canonical values."""

    normalized = AssetIdentifierNormalizer().normalize(symbol, market, exchange)

    assert str(normalized) == expected


@pytest.mark.parametrize(
    ("symbol", "market", "exchange"),
    [
        ("600519", "CN", None),
        ("700000", "HK", None),
        ("AAPL", "EU", None),
        ("US:AAPL", "HK", None),
    ],
)
def test_asset_identifier_rejects_ambiguous_or_invalid_values(
    symbol: str,
    market: str,
    exchange: str | None,
) -> None:
    """Invalid market identity fails instead of being guessed."""

    with pytest.raises(NormalizationError):
        AssetIdentifierNormalizer().normalize(symbol, market, exchange)


def test_instrument_normalization_hides_provider_payload_shape() -> None:
    """Only canonical domain fields leave the normalizer."""

    record = DataNormalizer().normalize_instrument(
        "wind_wds",
        {
            "symbol": "600519",
            "market": "CN",
            "exchange_code": "SSE",
            "company_name": "贵州茅台",
            "currency": "CNY",
            "provider_only_field": "must not leak",
        },
    )

    assert str(record.asset_id) == "CN:600519.SH"
    assert record.market is Market.CN
    assert record.source_primary == "wind_wds"
    assert "provider_only_field" not in record.model_dump()


def test_eod_normalization_validates_prices_and_missing_values() -> None:
    """Optional values stay missing while inconsistent prices fail."""

    normalizer = DataNormalizer()
    record = normalizer.normalize_eod_bar(
        "alpaca_market_data",
        {
            "symbol": "AAPL",
            "market": "US",
            "exchange_code": "NASDAQ",
            "trade_date": "2026-07-30",
            "open": "208.5",
            "high": 212.0,
            "low": 207.0,
            "close": 210.5,
        },
        received_at=NOW,
    )

    assert record.trade_date == date(2026, 7, 30)
    assert record.turnover is None
    assert record.ingestion_ts == NOW

    with pytest.raises(NormalizationError, match="high"):
        normalizer.normalize_eod_bar(
            "alpaca_market_data",
            {
                "symbol": "AAPL",
                "market": "US",
                "trade_date": "2026-07-30",
                "high": 100,
                "close": 101,
            },
        )


def test_document_normalization_preserves_raw_text_and_trace() -> None:
    """Document metadata retains source URL, timestamp, and text checksum."""

    normalized = DataNormalizer().normalize_document(
        "sec_edgar",
        {
            "document_id": "sec-aapl-10q",
            "asset_id": "US:AAPL",
            "market": "US",
            "doc_type": "filing",
            "title": "Form 10-Q",
            "raw_text": "Revenue increased.",
            "source_url": "https://www.sec.gov/example",
            "publish_ts": "2026-07-30T20:00:00Z",
            "metadata": {"form": "10-Q"},
        },
        received_at=NOW,
    )

    assert normalized.raw_text == "Revenue increased."
    assert normalized.record.doc_type is DocumentType.FILING
    assert normalized.record.source_id == "sec_edgar"
    assert normalized.record.checksum_sha256 is not None
    assert normalized.record.created_at == NOW


def test_required_provider_data_is_never_silently_filled() -> None:
    """Missing mandatory data raises a source-attributed error."""

    with pytest.raises(NormalizationError, match="fake instrument"):
        DataNormalizer().normalize_instrument(
            "fake",
            {"market": "US", "exchange_code": "NASDAQ"},
        )
