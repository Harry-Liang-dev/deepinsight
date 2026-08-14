"""Tests for Benchmark corpus versioning, markets, and strict references."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from src.models.enums import BenchmarkFixtureKind, ReportMarketScope
from src.schemas.benchmark import ResearchBenchmarkCase


def test_v1_corpus_covers_all_markets_and_required_scenarios(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """The small corpus covers the seven requested quality boundaries."""

    assert len(benchmark_cases) == 7
    assert {case.market for case in benchmark_cases} == {
        ReportMarketScope.CN,
        ReportMarketScope.HK,
        ReportMarketScope.US,
    }
    assert {case.scenario for case in benchmark_cases} == {
        "complete_company",
        "financial_data_missing",
        "news_fundamental_conflict",
        "high_volatility_major_event",
        "provider_partial_failure",
        "memory_empty",
        "analyst_failure",
    }


def test_every_case_has_auditable_source_expectations_and_thresholds(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """No case omits provenance, forbidden conclusions, or minimum gates."""

    for case in benchmark_cases:
        assert case.sources
        assert case.expected.required_facts
        assert case.expected.forbidden_conclusions
        assert case.thresholds.lifecycle_compliance_min == 1.0
        assert all(source.provider for source in case.sources)
        assert all(source.source_locator for source in case.sources)
        assert all(source.usage_basis for source in case.sources)
        assert all(source.collected_at for source in case.sources)
        assert all(source.published_at for source in case.sources)
        if case.market in {ReportMarketScope.CN, ReportMarketScope.HK}:
            assert all(
                source.fixture_kind is BenchmarkFixtureKind.SYNTHETIC
                for source in case.sources
            )


def test_unknown_claim_evidence_is_rejected(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """A report statement cannot cite an undefined Benchmark source."""

    raw = copy.deepcopy(benchmark_cases[0].model_dump(mode="json"))
    assert isinstance(raw["report"], dict)
    raw["report"]["facts"][0]["evidence_ids"] = ["undefined-source"]

    with pytest.raises(ValidationError, match="unknown evidence"):
        ResearchBenchmarkCase.model_validate(raw)


def test_report_and_failure_observation_are_mutually_exclusive(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """A failed Analyst case cannot carry a fabricated final report."""

    failure = next(
        case for case in benchmark_cases if case.scenario == "analyst_failure"
    )
    report_case = next(case for case in benchmark_cases if case.report is not None)
    assert report_case.report is not None
    raw = failure.model_dump(mode="json")
    raw["report"] = report_case.report.model_dump(mode="json")
    raw["sources"] = [source.model_dump(mode="json") for source in report_case.sources]

    with pytest.raises(ValidationError, match="cannot carry a report"):
        ResearchBenchmarkCase.model_validate(raw)
