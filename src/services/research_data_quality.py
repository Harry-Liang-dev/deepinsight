"""Context-first comparisons and consumer-specific quality; no acquisition."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from pydantic import ValidationError

from src.schemas.evidence_closure import ResearchEvidenceClosureV2
from src.schemas.production_descriptors import (
    ProductionDescriptorInput,
    descriptor_hash,
)
from src.schemas.research_data import (
    DataAvailabilityStatus,
    DataCapability,
    DataQualityStatus,
    FreshnessStatus,
    ResearchEvidenceItem,
)
from src.schemas.research_data_quality import (
    TOLERANCE_POLICY,
    ConsumerQualityAssessmentV1,
    ConsumerRequirementProfileV1,
    ConsumerRequirementV1,
    ContextDimension,
    IndependentFactValidityV1,
    MetricComparisonAssessmentV1,
    MetricComparisonContextV1,
    RequirementAssessmentV1,
    quality_hash,
)


class ComparisonBindingError(ValueError):
    """Credential-free failure codes for supplied comparison integrity."""

    def __init__(self, reason_code: str, comparison_index: int | None = None) -> None:
        super().__init__("comparison binding failure in consumer Evidence inventory")
        self.reason_code = reason_code
        self.comparison_index = comparison_index


def validate_comparison_identity(
    comparison: MetricComparisonAssessmentV1,
) -> MetricComparisonAssessmentV1:
    """Verify every supplied content identity before ownership lookup/filtering."""

    def check_hashes(value: object, *, root: bool = False) -> None:
        if isinstance(value, dict):
            if "content_identity" in value:
                identity = value["content_identity"]
                if not identity or identity != quality_hash(
                    {k: v for k, v in value.items() if k != "content_identity"}
                ):
                    raise ComparisonBindingError(
                        "COMPARISON_HASH_MISMATCH" if root else "NESTED_HASH_MISMATCH"
                    )
            for nested in value.values():
                check_hashes(nested)
        elif isinstance(value, list):
            for nested in value:
                check_hashes(nested)

    try:
        payload = json.loads(comparison.model_dump_json(warnings="error"))
        if (
            payload.get("schema_version") != "metric_comparison_assessment_v1"
            or payload.get("quality_contract")
            != "research_data_quality_contract_v1/1.0.0"
        ):
            raise ComparisonBindingError("UNKNOWN_COMPARISON_VERSION")
        # Nested hashes first: an invalid record cannot disappear via its subject.
        for value in payload.values():
            check_hashes(value)
        check_hashes(payload, root=True)
        return MetricComparisonAssessmentV1.model_validate_json(
            json.dumps(payload, allow_nan=False)
        )
    except ComparisonBindingError:
        raise
    except ValidationError as exc:
        reason = (
            "UNKNOWN_COMPARISON_VERSION"
            if any(
                "schema_version" in error["loc"] or "quality_contract" in error["loc"]
                for error in exc.errors()
            )
            else "INVALID_COMPARISON_STRUCTURE"
        )
        raise ComparisonBindingError(reason) from None
    except (TypeError, ValueError):
        raise ComparisonBindingError("INVALID_COMPARISON_STRUCTURE") from None


def validate_comparison_binding(
    comparison: MetricComparisonAssessmentV1,
    inputs: ProductionDescriptorInput,
) -> None:
    """Bind both operand witnesses and the canonical primary to one consumer.

    Secondary operands retain the frozen separate context/validity witness;
    they do not replace or enlarge the canonical primary Evidence inventory.
    Any secondary also present in that inventory must match it exactly.
    """
    comparison = validate_comparison_identity(comparison)
    asset = str(inputs.data_bundle.asset_id)
    if asset != str(inputs.research_state.asset_id):
        raise ComparisonBindingError("ASSET_BINDING_MISMATCH")
    items = {
        item.evidence_id: item
        for cap in DataCapability
        for item in getattr(inputs.data_bundle, cap.value).items
    }
    for context, validity, value in (
        (
            comparison.primary_context,
            comparison.primary_validity,
            comparison.primary_value,
        ),
        (
            comparison.secondary_context,
            comparison.secondary_validity,
            comparison.secondary_value,
        ),
    ):
        item = items.get(context.evidence_id)
        if item is not None and item.subject_id != asset:
            raise ComparisonBindingError("EVIDENCE_OWNERSHIP_MISMATCH")
        subject = context.dimensions[ContextDimension.SUBJECT]
        if subject.status != "KNOWN" or subject.value != asset:
            raise ComparisonBindingError("ASSET_BINDING_MISMATCH")
        if (
            validity.evidence_id != context.evidence_id
            or validity.evidence_content_hash != context.evidence_content_hash
            or validity.context_identity != context.content_identity
            or context.evidence_id != f"ev_{context.evidence_content_hash[:24]}"
        ):
            raise ComparisonBindingError("OPERAND_WITNESS_BINDING_MISMATCH")
        if (
            validity.research_as_of != inputs.data_bundle.as_of
            or validity.research_as_of != inputs.research_state.research_as_of
        ):
            raise ComparisonBindingError("RESEARCH_CUTOFF_BINDING_MISMATCH")
        if item is None:
            if context is comparison.primary_context:
                raise ComparisonBindingError("ORPHANED_COMPARISON_EVIDENCE")
            continue
        if (
            not evidence_hash_matches(item)
            or item.content_hash != context.evidence_content_hash
        ):
            raise ComparisonBindingError("EVIDENCE_HASH_MISMATCH")
        if (
            item.source.provider_name != context.provider
            or _numeric(item.value) != value
        ):
            raise ComparisonBindingError("METRIC_EVIDENCE_BINDING_MISMATCH")


# Existing standardized comparison scope, not a new tolerance for arbitrary amounts.
STANDARDIZED_METRICS = frozenset(
    {
        "revenue_yoy",
        "net_income_yoy",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "debt_to_equity",
        "current_ratio",
        "eps_ttm",
        "book_value_per_share",
        "market_cap",
        "pe_ttm",
        "pb",
        "earnings_yield",
    }
)
OPTIONAL_OHLCV = frozenset({"ohlcv.adj_close", "ohlcv.turnover", "ohlcv.vwap"})


EVIDENCE_SCHEMA_VERSION = "ResearchEvidenceItem/" + quality_hash(
    ResearchEvidenceItem.model_json_schema()
)
SOURCE_VERSIONS = ("ResearchDataBundle/1.0", EVIDENCE_SCHEMA_VERSION)
TRANSFORM_VERSIONS = (
    "fundamental_features/fundamental_features_v2",
    "technical_feature/1.0",
    "benchmark_context/market_context_v1",
    "market_context/market_context_v1",
    "valuation/valuation_v1",
    "macro_snapshot/macro_snapshot_v1",
    "sentiment_presentation/sentiment_presentation_v1",
)


def evidence_hash_matches(item: ResearchEvidenceItem) -> bool:
    """Reuse the canonical Evidence hash representation, excluding quality flags."""
    payload: dict[str, object] = {
        "subject_id": item.subject_id,
        "field_path": item.field_path,
        "effective_at": item.effective_at.isoformat(),
        "observed_at": item.observed_at.isoformat(),
        "value": item.value,
        "unit": item.unit,
        "currency": item.currency,
        "source": item.source.model_dump(mode="json", exclude_none=True),
    }
    if item.transformation_name is not None:
        payload.update(
            transformation_name=item.transformation_name,
            transformation_version=item.transformation_version,
            parent_evidence_ids=item.parent_evidence_ids,
        )
    try:
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    except ValueError:
        return False
    return item.content_hash == digest and item.evidence_id == f"ev_{digest[:24]}"


def validate_fact(
    item: ResearchEvidenceItem,
    context: MetricComparisonContextV1,
    cutoff: datetime,
) -> IndependentFactValidityV1:
    """Independently check binding, closure, identity and source availability."""
    reasons = []
    if not evidence_hash_matches(item):
        reasons.append("EVIDENCE_CONTENT_HASH_INVALID")
    if (
        item.evidence_id != context.evidence_id
        or item.content_hash != context.evidence_content_hash
    ):
        reasons.append("EVIDENCE_BINDING_MISMATCH")
    if item.source.provider_name != context.provider:
        reasons.append("PROVIDER_BINDING_MISMATCH")
    if (
        isinstance(item.value, bool)
        or not isinstance(item.value, int | float)
        or not math.isfinite(item.value)
    ):
        reasons.append("NONFINITE_OR_NONNUMERIC")
    if item.quality in {DataQualityStatus.FAIL, DataQualityStatus.CONFLICT}:
        reasons.append("INDEPENDENT_SOURCE_UNUSABLE")
    subject = context.dimensions[ContextDimension.SUBJECT]
    if subject.status != "KNOWN" or subject.value != item.subject_id:
        reasons.append("SUBJECT_UNPROVEN")
    if not context.grounding_refs or not context.closure_refs:
        reasons.append("GROUNDING_OR_SOURCE_CLOSURE_UNPROVEN")
    if (
        context.available_at is None
        or context.observed_at is None
        or context.ingested_at is None
        or not context.clock_evidence_refs
    ):
        reasons.append("REQUIRED_CLOCK_UNPROVEN")
    elif context.available_at > cutoff or item.effective_at > cutoff:
        reasons.append("NOT_AVAILABLE_AT_CUTOFF")
    return IndependentFactValidityV1(
        evidence_id=item.evidence_id,
        evidence_content_hash=item.content_hash,
        context_identity=context.content_identity,
        status="INVALID" if reasons else "VALID",
        reasons=tuple(reasons),
        research_as_of=cutoff,
    )


def compare_metrics(
    primary: ResearchEvidenceItem,
    secondary: ResearchEvidenceItem,
    primary_context: MetricComparisonContextV1,
    secondary_context: MetricComparisonContextV1,
    *,
    research_as_of: datetime,
) -> MetricComparisonAssessmentV1:
    """Prove same-fact context before applying the unchanged tolerance."""
    # Revalidate nested immutable evidence to detect model_copy/mutable-map tampering.
    a = MetricComparisonContextV1.model_validate_json(primary_context.model_dump_json())
    b = MetricComparisonContextV1.model_validate_json(
        secondary_context.model_dump_json()
    )
    valid_a, valid_b = validate_fact(primary, a, research_as_of), validate_fact(
        secondary, b, research_as_of
    )
    mismatches: list[str] = []
    missing: list[str] = []
    for dimension in ContextDimension:
        left, right = a.dimensions[dimension], b.dimensions[dimension]
        if left.status == "UNKNOWN" or right.status == "UNKNOWN":
            missing.append(dimension.value)
        elif left.status != right.status:
            mismatches.append(dimension.value)
        elif left.status == "KNOWN" and left.value != right.value:
            mismatches.append(dimension.value)
        elif left.status == "NOT_APPLICABLE":
            # Only explicit metric-profile inapplicability can discharge a dimension.
            metric = primary.field_path.rsplit(".", 1)[-1]
            policy = f"metric_context_inapplicable_v1/{metric}/{dimension.value}"
            growth_only = {
                ContextDimension.GROWTH_FORMULA,
                ContextDimension.GROWTH_CURRENT,
                ContextDimension.GROWTH_BASELINE,
                ContextDimension.FISCAL_ALIGNMENT,
            }
            instant_only = {ContextDimension.PERIOD_START, ContextDimension.DURATION}
            instant = (
                a.dimensions[ContextDimension.MEASUREMENT].value == "INSTANT"
                and b.dimensions[ContextDimension.MEASUREMENT].value == "INSTANT"
            )
            allowed = (
                dimension in growth_only
                and not metric.endswith("_yoy")
                or dimension in instant_only
                and instant
            )
            if not allowed or left.policy_ref != policy or right.policy_ref != policy:
                missing.append(dimension.value)
    if (
        a.provider == b.provider
        or not a.independent_source_refs
        or not b.independent_source_refs
        or set(a.independent_source_refs) & set(b.independent_source_refs)
    ):
        missing.append("independent_source")
    metric = primary.field_path.rsplit(".", 1)[-1]
    policy = (
        TOLERANCE_POLICY
        if metric in STANDARDIZED_METRICS
        else "NUMERIC_POLICY_NOT_REVIEWED"
    )
    if policy != TOLERANCE_POLICY:
        missing.append("numeric_policy")
    numeric: dict[str, float | bool | None] = {
        "absolute_difference": None,
        "applied_tolerance": None,
        "conflict": None,
    }
    if "INVALID" in {valid_a.status, valid_b.status}:
        status, disposition, outcome = "NOT_EVALUATED", "INVALID_INPUT", "NOT_EVALUATED"
    elif mismatches:
        status, disposition, outcome = (
            "INCOMPARABLE_CONTEXT",
            "INCOMPARABLE_CONTEXT",
            "NOT_EVALUATED",
        )
    elif missing:
        status, disposition, outcome = (
            "INSUFFICIENT_CONTEXT",
            "INSUFFICIENT_CONTEXT",
            "NOT_EVALUATED",
        )
    else:
        difference = abs(float(primary.value) - float(secondary.value))
        tolerance = max(0.02, abs(float(primary.value)) * 0.10)
        conflict = difference > tolerance
        numeric = {
            "absolute_difference": difference,
            "applied_tolerance": tolerance,
            "conflict": conflict,
        }
        status, disposition, outcome = (
            "COMPARABLE",
            "CONFLICT" if conflict else "COMPARABLE",
            "CONFLICT" if conflict else "AGREE",
        )
    return MetricComparisonAssessmentV1.model_validate(
        {
            "primary_context": a,
            "secondary_context": b,
            "primary_validity": valid_a,
            "secondary_validity": valid_b,
            "context_status": status,
            "disposition": disposition,
            "numeric_outcome": outcome,
            "context_diagnostic": (
                "INCOMPARABLE_CONTEXT"
                if mismatches
                else "INSUFFICIENT_CONTEXT" if missing else "COMPARABLE"
            ),
            "mismatched_dimensions": tuple(mismatches),
            "missing_dimensions": tuple(missing),
            "primary_value": _numeric(primary.value),
            "secondary_value": _numeric(secondary.value),
            "tolerance_policy": policy,
            **numeric,
        }
    )


def _numeric(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def inventory_profile(
    *,
    dependencies: tuple[str, ...] = (),
    source_versions: tuple[str, ...] = SOURCE_VERSIONS,
    transform_versions: tuple[str, ...] = TRANSFORM_VERSIONS,
) -> ConsumerRequirementProfileV1:
    """Freeze all twelve capabilities and explicit field/age requirements."""
    if source_versions != SOURCE_VERSIONS or transform_versions != TRANSFORM_VERSIONS:
        raise ValueError("unreviewed source/transform version profile")
    requirements = []
    for cap in DataCapability:
        requirements.append(
            ConsumerRequirementV1(
                requirement_id=f"{cap.value}.inventory",
                capability=cap.value,
                condition="CAPABILITY",
                policy="REQUIRED_APPLICABLE",
                dependencies=dependencies,
                source_versions=source_versions,
                transform_versions=transform_versions,
            )
        )
        requirements.append(
            ConsumerRequirementV1(
                requirement_id=f"{cap.value}.age",
                capability=cap.value,
                condition="AGE",
                policy=(
                    "NOT_APPLICABLE_ALLOWED"
                    if cap == DataCapability.ASSET_IDENTITY
                    else "REQUIRED_APPLICABLE"
                ),
                applicability_policy=(
                    "static_instrument_identity/1.0"
                    if cap == DataCapability.ASSET_IDENTITY
                    else None
                ),
            )
        )
    for field in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_close",
        "turnover",
        "vwap",
        "feed_identity",
        "coverage_scope",
    ):
        path = f"ohlcv.{field}"
        requirements.append(
            ConsumerRequirementV1(
                requirement_id=path,
                capability="ohlcv",
                field=path,
                condition="FIELD",
                policy=(
                    "OPTIONAL_APPLICABLE"
                    if path in OPTIONAL_OHLCV and path not in dependencies
                    else "REQUIRED_APPLICABLE"
                ),
                dependencies=dependencies,
            )
        )
    for field in ("asset_id", "market", "ticker", "exchange_code"):
        requirements.append(
            ConsumerRequirementV1(
                requirement_id=f"asset_identity.{field}",
                capability="asset_identity",
                field=f"asset_identity.{field}",
                condition="FIELD",
                policy="REQUIRED_APPLICABLE",
            )
        )
    for path in sorted(set(dependencies)):
        if path not in {r.requirement_id for r in requirements}:
            requirements.append(
                ConsumerRequirementV1(
                    requirement_id=path,
                    capability=path.split(".", 1)[0],
                    field=path,
                    condition="DEPENDENCY",
                    policy="REQUIRED_APPLICABLE",
                )
            )
    return ConsumerRequirementProfileV1(requirements=tuple(requirements))


def validate_requirement_profile(
    profile: ConsumerRequirementProfileV1,
) -> ConsumerRequirementProfileV1:
    """Validate the frozen reviewed profile before consumer routing."""
    profile = ConsumerRequirementProfileV1.model_validate_json(
        profile.model_dump_json()
    )
    if not profile.requirements:
        raise ValueError("unreviewed empty requirement profile")
    canonical = inventory_profile(
        dependencies=tuple(
            sorted({p for r in profile.requirements for p in r.dependencies})
        ),
        source_versions=profile.requirements[0].source_versions,
        transform_versions=profile.requirements[0].transform_versions,
    )
    if profile != canonical:
        raise ValueError("unreviewed requirement profile")
    return profile


def assess_requirements(
    inputs: ProductionDescriptorInput,
    *,
    profile: ConsumerRequirementProfileV1,
    comparisons: tuple[MetricComparisonAssessmentV1, ...] = (),
    closure: ResearchEvidenceClosureV2 | None = None,
) -> ConsumerQualityAssessmentV1:
    """Explain exemptions without rewriting original quality or inventory."""
    profile = validate_requirement_profile(profile)
    if inputs.data_bundle.schema_version != "1.0":
        raise ValueError("unreviewed Data bundle schema version")
    sections = {
        cap.value: getattr(inputs.data_bundle, cap.value) for cap in DataCapability
    }
    all_items = {
        item.evidence_id: item for sec in sections.values() for item in sec.items
    }
    for comparison in comparisons:
        validate_comparison_binding(comparison, inputs)
    closure_nodes = {}
    if closure is not None:
        from src.services.evidence_closure import validate_closure

        closure = validate_closure(inputs, closure, comparisons=comparisons)
        closure_nodes = {node.canonical_id: node for node in closure.nodes}
        all_items.update(
            {
                node.canonical_id: node.structured_payload
                for node in closure.nodes
                if node.structured_payload is not None
            }
        )
    # Exact transitive Evidence closure; unknown parents cannot establish unused fields.
    used = {eid for row in inputs.accepted_claims for eid in row.claim.evidence_ids}
    used.update(
        parent for item in all_items.values() for parent in item.parent_evidence_ids
    )
    pending = list(used)
    closure_missing = False
    while pending:
        key = pending.pop()
        item = all_items.get(key)
        if item is None:
            if key not in closure_nodes:
                closure_missing = True
            continue
        for parent in item.parent_evidence_ids:
            if parent not in used:
                used.add(parent)
                pending.append(parent)
    consumed_paths = {all_items[key].field_path for key in used if key in all_items}
    declared_dependencies = {d for r in profile.requirements for d in r.dependencies}
    rows: list[RequirementAssessmentV1] = []
    for req in profile.requirements:
        sec = sections.get(req.capability)
        required = (
            req.policy != "OPTIONAL_APPLICABLE"
            or req.field in consumed_paths
            or req.field in declared_dependencies
        )
        status, applicability, reason = (
            "SATISFIED",
            "APPLICABLE",
            "required evidence retained",
        )
        refs: tuple[str, ...] = ()
        source_status = "missing"
        if sec is None:
            status, reason = "UNMET", "unknown requirement capability"
        else:
            source_status = f"{sec.status}/{sec.quality.status}/{sec.freshness.status}"
            refs = tuple(item.evidence_id for item in sec.items)
            bad = (
                any(not evidence_hash_matches(item) for item in sec.items)
                or sec.quality.status
                in {
                    DataQualityStatus.FAIL,
                    DataQualityStatus.CONFLICT,
                }
                or any(
                    item.quality in {DataQualityStatus.FAIL, DataQualityStatus.CONFLICT}
                    for item in sec.items
                )
            )
            unknown_transform = any(
                item.transformation_name
                and (
                    f"{item.transformation_name.split('.')[0]}/"
                    f"{item.transformation_version}"
                )
                not in TRANSFORM_VERSIONS
                for item in sec.items
            )
            bad = bad or unknown_transform
            if req.condition == "AGE":
                if sec.freshness.status == FreshnessStatus.NOT_APPLICABLE:
                    applicability = "NOT_APPLICABLE"
                    policy = (
                        f"{sec.freshness.policy_name}/{sec.freshness.policy_version}"
                    )
                    if (
                        req.policy == "NOT_APPLICABLE_ALLOWED"
                        and req.applicability_policy == policy
                        and sec.items
                        and sec.freshness.reason
                    ):
                        status, reason = (
                            "EXEMPT",
                            f"only age exempt under {policy}: {sec.freshness.reason}",
                        )
                    else:
                        status, reason = (
                            "UNMET",
                            "unproved or forbidden applicability exemption",
                        )
                elif sec.freshness.status != FreshnessStatus.FRESH:
                    status, reason = "UNMET", "required applicable freshness unmet"
            elif req.condition in {"FIELD", "DEPENDENCY"}:
                matching = tuple(
                    item for item in sec.items if item.field_path == req.field
                )
                gaps = tuple(
                    gap for gap in sec.missing_data if gap.field_path == req.field
                )
                if any(
                    item.quality in {DataQualityStatus.FAIL, DataQualityStatus.CONFLICT}
                    or not evidence_hash_matches(item)
                    for item in matching
                ):
                    status, reason = (
                        "UNUSABLE",
                        "present corrupt Evidence is never exempt",
                    )
                elif not matching or gaps:
                    status = "UNMET" if required or closure_missing else "GAP"
                    reason = (
                        "required field coverage unmet"
                        if status == "UNMET"
                        else "optional absence; dependency closure proves unused"
                    )
                elif any(
                    item.quality in {DataQualityStatus.FAIL, DataQualityStatus.CONFLICT}
                    for item in matching
                ):
                    status, reason = (
                        "UNUSABLE",
                        "present optional/required Evidence is corrupt",
                    )
            else:
                optional_gaps = (
                    bool(sec.missing_data)
                    and all(
                        gap.field_path in OPTIONAL_OHLCV
                        and not gap.required
                        and gap.field_path not in consumed_paths | declared_dependencies
                        for gap in sec.missing_data
                    )
                    and not closure_missing
                )
                # Only recognized completeness warnings can be explained.
                explained_optional = (
                    sec.capability == DataCapability.OHLCV
                    and optional_gaps
                    and sec.quality.validity_ratio == 1.0
                    and sec.quality.lineage_coverage_ratio == 1.0
                    and sec.freshness.status == FreshnessStatus.FRESH
                    and sec.quality.reason
                    in {
                        None,
                        "some normalized OHLCV observations are incomplete",
                        "optional OHLCV fields are missing",
                    }
                )
                if bad:
                    status, reason = (
                        "UNUSABLE",
                        "independently unusable inventory Evidence",
                    )
                elif (
                    sec.status
                    not in {
                        DataAvailabilityStatus.PRESENT,
                        DataAvailabilityStatus.PARTIAL,
                    }
                    or not sec.items
                ):
                    status, reason = "UNMET", "required capability absent/stale"
                elif (
                    sec.missing_data
                    or sec.available_field_count != sec.requested_field_count
                    or sec.quality.status != DataQualityStatus.PASS
                    or sec.status != DataAvailabilityStatus.PRESENT
                ) and not explained_optional:
                    status, reason = (
                        "UNMET",
                        "unexplained coverage/quality disposition retained",
                    )
                elif any(item.quality != DataQualityStatus.PASS for item in sec.items):
                    status, reason = "UNMET", "unresolved item quality retained"
                if any(
                    item.observed_at > inputs.data_bundle.as_of
                    or item.effective_at > inputs.data_bundle.as_of
                    for item in sec.items
                ):
                    status, reason = "UNUSABLE", "required inventory violates cutoff"
        rows.append(
            RequirementAssessmentV1.model_validate(
                {
                    "requirement_id": req.requirement_id,
                    "source_status": source_status,
                    "applicability": applicability,
                    "status": status,
                    "reason": reason,
                    "evidence_refs": refs,
                    "required": required,
                }
            )
        )
    if closure_missing:
        rows.append(
            RequirementAssessmentV1(
                requirement_id="required_dependency_closure",
                source_status="missing",
                applicability="UNKNOWN",
                status="UNUSABLE",
                reason="required transitive Evidence closure missing",
                required=True,
            )
        )
    for node in closure_nodes.values():
        if node.document_payload is not None:
            temporal = node.temporal_provenance
            if (
                any(
                    clock is None
                    for clock in (
                        temporal.available_at,
                        temporal.observed_at,
                        temporal.ingested_at,
                    )
                )
                or not temporal.clock_evidence_refs
            ):
                rows.append(
                    RequirementAssessmentV1(
                        requirement_id="document_clock:" + node.canonical_id,
                        source_status="UNKNOWN",
                        applicability="APPLICABLE",
                        status="UNUSABLE",
                        reason="document required clock unproven",
                        required=True,
                        evidence_refs=(node.canonical_id,),
                    )
                )
            elif (
                temporal.available_at is not None
                and temporal.available_at > inputs.data_bundle.as_of
            ):
                rows.append(
                    RequirementAssessmentV1(
                        requirement_id="document_clock:" + node.canonical_id,
                        source_status="FUTURE",
                        applicability="APPLICABLE",
                        status="UNUSABLE",
                        reason="document not available at cutoff",
                        required=True,
                        evidence_refs=(node.canonical_id,),
                    )
                )
    unusable = any(row.status == "UNUSABLE" for row in rows) or any(
        a.disposition in {"CONFLICT", "INVALID_INPUT"} for a in comparisons
    )
    partial = any(row.status == "UNMET" for row in rows) or any(
        a.numeric_outcome == "NOT_EVALUATED" for a in comparisons
    )
    return ConsumerQualityAssessmentV1(
        profile=profile,
        source_input_sha256=(
            descriptor_hash(inputs.model_dump(mode="json"))
            if closure is None
            else descriptor_hash(
                {
                    "original_input": inputs.model_dump(mode="json"),
                    "closure": closure.model_dump(mode="json"),
                }
            )
        ),
        requirements=tuple(rows),
        comparisons=comparisons,
        status="UNUSABLE" if unusable else "PARTIAL" if partial else "SATISFIED",
        satisfied_count=sum(row.required and row.status == "SATISFIED" for row in rows),
        applicable_required_count=sum(
            row.required and row.status != "EXEMPT" for row in rows
        ),
        exempt_count=sum(row.status == "EXEMPT" for row in rows),
    )
