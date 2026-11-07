"""Additive, immutable quality evidence under Main's frozen v1 authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUALITY_CONTRACT: Final = "research_data_quality_contract_v1/1.0.0"
QUALITY_CONTRACT_SHA256: Final = (
    "8074edd9a0e6c944c6d99f56c21d83da0f23da093bc8abc268c9201977356678"
)
REQUIREMENT_PROFILE: Final = "research_evidence_inventory_requirements_v1/1.0.0"
TOLERANCE_POLICY = "fmp_standardized_absolute_0.02_relative_0.10_v1"
LEGACY_POLICY = "production_descriptor_quality_legacy_v1"


def quality_hash(value: object) -> str:
    """Hash canonical JSON without accepting nonfinite numbers."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class QualityModel(BaseModel):
    """Strict frozen evidence; serialized identities are checked on decoding."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    content_identity: str = ""

    @model_validator(mode="after")
    def verify_identity(self) -> Self:
        identity = quality_hash(
            self.model_dump(mode="json", exclude={"content_identity"})
        )
        if self.content_identity and self.content_identity != identity:
            raise ValueError("quality content identity mismatch")
        object.__setattr__(self, "content_identity", identity)
        return self


class ContextDimension(StrEnum):
    SUBJECT = "subject"
    ISSUER = "issuer_identity"
    METRIC = "metric_definition"
    SCOPE = "accounting_scope"
    MEASUREMENT = "measurement_kind"
    PERIOD_END = "period_end"
    PERIOD_START = "period_start"
    DURATION = "duration"
    BASIS = "period_basis"
    COVERED_PERIODS = "covered_periods"
    GROWTH_FORMULA = "growth_formula"
    GROWTH_CURRENT = "growth_current_operand"
    GROWTH_BASELINE = "growth_baseline_operand"
    FISCAL_ALIGNMENT = "fiscal_alignment"
    NUMERATOR = "numerator"
    DENOMINATOR = "denominator"
    DENOMINATOR_CONVENTION = "denominator_convention"
    UNIT = "unit"
    CURRENCY = "currency"
    SCALE = "scale_share_adjustment_basis"
    ACCOUNTING = "accounting_basis"
    REVISION = "revision_equivalence"
    EFFECTIVE = "effective_semantics"


class DimensionEvidenceV1(QualityModel):
    """One proved, unknown or policy-inapplicable semantic dimension."""

    schema_version: Literal["metric_dimension_evidence_v1"] = (
        "metric_dimension_evidence_v1"
    )
    status: Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]
    value: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None
    policy_ref: str | None = None
    justification: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "KNOWN":
            if (
                not self.value
                or not self.evidence_refs
                or self.reason
                or self.policy_ref
            ):
                raise ValueError("KNOWN requires a value and exact evidence references")
        elif self.status == "UNKNOWN":
            if not self.reason or self.value is not None or self.policy_ref:
                raise ValueError("UNKNOWN requires an explicit gap, never a value")
        elif (
            not self.policy_ref
            or not self.justification
            or not self.evidence_refs
            or self.value
        ):
            raise ValueError(
                "NOT_APPLICABLE requires policy, justification and evidence"
            )
        return self


def known(value: str, *refs: str) -> DimensionEvidenceV1:
    """Construct evidenced context without guessing values."""
    return DimensionEvidenceV1(status="KNOWN", value=value, evidence_refs=refs)


def unknown(reason: str) -> DimensionEvidenceV1:
    """Keep a missing dimension explicit."""
    return DimensionEvidenceV1(status="UNKNOWN", reason=reason)


class MetricComparisonContextV1(QualityModel):
    """Context binds an exact Evidence item to retained provider/operand proof."""

    schema_version: Literal["metric_comparison_context_v1"] = (
        "metric_comparison_context_v1"
    )
    quality_contract: Literal["research_data_quality_contract_v1/1.0.0"] = (
        QUALITY_CONTRACT
    )
    evidence_id: str = Field(min_length=1)
    evidence_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1)
    provider_snapshot: str = Field(min_length=1)
    field_locator: str = Field(min_length=1)
    computation_version: str = Field(min_length=1)
    dimensions: dict[ContextDimension, DimensionEvidenceV1]
    available_at: datetime | None
    observed_at: datetime | None
    ingested_at: datetime | None
    clock_evidence_refs: tuple[str, ...] = ()
    grounding_refs: tuple[str, ...] = ()
    closure_refs: tuple[str, ...] = ()
    independent_source_refs: tuple[str, ...] = ()
    operand_evidence_ids: tuple[str, ...] = ()
    filing_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if set(self.dimensions) != set(ContextDimension):
            raise ValueError("all comparison dimensions must be explicitly represented")
        for clock in (self.available_at, self.observed_at, self.ingested_at):
            if clock is not None and (
                clock.tzinfo is None or clock.utcoffset() is None
            ):
                raise ValueError("quality clocks must be timezone-aware")
        return self


class IndependentFactValidityV1(QualityModel):
    schema_version: Literal["independent_fact_validity_v1"] = (
        "independent_fact_validity_v1"
    )
    evidence_id: str
    evidence_content_hash: str
    context_identity: str
    status: Literal["VALID", "INVALID"]
    reasons: tuple[str, ...]
    research_as_of: datetime


class MetricComparisonAssessmentV1(QualityModel):
    """Numeric verdict is absent unless independently valid contexts match."""

    schema_version: Literal["metric_comparison_assessment_v1"] = (
        "metric_comparison_assessment_v1"
    )
    quality_contract: Literal["research_data_quality_contract_v1/1.0.0"] = (
        QUALITY_CONTRACT
    )
    primary_context: MetricComparisonContextV1
    secondary_context: MetricComparisonContextV1
    primary_validity: IndependentFactValidityV1
    secondary_validity: IndependentFactValidityV1
    context_status: Literal[
        "COMPARABLE", "INCOMPARABLE_CONTEXT", "INSUFFICIENT_CONTEXT", "NOT_EVALUATED"
    ]
    disposition: Literal[
        "COMPARABLE",
        "CONFLICT",
        "INCOMPARABLE_CONTEXT",
        "INSUFFICIENT_CONTEXT",
        "INVALID_INPUT",
    ]
    numeric_outcome: Literal["AGREE", "CONFLICT", "NOT_EVALUATED"]
    context_diagnostic: Literal[
        "COMPARABLE", "INCOMPARABLE_CONTEXT", "INSUFFICIENT_CONTEXT"
    ]
    mismatched_dimensions: tuple[str, ...] = ()
    missing_dimensions: tuple[str, ...] = ()
    primary_value: float | None
    secondary_value: float | None
    tolerance_policy: str
    absolute_difference: float | None = None
    applied_tolerance: float | None = None
    conflict: bool | None = None

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if self.numeric_outcome == "NOT_EVALUATED":
            if any(
                value is not None
                for value in (
                    self.absolute_difference,
                    self.applied_tolerance,
                    self.conflict,
                )
            ):
                raise ValueError("NOT_EVALUATED must retain null numeric verdicts")
        elif self.context_status != "COMPARABLE" or self.disposition not in {
            "COMPARABLE",
            "CONFLICT",
        }:
            raise ValueError("numeric verdict requires comparable valid inputs")
        elif any(
            v.status != "VALID"
            for v in (self.primary_validity, self.secondary_validity)
        ):
            raise ValueError("invalid inputs cannot have numeric verdicts")
        return self


class ConsumerRequirementV1(QualityModel):
    schema_version: Literal["consumer_requirement_v1"] = "consumer_requirement_v1"
    requirement_id: str
    capability: str
    field: str | None = None
    condition: Literal["CAPABILITY", "AGE", "FIELD", "DEPENDENCY"]
    policy: Literal[
        "REQUIRED_APPLICABLE", "OPTIONAL_APPLICABLE", "NOT_APPLICABLE_ALLOWED"
    ]
    applicable_policy: Literal["REQUIRED_APPLICABLE", "OPTIONAL_APPLICABLE"] = (
        "REQUIRED_APPLICABLE"
    )
    applicability_policy: str | None = None
    dependencies: tuple[str, ...] = ()
    source_versions: tuple[str, ...] = ()
    transform_versions: tuple[str, ...] = ()


class ConsumerRequirementProfileV1(QualityModel):
    schema_version: Literal["consumer_requirement_profile_v1"] = (
        "consumer_requirement_profile_v1"
    )
    profile_version: Literal["research_evidence_inventory_requirements_v1/1.0.0"] = (
        REQUIREMENT_PROFILE
    )
    requirements: tuple[ConsumerRequirementV1, ...]

    @model_validator(mode="after")
    def unique_requirements(self) -> Self:
        ids = [r.requirement_id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement identity")
        return self


class RequirementAssessmentV1(QualityModel):
    schema_version: Literal["requirement_assessment_v1"] = "requirement_assessment_v1"
    requirement_id: str
    source_status: str
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE", "UNKNOWN"]
    status: Literal["SATISFIED", "EXEMPT", "GAP", "UNMET", "UNUSABLE"]
    reason: str
    evidence_refs: tuple[str, ...] = ()
    required: bool


class ConsumerQualityAssessmentV1(QualityModel):
    schema_version: Literal["consumer_quality_assessment_v1"] = (
        "consumer_quality_assessment_v1"
    )
    quality_contract: Literal["research_data_quality_contract_v1/1.0.0"] = (
        QUALITY_CONTRACT
    )
    quality_contract_sha256: Literal[
        "8074edd9a0e6c944c6d99f56c21d83da0f23da093bc8abc268c9201977356678"
    ] = QUALITY_CONTRACT_SHA256
    profile: ConsumerRequirementProfileV1
    source_input_sha256: str
    requirements: tuple[RequirementAssessmentV1, ...]
    comparisons: tuple[MetricComparisonAssessmentV1, ...] = ()
    status: Literal["SATISFIED", "PARTIAL", "UNUSABLE"]
    satisfied_count: int
    applicable_required_count: int
    exempt_count: int


class QualityPolicyBindingV1(QualityModel):
    """Separate registration; never extends strict historical handoff JSON."""

    schema_version: Literal["research_quality_policy_binding_v1"] = (
        "research_quality_policy_binding_v1"
    )
    quality_contract: Literal["research_data_quality_contract_v1/1.0.0"] = (
        QUALITY_CONTRACT
    )
    quality_contract_sha256: Literal[
        "8074edd9a0e6c944c6d99f56c21d83da0f23da093bc8abc268c9201977356678"
    ] = QUALITY_CONTRACT_SHA256
    profile_identity: str
    plan_sha256: str
    producer_source_identity: str
    registered_at: datetime
