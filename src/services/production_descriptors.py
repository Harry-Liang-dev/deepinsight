"""Deterministic descriptor extraction from structured Research, without inference."""

from __future__ import annotations

from typing import Any

from src.models.enums import AgentStatus, ClaimIntent
from src.schemas.evidence_closure import ResearchEvidenceClosureV2
from src.schemas.production_descriptors import (
    DEFINITION_IDENTITY,
    DescriptorReason,
    DescriptorStatus,
    ProductionDescriptorInput,
    ProductionDescriptorObservation,
    descriptor_hash,
)
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    DataQualityStatus,
    FreshnessStatus,
    ResearchDataSection,
    ResearchEvidenceItem,
)
from src.schemas.research_data_quality import (
    LEGACY_POLICY,
    QUALITY_CONTRACT,
    ConsumerRequirementProfileV1,
    MetricComparisonAssessmentV1,
)
from src.schemas.research_episode import ResearchEpisodeTraceQuality
from src.schemas.research_state import ResearchStateSection, ResearchStateSectionName
from src.services.research_data_quality import assess_requirements


def build_information_density(
    inputs: ProductionDescriptorInput,
    *,
    quality_policy: str = LEGACY_POLICY,
    requirement_profile: ConsumerRequirementProfileV1 | None = None,
    comparisons: tuple[MetricComparisonAssessmentV1, ...] = (),
    closure: ResearchEvidenceClosureV2 | None = None,
) -> ProductionDescriptorObservation:
    """Count direct factual Claims per canonical Evidence item, not prose tokens.

    Args:
        inputs: Frozen same-run State, Episode, accepted Claims and Data bundle.

    Returns:
        A content-addressed observation or explicit null missingness record.

    Raises:
        ValueError: If input identities, temporal order or Claim closure contradict.
    """
    if closure is not None and quality_policy != QUALITY_CONTRACT:
        raise ValueError("v2 closure requires explicit DQ authority")
    if quality_policy not in {LEGACY_POLICY, QUALITY_CONTRACT}:
        raise ValueError("unknown descriptor quality policy")
    if quality_policy == LEGACY_POLICY and (
        requirement_profile is not None or comparisons
    ):
        raise ValueError(
            "legacy policy cannot silently consume successor quality evidence"
        )
    if quality_policy == QUALITY_CONTRACT and requirement_profile is None:
        raise ValueError("new quality policy requires an explicitly frozen profile")
    # Nested legacy models are mutable: reconstruct rather than trust model_copy.
    inputs = ProductionDescriptorInput.model_validate_json(inputs.model_dump_json())
    state, episode, data = (
        inputs.research_state,
        inputs.research_episode,
        inputs.data_bundle,
    )
    if (
        state.asset_id != data.asset_id
        or episode.asset_id != state.asset_id
        or state.research_as_of != data.as_of
        or episode.research_as_of != data.as_of
        or episode.research_state_id != state.research_state_id
        or state.lineage.data_bundle_id != data.bundle_id
        or state.lineage.data_snapshot_id != data.snapshot_id
        or state.lineage.dataset_version != data.dataset_version
        or not state.lineage.source_run_id
    ):
        raise ValueError("descriptor source identity mismatch")
    if not data.as_of <= episode.created_at <= inputs.generated_at:
        raise ValueError("descriptor generation predates completed Research")
    claims = {row.claim.claim_id: row for row in inputs.accepted_claims}
    if len(claims) != len(inputs.accepted_claims) or set(claims) != set(
        episode.accepted_claim_ids
    ):
        raise ValueError("accepted Claim inventory differs from Episode")
    features = {}
    for name in ResearchStateSectionName:
        section: ResearchStateSection = getattr(state, name.value)
        for feature in section.features:
            if feature.feature_name.startswith("claim."):
                features[feature.feature_name.removeprefix("claim.")] = feature
    for claim_id, row in claims.items():
        if (
            claim_id not in features
            or features[claim_id].value != row.claim.claim_text
            or features[claim_id].source_claim_ids != (claim_id,)
        ):
            raise ValueError("Claim does not match State feature")
        if not any(
            row.agent_role == trace.agent_role
            and row.agent_run_id == trace.agent_run_id
            and claim_id in trace.accepted_claim_ids
            for trace in episode.agent_traces
        ):
            raise ValueError("Claim producer is not the Episode producer")

    evidence: dict[str, ResearchEvidenceItem] = {}
    partial = False
    unusable = False
    for capability in DataCapability:
        section_data: ResearchDataSection = getattr(data, capability.value)
        partial |= (
            section_data.status != DataAvailabilityStatus.PRESENT
            or section_data.quality.status != DataQualityStatus.PASS
            or section_data.freshness.status != FreshnessStatus.FRESH
            or bool(section_data.missing_data)
            or section_data.available_field_count != section_data.requested_field_count
        )
        unusable |= section_data.quality.status in {
            DataQualityStatus.FAIL,
            DataQualityStatus.CONFLICT,
        }
        for item in section_data.items:
            if item.evidence_id in evidence and evidence[item.evidence_id] != item:
                raise ValueError("conflicting canonical Evidence identity")
            evidence[item.evidence_id] = item
            partial |= item.quality != DataQualityStatus.PASS
            unusable |= item.quality in {
                DataQualityStatus.FAIL,
                DataQualityStatus.CONFLICT,
            }

    if quality_policy == QUALITY_CONTRACT:
        assert requirement_profile is not None
        assessment = assess_requirements(
            inputs,
            profile=requirement_profile,
            comparisons=comparisons,
            closure=closure,
        )
        # Formula, canonical inventory and reason precedence remain shared.
        partial = assessment.status == "PARTIAL"
        unusable = assessment.status == "UNUSABLE"

    document_evidence = (
        {
            node.canonical_id: node
            for node in closure.nodes
            if node.document_payload is not None
            and node.membership == "COUNTED_EVIDENCE"
        }
        if closure is not None
        else {}
    )

    def source_reference(key: str) -> Any:
        if key in evidence:
            return evidence[key].to_source_reference()
        doc = document_evidence[key].document_payload
        assert doc is not None
        return doc.exact_citation_reference

    reason: DescriptorReason | None = None
    counted: list[str] = []
    if (
        episode.trace_quality != ResearchEpisodeTraceQuality.COMPLETE
        or not episode.agent_traces
        or any(trace.status != AgentStatus.OK for trace in episode.agent_traces)
    ):
        reason = "INCOMPLETE_EPISODE_TRACE"
    elif not evidence:
        reason = "NO_STRUCTURED_EVIDENCE"
    elif unusable:
        reason = "SOURCE_QUALITY_UNUSABLE"
    elif any(row.claim.claim_type is None for row in claims.values()):
        reason = "UNKNOWN_CLAIM_TYPE"
    else:
        for claim_id, row in claims.items():
            claim = row.claim
            if (
                claim.claim_type != "factual"
                or claim.claim_intent != ClaimIntent.FACT
                or not claim.evidence_ids
            ):
                continue
            refs = tuple(claim.source_references)
            expected = [
                source_reference(key)
                for key in claim.evidence_ids
                if key in evidence or key in document_evidence
            ]
            if (
                len(expected) != len(claim.evidence_ids)
                or len(refs) != len(expected)
                or any(ref not in refs for ref in expected)
            ):
                reason = "EVIDENCE_CLOSURE_UNAVAILABLE"
                break
            assert claim_id is not None
            counted.append(claim_id)
    missing = reason is not None
    status: DescriptorStatus = (
        "MISSING_INPUT" if missing else "PARTIAL" if partial else "PRESENT"
    )
    if not missing and partial:
        reason = "PARTIAL_SOURCE_COVERAGE"
    keys = tuple(sorted(set(evidence) | set(document_evidence)))
    payload: dict[str, Any] = {
        "schema_version": "production_descriptor_observation_v1",
        "descriptor_id": "INFORMATION_DENSITY",
        "definition_version": "information_density_v1",
        "transform_version": "direct_factual_claims_per_evidence_v1",
        "definition_identity": DEFINITION_IDENTITY,
        "source_input_sha256": (
            descriptor_hash(inputs.model_dump(mode="json"))
            if closure is None
            else descriptor_hash(
                {
                    "original_input": inputs.model_dump(mode="json"),
                    "closure": closure.model_dump(mode="json"),
                }
            )
        ),
        "asset_id": str(state.asset_id),
        "source_run_id": state.lineage.source_run_id,
        "research_state_id": state.research_state_id,
        "episode_id": episode.episode_id,
        "data_bundle_id": data.bundle_id,
        "research_as_of": data.as_of.isoformat(),
        "generated_at": inputs.generated_at.isoformat(),
        "available_at": inputs.generated_at.isoformat(),
        "status": status,
        "reason": reason,
        "value": None if missing else len(counted) / len(keys),
        "numerator": None if missing else len(counted),
        "denominator": len(keys),
        "counted_claim_ids": tuple(sorted(counted)) if not missing else (),
        "evidence_ids": keys,
        "evidence_content_hashes": tuple(
            (
                evidence[key].content_hash
                if key in evidence
                else document_evidence[key].content_hash
            )
            for key in keys
        ),
        "unit": "claims/evidence_item",
        "source_publication_evidence": None,
        "publication_evidence_reason": "NOT_EXPLICIT_IN_RESEARCH_EVIDENCE_ITEM",
    }
    # Canonicalize datetimes exactly as the wire model (UTC uses Z).
    for field in ("research_as_of", "generated_at", "available_at"):
        payload[field] = payload[field].replace("+00:00", "Z")
    payload["observation_id"] = "production_descriptor_" + descriptor_hash(payload)
    return ProductionDescriptorObservation.model_validate(payload)
