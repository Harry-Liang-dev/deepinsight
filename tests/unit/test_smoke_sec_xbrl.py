"""Offline tests for the independent SEC XBRL live smoke command."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import pytest

from scripts import smoke_sec_xbrl
from src.adapters import ProviderRecord
from src.core import AppSettings


def test_sec_xbrl_smoke_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing SEC identity skips before constructing a network Adapter."""

    settings = AppSettings()
    settings.providers.sec_user_agent = None
    monkeypatch.setattr(smoke_sec_xbrl, "load_settings", lambda: settings)

    assert smoke_sec_xbrl.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "configuration_error"


def test_sec_xbrl_smoke_outputs_safe_normalized_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Injected records prove the live command shape without network access."""

    requested: list[tuple[list[str], date, date]] = []

    class FakeSECAdapter:
        provider_name = "sec_edgar"

        def __init__(self, **kwargs: object) -> None:
            assert kwargs["user_agent"] == "DeepInsight test@example.com"

        def fetch_fundamentals_range(
            self,
            asset_ids: list[str],
            start_date: date,
            end_date: date,
        ) -> Iterable[ProviderRecord]:
            requested.append((asset_ids, start_date, end_date))
            return (
                {
                    "asset_id": "US:AAPL",
                    "market": "US",
                    "fiscal_period_end": "2026-06-27",
                    "report_type": "10-Q",
                    "revenue": 94.0,
                    "net_income": 24.0,
                    "filing_url": (
                        "https://www.sec.gov/Archives/edgar/data/320193/"
                        "000032019326000001/"
                    ),
                },
            )

    settings = AppSettings()
    settings.providers.sec_user_agent = "DeepInsight test@example.com"
    settings.providers.sec_cik_map = {"US:AAPL": "0000320193"}
    monkeypatch.setattr(smoke_sec_xbrl, "load_settings", lambda: settings)
    monkeypatch.setattr(smoke_sec_xbrl, "SECEDGARAdapter", FakeSECAdapter)

    assert (
        smoke_sec_xbrl.main(
            [
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-08-07",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["fundamental_count"] == 1
    assert result["first_period"] == "2026-06-27"
    assert result["last_period"] == "2026-06-27"
    assert result["source_id"] == "sec_edgar"
    assert result["populated_fields"] == ["net_income", "revenue"]
    assert "user_agent" not in result
    assert "cik" not in result
    assert requested == [(["US:AAPL"], date(2026, 7, 1), date(2026, 8, 7))]
