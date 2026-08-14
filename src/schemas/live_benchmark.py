"""Contracts for fixed-input, real-provider Agent Benchmark runs."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.models.enums import AgentName, EvaluationDimension, ReportMarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject
from src.schemas.agents import AgentContext
from src.schemas.evaluation import EvaluationResult
from src.schemas.reports import ResearchReport


class LiveSnapshotSource(DomainModel):
    """One immutable, attributable text or structured-data excerpt."""

    evidence_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    collected_at: datetime
    published_at: datetime
    usage_basis: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @field_validator("collected_at", "published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Require source timestamps independent of the host timezone."""

        if value.tzinfo is None:
            raise ValueError("live snapshot timestamps require a timezone")
        return value


class LiveSnapshotMemory(DomainModel):
    """One fixed attributable Memory result supplied to selected scenarios."""

    memory_id: str = Field(min_length=1)
    source_evidence_id: str = Field(min_length=1)
    summary_text: str = Field(min_length=1)
    memory_level: Literal["L0", "L1", "L2", "L3", "L4"]
    namespace_key: str = Field(min_length=1)
    memory_type: str = Field(min_length=1)
    effective_ts: datetime
    score: float
    importance_score: float = Field(ge=0.0, le=1.0)

    @field_validator("effective_ts")
    @classmethod
    def require_effective_timezone(cls, value: datetime) -> datetime:
        """Require an explicit Memory effective timezone."""

        if value.tzinfo is None:
            raise ValueError("live snapshot Memory time requires a timezone")
        return value


class LiveAgentScenario(DomainModel):
    """One fixed projection of a shared live source snapshot."""

    case_id: str = Field(min_length=1)
    scenario: Literal[
        "normal_fundamentals",
        "missing_data",
        "conflicting_evidence",
        "material_event",
        "high_volatility",
        "incomplete_memory",
    ]
    asset_id: AssetId
    report_date: date
    source_ids: list[str] = Field(min_length=1)
    memory_ids: list[str] = Field(default_factory=list)
    structured_features: JsonObject
    known_missing_data: list[str] = Field(default_factory=list)

    @field_validator("source_ids", "memory_ids")
    @classmethod
    def require_unique_ids(cls, value: list[str]) -> list[str]:
        """Reject duplicate references that would skew Agent input."""

        if len(value) != len(set(value)):
            raise ValueError("live scenario references must be unique")
        return value


class LiveBenchmarkSnapshot(DomainModel):
    """Versioned shared dataset for all live Agent scenarios."""

    dataset_version: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    market_coverage: list[ReportMarketScope] = Field(min_length=1)
    coverage_limitations: list[str] = Field(min_length=1)
    data_start: date
    data_end: date
    sources: list[LiveSnapshotSource] = Field(min_length=1)
    memories: list[LiveSnapshotMemory] = Field(default_factory=list)
    scenarios: list[LiveAgentScenario] = Field(min_length=6)

    @model_validator(mode="after")
    def validate_snapshot_graph(self) -> Self:
        """Require exact US-v1 coverage and resolvable scenario references."""

        if self.market_coverage != [ReportMarketScope.US]:
            raise ValueError("live_agent_benchmark_v1 currently supports US only")
        if self.data_start > self.data_end:
            raise ValueError("snapshot data window is invalid")
        source_ids = [item.evidence_id for item in self.sources]
        memory_ids = [item.memory_id for item in self.memories]
        case_ids = [item.case_id for item in self.scenarios]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("snapshot source IDs must be unique")
        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("snapshot Memory IDs must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("live scenario IDs must be unique")
        expected_scenarios = {
            "normal_fundamentals",
            "missing_data",
            "conflicting_evidence",
            "material_event",
            "high_volatility",
            "incomplete_memory",
        }
        if {item.scenario for item in self.scenarios} != expected_scenarios:
            raise ValueError("live snapshot must contain the six required scenarios")
        source_set = set(source_ids)
        memory_set = set(memory_ids)
        for memory in self.memories:
            if memory.source_evidence_id not in source_set:
                raise ValueError("snapshot Memory references an unknown source")
        for scenario in self.scenarios:
            if scenario.asset_id.market.value != ReportMarketScope.US.value:
                raise ValueError("live v1 scenarios must use US assets")
            if not set(scenario.source_ids) <= source_set:
                raise ValueError("live scenario references an unknown source")
            if not set(scenario.memory_ids) <= memory_set:
                raise ValueError("live scenario references an unknown Memory item")
        return self


class LiveBenchmarkConfig(DomainModel):
    """Auditable real-provider runtime configuration without credentials."""

    run_id: str = Field(min_length=1)
    provider: Literal["openai", "qwen"]
    provider_real: bool
    judge_real: bool
    model_name: str = Field(min_length=1)
    prompt_versions: dict[AgentName, str]
    prompt_sha256: dict[AgentName, str]
    inference_parameters: JsonObject
    evaluation_ruleset_version: str = Field(min_length=1)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def require_generated_timezone(cls, value: datetime) -> datetime:
        """Require an auditable timezone-aware run time."""

        if value.tzinfo is None:
            raise ValueError("live Benchmark run time requires a timezone")
        return value

    @model_validator(mode="after")
    def require_real_pipeline(self) -> Self:
        """Fail closed before any evaluation can use a fake component."""

        if not self.provider_real or not self.judge_real:
            raise ValueError("live Agent Benchmark requires real LLM and Judge")
        if set(self.prompt_versions) != set(AgentName):
            raise ValueError("all Agent prompt versions must be recorded")
        if set(self.prompt_sha256) != set(AgentName) or any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in self.prompt_sha256.values()
        ):
            raise ValueError("all Agent prompt hashes must be recorded")
        return self


