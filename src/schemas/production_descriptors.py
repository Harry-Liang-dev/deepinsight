"""Closed Phase5A descriptors; additive to, not members of, the frozen v1 wire."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.models.identifiers import AssetId
from src.models.types import DomainModel
from src.schemas.research_data import ResearchDataBundle
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateClaimInput, ResearchStateSnapshot
from src.schemas.temporal import require_utc_aware


def descriptor_json_bytes(value: object) -> bytes:
    """Encode canonical finite JSON for descriptor identities and replay."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def descriptor_hash(value: object) -> str:
    """Hash canonical descriptor JSON, not mutable object reprs."""
    return hashlib.sha256(descriptor_json_bytes(value)).hexdigest()


class ProductionDescriptorDefinition(DomainModel):
    """One closed descriptive inventory measure, with no investment direction."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["production_descriptor_definition_v1"] = (
        "production_descriptor_definition_v1"
    )
    descriptor_id: Literal["INFORMATION_DENSITY"] = "INFORMATION_DENSITY"
    definition_version: Literal["information_density_v1"] = "information_density_v1"
    transform_version: Literal["direct_factual_claims_per_evidence_v1"] = (
        "direct_factual_claims_per_evidence_v1"
    )
    meaning: Literal[
        "accepted direct factual Claim IDs per unique bundle Evidence ID"
    ] = "accepted direct factual Claim IDs per unique bundle Evidence ID"
    unit: Literal["claims/evidence_item"] = "claims/evidence_item"
    numeric_type: Literal["finite_nonnegative_float"] = "finite_nonnegative_float"
    direction: Literal["NONE_DESCRIPTIVE_ONLY"] = "NONE_DESCRIPTIVE_ONLY"
    scope: Literal["OBSERVED_BUNDLE_12_CAPABILITIES_NOT_NEWS_ONLY"] = (
        "OBSERVED_BUNDLE_12_CAPABILITIES_NOT_NEWS_ONLY"
    )
    availability_rule: Literal["actual_descriptor_generation_time"] = (
        "actual_descriptor_generation_time"
    )
    numerator_rule: Literal["distinct_accepted_factual_FACT_direct_claim_ids"] = (
        "distinct_accepted_factual_FACT_direct_claim_ids"
    )
    denominator_rule: Literal[
        "unique_canonical_evidence_ids_across_all_12_capabilities"
    ] = "unique_canonical_evidence_ids_across_all_12_capabilities"
    closure_rule: Literal["exact_episode_state_claims_and_canonical_citation_refs"] = (
        "exact_episode_state_claims_and_canonical_citation_refs"
    )
    missing_rule: Literal[
        "empty_evidence_incomplete_trace_unknown_type_open_closure_bad_quality"
    ] = "empty_evidence_incomplete_trace_unknown_type_open_closure_bad_quality"
    partial_rule: Literal[
        "observed_scope_if_any_section_incomplete_stale_or_not_pass"
    ] = "observed_scope_if_any_section_incomplete_stale_or_not_pass"
    predecessor_rule: Literal["NONE_SINGLE_COMPLETED_RUN_ONLY"] = (
        "NONE_SINGLE_COMPLETED_RUN_ONLY"
    )


DEFINITION = ProductionDescriptorDefinition()
DEFINITION_IDENTITY = descriptor_hash(DEFINITION.model_dump(mode="json"))


class ProductionDescriptorRegistration(DomainModel):
    """Pre-generation opt-in, separately versioned from the frozen capture plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["production_descriptor_registration_v1"] = (
        "production_descriptor_registration_v1"
    )
    capture_id: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: Literal["LIVE_RESEARCH", "SYNTHETIC_COMPATIBILITY_ONLY"]
    definition_identity: str = DEFINITION_IDENTITY
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        """Require an explicit UTC registration clock."""
        return require_utc_aware(value)

    @field_validator("definition_identity")
    @classmethod
    def known_definition(cls, value: str) -> str:
        """Fail closed for unknown or modified formulas."""
        if value != DEFINITION_IDENTITY:
            raise ValueError("unknown production descriptor definition")
        return value


