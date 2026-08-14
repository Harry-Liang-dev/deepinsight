"""Offline tests for the opt-in FMP live smoke command."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date

import pytest
from pydantic import SecretStr

from scripts import smoke_fmp
from src.adapters import ProviderRecord
from src.core import AppSettings


def test_fmp_smoke_requires_explicit_enablement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A configured key does not silently enable this optional Provider."""

    settings = AppSettings()
    settings.providers.fmp_api_key = SecretStr("secret-fmp-value")
    monkeypatch.setattr(smoke_fmp, "load_settings", lambda: settings)

    assert smoke_fmp.main([]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "not_configured"
    assert "secret-fmp-value" not in output


def test_fmp_smoke_outputs_safe_metric_coverage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An injected response exposes only metrics and point-in-time metadata."""

    class FakeFMPAdapter:
        provider_name = "financial_modeling_prep"

        def __init__(self, **kwargs: object) -> None:
            assert kwargs["api_key"] == "secret-fmp-value"

        def fetch_fundamentals_range(
            self,
            asset_ids: list[str],
            start_date: date,
            end_date: date,
        ) -> Iterable[ProviderRecord]:
            assert asset_ids == ["US:AAPL"]
            assert end_date == date(2026, 8, 14)
            assert start_date == date(2024, 8, 4)
            return (
                {
                    "asset_id": "US:AAPL",
                    "market": "US",
                    "fiscal_period_end": "2026-06-27",
                    "report_type": "TTM_STANDARDIZED",
                    "accepted_at": "2026-07-31T06:01:02+00:00",
                    "revenue_yoy": -0.015,
                    "gross_margin": 0.48,
                    "market_cap": 4_483_462_292_560.0,
                    "source_locator": "fmp:stable:standardized-metrics:AAPL",
                    "quality": "provider_standardized",
                },
            )

    settings = AppSettings()
    settings.providers.fmp_enabled = True
    settings.providers.fmp_api_key = SecretStr("secret-fmp-value")
    monkeypatch.setattr(smoke_fmp, "load_settings", lambda: settings)
    monkeypatch.setattr(smoke_fmp, "FinancialModelingPrepAdapter", FakeFMPAdapter)

    assert smoke_fmp.main(["--end-date", "2026-08-14"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["status"] == "ok"
    assert result["available_metrics"] == {
        "gross_margin": 0.48,
        "market_cap": 4_483_462_292_560.0,
        "revenue_yoy": -0.015,
    }
    assert "pe_ttm" in result["missing_metrics"]
    assert result["reporting_period"] == "2026-06-27"
    assert result["provider_timestamp"] == "2026-07-31T06:01:02+00:00"
    assert "secret-fmp-value" not in output
