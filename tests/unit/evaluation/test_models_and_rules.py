"""Validation tests for versioned report-evaluation contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evaluation import EvaluationRuleLoader, EvaluationRuleLoadError
from src.models.enums import EvaluationDimension
from src.schemas.evaluation import EvaluationEvidenceItem, EvaluationInput


def test_rule_loader_reads_complete_versioned_rules(
    rule_loader: EvaluationRuleLoader,
) -> None:
    """The checked-in rule set must cover all twelve dimensions."""

    rules = rule_loader.load("report_quality_v1")

    assert rules.version == "report_quality_v1"
    assert set(rules.dimension_weights) == set(EvaluationDimension)
    assert set(rules.component_weights) == set(EvaluationDimension)
    assert rules.pass_threshold == 0.8


def test_v2_preserves_thresholds_and_closes_judge_shape_ambiguity(
    rule_loader: EvaluationRuleLoader,
) -> None:
    """The live rules change only the Qwen-compatible output contract."""

    previous = rule_loader.load("report_quality_v1")
    current = rule_loader.load("report_quality_v2")

    assert current.dimension_weights == previous.dimension_weights
    assert current.component_weights == previous.component_weights
    assert current.pass_threshold == previous.pass_threshold
    assert current.max_evidence_age_days == previous.max_evidence_age_days
    assert 'only top-level key must be "metrics"' in current.judge_prompt
    assert "never return a bare numeric score" in current.judge_prompt


def test_rule_loader_rejects_missing_unsafe_and_mismatched_versions(
    tmp_path: Path,
) -> None:
    """Callers cannot escape the rule directory or relabel a rule file."""

    loader = EvaluationRuleLoader(tmp_path)
    with pytest.raises(EvaluationRuleLoadError, match="unavailable"):
        loader.load("report_quality_v1")
    with pytest.raises(EvaluationRuleLoadError, match="invalid"):
        loader.load("../outside")

    (tmp_path / "claimed.yaml").write_text(
        "version: actual\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationRuleLoadError):
        loader.load("claimed")


def test_evaluation_input_rejects_duplicate_evidence_identifiers(
    evaluation_input: EvaluationInput,
) -> None:
    """Evidence IDs remain unambiguous throughout an audit."""

    duplicate = EvaluationEvidenceItem(
        evidence_id=evaluation_input.evidence_items[0].evidence_id,
        source_ref=evaluation_input.evidence_items[0].source_ref,
        text="Different text.",
    )

    raw = evaluation_input.model_dump()
    raw["evidence_items"] = [
        *evaluation_input.evidence_items,
        duplicate,
    ]
    with pytest.raises(ValidationError, match="must be unique"):
        EvaluationInput.model_validate(
            raw,
        )