class ProductionDescriptorInput(DomainModel):
    """Exact local evidence and same-run State/Episode accepted Claim closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["production_descriptor_input_v1"] = (
        "production_descriptor_input_v1"
    )
    data_bundle: ResearchDataBundle
    research_state: ResearchStateSnapshot
    research_episode: ResearchEpisode
    accepted_claims: tuple[ResearchStateClaimInput, ...]
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        """Require the actual descriptor-generation instant, never period end."""
        return require_utc_aware(value)


type DescriptorStatus = Literal["PRESENT", "PARTIAL", "MISSING_INPUT"]
type DescriptorReason = Literal[
    "NO_STRUCTURED_EVIDENCE",
    "INCOMPLETE_EPISODE_TRACE",
    "UNKNOWN_CLAIM_TYPE",
    "EVIDENCE_CLOSURE_UNAVAILABLE",
    "SOURCE_QUALITY_UNUSABLE",
    "PARTIAL_SOURCE_COVERAGE",
]


class ProductionDescriptorObservation(DomainModel):
    """Numeric observation referencing immutable inputs; never an alpha score."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["production_descriptor_observation_v1"] = (
        "production_descriptor_observation_v1"
    )
    descriptor_id: Literal["INFORMATION_DENSITY"] = "INFORMATION_DENSITY"
    definition_version: Literal["information_density_v1"] = "information_density_v1"
    transform_version: Literal["direct_factual_claims_per_evidence_v1"] = (
        "direct_factual_claims_per_evidence_v1"
    )
    definition_identity: str = DEFINITION_IDENTITY
    observation_id: str = Field(pattern=r"^production_descriptor_[0-9a-f]{64}$")
    source_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_id: AssetId
    source_run_id: str
    research_state_id: str
    episode_id: str
    data_bundle_id: str
    research_as_of: datetime
    generated_at: datetime
    available_at: datetime
    status: DescriptorStatus
    reason: DescriptorReason | None
    value: float | None = Field(ge=0)
    numerator: int | None = Field(ge=0)
    denominator: int = Field(ge=0)
    counted_claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_content_hashes: tuple[str, ...]
    unit: Literal["claims/evidence_item"] = "claims/evidence_item"
    source_publication_evidence: None = None
    publication_evidence_reason: Literal["NOT_EXPLICIT_IN_RESEARCH_EVIDENCE_ITEM"] = (
        "NOT_EXPLICIT_IN_RESEARCH_EVIDENCE_ITEM"
    )

    @field_validator("research_as_of", "generated_at", "available_at")
    @classmethod
    def clocks(cls, value: datetime) -> datetime:
        """Retain explicit UTC clocks without historical backfill."""
        return require_utc_aware(value)

    @model_validator(mode="after")
    def branches(self) -> Self:
        """Validate finite ratios, sorted closure, timestamps and content identity."""
        if self.definition_identity != DEFINITION_IDENTITY:
            raise ValueError("unknown definition identity")
        if not self.research_as_of <= self.generated_at == self.available_at:
            raise ValueError("descriptor cannot predate actual generation")
        for ids in (self.counted_claim_ids, self.evidence_ids):
            if ids != tuple(sorted(set(ids))):
                raise ValueError("descriptor identities must be sorted and unique")
        if self.denominator != len(self.evidence_ids) or self.denominator != len(
            self.evidence_content_hashes
        ):
            raise ValueError("evidence denominator/lineage mismatch")
        if self.status == "MISSING_INPUT":
            if (
                self.value is not None
                or self.numerator is not None
                or self.counted_claim_ids
                or not self.reason
                or self.reason == "PARTIAL_SOURCE_COVERAGE"
            ):
                raise ValueError("missing descriptor must remain null with reason")
        else:
            if (
                self.denominator == 0
                or self.numerator != len(self.counted_claim_ids)
                or self.value != len(self.counted_claim_ids) / self.denominator
            ):
                raise ValueError("descriptor ratio does not reconcile")
            expected = "PARTIAL_SOURCE_COVERAGE" if self.status == "PARTIAL" else None
            if self.reason != expected:
                raise ValueError("available descriptor status/reason mismatch")
        payload = self.model_dump(mode="json", exclude={"observation_id"})
        if self.observation_id != "production_descriptor_" + descriptor_hash(payload):
            raise ValueError("descriptor content identity mismatch")
        return self
