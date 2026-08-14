"""Versioned contracts for deterministic research-report Benchmarks."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import (
    BenchmarkExpectedOutcome,
    BenchmarkFixtureKind,
    BenchmarkRunMode,
    EvaluationDimension,
    ReportMarketScope,
)
from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.evaluation import EvaluationResult

_DETERMINISTIC_CHECK_IDS = frozenset(
    {
        "structure_completeness",
        "numeric_grounding",
        "citation_coverage",
        "citation_traceability",
        "uncertainty_presence",
        "temporal_validity",
        "trading_instruction_compliance",
        "missing_data_disclosure",
    }
)


class BenchmarkManifest(DomainModel):
    """Version and deterministic execution metadata for one corpus."""

    benchmark_version: str = Field(min_length=1)
    case_directory: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    evaluation_ruleset_version: str = Field(min_length=1)
    default_generated_at: datetime

    @field_validator("default_generated_at")
    @classmethod
    def require_timezone_aware_time(cls, value: datetime) -> datetime:
        """Require an ISO timestamp carrying an explicit timezone."""

        if value.tzinfo is None:
            raise ValueError("Benchmark generated time must include timezone")
        return value


class BenchmarkSource(DomainModel):
    """Fixed, attributable source stored with one Benchmark case."""

    evidence_id: str = Field(min_length=1)
    fixture_kind: BenchmarkFixtureKind
    provider: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    excerpt_ref: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    collected_at: date
    published_at: datetime
    usage_basis: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @field_validator("published_at")
    @classmethod
    def require_timezone_aware_publication(
        cls,
        value: datetime,
    ) -> datetime:
        """Keep source-time comparisons independent of host timezone."""

        if value.tzinfo is None:
            raise ValueError("Benchmark source publication time needs timezone")
        return value


class BenchmarkClaim(DomainModel):
    """One fixed statement and the evidence IDs it cites."""

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        """Reject duplicated citations within one claim."""

        if len(value) != len(set(value)):
            raise ValueError("Benchmark claim evidence IDs must be unique")
        return value


class BenchmarkReportFixture(DomainModel):
    """Compact fixed semantic material deterministically forming ten sections."""

    title: str = Field(min_length=1)
    facts: list[BenchmarkClaim] = Field(min_length=1)
    inferences: list[BenchmarkClaim] = Field(min_length=1)
    risks: list[BenchmarkClaim] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1)
    bull_summary: str = Field(min_length=1)
    bear_summary: str = Field(min_length=1)
    risk_summary: str = Field(min_length=1)
    final_recommendation: str = Field(min_length=1)


class BenchmarkThresholds(DomainModel):
    """Minimum quality gates for default and optional live execution."""

    lifecycle_compliance_min: float = Field(ge=0.0, le=1.0)
    deterministic_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_fact_coverage_min: float = Field(ge=0.0, le=1.0)
    forbidden_conclusion_compliance_min: float = Field(ge=0.0, le=1.0)
    check_minimums: dict[str, float] = Field(default_factory=dict)
    live_dimension_minimums: dict[EvaluationDimension, float] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_metric_thresholds(self) -> Self:
        """Require finite thresholds for known deterministic checks."""

        unknown = set(self.check_minimums) - _DETERMINISTIC_CHECK_IDS
        if unknown:
            raise ValueError(f"unknown deterministic checks: {sorted(unknown)}")
        values = [
            *self.check_minimums.values(),
            *self.live_dimension_minimums.values(),
        ]
        if any(
            not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values
        ):
            raise ValueError("Benchmark thresholds must be finite and within [0, 1]")
        return self


class BenchmarkExpected(DomainModel):
    """Structured expectations independent of complete report wording."""

    required_facts: list[str] = Field(default_factory=list)
    allowed_missing_items: list[str] = Field(default_factory=list)
    forbidden_conclusions: list[str] = Field(min_length=1)
    expected_failure_code: str | None = None


class ResearchBenchmarkCase(DomainModel):
    """One complete, versioned and self-contained Benchmark case."""

    benchmark_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    case_version: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    market: ReportMarketScope
    asset_id: AssetId
    report_date: date
    expected_outcome: BenchmarkExpectedOutcome
    sources: list[BenchmarkSource]
    known_missing_data: list[str] = Field(default_factory=list)
    simulated_failures: list[str] = Field(default_factory=list)
    report: BenchmarkReportFixture | None = None
    observed_failure_code: str | None = None
    expected: BenchmarkExpected
    thresholds: BenchmarkThresholds

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        """Reject ambiguous markets, outcomes, sources, and references."""

        if self.market not in {
            ReportMarketScope.CN,
            ReportMarketScope.HK,
            ReportMarketScope.US,
        }:
            raise ValueError("Benchmark market must be CN, HK, or US")
        if self.asset_id.root.split(":", maxsplit=1)[0] != self.market.value:
            raise ValueError("Benchmark asset market must match case market")
        source_ids = [source.evidence_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Benchmark source evidence IDs must be unique")
        source_id_set = set(source_ids)
        claims = (
            []
            if self.report is None
            else [
                *self.report.facts,
                *self.report.inferences,
                *self.report.risks,
            ]
        )
        unknown_refs = {
            evidence_id
            for claim in claims
            for evidence_id in claim.evidence_ids
            if evidence_id not in source_id_set
        }
        if unknown_refs:
            raise ValueError(
                f"Benchmark claims reference unknown evidence: {sorted(unknown_refs)}"
            )
        if not set(self.known_missing_data) <= set(self.expected.allowed_missing_items):
            raise ValueError("known missing data must be explicitly allowed")
        if self.expected_outcome is BenchmarkExpectedOutcome.REPORT:
            if self.report is None or self.observed_failure_code is not None:
                raise ValueError("report outcome requires exactly one report fixture")
            if not self.sources or not self.expected.required_facts:
                raise ValueError("report outcome requires sources and expected facts")
            if self.thresholds.deterministic_score_min is None:
                raise ValueError(
                    "report outcome requires deterministic score threshold"
                )
            if self.expected.expected_failure_code is not None:
                raise ValueError("report outcome cannot expect a failure code")
        else:
            if self.report is not None or self.observed_failure_code is None:
                raise ValueError("failure outcome cannot carry a report fixture")
            if (
                self.expected.expected_failure_code is None
                or self.expected.expected_failure_code != self.observed_failure_code
            ):
                raise ValueError("failure outcome must match its expected failure code")
            if self.thresholds.deterministic_score_min is not None:
                raise ValueError("failure outcome cannot set report score threshold")
        return self


class BenchmarkMetricFailure(DomainModel):
    """One explicit threshold violation in a Benchmark case."""

    metric: str = Field(min_length=1)
    actual: float
    threshold: float
    reason: str = Field(min_length=1)


class BenchmarkCaseResult(DomainModel):
    """Machine-readable outcome for one fixed Benchmark case."""

    case_id: str = Field(min_length=1)
    case_version: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    market: ReportMarketScope
    asset_id: AssetId
    passed: bool
    lifecycle_compliance: float = Field(ge=0.0, le=1.0)
    expected_fact_coverage: float = Field(ge=0.0, le=1.0)
    forbidden_conclusion_compliance: float = Field(ge=0.0, le=1.0)
    observed_failure_code: str | None = None
    evaluation: EvaluationResult | None = None
    check_scores: dict[str, float] = Field(default_factory=dict)
    dimension_scores: dict[EvaluationDimension, float] = Field(default_factory=dict)
    failures: list[BenchmarkMetricFailure] = Field(default_factory=list)


class BenchmarkRunResult(DomainModel):
    """Complete deterministic or live Benchmark summary."""

    benchmark_version: str = Field(min_length=1)
    mode: BenchmarkRunMode
    evaluation_ruleset_version: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    generated_at: datetime
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    cases: list[BenchmarkCaseResult]

    @model_validator(mode="after")
    def validate_summary_counts(self) -> Self:
        """Require summary counters to match the attached case results."""

        if self.total_cases != len(self.cases):
            raise ValueError("Benchmark total count does not match case results")
        if self.passed_cases != sum(item.passed for item in self.cases):
            raise ValueError("Benchmark passed count does not match case results")
        if self.failed_cases != self.total_cases - self.passed_cases:
            raise ValueError("Benchmark failed count does not match case results")
        return self
