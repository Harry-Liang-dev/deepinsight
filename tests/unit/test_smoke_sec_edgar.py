"""Offline tests for the independent SEC Provider live smoke command."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import pytest

from scripts import smoke_sec_edgar
from src.adapters import ProviderRecord
from src.core import AppSettings


def test_sec_smoke_requires_explicit_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The smoke command must not access SEC without a declared identity."""

    settings = AppSettings()
    settings.providers.sec_user_agent = None
    monkeypatch.setattr(
        smoke_sec_edgar,
        "load_settings",
        lambda: settings,
    )

    assert smoke_sec_edgar.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "configuration_error"


def test_sec_smoke_requires_asset_identifier_mapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The smoke command must not substitute a hard-coded issuer CIK."""

    settings = AppSettings()
    settings.providers.sec_user_agent = "DeepInsight test@example.com"
    settings.providers.sec_cik_map = {}
    monkeypatch.setattr(smoke_sec_edgar, "load_settings", lambda: settings)

    assert smoke_sec_edgar.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "configuration_error"
    assert "SEC_CIK_MAP" in result["message"]


def test_sec_smoke_reports_safe_metadata_without_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An injected adapter proves output shape without network access."""

    requested_windows: list[tuple[date, date]] = []

    class FakeSECAdapter:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def fetch_instruments(self) -> Iterable[ProviderRecord]:
            return (
                {
                    "asset_id": "US:AAPL",
                    "market": "US",
                    "exchange_code": "NASDAQ",
                },
            )

        def fetch_documents(
            self,
            asset_ids: list[str],
            start_date: date,
            end_date: date,
        ) -> Iterable[ProviderRecord]:
            del asset_ids
            requested_windows.append((start_date, end_date))
            return (
                {
                    "document_id": "sec-doc",
                    "publish_ts": "2026-08-01T12:00:00+00:00",
                    "source_url": "https://www.sec.gov/Archives/example",
                    "raw_text": "private raw fixture",
                    "metadata": {"provider_locator": "sec:accession:test"},
                },
            )

    settings = AppSettings()
    settings.providers.sec_user_agent = "DeepInsight test@example.com"
    settings.providers.sec_cik_map = {"US:AAPL": "0000320193"}
    monkeypatch.setattr(
        smoke_sec_edgar,
        "load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(smoke_sec_edgar, "SECEDGARAdapter", FakeSECAdapter)

    assert (
        smoke_sec_edgar.main(
            [
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-08-01",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["provider_locator"] == "sec:accession:test"
    assert result["raw_text_chars"] == len("private raw fixture")
    assert "private raw fixture" not in result.values()
    assert requested_windows == [(date(2026, 7, 1), date(2026, 8, 1))]
