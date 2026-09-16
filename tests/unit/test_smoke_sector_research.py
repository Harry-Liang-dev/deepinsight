"""Offline regression tests for the Sector Research smoke runtime boundary."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from scripts import smoke_sector_research
from src.core import LLMProviderName
from src.models.enums import AgentStatus, SectorId
from src.schemas.common import ErrorInfo
from src.schemas.sector_research import SectorResearchExecutionResult
from src.services import LLMFailureMetadata


def test_live_sector_smoke_uses_production_factory_and_persists_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Live smoke must share production config and retain safe Gateway RCA."""

    source_paths = tuple(tmp_path / f"source-{index}.duckdb" for index in range(3))
    for path in source_paths:
        path.touch()
    output_root = tmp_path / "output"
    settings = object()
    provider = SimpleNamespace(provider_name="qwen")
    factory_calls: list[object] = []
    gateway_options: dict[str, object] = {}

    def configured_factory(received: object) -> SimpleNamespace:
        factory_calls.append(received)
        return SimpleNamespace(
            provider=provider,
            provider_name=LLMProviderName.QWEN,
            model_default="qwen-configured-model",
        )

    class GatewayStub:
        def __init__(self, cache: object, **kwargs: object) -> None:
            del cache
            gateway_options.update(kwargs)

    class AgentStub:
        def __init__(self, gateway: object, prompt_loader: object) -> None:
            del gateway, prompt_loader

        def run(self, **kwargs: object) -> SectorResearchExecutionResult:
            failure_sink = gateway_options["failure_sink"]
            failure_sink = cast(Any, failure_sink)
            failure_sink.record_failure(
                LLMFailureMetadata(
                    provider="qwen",
                    model=str(kwargs["model_name"]),
                    error_code="configuration_error",
                    error_message_safe=(
                        "Qwen client initialization requires HTTPX SOCKS support"
                    ),
                    configuration_stage="client_initialization",
                    timestamp=datetime(2026, 9, 15, tzinfo=UTC),
                )
            )
            return SectorResearchExecutionResult(
                run_id=str(kwargs["run_id"]),
                status=AgentStatus.ERROR,
                error=ErrorInfo(
                    code="configuration_error",
                    message="LLM provider request failed during Sector research.",
                ),
            )

    research_input = SimpleNamespace(
        sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
    )
    monkeypatch.setattr(smoke_sector_research, "load_settings", lambda: settings)
    monkeypatch.setattr(
        smoke_sector_research,
        "build_configured_llm_provider",
        configured_factory,
    )
    monkeypatch.setattr(smoke_sector_research, "LLMGateway", GatewayStub)
    monkeypatch.setattr(smoke_sector_research, "DuckDBDatabase", lambda path: path)
    monkeypatch.setattr(
        smoke_sector_research,
        "SectorOntologyRepository",
        lambda database: database,
    )
    monkeypatch.setattr(
        smoke_sector_research,
        "_latest_common_as_of",
        lambda state, macro: date(2026, 8, 29),
    )
    monkeypatch.setattr(
        smoke_sector_research,
        "_build_input",
        lambda *args, **kwargs: research_input,
    )
    monkeypatch.setattr(smoke_sector_research, "SectorResearchAgent", AgentStub)
    monkeypatch.setattr(
        smoke_sector_research,
        "SectorResearchPromptLoader",
        lambda path: path,
    )

    exit_code = smoke_sector_research.main(
        [
            "--live",
            "--sector",
            "S03",
            "--sector-state-db",
            str(source_paths[0]),
            "--sector-macro-db",
            str(source_paths[1]),
            "--sector-radar-db",
            str(source_paths[2]),
            "--output-root",
            str(output_root),
        ]
    )

    manifest_path = next(output_root.glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sector = manifest["sectors"][0]
    assert exit_code == 1
    assert factory_calls == [settings]
    assert gateway_options["provider"] is provider
    assert sector == {
        "configuration_stage": "client_initialization",
        "error_code": "configuration_error",
        "error_details": None,
        "error_message_safe": (
            "Qwen client initialization requires HTTPX SOCKS support"
        ),
        "model": "qwen-configured-model",
        "provider": "qwen",
        "sector_id": "S03",
        "status": "error",
    }
    assert manifest["gates"] == {
        "gateway_initialization": "FAIL",
        "sector_validation": "NOT_REACHED",
    }
    assert manifest["prompt_version"] == "sector_research_prompt_v4"
    assert "API key" not in manifest_path.read_text(encoding="utf-8")


def test_sector_smoke_model_override_does_not_change_production_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI model resolution may override only the factory's configured model."""

    captured: dict[str, Any] = {}
    configured = SimpleNamespace(
        provider=SimpleNamespace(provider_name="qwen"),
        provider_name=LLMProviderName.QWEN,
        model_default="qwen-configured-model",
    )

    class GatewayStub:
        def __init__(self, cache: object, **kwargs: object) -> None:
            del cache
            captured.update(kwargs)

    for name in ("state", "macro", "radar"):
        (tmp_path / f"{name}.duckdb").touch()
    monkeypatch.setattr(smoke_sector_research, "load_settings", object)
    monkeypatch.setattr(
        smoke_sector_research,
        "build_configured_llm_provider",
        lambda settings: configured,
    )
    monkeypatch.setattr(smoke_sector_research, "LLMGateway", GatewayStub)
    monkeypatch.setattr(smoke_sector_research, "DuckDBDatabase", lambda path: path)
    monkeypatch.setattr(
        smoke_sector_research,
        "SectorOntologyRepository",
        lambda database: database,
    )
    monkeypatch.setattr(
        smoke_sector_research,
        "_latest_common_as_of",
        lambda state, macro: date(2026, 8, 29),
    )

    research_input = SimpleNamespace(
        sector_id=SectorId.CONSUMER_ELECTRONICS_HARDWARE,
    )
    monkeypatch.setattr(
        smoke_sector_research,
        "_build_input",
        lambda *args, **kwargs: research_input,
    )

    class AgentStub:
        def __init__(self, gateway: object, prompt_loader: object) -> None:
            del gateway, prompt_loader

        def run(self, **kwargs: object) -> SectorResearchExecutionResult:
            captured["model_name"] = kwargs["model_name"]
            return SectorResearchExecutionResult(
                run_id=str(kwargs["run_id"]),
                status=AgentStatus.ERROR,
                error=ErrorInfo(code="remote_error", message="safe remote error"),
            )

    monkeypatch.setattr(smoke_sector_research, "SectorResearchAgent", AgentStub)
    monkeypatch.setattr(
        smoke_sector_research,
        "SectorResearchPromptLoader",
        lambda path: path,
    )

    exit_code = smoke_sector_research.main(
        [
            "--live",
            "--model",
            "qwen-explicit-model",
            "--sector",
            "S03",
            "--sector-state-db",
            str(tmp_path / "state.duckdb"),
            "--sector-macro-db",
            str(tmp_path / "macro.duckdb"),
            "--sector-radar-db",
            str(tmp_path / "radar.duckdb"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )

    assert exit_code == 1
    assert captured["provider"] is configured.provider
    assert captured["model_name"] == "qwen-explicit-model"
