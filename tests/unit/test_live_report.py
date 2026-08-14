"""Offline tests for the Day 17 live-run hard gate."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from scripts import live_report
from scripts.live_report import _preflight
from src.core import AppSettings, LLMProviderName
from src.repositories import DuckDBDatabase


def test_live_preflight_fails_closed_without_complete_configuration() -> None:
    """A partial live configuration must never be treated as runnable."""

    settings = AppSettings()
    settings.qwen.api_key = SecretStr("secret-qwen-value")

    result = _preflight(settings)

    assert result["status"] == "FAIL"
    assert result["fake"] == {"llm": False, "judge": False}
    assert "secret-qwen-value" not in json.dumps(result)


def test_live_preflight_passes_only_for_complete_real_provider_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete Research Completeness live configuration should pass."""

    settings = AppSettings()
    settings.llm.provider = LLMProviderName.QWEN
    settings.qwen.api_key = SecretStr("secret-qwen-value")
    settings.providers.sec_user_agent = "DeepInsight test@example.com"
    settings.providers.sec_cik_map = {"US:AAPL": "0000320193"}
    settings.providers.alpaca_api_key_id = SecretStr("secret-alpaca-id")
    settings.providers.alpaca_api_secret_key = SecretStr("secret-alpaca-value")
    settings.providers.fred_api_key = SecretStr("secret-fred-value")
    settings.providers.fmp_enabled = True
    settings.providers.fmp_api_key = SecretStr("secret-fmp-value")
    settings.providers.stocktwits_mcp_enabled = True
    settings.live.dataset_version = "live_aapl_multisource_baseline_v1"
    settings.live.as_of_date = date(2026, 8, 7)
    settings.live.data_start = date(2026, 5, 7)
    settings.live.data_end = date(2026, 8, 7)

    monkeypatch.setattr(
        live_report,
        "stocktwits_authorization_configured",
        lambda _settings: True,
    )

    result = _preflight(settings)

    assert result["status"] == "PASS"
    llm = result["llm"]
    sec = result["sec"]
    alpaca = result["alpaca"]
    assert isinstance(llm, dict)
    assert isinstance(sec, dict)
    assert isinstance(alpaca, dict)
    assert llm == {
        "provider": "qwen",
        "model": "qwen3.7-flash",
        "credential": "configured",
        "real": True,
        "e2e_max_retries": 1,
    }
    assert sec["asset_resolved"] is True
    assert alpaca["configured"] is True
    assert result["fred"] == {"configured": True, "series_count": 12}
    assert result["fmp"] == {
        "enabled": True,
        "credential": "configured",
        "asset_resolved": True,
    }
    assert result["stocktwits"] == {
        "enabled": True,
        "provider_status": "CONFIGURED",
        "authorization": "configured",
    }
    serialized = json.dumps(result)
    assert "secret-qwen-value" not in serialized
    assert "secret-alpaca" not in serialized
    assert "secret-fred" not in serialized
    assert "secret-fmp" not in serialized


def test_live_preflight_requires_oauth_when_stocktwits_is_enabled(
    tmp_path: Path,
) -> None:
    """Enabled sentiment must fail closed without local OAuth state."""

    settings = AppSettings()
    settings.llm.provider = LLMProviderName.QWEN
    settings.qwen.api_key = SecretStr("secret-qwen-value")
    settings.providers.sec_user_agent = "DeepInsight test@example.com"
    settings.providers.sec_cik_map = {"US:AAPL": "0000320193"}
    settings.providers.alpaca_api_key_id = SecretStr("secret-alpaca-id")
    settings.providers.alpaca_api_secret_key = SecretStr("secret-alpaca-value")
    settings.providers.stocktwits_mcp_enabled = True
    settings.providers.stocktwits_mcp_token_store = tmp_path / "not-authorized"
    settings.live.dataset_version = "live_aapl_multisource_baseline_v1"
    settings.live.as_of_date = date(2026, 8, 7)
    settings.live.data_start = date(2026, 5, 7)
    settings.live.data_end = date(2026, 8, 7)

    result = _preflight(settings)

    assert result["status"] == "FAIL"
    assert result["stocktwits"] == {
        "enabled": True,
        "provider_status": "NOT_CONFIGURED",
        "authorization": "authorization required",
    }


def test_live_main_stops_before_smokes_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No live Provider may run after an invalid hard-gate result."""

    settings = AppSettings()
    called = False

    def forbidden_smoke(*args: object, **kwargs: object) -> int:
        del args, kwargs
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(live_report, "load_settings", lambda: settings)
    monkeypatch.setattr(live_report.smoke_sec_edgar, "main", forbidden_smoke)
    monkeypatch.setattr(live_report.smoke_alpaca, "main", forbidden_smoke)
    monkeypatch.setattr(live_report.smoke_qwen, "main", forbidden_smoke)

    assert live_report.main() == 2
    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "INVALID LIVE RUN"
    assert result["preflight"]["status"] == "FAIL"
    assert called is False


def test_manifest_agent_query_matches_bootstrapped_schema(tmp_path: Path) -> None:
    """Manifest collection must use real agent_runs persistence columns."""

    database = DuckDBDatabase(tmp_path / "manifest.duckdb")
    database.bootstrap()

    assert live_report._agent_run_manifest_rows(database) == []


def test_sec_filing_window_is_independent_from_short_price_window() -> None:
    """Sparse filings use the bounded SEC lookback, not the EOD price window."""

    data_start = date(2025, 1, 1)
    data_end = date(2025, 1, 15)
    sec_start = data_end - timedelta(days=live_report._SEC_LOOKBACK_DAYS)

    assert (data_end - data_start).days == 14
    assert live_report._SEC_LOOKBACK_DAYS == 740
    assert sec_start == date(2023, 1, 6)
