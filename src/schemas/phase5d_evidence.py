"""Closed successor evidence/receipt models; legacy models remain unchanged."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.schemas.evidence_closure import ResearchEvidenceClosureV2
from src.schemas.production_descriptors import ProductionDescriptorInput
from src.schemas.research_data_quality import (
    ContextDimension,
    MetricComparisonContextV1,
    QualityModel,
    RequirementAssessmentV1,
)
from src.schemas.temporal import require_utc_aware

PolicyId = Literal[
    "SEC_ACCESSION_EXPLICIT_OFFSET_V1",
    "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1",
    "DOCUMENT_RETRIEVAL_WITNESS_V1",
    "DETERMINISTIC_PARENT_MAX_V1",
]
Participation = Literal[
    "PIT_COUNTED_EVIDENCE",
    "DEPENDENCY_WITNESS",
    "DIAGNOSTIC_EVIDENCE",
    "UNUSABLE_EVIDENCE",
]


class ClockModel(QualityModel):
    """Require UTC aware actual clocks; never normalize naive timestamps."""

    @field_validator("*", mode="after")
    @classmethod
    def clock(cls, value: object) -> object:
        """Validate datetime fields without changing their original meanings."""
        return require_utc_aware(value) if isinstance(value, datetime) else value


class AcquisitionReceipt(ClockModel):
    """Exact transport bytes and actual receipt clock, without credentials."""

    schema_version: Literal["phase5d_acquisition_receipt_v1"] = (
        "phase5d_acquisition_receipt_v1"
    )
    artifact_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    body_base64: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    content_encoding: Literal["identity", "gzip", "deflate"] = "identity"
    observed_at: datetime


class SourceClock(ClockModel):
    """Raw field extraction preserves precision/offset and claimed UTC result."""

    field_locator: str
    literal: str
    semantics: Literal[
        "SEC_ACCESSION_ACCEPTANCE", "NEWS_PUBLICATION", "RETURNED_REVISION_AVAILABILITY"
    ]
    native_zone: str
    precision: Literal["SECOND", "FRACTIONAL_SECOND", "DATE", "UNZONED"]
    normalized_at: datetime | None


class NormalizationReceipt(ClockModel):
    """Own source receipt, exact parser/build, revision and materialization."""

    schema_version: Literal["phase5d_normalization_receipt_v1"] = (
        "phase5d_normalization_receipt_v1"
    )
    acquisition_identity: str
    parser_version: Literal["phase5d_json_pointer_v1"] = "phase5d_json_pointer_v1"
    parser_build_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingested_at: datetime
    materialized_at: datetime
    revision_locator: str
    revision_literal: str
    primary_document_locator: str | None = None
    primary_document_literal: str | None = None
    canonical_value_locator: str | None = None
    clocks: tuple[SourceClock, ...] = ()


class DocumentExtraction(ClockModel):
    """Raw response to exact canonical document/chunk association."""

    receipt: AcquisitionReceipt
    document_id: str
    extraction: Literal["UTF8_IDENTITY_V1", "JSON_HTML_TEXT_V1", "HTML_TEXT_V1"]
    text_locator: str | None = None
    extracted_text_sha256: str
    ingested_at: datetime
    materialized_at: datetime
    chunk_materialized_at: datetime


class TemporalAuthority(ClockModel):
    """Closed local authority, requiring independent receipt/policy resolution."""

    schema_version: Literal["evidence_temporal_authority_v1/1.0.0"] = (
        "evidence_temporal_authority_v1/1.0.0"
    )
    evidence_id: str
    namespace: Literal["STRUCTURED_EVIDENCE", "DOCUMENT_CHUNK_EVIDENCE"]
    object_type: Literal[
        "TARGET_CAPABILITY_EVIDENCE", "BENCHMARK_CONTEXT_PARENT", "DOCUMENT_CHUNK"
    ]
    content_hash: str
    owner: str
    consumer_asset: str
    capture_id: str
    consumer_run_id: str
    data_bundle_id: str
    usage_identity: str
    research_as_of: datetime
    generated_at: datetime
    mode: Literal["LIVE_ACQUISITION", "HISTORICAL_REPLAY"]
    policy_id: PolicyId
    policy_version: Literal["1.0.0"] = "1.0.0"
    policy_reference: str
    policy_identity: str
    acquisition: AcquisitionReceipt | None = None
    normalization: NormalizationReceipt | None = None
    document: DocumentExtraction | None = None
    available_at: datetime | None
    computed_at: datetime | None = None
    operator_name: str | None = None
    operator_version: str | None = None
    operator_identity: str | None = None
    operand_authorities: tuple[str, ...] = ()


class FactProof(QualityModel):
    """Exact SEC value/context operands, independent of comparison existence."""

    evidence_id: str
    acquisition: AcquisitionReceipt
    value_locator: str
    accession_locator: str
    unit_locator: str
    concept_locator: str
    period_end_locator: str
    period_start_locator: str | None = None
    form_locator: str
    context_identity: str
    context: MetricComparisonContextV1
    dimension_locators: dict[ContextDimension, str] = Field(default_factory=dict)


class PitEvidenceInput(QualityModel):
    """Full input binds included/excluded candidates and all raw proof inventories."""

    schema_version: Literal["research_pit_evidence_closure_v3/3.0.0"] = (
        "research_pit_evidence_closure_v3/3.0.0"
    )
    profile_version: Literal["research_evidence_inventory_requirements_v3/3.0.0"] = (
        "research_evidence_inventory_requirements_v3/3.0.0"
    )
    profile_identity: Literal[
        "78ac26d471fff0e3d9bb0dfbef6b92807bba3f169edf883cfdc088cbf9f56416"
    ] = "78ac26d471fff0e3d9bb0dfbef6b92807bba3f169edf883cfdc088cbf9f56416"
    original_input: ProductionDescriptorInput
    closure: ResearchEvidenceClosureV2
    authorities: tuple[TemporalAuthority, ...] = ()
    fact_proofs: tuple[FactProof, ...] = ()


class EvidenceValidity(QualityModel):
    """Participation never implies validity or required-slot satisfaction."""

    evidence_id: str
    participation: Participation
    independently_valid: bool
    available_at: datetime | None
    authority_identity: str | None
    reason_codes: tuple[str, ...]
    required_slot_satisfied: bool


class ClaimEligibility(QualityModel):
    """Complete citations and dependencies; no successful-subset Claim selection."""

    claim_id: str
    required_evidence: tuple[str, ...]
    eligible_for_pit_count: bool
    reason_codes: tuple[str, ...]


class PitEvaluation(QualityModel):
    """Auditable independent walk over the complete graph before comparisons."""

    input_identity: str
    evidence: tuple[EvidenceValidity, ...]
    claims: tuple[ClaimEligibility, ...]
    requirement_assessments: tuple[RequirementAssessmentV1, ...]
    mandatory_failures: tuple[str, ...]


class DensityObservationV2(ClockModel):
    """Explicit successor definition/profile, without widening the v1 mapping."""

    schema_version: Literal["production_descriptor_observation_v2"] = (
        "production_descriptor_observation_v2"
    )
    descriptor_id: Literal["INFORMATION_DENSITY"] = "INFORMATION_DENSITY"
    definition_version: Literal["information_density_v2"] = "information_density_v2"
    transform_version: Literal["pit_eligible_direct_factual_claims_per_evidence_v1"] = (
        "pit_eligible_direct_factual_claims_per_evidence_v1"
    )
    definition_identity: Literal[
        "668fc2c3c2277653f8f25557cc807bf0835c03fc80a188bda8d5c15733801edf"
    ] = "668fc2c3c2277653f8f25557cc807bf0835c03fc80a188bda8d5c15733801edf"
    profile_identity: Literal[
        "78ac26d471fff0e3d9bb0dfbef6b92807bba3f169edf883cfdc088cbf9f56416"
    ]
    policy_registry_identity: Literal[
        "87dff2aef42ad76329625c6fd636efb819f0e74d03b4ec2814056c6e7fe61b8d"
    ]
    source_input_identity: str
    evaluation_identity: str
    asset_id: str
    source_run_id: str
    research_as_of: datetime
    generated_at: datetime
    available_at: datetime
    status: Literal["PRESENT", "PARTIAL", "MISSING_INPUT"]
    value: float | None
    numerator: int
    denominator: int
    eligible_claim_ids: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    mandatory_failures: tuple[str, ...]
    unit: Literal["claims/evidence_item"] = "claims/evidence_item"
    direction: Literal["NONE_DESCRIPTIVE_ONLY"] = "NONE_DESCRIPTIVE_ONLY"

    @model_validator(mode="after")
    def semantics(self) -> Self:
        """Prevent rehashed cross-version, scope, clock and null-to-zero bypasses."""
        if not self.research_as_of <= self.generated_at == self.available_at:
            raise ValueError("DESCRIPTOR_GENERATION_CLOCK")
        for keys in (
            self.eligible_claim_ids,
            self.eligible_evidence_ids,
            self.excluded_evidence_ids,
        ):
            if keys != tuple(sorted(set(keys))):
                raise ValueError("NONCANONICAL_ID_ORDER")
        if set(self.eligible_evidence_ids) & set(self.excluded_evidence_ids):
            raise ValueError("OVERLAPPING_PARTITIONS")
        if self.numerator != len(self.eligible_claim_ids) or self.denominator != len(
            self.eligible_evidence_ids
        ):
            raise ValueError("MEMBERSHIP_COUNTS")
        if self.status == "MISSING_INPUT":
            if self.value is not None:
                raise ValueError("MISSING_MUST_BE_NULL")
        elif (
            self.mandatory_failures
            or not self.denominator
            or self.value != self.numerator / self.denominator
        ):
            raise ValueError("QUALITY_RATIO_SCOPE")
        if self.status == "PRESENT" and self.excluded_evidence_ids:
            raise ValueError("PRESENT_REQUIRES_COMPLETE_ELIGIBLE_SCOPE")
        return self
