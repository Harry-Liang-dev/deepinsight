"""Versioned and auditable research-report evaluation contracts."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import (
    EvaluationDimension,
    EvaluationEvidenceKind,
    EvaluatorKind,
)
from src.models.types import DomainModel
from src.schemas.common import SourceReference
from src.schemas.llm import LLMRunMetadata
from src.schemas.reports import ResearchReport


class EvaluationEvidenceItem(DomainModel):
    """Source text available to deterministic checks and the LLM Judge."""

    evidence_id: str = Field(min_length=1)
    source_ref: SourceReference
    text: str = Field(min_length=1)
    published_at: datetime | None = None


class EvaluationInput(DomainModel):
    """Complete immutable input required to evaluate one report."""

    report: ResearchReport
    evidence_items: list[EvaluationEvidenceItem]
    known_missing_data: list[str] = Field(default_factory=list)
    ruleset_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> Self:
        """Reject ambiguous evidence identifiers."""

        identifiers = [item.evidence_id for item in self.evidence_items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evaluation evidence IDs must be unique")
        return self


class EvaluationEvidenceRef(DomainModel):
    """One report, source, or diagnostic locator supporting a score."""

    kind: EvaluationEvidenceKind
    locator: str = Field(min_length=1)
    excerpt: str | None = None


class EvaluationCheck(DomainModel):
    """One independently auditable deterministic or Judge score."""

    check_id: str = Field(min_length=1)
    dimension: EvaluationDimension
    evaluator: EvaluatorKind
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str = Field(min_length=1)
    evidence: list[EvaluationEvidenceRef] = Field(min_length=1)


class JudgeEvaluation(DomainModel):
    """Semantic checks paired with optional real Gateway run metadata."""

    checks: list[EvaluationCheck] = Field(min_length=1)
    llm_run_metadata: LLMRunMetadata | None = None


class DimensionScore(DomainModel):
    """Versioned aggregation of one or more component checks."""

    dimension: EvaluationDimension
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str = Field(min_length=1)
    evidence: list[EvaluationEvidenceRef] = Field(min_length=1)
    component_check_ids: list[str] = Field(min_length=1)


class JudgeMetric(DomainModel):
    """Strict structured metric returned by an LLM Judge."""

    check_id: str = Field(min_length=1)
    dimension: EvaluationDimension
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    evidence: list[EvaluationEvidenceRef] = Field(min_length=1)


class JudgeResponse(DomainModel):
    """Structured LLM Judge response before local pass/fail derivation."""

    metrics: list[JudgeMetric] = Field(min_length=1)


class EvaluationRuleSet(DomainModel):
    """Versioned thresholds, weights, time rules, and Judge prompt."""

    version: str = Field(min_length=1)
    pass_threshold: float = Field(ge=0.0, le=1.0)
    max_evidence_age_days: int = Field(gt=0)
    dimension_weights: dict[EvaluationDimension, float]
    component_weights: dict[EvaluationDimension, dict[str, float]]
    judge_prompt: str = Field(min_length=1)

    @field_validator("judge_prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        """Reject whitespace-only Judge instructions."""

        if not value.strip():
            raise ValueError("evaluation Judge prompt cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_weights(self) -> Self:
        """Require complete positive dimension and component weights."""

        dimensions = set(EvaluationDimension)
        if set(self.dimension_weights) != dimensions:
            raise ValueError("dimension weights must cover all evaluation dimensions")
        if set(self.component_weights) != dimensions:
            raise ValueError("component weights must cover all evaluation dimensions")
        if any(
            not math.isfinite(weight) or weight <= 0
            for weight in self.dimension_weights.values()
        ):
            raise ValueError("dimension weights must be positive")
        for weights in self.component_weights.values():
            if not weights or any(
                not math.isfinite(weight) or weight <= 0 for weight in weights.values()
            ):
                raise ValueError("component weights must be non-empty and positive")
        return self


class EvaluationResult(DomainModel):
    """Complete persisted output of one report evaluation run."""

    evaluation_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_checks: list[EvaluationCheck] = Field(min_length=1)
    judge_checks: list[EvaluationCheck] = Field(min_length=1)
    dimensions: list[DimensionScore] = Field(min_length=1)
    deterministic_score: float = Field(ge=0.0, le=1.0)
    judge_score: float = Field(ge=0.0, le=1.0)
    judge_run_metadata: LLMRunMetadata | None = None
    overall_score: float = Field(ge=0.0, le=1.0)
    evaluated_at: datetime

    @model_validator(mode="after")
    def validate_complete_unique_result(self) -> Self:
        """Require unique checks and exactly twelve dimensions."""

        checks = [*self.deterministic_checks, *self.judge_checks]
        if any(
            check.evaluator is not EvaluatorKind.DETERMINISTIC
            for check in self.deterministic_checks
        ):
            raise ValueError("deterministic checks must use deterministic evaluator")
        if any(
            check.evaluator is not EvaluatorKind.LLM_JUDGE
            for check in self.judge_checks
        ):
            raise ValueError("Judge checks must use LLM Judge evaluator")
        check_ids = [check.check_id for check in checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("evaluation check IDs must be unique")
        dimensions = [item.dimension for item in self.dimensions]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("evaluation dimensions must be unique")
        if set(dimensions) != set(EvaluationDimension):
            raise ValueError("evaluation result must contain all dimensions")
        known_checks = set(check_ids)
        if any(
            check_id not in known_checks
            for dimension in self.dimensions
            for check_id in dimension.component_check_ids
        ):
            raise ValueError("dimension referenced an unknown component check")
        return self
