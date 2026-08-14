"""Tests for Gateway-backed and offline semantic Judges."""

from __future__ import annotations

from typing import cast

import pytest

from src.evaluation import (
    EvaluationRuleLoader,
    FakeReportJudge,
    LLMReportJudge,
    ReportJudgeError,
)
from src.models.enums import EvaluationDimension, EvaluatorKind
from src.models.types import JsonObject, JsonValue
from src.schemas.evaluation import EvaluationInput, JudgeResponse

_CHECKS = {
    "semantic_factuality": "factual_correctness",
    "conclusion_evidence_consistency": "conclusion_evidence_consistency",
    "bull_bear_balance": "bull_bear_balance",
    "risk_identification_quality": "risk_identification_quality",
    "uncertainty_quality": "uncertainty_expression",
    "readability": "readability",
}


class _Gateway:
    """Capture one structured invocation and return controlled JSON."""

    def __init__(self, response: JsonObject) -> None:
        self.response = response
        self.calls: list[tuple[str, str, JsonObject]] = []

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[JudgeResponse] | None = None,
    ) -> JsonObject:
        assert prompt_version.startswith("evaluation_rules:")
        assert schema_version == "judge_response_v1"
        assert response_model is JudgeResponse
        self.calls.append((model, system_prompt, input_payload))
        return self.response


def _response() -> JsonObject:
    return cast(
        JsonObject,
        {
            "metrics": [
                {
                    "check_id": check_id,
                    "dimension": dimension,
                    "score": 0.9,
                    "reason": f"Evidence supports {check_id}.",
                    "evidence": [
                        {
                            "kind": "report_path",
                            "locator": "report.report_json",
                        }
                    ],
                }
                for check_id, dimension in _CHECKS.items()
            ]
        },
    )


def test_llm_judge_uses_existing_gateway_and_validates_response(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """The live Judge has no second provider-call implementation."""

    rules = rule_loader.load("report_quality_v1")
    gateway = _Gateway(_response())
    result = LLMReportJudge(gateway, "judge-model").evaluate(
        evaluation_input,
        rules,
    )
    checks = result.checks

    assert len(gateway.calls) == 1
    assert gateway.calls[0][0] == "judge-model"
    assert gateway.calls[0][1] == rules.judge_prompt
    report = cast(JsonObject, gateway.calls[0][2]["report"])
    assert report["report_id"] == "report-1"
    assert {item.check_id for item in checks} == set(_CHECKS)
    assert all(item.evaluator is EvaluatorKind.LLM_JUDGE for item in checks)


def test_llm_judge_normalizes_exact_keyed_provider_response(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """A complete keyed response retains scores while local IDs stay canonical."""

    keyed = cast(
        JsonObject,
        {
            check_id: {
                "check_id": dimension,
                "dimension": dimension,
                "score": 0.7,
                "reason": f"Evidence supports {check_id}.",
                "evidence": [
                    {
                        "kind": "report_path",
                        "locator": "report.report_json",
                    }
                ],
            }
            for check_id, dimension in _CHECKS.items()
        },
    )

    result = LLMReportJudge(_Gateway(keyed), "judge-model").evaluate(
        evaluation_input,
        rule_loader.load("report_quality_v1"),
    )
    checks = result.checks

    assert [item.check_id for item in checks] == list(_CHECKS)
    assert all(item.score == 0.7 for item in checks)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("duplicate", "duplicate"),
        ("missing", "incomplete"),
        ("unknown", "incomplete"),
        ("out_of_range", "schema validation"),
    ],
)
def test_llm_judge_rejects_invalid_contract(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
    failure: str,
    message: str,
) -> None:
    """Plausible but invalid Judge payloads cannot be silently accepted."""

    rules = rule_loader.load("report_quality_v1")
    response = _response()
    metrics = cast(list[JsonValue], response["metrics"])
    if failure == "duplicate":
        response["metrics"] = [*metrics[:-1], metrics[0]]
    elif failure == "missing":
        response["metrics"] = metrics[:-1]
    else:
        last = cast(JsonObject, metrics[-1]).copy()
        if failure == "unknown":
            last["check_id"] = "unsupported_metric"
        else:
            last["score"] = 1.1
        response["metrics"] = [*metrics[:-1], last]

    with pytest.raises(ReportJudgeError, match=message):
        LLMReportJudge(_Gateway(response), "judge-model").evaluate(
            evaluation_input,
            rules,
        )


def test_fake_judge_is_deterministic_and_evidence_carrying(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Default tests can exercise aggregation without network access."""

    rules = rule_loader.load("report_quality_v1")
    result = FakeReportJudge({"readability": 0.4}).evaluate(
        evaluation_input,
        rules,
    )
    checks = result.checks

    assert len(checks) == 6
    assert next(item for item in checks if item.check_id == "readability").score == 0.4
    assert all(item.reason and item.evidence for item in checks)
    assert {item.dimension for item in checks} == {
        EvaluationDimension.FACTUAL_CORRECTNESS,
        EvaluationDimension.CONCLUSION_EVIDENCE_CONSISTENCY,
        EvaluationDimension.BULL_BEAR_BALANCE,
        EvaluationDimension.RISK_IDENTIFICATION_QUALITY,
        EvaluationDimension.UNCERTAINTY_EXPRESSION,
        EvaluationDimension.READABILITY,
    }
