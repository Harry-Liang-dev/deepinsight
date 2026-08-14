"""Unit tests for the opt-in live LLM smoke diagnostic surface."""

from __future__ import annotations

from typing import cast

from pydantic import SecretStr

from scripts.smoke_llm import _diagnostic_request, _validate_response
from src.core import (
    AppSettings,
    LLMProviderName,
    LLMSettings,
    OpenAISettings,
    QwenSettings,
)


def test_diagnostic_request_matches_provider_request_without_credentials() -> None:
    """Diagnostic output should show the exact body and omit authorization."""

    settings = AppSettings(
        openai=OpenAISettings(
            api_key=SecretStr("must-not-appear"),
            model_fast="gpt-5.6-luna",
            timeout_seconds=17,
            max_retries=0,
            store_remote=False,
        )
    )

    diagnostic = _diagnostic_request(settings)

    assert diagnostic["endpoint"] == "https://api.openai.com/v1/responses"
    assert diagnostic["provider"] == "openai"
    assert diagnostic["request_body"] == {
        "model": "gpt-5.6-luna",
        "instructions": (
            "Return only one compact JSON object with exactly these fields: "
            "confirmed_risks, scenario_risks, watch_items, "
            "narrative_risk_score. Each list must contain exactly one short "
            "string. narrative_risk_score must be a number from 0 to 1. "
            "Do not add markdown, citations, recommendations, or extra fields."
        ),
        "input": 'JSON input:\n{"context":"deepinsight-live-smoke-minimal-input"}',
        "text": {"format": {"type": "json_object"}},
        "store": False,
    }
    assert "api_key" not in repr(diagnostic)
    assert "must-not-appear" not in repr(diagnostic)


def test_qwen_diagnostic_uses_selected_provider_without_credentials() -> None:
    """Qwen diagnostics should describe the same unified request boundary."""

    settings = AppSettings(
        llm=LLMSettings(provider=LLMProviderName.QWEN),
        qwen=QwenSettings(
            api_key=SecretStr("qwen-must-not-appear"),
            model_fast="qwen3.7-flash",
            base_url="https://example.invalid/compatible-mode/v1",
            timeout_seconds=19,
            max_retries=0,
            store_remote=False,
            enable_thinking=False,
        ),
    )

    diagnostic = _diagnostic_request(settings)
    request_body = cast(dict[str, object], diagnostic["request_body"])

    assert diagnostic["provider"] == "qwen"
    assert diagnostic["endpoint"] == (
        "https://example.invalid/compatible-mode/v1/responses"
    )
    assert request_body["model"] == "qwen3.7-flash"
    assert request_body["enable_thinking"] is False
    assert "qwen-must-not-appear" not in repr(diagnostic)


def test_smoke_accepts_schema_valid_nonempty_provider_lists() -> None:
    """Smoke must not add a stricter list cardinality than the Agent schema."""

    response = _validate_response(
        {
            "confirmed_risks": ["first", "second"],
            "scenario_risks": ["scenario"],
            "watch_items": ["watch"],
            "narrative_risk_score": 0.25,
        }
    )

    assert response.confirmed_risks == ["first", "second"]
