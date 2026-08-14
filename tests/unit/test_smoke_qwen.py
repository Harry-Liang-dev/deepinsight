"""Offline tests for the Qwen compatibility smoke entry point."""

from __future__ import annotations

import json

import pytest

from scripts import smoke_qwen


def test_qwen_smoke_requires_explicit_provider_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The compatibility command must not silently override runtime config."""

    monkeypatch.setenv("DEEPINSIGHT_LLM_PROVIDER", "openai")

    assert smoke_qwen.main([]) == 2
    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "configuration_error"
    assert "DEEPINSIGHT_LLM_PROVIDER=qwen" in result["message"]


def test_qwen_smoke_delegates_to_unified_gateway_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qwen smoke must contain no independent SDK invocation path."""

    calls: list[object] = []
    monkeypatch.setenv("DEEPINSIGHT_LLM_PROVIDER", "qwen")

    def delegate(argv: object) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(
        smoke_qwen,
        "gateway_smoke_main",
        delegate,
    )

    assert smoke_qwen.main(["--diagnostic"]) == 0
    assert calls == [["--diagnostic"]]
