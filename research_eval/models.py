"""Versioned data interfaces, not caller-issued execution permissions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def encoded(value: Any) -> bytes:
    """Encode an immutable data identity without binary-float monetary math."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def identity(value: Any) -> str:
    """Hash canonical data, not a statement of source authority."""
    return hashlib.sha256(encoded(value)).hexdigest()


class Record(BaseModel):
    """Reject undeclared control fields in every exchanged record."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(Record):
    """Retained byte reference; current ACL must separately authorize access."""

    source_id: Identifier
    path: str
    sha256: Hash
    available_at: datetime
    license: str


class DatasetCase(Record):
    """Model-visible task and source projection, without evaluator-only labels."""

    case_id: Identifier
    task_kind: Literal["technical", "financial"]
    specialist_role: Literal[
        "technical_schema_probe", "fundamental_analyst", "news_event_analyst"
    ] = "fundamental_analyst"
    full_claim: str = Field(min_length=1)
    research_as_of: datetime
    sources: tuple[SourceRef, ...]
    handles: dict[str, str]
    visible_input: dict[str, Any]
    authority_binding: Hash
    required_handles: tuple[str, ...] = ()
    gold_status: Literal["NONE", "DEVELOPMENT_EXPECTATION", "INDEPENDENT"] = "NONE"
    holdout: bool = False
    local_export_allowed: bool = False

    @model_validator(mode="after")
    def boundaries(self) -> DatasetCase:
        """Require timezone and exact source membership without fuzzy resolution."""
        if self.research_as_of.tzinfo is None or any(
            s.available_at.tzinfo is None for s in self.sources
        ):
            raise ValueError("TIMEZONE_REQUIRED")
        ids = [s.source_id for s in self.sources]
        if len(ids) != len(set(ids)) or set(self.handles.values()) - set(ids):
            raise ValueError("SOURCE_MEMBERSHIP")
        if set(self.required_handles) - set(self.handles):
            raise ValueError("REQUIRED_HANDLE_UNKNOWN")
        if any(s.available_at > self.research_as_of for s in self.sources):
            raise ValueError("FUTURE_SOURCE")
        return self


class Dataset(Record):
    """Public evaluation population; private Gold is never part of this object."""

    version: Literal["eval-dataset-v1"] = "eval-dataset-v1"
    dataset_id: Identifier
    cases: tuple[DatasetCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Dataset:
        """Reject duplicate cases and implicit holdout access."""
        if len({x.case_id for x in self.cases}) != len(self.cases):
            raise ValueError("DUPLICATE_CASE")
        return self


class PromptVariant(Record):
    """Mutable-policy candidate data cannot carry grants, tools or network targets."""

    variant_id: Identifier
    parent_variant_id: Identifier | None = None
    content: str = Field(min_length=1)
    prompt_sha256: Hash
    task_types: tuple[Literal["technical", "financial"], ...]
    model: Literal["qwen3.8-flash"] = "qwen3.8-flash"
    output_cap: Literal[512, 1024] = 512
    dataset_identity: Hash
    created_by: str
    experiment_group: str
    hypothesis: str
    immutable_boundary_identity: Hash

    @model_validator(mode="after")
    def content_hash(self) -> PromptVariant:
        """Require the exact prompt bytes, never silently recompute an old version."""
        if hashlib.sha256(self.content.encode()).hexdigest() != self.prompt_sha256:
            raise ValueError("PROMPT_HASH_MISMATCH")
        return self


class Budget(Record):
    """Campaign ceilings; reservations are bounds, never measured token counts."""

    max_samples: int = Field(gt=0, le=10000)
    max_attempts: int = Field(gt=0, le=10000)
    max_tokens: int = Field(gt=0)
    max_reference_cost_cny: Decimal = Field(gt=0)
    concurrency: int = Field(gt=0, le=16)
    requests_per_second: float = Field(gt=0, le=100)


class TrustedExperimentCampaign(Record):
    """Prospective review object; deserializing it confers no authority."""

    version: Literal["eval-campaign-v1"] = "eval-campaign-v1"
    campaign_id: Identifier
    execution_mode: Literal["OFFLINE", "LIVE"] = "OFFLINE"
    ledger_root: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_hashes: dict[str, Hash]
    dataset_identity: Hash
    permitted_source_hashes: tuple[Hash, ...]
    authority_bindings: tuple[Hash, ...]
    evaluator_protocol_sha256: Hash
    model: Literal["qwen3.8-flash"] = "qwen3.8-flash"
    provider: Literal["Qwen"] = "Qwen"
    endpoint: Literal["https://dashscope.aliyuncs.com/compatible-mode/v1/responses"] = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    )
    region: Literal["cn-beijing"] = "cn-beijing"
    tools: tuple[()] = ()
    read_scope: Literal["READ_HISTORY"] = "READ_HISTORY"
    allowed_prompt_fields: tuple[
        Literal[
            "content",
            "hypothesis",
            "variant_id",
            "parent_variant_id",
            "experiment_group",
        ],
        ...,
    ] = ("content", "hypothesis", "variant_id", "parent_variant_id", "experiment_group")
    output_cap: Literal[512, 1024] = 512
    budget: Budget
    created_at: datetime
    expires_at: datetime
    business_writes: Literal[False] = False
    scientific_admission: Literal[False] = False

    @model_validator(mode="after")
    def times(self) -> TrustedExperimentCampaign:
        """Forbid naive or reversed release clocks."""
        if (
            self.created_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.expires_at <= self.created_at
        ):
            raise ValueError("CAMPAIGN_TIME")
        if self.allowed_prompt_fields != (
            "content",
            "hypothesis",
            "variant_id",
            "parent_variant_id",
            "experiment_group",
        ):
            raise ValueError("UNSUPPORTED_PROMPT_MUTABILITY_POLICY")
        return self


class ExperimentSpec(Record):
    """Frozen finite subpopulation inside a reviewed campaign."""

    experiment_id: Identifier
    campaign_identity: Hash
    dataset_identity: Hash
    variant_identities: tuple[Hash, ...]
    mode: Literal["OFFLINE", "LIVE"] = "OFFLINE"


class FrozenRequest(Record):
    """Exact SDK body and the independent source/task/policy identities."""

    run_id: Hash
    case_id: Identifier
    variant_id: Identifier
    task_identity: Hash
    prompt_identity: Hash
    schema_identity: Hash
    request_sha256: Hash
    raw_body: str
    system_prompt: str
    input_payload: dict[str, Any]
    response_schema: dict[str, Any]


class FrozenExperiment(Record):
    """A manifest cannot be modified after any output is observed."""

    spec: ExperimentSpec
    campaign: TrustedExperimentCampaign
    dataset: Dataset
    variants: tuple[PromptVariant, ...]
    requests: tuple[FrozenRequest, ...]


class FailureKind(StrEnum):
    """Mechanical and semantic failures remain distinct."""

    PROTOCOL_FAILURE = "PROTOCOL_FAILURE"
    SCHEMA_FAILURE = "SCHEMA_FAILURE"
    LOCAL_GUARD_FAILURE = "LOCAL_GUARD_FAILURE"
    SOURCE_AUTHORITY_FAILURE = "SOURCE_AUTHORITY_FAILURE"
    EVIDENCE_RESOLUTION_FAILURE = "EVIDENCE_RESOLUTION_FAILURE"
    NUMERIC_GROUNDING_FAILURE = "NUMERIC_GROUNDING_FAILURE"
    VERDICT_REASONING_CONTRADICTION = "VERDICT_REASONING_CONTRADICTION"
    UNSUPPORTED_CAUSAL_ACCEPTANCE = "UNSUPPORTED_CAUSAL_ACCEPTANCE"
    TOOL_SELECTION_FAILURE = "TOOL_SELECTION_FAILURE"
    DATA_COVERAGE_FAILURE = "DATA_COVERAGE_FAILURE"
    COST_OR_LATENCY_REGRESSION = "COST_OR_LATENCY_REGRESSION"
    UNKNOWN_OR_NOT_EVALUATED = "UNKNOWN_OR_NOT_EVALUATED"


class Failure(Record):
    """Explicit location and rule; never a repaired model answer."""

    kind: FailureKind
    pointer: str
    rule: str
    severity: Literal["INFO", "ERROR", "CRITICAL"] = "ERROR"


class Metric(Record):
    """Unknown cannot become zero or pass by aggregation."""

    status: Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
    value: float | None = None
    evidence: tuple[str, ...] = ()


class EvaluationResult(Record):
    """W5 exchange envelope with fixed denominator and no automatic admission."""

    version: Literal["eval-result-v1"] = "eval-result-v1"
    run_id: Hash
    evaluator_id: str
    protocol_sha256: Hash
    trace_sha256: Hash
    provenance: Literal["MECHANICAL", "INTERNAL_PRECHECK", "W5_INDEPENDENT"]
    gold_status: Literal["NONE", "DEVELOPMENT_EXPECTATION", "INDEPENDENT"]
    metrics: dict[str, Metric]
    failures: tuple[Failure, ...] = ()
    scientific_admission: Literal[False] = False

    @model_validator(mode="after")
    def independent_gold_provenance(self) -> EvaluationResult:
        """A local scorer cannot promote its expectations to independent Gold."""
        if self.gold_status == "INDEPENDENT" and self.provenance != "W5_INDEPENDENT":
            raise ValueError("INDEPENDENT_GOLD_PROVENANCE")
        return self
