"""Tests for canonical security identifiers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.enums import Market
from src.models.identifiers import AssetId


@pytest.mark.parametrize(
    ("value", "market"),
    [
        ("CN:600519.SH", Market.CN),
        ("CN:000001.SZ", Market.CN),
        ("HK:0700.HK", Market.HK),
        ("US:AAPL", Market.US),
    ],
)
def test_asset_id_accepts_master_spec_examples(
    value: str,
    market: Market,
) -> None:
    """Canonical examples should validate and expose their market."""
    asset_id = AssetId(value)

    assert str(asset_id) == value
    assert asset_id.market is market
    assert asset_id.model_dump() == value


@pytest.mark.parametrize(
    "value",
    [
        "600519.SH",
        "CN:600519",
        "CN:600519.HK",
        "HK:700.HK",
        "US:",
        "us:AAPL",
        "GLOBAL:AAPL",
    ],
)
def test_asset_id_rejects_noncanonical_values(value: str) -> None:
    """Unsupported or ambiguous identifier forms should be rejected."""
    with pytest.raises(ValidationError):
        AssetId(value)
