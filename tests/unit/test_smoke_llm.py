"""Unit tests for the opt-in live LLM smoke diagnostic surface."""

from __future__ import annotations

from pydantic import SecretStr

from scripts.smoke_llm import _diagnostic_request
from src.core import AppSettings, OpenAISettings


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
