"""Additive counted/witness namespace and source-role contracts; v1 unchanged."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from src.schemas.common import SourceReference
from src.schemas.production_descriptors import ProductionDescriptorInput
from src.schemas.research_data import ResearchEvidenceItem
from src.schemas.research_data_quality import (
    MetricComparisonAssessmentV1,
    MetricComparisonContextV1,
    QualityModel,
)
from src.schemas.temporal import require_utc_aware


class ClosureBindingV2(QualityModel):
    """Same-run usage, distinct from the generation identity of reused sources."""

    capture_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    consumer_asset: str = Field(min_length=1)
    data_bundle_id: str = Field(min_length=1)
    research_state_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    state_episode_usage_binding: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")


class TemporalProvenanceV2(QualityModel):
    """Unknown source clocks stay unknown with explicit evidence/gap references."""

    effective_at: datetime | None
    available_at: datetime | None
    observed_at: datetime | None
    ingested_at: datetime | None
    clock_evidence_refs: tuple[str, ...]
    unavailable_reason: str | None = None

    @field_validator("effective_at", "available_at", "observed_at", "ingested_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        """Reject a timezone guessed from a naive database value."""
        return None if value is None else require_utc_aware(value)

    @model_validator(mode="after")
    def explicit_clock_gaps(self) -> Self:
        """Unknown meanings require explicit retained gap evidence, never aliases."""
        if not self.clock_evidence_refs or (
            any(
                c is None
                for c in (
                    self.effective_at,
                    self.available_at,
                    self.observed_at,
                    self.ingested_at,
                )
            )
            and not self.unavailable_reason
        ):
            raise ValueError("CLOCK_PROVENANCE_OR_GAP_UNBOUND")
        return self


class SourceIdentityV2(QualityModel):
    """Exact source object and retained artifact identities, never invented clocks."""

    provider: str = Field(min_length=1)
    normalized_record_id: str = Field(min_length=1)
    source_url: str | None
    raw_receipt_identity: str | None
    snapshot_identity: str = Field(min_length=1)
    unavailable_reason: str | None = None


class DocumentChunkProofV2(QualityModel):
    """Canonical text/offset proof with exact original document and chunk IDs."""

    document_id: str
    document_owner: str
    source_evidence_id: str
    source_evidence_hash: str
    canonical_id: str = Field(pattern=r"^chunk_[0-9a-f]{32}$")
    object_type: Literal["filing", "news"]
    chunk_index: int = Field(ge=0)
    chunk_text: str
    chunk_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offset_convention: Literal["PYTHON_UNICODE_CODEPOINTS_SLICE_STRIP_V1"]
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    raw_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_citation_reference: SourceReference
    source_identity: SourceIdentityV2
    temporal_provenance: TemporalProvenanceV2


class SourceDocumentWitnessV2(QualityModel):
    """Exact immutable document bytes decoded under the canonical UTF8 convention."""

    document_id: str
    owner_subject: str
    raw_text: str
    raw_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_clock_literal: str | None = None
    repository_created_clock_literal: str | None = None
    canonical_clock_policy_reference: str | None = None


class ClosureNodeV2(QualityModel):
    """One original canonical object; witnesses are not counted aliases."""

    namespace: Literal["STRUCTURED_EVIDENCE", "DOCUMENT_CHUNK_EVIDENCE"]
    object_type: Literal[
        "TARGET_CAPABILITY_EVIDENCE", "BENCHMARK_CONTEXT_PARENT", "DOCUMENT_CHUNK"
    ]
    canonical_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_convention: Literal["RESEARCH_EVIDENCE_ITEM_V1", "EXACT_CHUNK_UTF8_SHA256"]
    payload_reference: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_subject: str
    consumer_asset: str
    capability: str
    membership: Literal["COUNTED_EVIDENCE", "DEPENDENCY_WITNESS"]
    membership_reason: Literal[
        "BASE_CANONICAL_INVENTORY",
        "DIRECT_FACT_CITATION",
        "NONCOUNTABLE_CLAIM_CITATION",
        "BENCHMARK_CONTEXT_PARENT",
    ]
    source_identity: SourceIdentityV2
    temporal_provenance: TemporalProvenanceV2
    binding_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    structured_payload: ResearchEvidenceItem | None = None
    document_payload: DocumentChunkProofV2 | None = None


class ClosureEdgeV2(QualityModel):
    """Hash-bound DAG edge with a closed owner relationship."""

    source_id: str
    target_id: str
    source_hash: str
    target_hash: str
    relationship: Literal["DERIVED_PARENT", "CLAIM_CITATION"]
    owner_relationship: Literal[
        "SAME_OWNER", "BENCHMARK_CONTEXT_PARENT", "BASE_MACRO_CONTEXT_PARENT"
    ]
    binding_identity: str


class ProviderRoleV2(QualityModel):
    """Metric-level retained use is separate from independent comparison validity."""

    policy_version: Literal["research_provider_validity_roles_v1/1.0.0"] = (
        "research_provider_validity_roles_v1/1.0.0"
    )
    evidence_id: str
    metric: str
    provider: str
    endpoint: str
    revision_identity: str
    response_identity: str
    retained_use_role: Literal[
        "AUTHORITATIVE_PIT_FACT", "CORROBORATING_PIT_FACT", "DIAGNOSTIC_ONLY"
    ]
    comparison_eligibility: Literal[
        "ELIGIBLE_SUBJECT_TO_DQ_V1_COMPARABILITY", "UNUSABLE_FOR_PIT_COMPARISON"
    ]
    reason: str | None
    context: MetricComparisonContextV1 | None


class ResearchEvidenceClosureV2(QualityModel):
    """The complete additive input; every supplied object participates in identity."""

    schema_version: Literal["research_evidence_closure_v2/2.0.0"] = (
        "research_evidence_closure_v2/2.0.0"
    )
    profile_version: Literal["research_evidence_inventory_requirements_v2/2.0.0"] = (
        "research_evidence_inventory_requirements_v2/2.0.0"
    )
    profile_identity: Literal[
        "ee2a878343e76bb300d8b25f57eb1d517ffa427ef3e9e03b65d3feaa79d91a09"
    ] = "ee2a878343e76bb300d8b25f57eb1d517ffa427ef3e9e03b65d3feaa79d91a09"
    binding: ClosureBindingV2
    original_input_identity: str
    nodes: tuple[ClosureNodeV2, ...]
    source_documents: tuple[SourceDocumentWitnessV2, ...] = ()
    edges: tuple[ClosureEdgeV2, ...]
    comparisons: tuple[MetricComparisonAssessmentV1, ...]
    roles: tuple[ProviderRoleV2, ...]
    metric_receipts: tuple[MetricReceiptWitnessV2, ...] = ()
    counted_identity: str
    witness_identity: str
    edge_identity: str
    comparison_identity: str
    role_identity: str


class EvidenceInputV2(QualityModel):
    """An explicit successor envelope, not a permissive legacy model upgrade."""

    schema_version: Literal["production_descriptor_input_v2"] = (
        "production_descriptor_input_v2"
    )
    original_input: ProductionDescriptorInput
    closure: ResearchEvidenceClosureV2


class EvidenceProfileRegistrationV2(QualityModel):
    """Explicit registration before acquisition; live execution is not activated."""

    schema_version: Literal["evidence_profile_registration_v2"] = (
        "evidence_profile_registration_v2"
    )
    profile_version: Literal["research_evidence_inventory_requirements_v2/2.0.0"] = (
        "research_evidence_inventory_requirements_v2/2.0.0"
    )
    profile_identity: Literal[
        "ee2a878343e76bb300d8b25f57eb1d517ffa427ef3e9e03b65d3feaa79d91a09"
    ] = "ee2a878343e76bb300d8b25f57eb1d517ffa427ef3e9e03b65d3feaa79d91a09"
    role_policy: Literal["research_provider_validity_roles_v1/1.0.0"] = (
        "research_provider_validity_roles_v1/1.0.0"
    )
    closure_version: Literal["research_evidence_closure_v2/2.0.0"] = (
        "research_evidence_closure_v2/2.0.0"
    )
    capture_id: str
    plan_sha256: str
    producer_source_identity: str
    executable_schema_identity: str
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        """Keep a real registration clock, distinct from evidence availability."""
        return require_utc_aware(value)


class MetricReceiptWitnessV2(QualityModel):
    """Exact FMP field/response binding; transport time is never availability."""

    context_identity: str
    evidence_id: str
    metric_id: str
    endpoint: Literal["ratios-ttm", "key-metrics-ttm", "income-statement-growth"]
    field_locator: str
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    body_base64: str
    content_encoding: str
    acquired_at: datetime
    raw_value: float
    raw_unit: str
    normalization: Literal["fmp_direct_numeric_mapping_v1"]
    revision_identity: Literal["UNPROVEN_PROVIDER_REVISION"] = (
        "UNPROVEN_PROVIDER_REVISION"
    )

    @field_validator("acquired_at")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        """Keep exact endpoint acquisition lineage; no availability inference."""
        return require_utc_aware(value)


ResearchEvidenceClosureV2.model_rebuild()
EvidenceInputV2.model_rebuild()
