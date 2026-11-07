"""Exact v2 closure assembly and validation; no provider or model execution."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from src.models.enums import ClaimIntent
from src.repositories.documents import DocumentRepository
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.common import SourceReference
from src.schemas.evidence_closure import (
    ClosureBindingV2,
    ClosureEdgeV2,
    ClosureNodeV2,
    DocumentChunkProofV2,
    MetricReceiptWitnessV2,
    ProviderRoleV2,
    ResearchEvidenceClosureV2,
    SourceDocumentWitnessV2,
    SourceIdentityV2,
    TemporalProvenanceV2,
)
from src.schemas.phase5c_authority import PROFILE_IDENTITY, frozen_profile
from src.schemas.production_descriptors import (
    ProductionDescriptorInput,
    descriptor_hash,
)
from src.schemas.research_data import DataCapability, ResearchEvidenceItem
from src.schemas.research_data_quality import (
    MetricComparisonAssessmentV1,
    MetricComparisonContextV1,
    quality_hash,
)
from src.services.document_processing import _chunk_id
from src.services.research_data_quality import (
    evidence_hash_matches,
    validate_comparison_binding,
)


def countable_claim(claim: ClaimEvidenceBinding) -> bool:
    """Reuse the exact frozen direct factual FACT selector, without tuning."""
    return bool(
        claim.claim_type == "factual"
        and claim.claim_intent == ClaimIntent.FACT
        and claim.evidence_ids
    )


def usage_identity(inputs: ProductionDescriptorInput) -> str:
    """Bind the full State/Episode/accepted-Claim association, including upstreams."""
    return quality_hash(
        [
            inputs.research_state.model_dump(mode="json"),
            inputs.research_episode.model_dump(mode="json"),
            [r.model_dump(mode="json") for r in inputs.accepted_claims],
        ]
    )


def binding_for(
    inputs: ProductionDescriptorInput,
    *,
    capture_id: str,
    plan_sha256: str,
    producer_source_identity: str,
) -> ClosureBindingV2:
    """Create an explicit same-run usage binding for original or reused artifacts."""
    return ClosureBindingV2(
        capture_id=capture_id,
        source_run_id=str(inputs.research_state.lineage.source_run_id),
        consumer_asset=str(inputs.data_bundle.asset_id),
        data_bundle_id=inputs.data_bundle.bundle_id,
        research_state_id=inputs.research_state.research_state_id,
        episode_id=inputs.research_episode.episode_id,
        state_episode_usage_binding=usage_identity(inputs),
        plan_sha256=plan_sha256,
        producer_source_identity=producer_source_identity,
    )


def _inventory(inputs: ProductionDescriptorInput) -> dict[str, ResearchEvidenceItem]:
    items: dict[str, ResearchEvidenceItem] = {}
    for cap in DataCapability:
        for item in getattr(inputs.data_bundle, cap.value).items:
            if item.evidence_id in items and items[item.evidence_id] != item:
                raise ValueError("CONFLICTING_CANONICAL_EVIDENCE")
            items[item.evidence_id] = item
    return items


def _structured_node(
    item: ResearchEvidenceItem, binding: ClosureBindingV2, *, witness: bool
) -> ClosureNodeV2:
    payload = item.model_dump(mode="json")
    return ClosureNodeV2(
        namespace="STRUCTURED_EVIDENCE",
        object_type=(
            "BENCHMARK_CONTEXT_PARENT" if witness else "TARGET_CAPABILITY_EVIDENCE"
        ),
        canonical_id=item.evidence_id,
        content_hash=item.content_hash,
        hash_convention="RESEARCH_EVIDENCE_ITEM_V1",
        payload_reference=quality_hash(payload),
        owner_subject=item.subject_id,
        consumer_asset=binding.consumer_asset,
        capability=item.field_path.split(".")[0],
        membership="DEPENDENCY_WITNESS" if witness else "COUNTED_EVIDENCE",
        membership_reason=(
            "BENCHMARK_CONTEXT_PARENT" if witness else "BASE_CANONICAL_INVENTORY"
        ),
        source_identity=SourceIdentityV2(
            provider=item.source.provider_name,
            normalized_record_id=item.source.normalized_record_key,
            source_url=item.source.source_url,
            raw_receipt_identity=None,
            snapshot_identity=quality_hash(payload),
            unavailable_reason="RAW_TRANSPORT_RECEIPT_NOT_IN_LEGACY_EVIDENCE",
        ),
        temporal_provenance=TemporalProvenanceV2(
            effective_at=item.effective_at,
            available_at=None,
            observed_at=item.observed_at,
            ingested_at=None,
            clock_evidence_refs=(item.content_hash,),
            unavailable_reason="LEGACY_ITEM_HAS_NO_SEPARATE_AVAILABLE_INGESTED_CLOCKS",
        ),
        binding_identity=binding.content_identity,
        structured_payload=item,
    )


def assemble_closure(
    inputs: ProductionDescriptorInput,
    *,
    binding: ClosureBindingV2,
    benchmark_parents: Iterable[ResearchEvidenceItem] = (),
    documents: tuple[DocumentChunkProofV2, ...] = (),
    source_documents: tuple[SourceDocumentWitnessV2, ...] = (),
    comparisons: tuple[MetricComparisonAssessmentV1, ...] = (),
    metric_contexts: tuple[MetricComparisonContextV1, ...] = (),
    metric_receipts: tuple[MetricReceiptWitnessV2, ...] = (),
) -> ResearchEvidenceClosureV2:
    """Retain every supplied node; validation rejects extras rather than filtering."""
    nodes = [
        _structured_node(item, binding, witness=False)
        for item in _inventory(inputs).values()
    ]
    seen: dict[str, ResearchEvidenceItem] = {}
    for item in benchmark_parents:
        if item.evidence_id in seen:
            if seen[item.evidence_id] != item:
                raise ValueError("CONFLICTING_BENCHMARK_DUPLICATE")
            continue
        seen[item.evidence_id] = item
        nodes.append(_structured_node(item, binding, witness=True))
    direct = {
        key
        for row in inputs.accepted_claims
        if countable_claim(row.claim)
        for key in row.claim.evidence_ids
    }
    for doc in documents:
        counted = doc.canonical_id in direct
        nodes.append(
            ClosureNodeV2(
                namespace="DOCUMENT_CHUNK_EVIDENCE",
                object_type="DOCUMENT_CHUNK",
                canonical_id=doc.canonical_id,
                content_hash=doc.chunk_text_sha256,
                hash_convention="EXACT_CHUNK_UTF8_SHA256",
                payload_reference=doc.content_identity,
                owner_subject=doc.document_owner,
                consumer_asset=binding.consumer_asset,
                capability=(
                    "filings" if doc.object_type == "filing" else "news_evidence"
                ),
                membership="COUNTED_EVIDENCE" if counted else "DEPENDENCY_WITNESS",
                membership_reason=(
                    "DIRECT_FACT_CITATION" if counted else "NONCOUNTABLE_CLAIM_CITATION"
                ),
                source_identity=doc.source_identity,
                temporal_provenance=doc.temporal_provenance,
                binding_identity=binding.content_identity,
                document_payload=doc,
            )
        )
    by_id = {node.canonical_id: node for node in nodes}
    edges = []
    for node in nodes:
        if node.structured_payload is not None:
            for key in node.structured_payload.parent_evidence_ids:
                target = by_id.get(key)
                if target is None:
                    raise ValueError("MISSING_BENCHMARK_OR_PARENT")
                edges.append(
                    ClosureEdgeV2(
                        source_id=node.canonical_id,
                        target_id=key,
                        source_hash=node.content_hash,
                        target_hash=target.content_hash,
                        relationship="DERIVED_PARENT",
                        owner_relationship=(
                            "SAME_OWNER"
                            if node.owner_subject == target.owner_subject
                            else (
                                "BASE_MACRO_CONTEXT_PARENT"
                                if target.canonical_id in _inventory(inputs)
                                else "BENCHMARK_CONTEXT_PARENT"
                            )
                        ),
                        binding_identity=binding.content_identity,
                    )
                )
    for row in inputs.accepted_claims:
        for key in row.claim.evidence_ids:
            target = by_id.get(key)
            if target is None:
                raise ValueError("MISSING_DOCUMENT_OR_CLAIM_EVIDENCE")
            edges.append(
                ClosureEdgeV2(
                    source_id=str(row.claim.claim_id),
                    target_id=key,
                    source_hash=quality_hash(row.model_dump(mode="json")),
                    target_hash=target.content_hash,
                    relationship="CLAIM_CITATION",
                    owner_relationship="SAME_OWNER",
                    binding_identity=binding.content_identity,
                )
            )
    contexts = {context.content_identity: context for context in metric_contexts}
    for comparison in comparisons:
        for context in (comparison.primary_context, comparison.secondary_context):
            contexts[context.content_identity] = context
    receipt_index = {r.context_identity: r for r in metric_receipts}
    roles = []
    for context in contexts.values():
        if context.provider == "financial_modeling_prep":
            receipt = receipt_index.get(context.content_identity)
            if receipt is None:
                raise ValueError("FMP_METRIC_RECEIPT_UNBOUND")
            roles.append(
                ProviderRoleV2(
                    evidence_id=context.evidence_id,
                    metric=context.field_locator,
                    provider=context.provider,
                    endpoint=receipt.endpoint,
                    revision_identity=receipt.revision_identity,
                    response_identity=receipt.response_sha256,
                    retained_use_role="DIAGNOSTIC_ONLY",
                    comparison_eligibility="UNUSABLE_FOR_PIT_COMPARISON",
                    reason="REQUIRED_CLOCK_UNPROVEN",
                    context=context,
                )
            )
        elif context.provider == "sec_edgar":
            valid = [
                c.secondary_validity
                for c in comparisons
                if c.secondary_context.content_identity == context.content_identity
            ] + [
                c.primary_validity
                for c in comparisons
                if c.primary_context.content_identity == context.content_identity
            ]
            eligible = bool(valid) and all(v.status == "VALID" for v in valid)
            roles.append(
                ProviderRoleV2(
                    evidence_id=context.evidence_id,
                    metric=context.field_locator,
                    provider=context.provider,
                    endpoint=context.field_locator,
                    revision_identity=quality_hash(context.filing_refs),
                    response_identity=context.evidence_content_hash,
                    retained_use_role=(
                        "CORROBORATING_PIT_FACT" if eligible else "DIAGNOSTIC_ONLY"
                    ),
                    comparison_eligibility=(
                        "ELIGIBLE_SUBJECT_TO_DQ_V1_COMPARABILITY"
                        if eligible
                        else "UNUSABLE_FOR_PIT_COMPARISON"
                    ),
                    reason=None if eligible else "SEC_PER_METRIC_VALIDITY_UNPROVEN",
                    context=context,
                )
            )
        else:
            raise ValueError("UNREVIEWED_PROVIDER_ROLE")
    nodes = sorted(nodes, key=lambda n: (n.namespace, n.canonical_id))
    edges = sorted(edges, key=lambda e: (e.relationship, e.source_id, e.target_id))
    roles = sorted(roles, key=lambda r: r.content_identity)
    closure = ResearchEvidenceClosureV2(
        binding=binding,
        original_input_identity=descriptor_hash(inputs.model_dump(mode="json")),
        nodes=tuple(nodes),
        source_documents=source_documents,
        edges=tuple(edges),
        comparisons=comparisons,
        roles=tuple(roles),
        metric_receipts=metric_receipts,
        counted_identity=quality_hash(
            [n.content_identity for n in nodes if n.membership == "COUNTED_EVIDENCE"]
        ),
        witness_identity=quality_hash(
            [n.content_identity for n in nodes if n.membership == "DEPENDENCY_WITNESS"]
        ),
        edge_identity=quality_hash([e.content_identity for e in edges]),
        comparison_identity=quality_hash([c.content_identity for c in comparisons]),
        role_identity=quality_hash([r.content_identity for r in roles]),
    )
    return validate_closure(inputs, closure, comparisons=comparisons)


def validate_closure(
    inputs: ProductionDescriptorInput,
    closure: ResearchEvidenceClosureV2,
    *,
    comparisons: tuple[MetricComparisonAssessmentV1, ...] = (),
) -> ResearchEvidenceClosureV2:
    """Validate ALL bytes, namespaces, owners, usage and edges before membership."""
    closure = ResearchEvidenceClosureV2.model_validate_json(closure.model_dump_json())
    if quality_hash(frozen_profile()) != PROFILE_IDENTITY:
        raise ValueError("FROZEN_PROFILE_IDENTITY_MISMATCH")
    bind = closure.binding
    if (
        closure.original_input_identity
        != descriptor_hash(inputs.model_dump(mode="json"))
        or bind.consumer_asset != str(inputs.data_bundle.asset_id)
        or bind.source_run_id != inputs.research_state.lineage.source_run_id
        or bind.data_bundle_id != inputs.data_bundle.bundle_id
        or bind.research_state_id != inputs.research_state.research_state_id
        or bind.episode_id != inputs.research_episode.episode_id
        or bind.state_episode_usage_binding != usage_identity(inputs)
    ):
        raise ValueError("CLOSURE_RUN_CAPTURE_USAGE_BINDING")
    if closure.comparisons != comparisons:
        raise ValueError("COMPLETE_COMPARISON_INVENTORY_MISMATCH")
    for comparison in closure.comparisons:
        validate_comparison_binding(comparison, inputs)
    base = _inventory(inputs)
    nodes = {n.canonical_id: n for n in closure.nodes}
    if len(nodes) != len(closure.nodes):
        raise ValueError("DUPLICATE_CANONICAL_ALIAS")
    docs = {d.document_id: d for d in closure.source_documents}
    if len(docs) != len(closure.source_documents):
        raise ValueError("DUPLICATE_SOURCE_DOCUMENT")
    for source_doc in docs.values():
        if (
            hashlib.sha256(source_doc.raw_text.encode()).hexdigest()
            != source_doc.raw_document_sha256
        ):
            raise ValueError("RAW_DOCUMENT_HASH")
    direct = {
        key
        for row in inputs.accepted_claims
        if countable_claim(row.claim)
        for key in row.claim.evidence_ids
    }
    refs = {key for row in inputs.accepted_claims for key in row.claim.evidence_ids}
    parents = {key for item in base.values() for key in item.parent_evidence_ids}
    expected = set(base) | refs | parents
    pending = list(parents)
    while pending:
        key = pending.pop()
        node = nodes.get(key)
        if node is None:
            raise ValueError("DANGLING_PARENT")
        if node.structured_payload:
            for parent in node.structured_payload.parent_evidence_ids:
                if parent not in expected:
                    expected.add(parent)
                    pending.append(parent)
    if set(nodes) != expected:
        raise ValueError("INJECTED_OR_MISSING_CLOSURE_NODE")
    used_docs = set()
    for node in closure.nodes:
        if (
            node.binding_identity != bind.content_identity
            or node.consumer_asset != bind.consumer_asset
        ):
            raise ValueError("NODE_BINDING_MISMATCH")
        if node.namespace == "STRUCTURED_EVIDENCE":
            item = node.structured_payload
            if (
                item is None
                or node.document_payload is not None
                or not evidence_hash_matches(item)
                or (node.canonical_id, node.content_hash, node.owner_subject)
                != (item.evidence_id, item.content_hash, item.subject_id)
                or node.capability != item.field_path.split(".")[0]
                or node.temporal_provenance
                != _structured_node(
                    item, bind, witness=node.canonical_id not in base
                ).temporal_provenance
                or node.source_identity
                != _structured_node(
                    item, bind, witness=node.canonical_id not in base
                ).source_identity
                or node.payload_reference != quality_hash(item.model_dump(mode="json"))
                or node.hash_convention != "RESEARCH_EVIDENCE_ITEM_V1"
            ):
                raise ValueError("STRUCTURED_PAYLOAD_HASH_NAMESPACE")
            if (
                node.source_identity.provider != item.source.provider_name
                or node.source_identity.normalized_record_id
                != item.source.normalized_record_key
                or node.source_identity.source_url != item.source.source_url
            ):
                raise ValueError("STRUCTURED_SOURCE_MISMATCH")
            if node.canonical_id in base:
                if (
                    item != base[node.canonical_id]
                    or node.membership != "COUNTED_EVIDENCE"
                    or node.object_type != "TARGET_CAPABILITY_EVIDENCE"
                    or node.membership_reason != "BASE_CANONICAL_INVENTORY"
                ):
                    raise ValueError("BASE_INVENTORY_LAUNDERING")
            elif (
                node.object_type != "BENCHMARK_CONTEXT_PARENT"
                or node.membership != "DEPENDENCY_WITNESS"
                or node.membership_reason != "BENCHMARK_CONTEXT_PARENT"
                or item.field_path != "ohlcv.close"
                or node.owner_subject not in ("US:SPY", "US:QQQ", "US:XLK")
            ):
                raise ValueError("UNAPPROVED_CROSS_OWNER_DEPENDENCY")
        else:
            doc = node.document_payload
            if (
                doc is None
                or node.structured_payload is not None
                or node.object_type != "DOCUMENT_CHUNK"
                or node.hash_convention != "EXACT_CHUNK_UTF8_SHA256"
            ):
                raise ValueError("DOCUMENT_NAMESPACE_MISMATCH")
            raw = docs.get(doc.document_id)
            source = base.get(doc.source_evidence_id)
            if (
                raw is None
                or source is None
                or raw.owner_subject != bind.consumer_asset
                or doc.document_owner != bind.consumer_asset
                or node.owner_subject != bind.consumer_asset
                or source.content_hash != doc.source_evidence_hash
                or source.subject_id != bind.consumer_asset
                or source.source.provider_name != doc.source_identity.provider
                or source.source.source_url != doc.source_identity.source_url
            ):
                raise ValueError("DOCUMENT_OWNER_SOURCE_BINDING")
            expected_document_id = source.source.normalized_record_key
            if (
                doc.object_type == "news"
                and source.source.provider_name == "alpaca_market_data"
            ):
                expected_document_id = "alpaca-news-" + expected_document_id
            if (
                doc.document_id != expected_document_id
                or doc.source_identity.normalized_record_id != doc.document_id
            ):
                raise ValueError("DOCUMENT_REGISTRY_BINDING")
            if (
                doc.char_end > len(raw.raw_text)
                or doc.char_start >= doc.char_end
                or raw.raw_text[doc.char_start : doc.char_end].strip() != doc.chunk_text
                or doc.raw_document_sha256 != raw.raw_document_sha256
                or doc.source_identity.raw_receipt_identity != raw.raw_document_sha256
                or doc.source_identity.snapshot_identity != raw.raw_document_sha256
                or _chunk_id(doc.document_id, doc.chunk_index, doc.chunk_text)
                != doc.canonical_id
                or hashlib.sha256(doc.chunk_text.encode()).hexdigest()
                != doc.chunk_text_sha256
                or (node.canonical_id, node.content_hash)
                != (doc.canonical_id, doc.chunk_text_sha256)
                or node.payload_reference != doc.content_identity
                or node.source_identity != doc.source_identity
                or node.temporal_provenance != doc.temporal_provenance
            ):
                raise ValueError("DOCUMENT_TEXT_OFFSET_HASH")
            used_docs.add(doc.document_id)
            counted = node.canonical_id in direct
            if (
                node.membership
                != ("COUNTED_EVIDENCE" if counted else "DEPENDENCY_WITNESS")
                or node.membership_reason
                != (
                    "DIRECT_FACT_CITATION" if counted else "NONCOUNTABLE_CLAIM_CITATION"
                )
                or node.capability
                != ("filings" if doc.object_type == "filing" else "news_evidence")
            ):
                raise ValueError("DOCUMENT_COUNTED_MEMBERSHIP")
            claim_refs = [
                ref
                for row in inputs.accepted_claims
                if doc.canonical_id in row.claim.evidence_ids
                for ref in row.claim.source_references
            ]
            if (
                doc.exact_citation_reference not in claim_refs
                or doc.exact_citation_reference.document_id != doc.document_id
                or doc.exact_citation_reference.excerpt_ref != doc.canonical_id
            ):
                raise ValueError("DOCUMENT_CITATION_BINDING")
    if used_docs != set(docs):
        raise ValueError("UNRELATED_SOURCE_DOCUMENT_INJECTION")
    expected_edges = []
    for node in closure.nodes:
        if node.structured_payload:
            for key in node.structured_payload.parent_evidence_ids:
                target = nodes[key]
                cross = node.owner_subject != target.owner_subject
                macro_parent = bool(
                    target.canonical_id in base
                    and target.owner_subject == "US"
                    and target.capability == "macro_indicators"
                    and target.structured_payload is not None
                    and target.structured_payload.source.provider_name == "fred"
                    and node.capability == "macro_indicators"
                    and node.structured_payload.transformation_version
                    == "macro_snapshot_v1"
                    and node.structured_payload.transformation_name is not None
                    and node.structured_payload.transformation_name.startswith(
                        "macro_snapshot."
                    )
                )
                if (
                    cross
                    and not macro_parent
                    and (
                        target.object_type != "BENCHMARK_CONTEXT_PARENT"
                        or node.owner_subject != bind.consumer_asset
                        or node.structured_payload.transformation_version
                        not in ("market_context_v1", "1.0")
                        or node.structured_payload.transformation_name is None
                        or not node.structured_payload.transformation_name.startswith(
                            (
                                "benchmark_context.",
                                "technical_feature.relative_strength_",
                            )
                        )
                    )
                ):
                    raise ValueError("CROSS_ASSET_DEPENDENCY_LEAKAGE")
                expected_edges.append(
                    ClosureEdgeV2(
                        source_id=node.canonical_id,
                        target_id=key,
                        source_hash=node.content_hash,
                        target_hash=target.content_hash,
                        relationship="DERIVED_PARENT",
                        owner_relationship=(
                            "BASE_MACRO_CONTEXT_PARENT"
                            if macro_parent
                            else ("BENCHMARK_CONTEXT_PARENT" if cross else "SAME_OWNER")
                        ),
                        binding_identity=bind.content_identity,
                    )
                )
    claims = {str(r.claim.claim_id): r for r in inputs.accepted_claims}
    if len(claims) != len(inputs.accepted_claims) or any(
        key not in claims
        for row in claims.values()
        for key in row.claim.upstream_claim_ids
    ):
        raise ValueError("CLAIM_UPSTREAM_CLOSURE")
    for row in claims.values():
        for key in row.claim.evidence_ids:
            target = nodes[key]
            if target.owner_subject != bind.consumer_asset:
                raise ValueError("CLAIM_CROSS_ASSET_LEAKAGE")
            if countable_claim(row.claim) and target.membership != "COUNTED_EVIDENCE":
                raise ValueError("FACT_WITNESS_ONLY")
            expected_edges.append(
                ClosureEdgeV2(
                    source_id=str(row.claim.claim_id),
                    target_id=key,
                    source_hash=quality_hash(row.model_dump(mode="json")),
                    target_hash=target.content_hash,
                    relationship="CLAIM_CITATION",
                    owner_relationship="SAME_OWNER",
                    binding_identity=bind.content_identity,
                )
            )
    if closure.edges != tuple(
        sorted(expected_edges, key=lambda e: (e.relationship, e.source_id, e.target_id))
    ):
        raise ValueError("EDGE_INVENTORY_BINDING")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("DERIVATION_CYCLE")
        if key in visited:
            return
        visiting.add(key)
        item = nodes[key].structured_payload
        for parent in item.parent_evidence_ids if item else ():
            visit(parent)
        visiting.remove(key)
        visited.add(key)

    for key in nodes:
        visit(key)
    from src.services.evidence_role_receipts import validate_metric_receipts

    validate_metric_receipts(inputs, closure)
    for role in closure.roles:
        context = role.context
        if (
            context is None
            or context.evidence_id != role.evidence_id
            or context.provider != role.provider
            or role.metric != context.field_locator
        ):
            raise ValueError("ROLE_CONTEXT_BINDING")
        if role.provider == "financial_modeling_prep":
            if (
                role.retained_use_role != "DIAGNOSTIC_ONLY"
                or role.comparison_eligibility != "UNUSABLE_FOR_PIT_COMPARISON"
                or role.reason != "REQUIRED_CLOCK_UNPROVEN"
            ):
                raise ValueError("FMP_ROLE_LAUNDERING")
        elif role.provider == "sec_edgar":
            validities = [
                c.secondary_validity
                for c in comparisons
                if c.secondary_context == context
            ] + [
                c.primary_validity for c in comparisons if c.primary_context == context
            ]
            eligible = bool(validities) and all(v.status == "VALID" for v in validities)
            if role.retained_use_role != (
                "CORROBORATING_PIT_FACT" if eligible else "DIAGNOSTIC_ONLY"
            ) or role.comparison_eligibility != (
                "ELIGIBLE_SUBJECT_TO_DQ_V1_COMPARABILITY"
                if eligible
                else "UNUSABLE_FOR_PIT_COMPARISON"
            ):
                raise ValueError("SEC_PER_METRIC_ROLE")
        else:
            raise ValueError("UNREVIEWED_PROVIDER_ROLE")
    fmp_nodes = {
        n.canonical_id
        for n in closure.nodes
        if n.structured_payload is not None
        and n.structured_payload.source.provider_name == "financial_modeling_prep"
    }
    fmp_role_ids = {
        r.evidence_id for r in closure.roles if r.provider == "financial_modeling_prep"
    }
    if fmp_nodes != fmp_role_ids:
        raise ValueError("ALL_FMP_METRICS_ROLE_CENSUS")
    contexts = [r.context.content_identity for r in closure.roles if r.context]
    if len(contexts) != len(set(contexts)):
        raise ValueError("DUPLICATE_PROVIDER_ROLE")
    for role in closure.roles:
        if role.provider == "sec_edgar" and role.context:
            context = role.context
            if (
                role.revision_identity != quality_hash(context.filing_refs)
                or role.response_identity != context.evidence_content_hash
                or role.endpoint != context.field_locator
            ):
                raise ValueError("SEC_REVISION_RESPONSE_BINDING")
            if any(key not in nodes for key in context.operand_evidence_ids):
                raise ValueError("SEC_OPERAND_CLOSURE")
    needed = {
        context.content_identity
        for c in comparisons
        for context in (c.primary_context, c.secondary_context)
    }
    if any(
        r.context is not None
        and r.provider == "sec_edgar"
        and r.context.content_identity not in needed
        for r in closure.roles
    ):
        raise ValueError("UNREGISTERED_SEC_ROLE")
    if not needed.issubset(
        {r.context.content_identity for r in closure.roles if r.context}
    ):
        raise ValueError("MISSING_REGISTERED_ROLE")
    for field, values in [
        (
            "counted_identity",
            [
                n.content_identity
                for n in closure.nodes
                if n.membership == "COUNTED_EVIDENCE"
            ],
        ),
        (
            "witness_identity",
            [
                n.content_identity
                for n in closure.nodes
                if n.membership == "DEPENDENCY_WITNESS"
            ],
        ),
        ("edge_identity", [e.content_identity for e in closure.edges]),
        ("comparison_identity", [c.content_identity for c in comparisons]),
        ("role_identity", [r.content_identity for r in closure.roles]),
    ]:
        if getattr(closure, field) != quality_hash(values):
            raise ValueError("SUB_INVENTORY_IDENTITY")
    return closure


def document_reference(node: ClosureNodeV2) -> SourceReference:
    """Expose canonical citations without translating namespace IDs to ev aliases."""
    if node.structured_payload:
        return node.structured_payload.to_source_reference()
    assert node.document_payload is not None
    return node.document_payload.exact_citation_reference


def bridge_documents(
    inputs: ProductionDescriptorInput,
    repository: DocumentRepository,
    *,
    artifact_base: Path | None = None,
) -> tuple[tuple[DocumentChunkProofV2, ...], tuple[SourceDocumentWitnessV2, ...]]:
    """Resolve canonical repository chunks; temporal gaps stay explicit."""
    base = _inventory(inputs)
    references = {}
    for row in inputs.accepted_claims:
        for key in row.claim.evidence_ids:
            if key not in base:
                refs = [
                    ref for ref in row.claim.source_references if ref.excerpt_ref == key
                ]
                if len(refs) != 1 or refs[0].document_id is None:
                    raise ValueError("UNRESOLVED_DOCUMENT_REFERENCE")
                references[key] = refs[0]
    chunks = []
    documents = {}
    for key, ref in sorted(references.items()):
        if ref.document_id is None:
            raise ValueError("UNRESOLVED_DOCUMENT_REFERENCE")
        document = repository.get_document(ref.document_id)
        if (
            document is None
            or document.raw_text_path is None
            or document.checksum_sha256 is None
        ):
            raise ValueError("MISSING_SOURCE_DOCUMENT")
        if document.doc_type.value not in ("filing", "news"):
            raise ValueError("UNAPPROVED_DOCUMENT_TYPE")
        candidates = [
            item
            for item in base.values()
            if item.source.provider_name == document.source_id
            and item.source.source_url == document.source_url
            and (
                item.source.normalized_record_key == document.document_id
                or (
                    document.doc_type.value == "news"
                    and item.source.provider_name == "alpaca_market_data"
                    and "alpaca-news-" + item.source.normalized_record_key
                    == document.document_id
                )
            )
            and item.field_path.startswith(("filings.", "news_evidence."))
        ]
        if not candidates:
            raise ValueError("DOCUMENT_CANONICAL_SOURCE_UNBOUND")
        source = sorted(candidates, key=lambda item: item.evidence_id)[0]
        chunk = next(
            (
                item
                for item in repository.list_chunks(document.document_id)
                if item.chunk_id == key
            ),
            None,
        )
        if (
            chunk is None
            or chunk.asset_id != document.asset_id
            or chunk.market != document.market
        ):
            raise ValueError("MISSING_OR_WRONG_OWNER_CANONICAL_CHUNK")
        raw_path = Path(document.raw_text_path)
        if artifact_base is not None and not raw_path.is_absolute():
            raw_path = artifact_base / raw_path
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != document.checksum_sha256:
            raise ValueError("RAW_DOCUMENT_HASH")
        documents[document.document_id] = SourceDocumentWitnessV2(
            document_id=document.document_id,
            owner_subject=str(document.asset_id),
            raw_text=raw.decode("utf-8"),
            raw_document_sha256=document.checksum_sha256,
            publication_clock_literal=(
                document.publish_ts.isoformat() if document.publish_ts else None
            ),
            repository_created_clock_literal=document.created_at.isoformat(),
            canonical_clock_policy_reference=None,
        )
        metadata = chunk.metadata_json or {}
        start, end = metadata.get("char_start"), metadata.get("char_end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or isinstance(end, bool)
        ):
            raise ValueError("CHUNK_OFFSETS_UNPROVEN")
        # Bare SQL TIMESTAMP is not source timezone or clock-policy proof.
        temporal = TemporalProvenanceV2(
            effective_at=None,
            available_at=None,
            observed_at=None,
            ingested_at=None,
            clock_evidence_refs=(source.content_hash, document.checksum_sha256),
            unavailable_reason="CANONICAL_DOCUMENT_RETAINED_CLOCK_POLICY_NOT_EXPLICIT",
        )
        identity = SourceIdentityV2(
            provider=document.source_id,
            normalized_record_id=document.document_id,
            source_url=document.source_url,
            raw_receipt_identity=document.checksum_sha256,
            snapshot_identity=document.checksum_sha256,
        )
        chunks.append(
            DocumentChunkProofV2(
                document_id=document.document_id,
                document_owner=str(document.asset_id),
                source_evidence_id=source.evidence_id,
                source_evidence_hash=source.content_hash,
                canonical_id=chunk.chunk_id,
                object_type="filing" if document.doc_type.value == "filing" else "news",
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                chunk_text_sha256=hashlib.sha256(chunk.chunk_text.encode()).hexdigest(),
                offset_convention="PYTHON_UNICODE_CODEPOINTS_SLICE_STRIP_V1",
                char_start=start,
                char_end=end,
                raw_document_sha256=document.checksum_sha256,
                exact_citation_reference=ref,
                source_identity=identity,
                temporal_provenance=temporal,
            )
        )
    return tuple(chunks), tuple(documents[key] for key in sorted(documents))
