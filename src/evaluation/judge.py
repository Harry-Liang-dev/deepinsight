"""LLM Gateway and offline Fake implementations for semantic report judging."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from pydantic import ValidationError

from src.models.enums import (
    EvaluationDimension,
    EvaluationEvidenceKind,
    EvaluatorKind,
)
from src.models.types import JsonObject, JsonValue
from src.schemas.evaluation import (
    EvaluationCheck,
    EvaluationEvidenceRef,
    EvaluationInput,
    EvaluationRuleSet,
    JudgeEvaluation,
    JudgeResponse,
)
from src.schemas.llm import LLMRunMetadata

_JUDGE_DIMENSIONS = {
    "semantic_factuality": EvaluationDimension.FACTUAL_CORRECTNESS,
    "conclusion_evidence_consistency": (
        EvaluationDimension.CONCLUSION_EVIDENCE_CONSISTENCY
    ),
    "bull_bear_balance": EvaluationDimension.BULL_BEAR_BALANCE,
    "risk_identification_quality": EvaluationDimension.RISK_IDENTIFICATION_QUALITY,
    "uncertainty_quality": EvaluationDimension.UNCERTAINTY_EXPRESSION,
    "readability": EvaluationDimension.READABILITY,
}


class JudgeGateway(Protocol):
    """Existing structured LLM Gateway surface required by the Judge."""

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
        """Return structured JSON through the configured Gateway."""
        ...


class JudgeGatewayRunResult(Protocol):
    """Structured Gateway response without importing service implementation."""

    content: JsonObject
    metadata: LLMRunMetadata


class JudgeMetadataGateway(Protocol):
    """Metadata-capable production Gateway used by the semantic Judge."""

    def invoke_json_with_metadata(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[JudgeResponse] | None = None,
    ) -> JudgeGatewayRunResult:
        """Return Judge JSON plus credential-free LLM metadata."""

        ...


class ReportJudge(Protocol):
    """Replaceable semantic report-quality Judge."""

    @property
    def model_name(self) -> str:
        """Return the exact model identity stored with an evaluation."""
        ...

    def evaluate(
        self,
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> JudgeEvaluation:
        """Return exactly the configured semantic checks."""
        ...


class ReportJudgeError(RuntimeError):
    """Raised when a Judge output cannot be safely evaluated."""


class LLMReportJudge:
    """Invoke an LLM Judge only through the existing cached Gateway."""

    def __init__(self, gateway: JudgeGateway, model_name: str) -> None:
        """Bind an injected Gateway and explicit model name."""

        if not model_name.strip():
            raise ValueError("Judge model name cannot be empty")
        self._gateway = gateway
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        """Return the auditable Judge model identifier."""

        return self._model_name

    def evaluate(
        self,
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> JudgeEvaluation:
        """Request and strictly validate the six semantic quality checks."""

        input_payload = cast(
            JsonObject,
            {
                "ruleset_version": rules.version,
                "report": payload.report.model_dump(mode="json"),
                "evidence_items": [
                    item.model_dump(mode="json") for item in payload.evidence_items
                ],
                "known_missing_data": payload.known_missing_data,
            },
        )
        raw, metadata = _invoke_judge_gateway(
            self._gateway,
            model=self._model_name,
            system_prompt=rules.judge_prompt,
            input_payload=input_payload,
            prompt_version=f"evaluation_rules:{rules.version}",
        )
        try:
            response = JudgeResponse.model_validate(_normalize_judge_response(raw))
        except ValidationError as exc:
            raise ReportJudgeError(
                "LLM Judge response failed schema validation"
            ) from exc
        metrics = {metric.check_id: metric for metric in response.metrics}
        if len(metrics) != len(response.metrics):
            raise ReportJudgeError("LLM Judge returned duplicate metric IDs")
        if set(metrics) != set(_JUDGE_DIMENSIONS):
            raise ReportJudgeError("LLM Judge returned an incomplete metric set")
        checks: list[EvaluationCheck] = []
        for check_id, expected_dimension in _JUDGE_DIMENSIONS.items():
            metric = metrics[check_id]
            if metric.dimension is not expected_dimension:
                raise ReportJudgeError(f"LLM Judge dimension did not match {check_id}")
            checks.append(
                EvaluationCheck(
                    check_id=metric.check_id,
                    dimension=metric.dimension,
                    evaluator=EvaluatorKind.LLM_JUDGE,
                    score=metric.score,
                    passed=metric.score >= rules.pass_threshold,
                    reason=metric.reason,
                    evidence=metric.evidence,
                )
            )
        return JudgeEvaluation(checks=checks, llm_run_metadata=metadata)


def _normalize_judge_response(raw: JsonObject) -> JsonObject:
    """Normalize one strict keyed-metric compatibility response.

    Some OpenAI-compatible Providers return the six requested metrics as the
    top-level object instead of wrapping them in ``metrics``. Accept only the
    exact configured key set, preserve score/reason/evidence verbatim, and
    derive identity fields from the local versioned contract.
    """

    if "metrics" in raw or set(raw) != set(_JUDGE_DIMENSIONS):
        return raw
    metrics: list[JsonObject] = []
    for check_id, dimension in _JUDGE_DIMENSIONS.items():
        value = raw.get(check_id)
        if not isinstance(value, dict):
            return raw
        metrics.append(
            {
                **value,
                "check_id": check_id,
                "dimension": dimension.value,
            }
        )
    return {"metrics": cast(list[JsonValue], metrics)}


class FakeReportJudge:
    """Explicit deterministic semantic Judge used by default offline tests."""

    model_name = "fake-report-judge"

    def __init__(self, scores: Mapping[str, float] | None = None) -> None:
        """Configure optional per-check scores without any network dependency."""

        configured = dict(scores or {})
        unknown = set(configured) - set(_JUDGE_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown Fake Judge checks: {sorted(unknown)}")
        if any(score < 0.0 or score > 1.0 for score in configured.values()):
            raise ValueError("Fake Judge scores must be between 0 and 1")
        self._scores = configured

    def evaluate(
        self,
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> JudgeEvaluation:
        """Return deterministic, evidence-carrying semantic checks."""

        del payload
        checks: list[EvaluationCheck] = []
        for check_id, dimension in _JUDGE_DIMENSIONS.items():
            score = self._scores.get(check_id, 1.0)
            checks.append(
                EvaluationCheck(
                    check_id=check_id,
                    dimension=dimension,
                    evaluator=EvaluatorKind.LLM_JUDGE,
                    score=score,
                    passed=score >= rules.pass_threshold,
                    reason=(
                        f"Offline Fake Judge assigned the configured score "
                        f"for {check_id}."
                    ),
                    evidence=[
                        EvaluationEvidenceRef(
                            kind=EvaluationEvidenceKind.DIAGNOSTIC,
                            locator=f"fake_judge:{check_id}",
                        )
                    ],
                )
            )
        return JudgeEvaluation(checks=checks)


def _invoke_judge_gateway(
    gateway: JudgeGateway,
    *,
    model: str,
    system_prompt: str,
    input_payload: JsonObject,
    prompt_version: str,
) -> tuple[JsonObject, LLMRunMetadata | None]:
    metadata_call = getattr(gateway, "invoke_json_with_metadata", None)
    if callable(metadata_call):
        result = cast(JudgeMetadataGateway, gateway).invoke_json_with_metadata(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version="judge_response_v1",
            response_model=JudgeResponse,
        )
        return result.content, result.metadata
    return (
        gateway.invoke_json(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version="judge_response_v1",
            response_model=JudgeResponse,
        ),
        None,
    )
