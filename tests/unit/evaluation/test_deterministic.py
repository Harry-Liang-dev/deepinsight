"""Tests for objective report-quality checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from src.evaluation import DeterministicReportEvaluator, EvaluationRuleLoader
from src.models.types import JsonObject, JsonValue
from src.schemas.common import SourceReference
from src.schemas.evaluation import EvaluationEvidenceItem, EvaluationInput


def _scores(
    payload: EvaluationInput,
    loader: EvaluationRuleLoader,
) -> dict[str, float]:
    rules = loader.load(payload.ruleset_version)
    return {
        item.check_id: item.score
        for item in DeterministicReportEvaluator().evaluate(payload, rules)
    }


def test_complete_attributable_report_passes_objective_checks(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """The baseline fixture is structurally complete and fully traceable."""

    scores = _scores(evaluation_input, rule_loader)

    assert set(scores) == {
        "structure_completeness",
        "numeric_grounding",
        "citation_coverage",
        "citation_traceability",
        "uncertainty_presence",
        "temporal_validity",
        "trading_instruction_compliance",
        "missing_data_disclosure",
    }
    assert all(score == 1.0 for score in scores.values())


def test_malformed_section_and_uncited_claim_reduce_scores(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Checks inspect report content instead of trusting report status."""

    raw = evaluation_input.report.report_json.copy()
    fundamentals = cast(JsonObject, raw["fundamentals"]).copy()
    facts = list(cast(list[JsonValue], fundamentals["facts"]))
    first = cast(JsonObject, facts[0]).copy()
    first["citations"] = []
    facts[0] = first
    fundamentals["facts"] = facts
    raw["fundamentals"] = cast(JsonValue, fundamentals)
    del raw["sentiment"]
    payload = evaluation_input.model_copy(
        update={
            "report": evaluation_input.report.model_copy(update={"report_json": raw})
        }
    )

    scores = _scores(payload, rule_loader)

    assert scores["structure_completeness"] < 1.0
    assert scores["citation_coverage"] < 1.0


def test_numeric_quality_uses_upstream_claim_validation_status(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Evaluation does not duplicate Analyst raw grounding over report prose."""

    raw = evaluation_input.report.report_json.copy()
    fundamentals = cast(JsonObject, raw["fundamentals"]).copy()
    facts = list(cast(list[JsonValue], fundamentals["facts"]))
    first = cast(JsonObject, facts[0]).copy()
    first["text"] = "Revenue increased 12.5%."
    first["numeric_literals"] = ["12.5%"]
    first["claim_status"] = "accepted"
    facts[0] = first
    fundamentals["facts"] = facts
    raw["fundamentals"] = cast(JsonValue, fundamentals)
    payload = evaluation_input.model_copy(
        update={
            "report": evaluation_input.report.model_copy(update={"report_json": raw})
        }
    )

    assert _scores(payload, rule_loader)["numeric_grounding"] == 1.0


def test_numeric_grounding_does_not_treat_sentence_comma_as_token(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Punctuation after an evidence-backed number is not part of the number."""

    raw = evaluation_input.report.report_json.copy()
    fundamentals = cast(JsonObject, raw["fundamentals"]).copy()
    facts = list(cast(list[JsonValue], fundamentals["facts"]))
    first = cast(JsonObject, facts[0]).copy()
    first["text"] = "Revenue was 100, and remained evidence-backed."
    facts[0] = first
    fundamentals["facts"] = facts
    raw["fundamentals"] = cast(JsonValue, fundamentals)
    evidence = evaluation_input.evidence_items[0].model_copy(
        update={"text": "Revenue was 100 in the filing."}
    )
    payload = evaluation_input.model_copy(
        update={
            "report": evaluation_input.report.model_copy(update={"report_json": raw}),
            "evidence_items": [evidence],
        }
    )

    assert _scores(payload, rule_loader)["numeric_grounding"] == 1.0


def test_source_date_markdown_and_missing_data_are_independent(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Markdown prose cannot create a second compliance decision channel."""

    evidence = evaluation_input.evidence_items[0].model_copy(
        update={"published_at": datetime(2023, 1, 1, tzinfo=UTC)}
    )
    report = evaluation_input.report.model_copy(
        update={
            "report_markdown": (
                f"{evaluation_input.report.report_markdown}\nBuy the shares."
            )
        }
    )
    payload = evaluation_input.model_copy(
        update={
            "report": report,
            "evidence_items": [evidence],
            "known_missing_data": ["structured_features.pe_ttm"],
        }
    )

    scores = _scores(payload, rule_loader)

    assert scores["temporal_validity"] == 0.0
    assert scores["trading_instruction_compliance"] == 1.0
    assert scores["missing_data_disclosure"] == 0.0


def test_unresolved_source_and_absent_uncertainty_are_not_silently_accepted(
    evaluation_input: EvaluationInput,
    rule_loader: EvaluationRuleLoader,
) -> None:
    """Traceability and uncertainty presence use independent source inputs."""

    raw = evaluation_input.report.report_json.copy()
    for name, value in raw.items():
        section = cast(JsonObject, value).copy()
        section["uncertainties"] = []
        raw[name] = section
    report = evaluation_input.report.model_copy(update={"report_json": raw})
    evidence = EvaluationEvidenceItem(
        evidence_id="unrelated",
        source_ref=SourceReference(
            document_id="other-document",
            excerpt_ref="other-chunk",
        ),
        text="Unrelated source text.",
        published_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    payload = evaluation_input.model_copy(
        update={"report": report, "evidence_items": [evidence]}
    )

    scores = _scores(payload, rule_loader)

    assert scores["citation_traceability"] == 0.0
    assert scores["uncertainty_presence"] == 0.0