class LiveCaseResult(DomainModel):
    """One Agent scenario outcome and its complete measurement references."""

    case_id: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed", "failed"]
    agent_statuses: dict[AgentName, str]
    agent_success_rate: float = Field(ge=0.0, le=1.0)
    agent_result: JsonObject
    report: ResearchReport | None = None
    evaluation: EvaluationResult | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Keep completed and failed case artifacts mutually exclusive."""

        if self.status == "completed":
            if self.report is None or self.evaluation is None or self.error_code:
                raise ValueError("completed live case requires report and evaluation")
        elif (
            self.report is not None
            or self.evaluation is not None
            or not self.error_code
        ):
            raise ValueError("failed live case requires only an error code")
        return self


class LiveBenchmarkRunResult(DomainModel):
    """Complete machine-readable result of one real live Benchmark run."""

    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_coverage: list[ReportMarketScope] = Field(min_length=1)
    coverage_limitations: list[str] = Field(min_length=1)
    config: LiveBenchmarkConfig
    case_input_fingerprints: dict[str, str]
    cases: list[LiveCaseResult]
    completed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """Require counters and fingerprints to match attached cases."""

        if self.run_id != self.config.run_id:
            raise ValueError("run result and config IDs differ")
        if self.market_coverage != [ReportMarketScope.US]:
            raise ValueError(
                "live Agent Benchmark v1 result must disclose US-only scope"
            )
        if self.completed_cases != sum(x.status == "completed" for x in self.cases):
            raise ValueError("completed case count does not match")
        if self.failed_cases != len(self.cases) - self.completed_cases:
            raise ValueError("failed case count does not match")
        if set(self.case_input_fingerprints) != {x.case_id for x in self.cases}:
            raise ValueError("case fingerprint set does not match results")
        return self


class LiveCaseDelta(DomainModel):
    """Candidate-minus-baseline measurement for one comparable scenario."""

    case_id: str = Field(min_length=1)
    overall_score_delta: float | None = None
    agent_success_rate_delta: float
    dimension_deltas: dict[EvaluationDimension, float] = Field(default_factory=dict)

    @field_validator("overall_score_delta", "agent_success_rate_delta")
    @classmethod
    def require_finite_delta(cls, value: float | None) -> float | None:
        """Reject non-finite comparison output."""

        if value is not None and not math.isfinite(value):
            raise ValueError("live Benchmark deltas must be finite")
        return value


class LiveBenchmarkComparison(DomainModel):
    """Neutral A/B differences for two input-compatible real runs."""

    baseline_run_id: str = Field(min_length=1)
    candidate_run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_deltas: list[LiveCaseDelta]


class MaterializedLiveScenario(DomainModel):
    """Validated Agent and Evaluation input materialized from one snapshot."""

    case_id: str
    scenario: str
    context: AgentContext
    evidence_by_id: dict[str, LiveSnapshotSource]
    known_missing_data: list[str]
