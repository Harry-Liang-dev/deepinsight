"""Offline tests for the independent Alpaca Provider live smoke command."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import pytest
from pydantic import SecretStr

from scripts import smoke_alpaca
from src.adapters import ProviderRecord
from src.core import AppSettings


def test_alpaca_smoke_requires_both_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The smoke command must not access Alpaca without both credentials."""

    settings = AppSettings()
    settings.providers.alpaca_api_key_id = None
    settings.providers.alpaca_api_secret_key = None
    monkeypatch.setattr(smoke_alpaca, "load_settings", lambda: settings)

    assert smoke_alpaca.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not_configured"


def test_alpaca_smoke_reports_only_safe_bar_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An injected adapter proves the output shape without network access."""

    class FakeAlpacaAdapter:
        provider_name = "alpaca_market_data"

        def __init__(self, **kwargs: object) -> None:
            assert kwargs["api_key_id"] == "key-id-fixture"
            assert kwargs["api_secret_key"] == "secret-fixture"
            assert kwargs["api_base_url"] == "https://data.alpaca.markets"

        def fetch_eod_bars_range(
            self,
            asset_ids: list[str],
            start_date: date,
            end_date: date,
        ) -> Iterable[ProviderRecord]:
            assert asset_ids == ["US:AAPL"]
            assert start_date == date(2026, 8, 3)
            assert end_date == date(2026, 8, 4)
            return (
                {
                    "asset_id": "US:AAPL",
                    "market": "US",
                    "trade_date": "2026-08-03",
                    "close": 210.4,
                },
                {
                    "asset_id": "US:AAPL",
                    "market": "US",
                    "trade_date": "2026-08-04",
                    "close": 212.2,
                },
            )

    settings = AppSettings()
    settings.providers.alpaca_api_key_id = SecretStr("key-id-fixture")
    settings.providers.alpaca_api_secret_key = SecretStr("secret-fixture")
    monkeypatch.setattr(smoke_alpaca, "load_settings", lambda: settings)
    monkeypatch.setattr(smoke_alpaca, "AlpacaAdapter", FakeAlpacaAdapter)

    assert (
        smoke_alpaca.main(
            [
                "--start-date",
                "2026-08-03",
                "--end-date",
                "2026-08-04",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result == {
        "status": "ok",
        "bar_count": 2,
        "first_date": "2026-08-03",
        "last_date": "2026-08-04",
        "source_id": "alpaca_market_data",
    }
    assert "key-id-fixture" not in output
    assert "secret-fixture" not in output
