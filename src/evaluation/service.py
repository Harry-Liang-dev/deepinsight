"""Application service for reproducible report-quality evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from src.evaluation.deterministic import DeterministicReportEvaluator
from src.evaluation.judge import ReportJudge
from src.evaluation.rules import EvaluationRuleLoader
from src.models.enums import EvaluationDimension, EvaluatorKind
from src.schemas.evaluation import (
    DimensionScore,
    EvaluationCheck,
    EvaluationEvidenceRef,
    EvaluationInput,
    EvaluationResult,
    EvaluationRuleSet,
)


class EvaluationStore(Protocol):
    """Persistence boundary for complete evaluation results."""

    def save(self, result: EvaluationResult) -> None:
        """Persist one evaluation without overwriting an existing ID."""
        ...


class EvaluationError(RuntimeError):
    """Raised when checks cannot form one complete versioned result."""


class ReportEvaluationService:
    """Coordinate deterministic checks, semantic Judge, aggregation, and storage."""

    def __init__(
        self,
        rule_loader: EvaluationRuleLoader,
        deterministic_evaluator: DeterministicReportEvaluator,
        judge: ReportJudge,
        store: EvaluationStore,
        *,
        evaluation_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind replaceable evaluation dependencies."""

        if not judge.model_name.strip():
            raise ValueError("Judge model cannot be empty")
        self._rule_loader = rule_loader
        self._deterministic_evaluator = deterministic_evaluator
        self._judge = judge
        self._store = store
        self._judge_model = judge.model_name
        self._evaluation_id_factory = evaluation_id_factory or (
            lambda: f"eval_{uuid4().hex}"
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        """Evaluate, aggregate, persist, and return one report result."""

        rules = self._rule_loader.load(payload.ruleset_version)
        deterministic = self._deterministic_evaluator.evaluate(payload, rules)
        judge_result = self._judge.evaluate(payload, rules)
        judge = judge_result.checks
        all_checks = [*deterministic, *judge]
        _validate_check_contract(all_checks, rules)
        dimensions = _aggregate_dimensions(all_checks, rules)
        result = EvaluationResult(
            evaluation_id=self._evaluation_id_factory(),
            report_id=payload.report.report_id,
            ruleset_version=rules.version,
            judge_model=self._judge_model,
            input_fingerprint=_input_fingerprint(
                payload,
                rules,
                self._judge_model,
            ),
            deterministic_checks=deterministic,
            judge_checks=judge,
            dimensions=dimensions,
            deterministic_score=_kind_score(
                deterministic,
                rules,
                EvaluatorKind.DETERMINISTIC,
            ),
            judge_score=_kind_score(
                judge,
                rules,
                EvaluatorKind.LLM_JUDGE,
            ),
            judge_run_metadata=judge_result.llm_run_metadata,
            overall_score=_overall_score(dimensions, rules),
            evaluated_at=self._clock(),
        )
        self._store.save(result)
        return result


def _validate_check_contract(
    checks: Sequence[EvaluationCheck],
    rules: EvaluationRuleSet,
) -> None:
    identifiers = [check.check_id for check in checks]
    if len(identifiers) != len(set(identifiers)):
        raise EvaluationError("evaluation returned duplicate check IDs")
    configured = {
        check_id for weights in rules.component_weights.values() for check_id in weights
    }
    if set(identifiers) != configured:
        raise EvaluationError("evaluation checks did not match the rule set")
    by_id = {check.check_id: check for check in checks}
    for dimension, weights in rules.component_weights.items():
        if any(by_id[check_id].dimension is not dimension for check_id in weights):
            raise EvaluationError(
                f"evaluation component dimension mismatch for {dimension.value}"
            )


def _aggregate_dimensions(
    checks: Sequence[EvaluationCheck],
    rules: EvaluationRuleSet,
) -> list[DimensionScore]:
    by_id = {check.check_id: check for check in checks}
    dimensions: list[DimensionScore] = []
    for dimension in EvaluationDimension:
        weights = rules.component_weights[dimension]
        score = _weighted_average(
            (by_id[check_id].score, weight) for check_id, weight in weights.items()
        )
        component_ids = list(weights)
        evidence = _deduplicate_evidence(
            evidence
            for check_id in component_ids
            for evidence in by_id[check_id].evidence
        )
        reason = "Weighted components: " + ", ".join(
            f"{check_id}={by_id[check_id].score:.3f}" for check_id in component_ids
        )
        dimensions.append(
            DimensionScore(
                dimension=dimension,
                score=score,
                passed=score >= rules.pass_threshold,
                reason=reason,
                evidence=evidence,
                component_check_ids=component_ids,
            )
        )
    return dimensions


def _kind_score(
    checks: Sequence[EvaluationCheck],
    rules: EvaluationRuleSet,
    kind: EvaluatorKind,
) -> float:
    weighted: list[tuple[float, float]] = []
    for check in checks:
        if check.evaluator is not kind:
            raise EvaluationError("evaluation check was assigned to the wrong group")
        weight = (
            rules.dimension_weights[check.dimension]
            * rules.component_weights[check.dimension][check.check_id]
        )
        weighted.append((check.score, weight))
    return _weighted_average(weighted)


def _overall_score(
    dimensions: Sequence[DimensionScore],
    rules: EvaluationRuleSet,
) -> float:
    return _weighted_average(
        (item.score, rules.dimension_weights[item.dimension]) for item in dimensions
    )


def _weighted_average(values: Iterable[tuple[float, float]]) -> float:
    collected = list(values)
    denominator = sum(weight for _, weight in collected)
    if denominator <= 0:
        raise EvaluationError("evaluation weights did not have a positive sum")
    return sum(score * weight for score, weight in collected) / denominator


def _input_fingerprint(
    payload: EvaluationInput,
    rules: EvaluationRuleSet,
    judge_model: str,
) -> str:
    evidence = sorted(
        (item.model_dump(mode="json") for item in payload.evidence_items),
        key=lambda item: str(item["evidence_id"]),
    )
    canonical = json.dumps(
        {
            "evidence_items": evidence,
            "judge_model": judge_model,
            "known_missing_data": sorted(payload.known_missing_data),
            "report": payload.report.model_dump(mode="json"),
            "rules": rules.model_dump(mode="json"),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deduplicate_evidence(
    evidence: Iterable[EvaluationEvidenceRef],
) -> list[EvaluationEvidenceRef]:
    unique: dict[tuple[str, str, str], EvaluationEvidenceRef] = {}
    for item in evidence:
        key = (item.kind.value, item.locator, item.excerpt or "")
        unique.setdefault(key, item)
    return list(unique.values())
