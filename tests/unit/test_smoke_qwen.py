"""Offline tests for the temporary Qwen compatibility smoke script."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.smoke_qwen import (
    QwenSmokeConfig,
    QwenSmokeError,
    _diagnostic_request,
    _run_live,
    _validate_response,
)


class _ResponsesStub:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


class _ClientStub:
    def __init__(self, response: SimpleNamespace) -> None:
        self.responses = _ResponsesStub(response)


def _response(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_qwen_smoke",
        model="qwen3.8-max",
        output_text=output_text,
        output=[
            SimpleNamespace(
                type="reasoning",
                summary=[SimpleNamespace(text="bounded reasoning summary")],
            )
        ],
        usage=SimpleNamespace(input_tokens=21, output_tokens=16),
    )


def _valid_output() -> str:
    return json.dumps(
        {
            "confirmed_risks": ["one"],
            "scenario_risks": ["two"],
            "watch_items": ["three"],
            "narrative_risk_score": 0.25,
        }
    )


def test_diagnostic_request_contains_no_api_key() -> None:
    config = QwenSmokeConfig(
        api_key="secret-value",
        model="qwen3.8-max",
        base_url="https://example.invalid/compatible-mode/v1",
    )

    diagnostic = _diagnostic_request(config)

    assert diagnostic["endpoint"] == (
        "https://example.invalid/compatible-mode/v1/responses"
    )
    assert diagnostic["request_body"] == {
        "model": "qwen3.8-max",
        "input": (
            "Return only one compact JSON object. Do not use Markdown code fences.\n"
            "The JSON object must contain exactly these fields:\n"
            '- "confirmed_risks": an array containing exactly one short string\n'
            '- "scenario_risks": an array containing exactly one short string\n'
            '- "watch_items": an array containing exactly one short string\n'
            '- "narrative_risk_score": a number from 0 to 1\n'
            "Use this minimal context: deepinsight-qwen-live-smoke.\n"
            "Do not include investment advice, citations, or additional fields.\n"
        ),
        "enable_thinking": True,
    }
    assert "secret-value" not in repr(diagnostic)


def test_run_live_makes_one_request_and_validates_existing_schema() -> None:
    config = QwenSmokeConfig(
        api_key="secret-value",
        model="qwen3.8-max",
        base_url="https://example.invalid/compatible-mode/v1",
    )
    client = _ClientStub(_response(_valid_output()))

    result = _run_live(config, client=client, diagnostic=True)

    assert len(client.responses.calls) == 1
    assert client.responses.calls[0]["model"] == "qwen3.8-max"
    assert client.responses.calls[0]["extra_body"] == {"enable_thinking": True}
    assert result["status"] == "ok"
    assert result["schema"] == "RiskManagerResponse"
    assert result["input_tokens"] == 21
    assert result["output_tokens"] == 16
    assert result["reasoning_summary_previews"] == ["bounded reasoning summary"]
    assert "secret-value" not in repr(result)


@pytest.mark.parametrize("output_text", ["not-json", "[]"])
def test_validate_response_rejects_non_object_json(output_text: str) -> None:
    with pytest.raises(QwenSmokeError, match="JSON"):
        _validate_response(_response(output_text))


def test_validate_response_rejects_schema_mismatch() -> None:
    with pytest.raises(QwenSmokeError, match="RiskManagerResponse"):
        _validate_response(_response('{"confirmed_risks":[]}'))
