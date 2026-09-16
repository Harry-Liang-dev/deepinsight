"""Offline tests for the Day 17 live-run hard gate."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from scripts import live_report
from scripts.live_report import _preflight
from src.core import AppSettings, LLMProviderName
from src.repositories import DuckDBDatabase
from src.schemas import DataCapability
from src.schemas.common import SourceReference
from src.schemas.evaluation import EvaluationEvidenceItem
from src.schemas.sector_context import SectorContextBundle
from src.services.sector_context import FrozenSectorContextResolver
from tests.unit.services.test_sector_context import _aapl_bundle


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

    assert live_report.main([]) == 2
    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "INVALID LIVE RUN"
    assert result["preflight"]["status"] == "FAIL"
    assert called is False


def test_configuration_preflight_performs_no_provider_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator precheck must remain configuration-only and offline."""

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
    settings.live.dataset_version = "live-aapl-v1"
    settings.live.as_of_date = date(2026, 9, 15)
    settings.live.data_start = date(2025, 9, 15)
    settings.live.data_end = date(2026, 9, 15)

    monkeypatch.setattr(live_report, "load_settings", lambda: settings)
    monkeypatch.setattr(
        live_report,
        "stocktwits_authorization_configured",
        lambda _settings: True,
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("configuration preflight attempted data acquisition")

    monkeypatch.setattr(live_report, "_build_fmp_provider", forbidden)
    monkeypatch.setattr(live_report.smoke_fmp, "main", forbidden)

    assert live_report.main(["--configuration-preflight"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["preflight_type"] == "CONFIGURATION_PREFLIGHT"
    assert result["network_call_count"] == 0
    assert result["fmp_data_request_count"] == 0
    assert result["result"]["fmp"]["enabled"] is True


def test_full_run_does_not_use_fmp_smoke_as_preflight() -> None:
    """The authoritative run must acquire FMP only through its snapshot path."""

    assert "smoke_fmp.main" not in inspect.getsource(live_report._run)


def test_fmp_integrated_smoke_uses_live_run_provider_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FMP-only mode must use one run-scoped provider and request reuse."""

    settings = AppSettings()
    settings.live.data_end = date(2026, 9, 15)
    provider = cast(Any, object())
    captured: dict[str, object] = {}
    monkeypatch.setattr(live_report, "load_settings", lambda: settings)
    monkeypatch.setattr(
        live_report,
        "_preflight",
        lambda _settings: {"status": "PASS"},
    )

    def build_provider(
        _settings: AppSettings,
        *,
        research_as_of: datetime,
    ) -> object:
        captured["research_as_of"] = research_as_of
        return provider

    def integrated_smoke(argv: list[str], *, provider: object) -> int:
        captured["argv"] = argv
        captured["provider"] = provider
        return 0

    monkeypatch.setattr(live_report, "_build_fmp_provider", build_provider)
    monkeypatch.setattr(live_report.smoke_fmp, "main", integrated_smoke)

    assert (
        live_report.main(
            [
                "--fmp-integrated-smoke",
                "--as-of",
                "2026-09-15T12:54:25.196678Z",
            ]
        )
        == 0
    )
    assert captured["provider"] is provider
    assert captured["research_as_of"] == datetime(
        2026, 9, 15, 12, 54, 25, 196678, tzinfo=UTC
    )
    assert captured["argv"] == [
        "--asset-id",
        "US:AAPL",
        "--end-date",
        "2026-09-15",
        "--verify-reuse",
    ]


def test_resume_mode_is_forwarded_without_starting_a_new_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI should explicitly select the same-run post-acquisition path."""

    captured: dict[str, object] = {}

    async def resumed_run(
        sector_context_path: Path | None,
        research_clock: object,
        *,
        resume_acquired_run: bool,
        rerun_research: bool,
    ) -> dict[str, object]:
        captured["sector_context_path"] = sector_context_path
        captured["research_clock"] = research_clock
        captured["resume_acquired_run"] = resume_acquired_run
        captured["rerun_research"] = rerun_research
        return {"status": "ok", "run_id": "same-run"}

    monkeypatch.setattr(live_report, "_run", resumed_run)

    assert (
        live_report.main(
            [
                "--resume-acquired-run",
                "--sector-context",
                "context.json",
                "--as-of",
                "2026-09-16T06:17:59.936450Z",
            ]
        )
        == 0
    )
    assert captured["sector_context_path"] == Path("context.json")
    assert captured["resume_acquired_run"] is True
    assert captured["rerun_research"] is False
    assert json.loads(capsys.readouterr().out) == {
        "run_id": "same-run",
        "status": "ok",
    }


def test_manifest_agent_query_matches_bootstrapped_schema(tmp_path: Path) -> None:
    """Manifest collection must use real agent_runs persistence columns."""

    database = DuckDBDatabase(tmp_path / "manifest.duckdb")
    database.bootstrap()

    assert live_report._agent_run_manifest_rows(database) == []


def test_numeric_diagnostic_treats_complete_iso_timestamp_as_metadata() -> None:
    """Timestamp components are not standalone financial numeric facts."""

    assert live_report._numeric_fact_tokens(
        "Score was 48.0 as of 2026-09-16T03:59:59Z."
    ) == ["48.0"]


def test_numeric_diagnostic_retains_numbers_outside_timestamp() -> None:
    """Timestamp handling must not suppress unsupported numeric facts."""

    assert live_report._numeric_fact_tokens(
        "Score 48.0 changed by 15 as of 2026-09-16T03:59:59+00:00."
    ) == ["48.0", "15"]


def test_sec_filing_window_is_independent_from_short_price_window() -> None:
    """Sparse filings use the bounded SEC lookback, not the EOD price window."""

    data_start = date(2025, 1, 1)
    data_end = date(2025, 1, 15)
    sec_start = data_end - timedelta(days=live_report._SEC_LOOKBACK_DAYS)

    assert (data_end - data_start).days == 14
    assert live_report._SEC_LOOKBACK_DAYS == 740
    assert sec_start == date(2023, 1, 6)


def test_live_phase4_sector_context_resolver_is_explicit_and_aligned(
    tmp_path: Path,
) -> None:
    """The live entry should load one exact PIT Sector artifact for injection."""

    settings = AppSettings()
    bundle = _aapl_bundle()
    settings.live.as_of_date = bundle.research_as_of.date()
    expected_as_of = datetime.combine(
        settings.live.as_of_date,
        time.max,
        tzinfo=UTC,
    )
    bundle = SectorContextBundle.model_validate(
        {
            **bundle.model_dump(mode="json"),
            "research_as_of": expected_as_of,
        }
    )
    path = tmp_path / "sector-context.json"
    path.write_text(bundle.model_dump_json(), encoding="utf-8")

    resolver, loaded = live_report._load_sector_context_resolver(path, settings)

    assert resolver is not None
    assert loaded == bundle
    resolution = resolver.resolve(
        asset_id=bundle.asset_id,
        research_as_of=expected_as_of,
    )
    assert resolution.bundle == bundle
    assert "NVIDIA_AI_INFRA" in resolution.bundle.active_chain_ids


def test_live_workflow_factory_injects_sector_context_resolver() -> None:
    """The checked-in live factory must pass the resolver to orchestration."""

    bundle = _aapl_bundle()
    resolver = FrozenSectorContextResolver(bundle)
    dependency = cast(Any, object())

    workflow = live_report._build_research_workflow(
        provider=dependency,
        ingestion=dependency,
        market_data=dependency,
        documents=dependency,
        document_indexer=dependency,
        memory=dependency,
        coordinator=dependency,
        report_pipeline=dependency,
        data_bundle_builder=dependency,
        model_name="fixed-live-model",
        dataset_version="fixed-live-dataset-v1",
        sector_context_resolver=resolver,
    )

    assert workflow._sector_context_resolver is resolver


def test_sector_claim_sources_join_the_structured_traceability_bridge() -> None:
    """Accepted Sector Claim evidence must remain resolvable in the report gate."""

    sector_context = _aapl_bundle()
    empty_bundle = cast(
        Any,
        SimpleNamespace(
            **{
                capability.value: SimpleNamespace(items=())
                for capability in DataCapability
            }
        ),
    )

    references = live_report._structured_references(empty_bundle, sector_context)
    actual = {
        (
            reference.document_id,
            reference.excerpt_ref,
            reference.provider,
            reference.source_url,
        )
        for reference in references
    }
    expected = {
        (
            reference.document_id,
            reference.excerpt_ref,
            reference.provider,
            reference.source_url,
        )
        for claim in sector_context.accepted_claims
        for reference in claim.source_references
    }

    assert expected
    assert expected <= actual


def test_judge_payload_keeps_only_report_cited_evidence() -> None:
    """Semantic evaluation should not receive thousands of unrelated records."""

    cited = SourceReference(
        document_id="document-1",
        excerpt_ref="excerpt-1",
        provider="provider-1",
    )
    evidence = [
        EvaluationEvidenceItem(
            evidence_id="ev-cited",
            source_ref=cited,
            text="cited evidence",
            published_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
        EvaluationEvidenceItem(
            evidence_id="ev-unrelated",
            source_ref=SourceReference(
                document_id="document-2",
                excerpt_ref="excerpt-2",
                provider="provider-2",
            ),
            text="unrelated evidence",
            published_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
    ]
    report = cast(Any, SimpleNamespace(source_trace=(cited,)))

    selected = live_report._cited_evaluation_evidence(report, evidence)

    assert [item.evidence_id for item in selected] == ["ev-cited"]
