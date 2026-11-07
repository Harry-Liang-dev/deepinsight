"""Versioned evaluation-only contracts; none grant research/business authority."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MetricStatus = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
Verdict = Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED"]
Split = Literal[
    "DEVELOPMENT", "REGRESSION", "BLIND_HOLDOUT", "PROSPECTIVE", "PENDING_LABEL"
]


class Closed(BaseModel):
    """Reject undeclared fields rather than silently consume candidate metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ArtifactRef(Closed):
    """Content-addressed local immutable artifact; not an access grant."""

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str


class EvaluationCase(Closed):
    """One complete research obligation, independent of generated Claim count."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    case_id: str
    case_version: str
    task_family: str
    issuer: str | None
    security: str | None
    original_complete_claim: str | None
    research_question: str
    source_snapshot_refs: list[ArtifactRef]
    evidence_catalog_ref: ArtifactRef
    research_as_of: str
    clocks: dict[str, dict[str, str | None]]
    rights_and_access_profile: dict[str, Any]
    expected_task_behavior: list[str]
    known_counterevidence: list[dict[str, Any]]
    gold_status: Literal[
        "PENDING_INDEPENDENT_GOLD",
        "POSTHOC_DEVELOPMENT_ADJUDICATION",
        "DETERMINISTIC_REFERENCE_ONLY",
    ]
    difficulty: Literal["TECHNICAL", "BASIC", "INTERMEDIATE", "COMPOUND"]
    provenance: dict[str, Any]
    dataset_split: Split
    exposure_cluster: str
    evaluation_reference: ArtifactRef | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    native_schema_refs: dict[str, ArtifactRef] = Field(default_factory=dict)


class ArchivedTrace(Closed):
    """Runner output identity. Raw artifacts, native status and diagnostic stay distinct."""

    interface_version: Literal["1.0.0"] = "1.0.0"
    trace_id: str
    case_id: str
    case_version: str
    variant_id: str
    run_id: str
    task_identity: str
    source_context_fingerprint: str
    research_as_of: str
    rights_fingerprint: str
    execution_state: Literal[
        "COMPLETED", "SYSTEM_FAILURE", "UNKNOWN_SEND", "NOT_ATTEMPTED", "NOT_SCHEDULED"
    ]
    request: ArtifactRef | None
    response: ArtifactRef | None
    assistant: ArtifactRef | None
    native_schema: ArtifactRef | None
    original_native_result: dict[str, Any]
    model: str | None
    usage: dict[str, Any] | None
    latency_seconds: float | None
    reference_cost_cny: str | None
    actual_bill: Literal["UNKNOWN"] = "UNKNOWN"
    diagnostic_review_ref: ArtifactRef | None = None
    numeric_assertions: list[dict[str, Any]] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    tool_observation_refs: list[ArtifactRef] = Field(default_factory=list)
    task_completion_status: str | None = None
    memory_application_refs: list[str] = Field(default_factory=list)
    scientific_admission: Literal[False] = False


class MetricResult(Closed):
    """A scoped measurement, not a weighted reward or a ClaimDecision."""

    status: MetricStatus
    basis: str
    explanation: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    measurements: dict[str, Any] = Field(default_factory=dict)


class ScoreResult(Closed):
    """Separate metric populations and preserve failures/unknowns."""

    evaluator_version: Literal["1.0.0"] = "1.0.0"
    protocol_sha256: str
    trace_id: str
    case_id: str
    variant_id: str
    execution_state: str
    original_native_result: dict[str, Any]
    native_prediction: Verdict | None
    diagnostic_prediction: str | None
    metrics: dict[str, MetricResult]
    serious_errors: list[dict[str, Any]]
    failure_clusters: list[str]
    independent_gold: Literal[False] = False
    formal_accuracy: Literal["UNKNOWN"] = "UNKNOWN"
    scientific_admission: Literal[False] = False
    diagnostic_scope: Literal["POSTHOC_DIAGNOSTIC_ONLY", "OFFLINE_MOCK_INTERFACE_ONLY"]


class PromptVariant(Closed):
    """W3 authors strategies; W5 evaluates; W1 alone sends."""

    interface_version: Literal["1.0.0"] = "1.0.0"
    variant_id: str
    parent_variant_id: str | None
    owner_worker: Literal["A_CAUSAL", "B_EVIDENCE", "C_PLANNING", "BASELINE"]
    improvement_hypothesis: str
    prompt_ref: ArtifactRef
    git_source_commit: str
    model_configuration_sha256: str
    intended_task_families: list[str]
    source_policy_version: str
    candidate_changes: list[str]
    blind_holdout_access: Literal[False] = False
