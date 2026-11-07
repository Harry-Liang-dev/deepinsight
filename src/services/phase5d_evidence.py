"""Complete-graph PIT validity and the explicit, additive density v2 projection."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from src.schemas.common import SourceReference
from src.schemas.evidence_closure import ClosureNodeV2
from src.schemas.phase5d_authority import (
    DEFINITION_IDENTITY,
    PROFILE_IDENTITY,
    REGISTRY_IDENTITY,
    authority,
)
from src.schemas.phase5d_evidence import (
    ClaimEligibility,
    DensityObservationV2,
    EvidenceValidity,
    FactProof,
    Participation,
    PitEvaluation,
    PitEvidenceInput,
    TemporalAuthority,
)
from src.schemas.research_data import DataQualityStatus
from src.schemas.research_data_quality import (
    ContextDimension,
    RequirementAssessmentV1,
    quality_hash,
)
from src.services.evidence_closure import countable_claim, validate_closure
from src.services.phase5d_temporal import (
    FrozenTemporalPolicyResolver,
    pointer,
    receipt_bytes,
    verify_temporal,
)
from src.services.production_descriptors import build_information_density
from src.services.research_data_quality import (
    assess_requirements,
    inventory_profile,
    validate_fact,
)


def _sec_fact(
    envelope: PitEvidenceInput,
    key: str,
    proof: FactProof | None,
    temporal: TemporalAuthority | None,
) -> tuple[str, ...]:
    """Resolve exact SEC operands/context, independently of cross-source comparisons."""
    node = next(n for n in envelope.closure.nodes if n.canonical_id == key)
    item = node.structured_payload
    if proof is not None:
        receipt_bytes(proof.acquisition)
        if (
            proof.context_identity != proof.context.content_identity
            or proof.context.evidence_id != key
        ):
            raise ValueError("SEC_CONTEXT_BINDING")
    if item is None or proof is None or temporal is None:
        return ("SEC_PER_METRIC_FACT_CONTEXT_UNPROVEN",)
    context = proof.context
    if (
        proof.context_identity != context.content_identity
        or context.evidence_id != key
        or context.evidence_content_hash != item.content_hash
    ):
        raise ValueError("SEC_CONTEXT_BINDING")
    if (
        context.provider != "sec_edgar"
        or proof.acquisition.owner != node.owner_subject
        or proof.acquisition.provider != context.provider
    ):
        raise ValueError("SEC_SOURCE_OPERAND_OWNER")
    payload = json.loads(receipt_bytes(proof.acquisition))

    def literal(locator: str) -> Any:
        # XBRL units/concepts are actual JSON object keys, not guessed metadata.
        if locator.startswith("key:"):
            location = locator.removeprefix("key:")
            pointer(payload, location)
            return location.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
        return pointer(payload, locator)

    if not proof.acquisition.endpoint.startswith("https://data.sec.gov/api/xbrl/"):
        raise ValueError("SEC_FACT_RECEIPT_ENDPOINT")
    actual = {
        "value": pointer(payload, proof.value_locator),
        "accession": pointer(payload, proof.accession_locator),
        "unit": literal(proof.unit_locator),
        "concept": literal(proof.concept_locator),
        "period_end": pointer(payload, proof.period_end_locator),
        "form": pointer(payload, proof.form_locator),
    }
    _sec_split_association(envelope, node, proof, temporal, payload, actual)
    if (
        actual["value"] != item.value
        or actual["unit"] != item.unit
        or actual["accession"]
        != (temporal.acquisition.revision_id if temporal.acquisition else None)
    ):
        raise ValueError("SEC_EXACT_FACT_OPERAND_BINDING")
    from src.adapters.providers import _SEC_FACT_CONCEPTS

    aliases = {field: (tags, unit) for field, _, tags, unit in _SEC_FACT_CONCEPTS}
    field = item.field_path.rsplit(".", 1)[-1]
    if (
        field not in aliases
        or actual["concept"] not in aliases[field][0]
        or actual["unit"] != aliases[field][1]
    ):
        raise ValueError("SEC_CONCEPT_ALIAS_UNIT_BINDING")
    if proof.value_locator.endswith("/val"):
        own_fact = proof.value_locator.removesuffix("/val")
        if (
            proof.accession_locator != own_fact + "/accn"
            or proof.period_end_locator != own_fact + "/end"
            or proof.form_locator != own_fact + "/form"
            or proof.period_start_locator not in (None, own_fact + "/start")
        ):
            raise ValueError("SEC_CROSS_FACT_CONTEXT_BORROWING")
        if not own_fact.startswith(
            proof.unit_locator.removeprefix("key:") + "/"
        ) or not proof.unit_locator.removeprefix("key:").startswith(
            proof.concept_locator.removeprefix("key:") + "/units/"
        ):
            raise ValueError("SEC_XBRL_CONCEPT_UNIT_RECORD_ASSOCIATION")
    # These dimensions must be independently witnessed, not read out of a scalar.
    required = (
        ContextDimension.SUBJECT,
        ContextDimension.ISSUER,
        ContextDimension.METRIC,
        ContextDimension.SCOPE,
        ContextDimension.MEASUREMENT,
        ContextDimension.PERIOD_END,
        ContextDimension.BASIS,
        ContextDimension.UNIT,
        ContextDimension.CURRENCY,
        ContextDimension.SCALE,
        ContextDimension.REVISION,
        ContextDimension.EFFECTIVE,
    )
    reasons = [
        "SEC_CONTEXT_UNKNOWN:" + d.value
        for d in required
        if context.dimensions[d].status != "KNOWN"
    ]
    for dimension in required:
        witness = context.dimensions[dimension]
        if witness.status == "KNOWN":
            locator = proof.dimension_locators.get(dimension)
            if locator is None:
                reasons.append("SEC_DIMENSION_RAW_PROOF_MISSING:" + dimension.value)
            elif (
                str(pointer(payload, locator)) != witness.value
                or "receipt://" + proof.acquisition.content_identity + locator
                not in witness.evidence_refs
            ):
                raise ValueError("SEC_DIMENSION_RAW_PROOF_BINDING")
    if context.dimensions[ContextDimension.PERIOD_END].value != str(
        actual["period_end"]
    ) or context.dimensions[ContextDimension.UNIT].value != str(actual["unit"]):
        raise ValueError("SEC_PERIOD_UNIT_BINDING")
    if item.effective_at.date().isoformat() != str(actual["period_end"]):
        raise ValueError("SEC_CANONICAL_PERIOD_BINDING")
    if (
        actual["form"] in {"10-K", "10-K/A"}
        and context.dimensions[ContextDimension.BASIS].status == "KNOWN"
        and context.dimensions[ContextDimension.BASIS].value != "ANNUAL"
    ):
        raise ValueError("SEC_ANNUAL_PERIOD_BASIS_BINDING")
    if (
        actual["form"] in {"10-Q", "10-Q/A"}
        and context.dimensions[ContextDimension.BASIS].status == "KNOWN"
        and context.dimensions[ContextDimension.BASIS].value != "QUARTERLY"
    ):
        raise ValueError("SEC_QUARTERLY_PERIOD_BASIS_BINDING")
    if context.dimensions[ContextDimension.MEASUREMENT].value == "DURATION":
        if proof.period_start_locator is None:
            reasons.append("SEC_DURATION_START_UNPROVEN")
        elif context.dimensions[ContextDimension.PERIOD_START].value != str(
            pointer(payload, proof.period_start_locator)
        ):
            raise ValueError("SEC_DURATION_BINDING")
    if context.operand_evidence_ids != item.parent_evidence_ids:
        raise ValueError("SEC_SELECTED_OPERAND_CLOSURE")
    if item.parent_evidence_ids:
        # A scalar proof cannot certify an independently calculated financial metric.
        reasons.append("SEC_DERIVED_METRIC_REQUIRES_OPERAND_CONTEXT")
    if (
        context.available_at != temporal.available_at
        or context.observed_at
        != (temporal.acquisition.observed_at if temporal.acquisition else None)
        or context.ingested_at
        != (temporal.normalization.ingested_at if temporal.normalization else None)
    ):
        raise ValueError("SEC_CONTEXT_OWN_CLOCK_BINDING")
    reasons.extend(
        validate_fact(item, context, envelope.original_input.data_bundle.as_of).reasons
    )
    return tuple(sorted(set(reasons)))


def _sec_split_association(
    envelope: PitEvidenceInput,
    node: ClosureNodeV2,
    fact: FactProof,
    temporal: TemporalAuthority,
    payload: dict[str, Any],
    actual: dict[str, Any],
) -> None:
    """Join own SEC acceptance and own XBRL value without clock/value borrowing."""
    publication, normalization = temporal.acquisition, temporal.normalization
    item = node.structured_payload
    if publication is None or normalization is None or item is None:
        raise ValueError("SEC_SPLIT_REQUIRED_RECEIPTS")
    raw = fact.acquisition
    submission = json.loads(receipt_bytes(publication))
    # Each receipt has already been independently size/hash checked, not merged.
    company = re.fullmatch(
        r"https://data.sec.gov/api/xbrl/companyfacts/CIK(\d{10})\.json", raw.endpoint
    )
    filing = re.fullmatch(
        r"https://data.sec.gov/submissions/CIK(\d{10})\.json", publication.endpoint
    )
    if not company or not filing or company.group(1) != filing.group(1):
        raise ValueError("SEC_SPLIT_ISSUER_ENDPOINT")
    cik = company.group(1).lstrip("0")
    if (
        str(payload.get("cik", "")).lstrip("0") != cik
        or str(submission.get("cik", "")).lstrip("0") != cik
        or (fact.context.dimensions[ContextDimension.ISSUER].value or "").lstrip("0")
        != cik
        or item.source.provider_locator != raw.endpoint
        or fact.context.dimensions[ContextDimension.SUBJECT].value != item.subject_id
        or fact.context.dimensions[ContextDimension.CURRENCY].value != item.currency
    ):
        raise ValueError("SEC_SPLIT_ISSUER_BINDING")
    if (
        raw.owner != publication.owner
        or raw.source_run_id != publication.source_run_id
        or raw.source_run_id != envelope.closure.binding.source_run_id
        or raw.revision_id != publication.revision_id
        or actual["accession"] != publication.revision_id
        or fact.context.dimensions[ContextDimension.REVISION].value
        != actual["accession"]
        or fact.context.provider_snapshot != raw.content_identity
        or fact.context.field_locator != fact.value_locator
        or raw.content_identity not in fact.context.grounding_refs
        or publication.content_identity not in fact.context.clock_evidence_refs
    ):
        raise ValueError("SEC_SPLIT_ACCESSION_RUN_CONTEXT_BINDING")
    prefix, index = normalization.revision_locator.rsplit("/accessionNumber/", 1)
    accessions = pointer(submission, prefix + "/accessionNumber")
    if not isinstance(accessions, list) or accessions.count(actual["accession"]) != 1:
        raise ValueError("SEC_SPLIT_AMBIGUOUS_ACCESSION")
    if (
        pointer(submission, prefix + "/reportDate/" + index) != actual["period_end"]
        or pointer(submission, prefix + "/form/" + index) != actual["form"]
        or actual["form"] not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
        or not fact.value_locator.endswith("/val")
        or re.fullmatch(r"/facts/us-gaap/[^/]+/units/[^/]+/\d+/val", fact.value_locator)
        is None
    ):
        raise ValueError("SEC_SPLIT_PERIOD_FORM_REVISION_BINDING")
    if (
        temporal.available_at is not None and raw.observed_at < temporal.available_at
    ) or not raw.observed_at <= normalization.ingested_at <= temporal.generated_at:
        raise ValueError("SEC_SPLIT_VALUE_RECEIPT_CHRONOLOGY")
    if (
        temporal.mode == "HISTORICAL_REPLAY"
        and raw.observed_at > temporal.research_as_of
    ):
        raise ValueError("SEC_SPLIT_HISTORICAL_OBSERVATION")


def _sec_derived(
    envelope: PitEvidenceInput, key: str, valid_parents: bool
) -> tuple[str, ...]:
    """Reuse the reviewed traced SEC operator and its exact selected operands."""
    import pandas as pd  # type: ignore[import-untyped]

    from src.operators.fundamental_features import FundamentalFeatureOperator
    from src.services.fundamental_quality_context import derived_context

    node = next(n for n in envelope.closure.nodes if n.canonical_id == key)
    item = node.structured_payload
    assert item is not None
    if not valid_parents:
        return ("SEC_REQUIRED_OPERAND_UNUSABLE",)
    if (
        item.transformation_name
        != "fundamental_features." + item.field_path.rsplit(".", 1)[-1]
        or item.transformation_version != FundamentalFeatureOperator.version
    ):
        raise ValueError("SEC_UNREVIEWED_METRIC_OPERATOR")
    facts = {p.evidence_id: p for p in envelope.fact_proofs}
    parents = tuple(
        next(
            n.structured_payload for n in envelope.closure.nodes if n.canonical_id == p
        )
        for p in item.parent_evidence_ids
    )
    if any(p is None or p.evidence_id not in facts for p in parents):
        return ("SEC_SELECTED_OPERAND_CONTEXT_UNPROVEN",)
    rows: dict[str, dict[str, Any]] = {}
    ids = {}
    contexts = {}
    for parent in parents:
        assert parent is not None
        proof = facts[parent.evidence_id]
        context = proof.context
        payload = json.loads(receipt_bytes(proof.acquisition))
        form = str(pointer(payload, proof.form_locator))
        period = str(pointer(payload, proof.period_end_locator))
        record = parent.source.normalized_record_key
        row = rows.setdefault(
            record,
            dict(
                fiscal_period_end=period,
                report_type=form,
                revenue=None,
                net_income=None,
            ),
        )
        if row["fiscal_period_end"] != period or row["report_type"] != form:
            raise ValueError("SEC_SELECTED_RECORD_SCOPE_MISMATCH")
        field = parent.field_path.rsplit(".", 1)[-1]
        if field in row and row[field] is not None:
            raise ValueError("SEC_VERSION_AMBIGUOUS_OPERAND")
        row[field] = parent.value
        ids[(record, field)] = parent.evidence_id
        contexts[parent.evidence_id] = context
    frame = pd.DataFrame.from_dict(rows, orient="index")
    traced = FundamentalFeatureOperator().compute_traced(frame)
    metric = item.field_path.rsplit(".", 1)[-1]
    selected = traced.operands.get(metric, ())
    expected = tuple(ids[(p.row_index, p.field)] for p in selected)
    if expected != item.parent_evidence_ids or traced.values.get(metric) != item.value:
        raise ValueError("SEC_OPERATOR_VALUE_OR_SELECTED_OPERAND_MISMATCH")
    current_form = (
        str(frame.loc[selected[0].row_index, "report_type"]) if selected else "UNKNOWN"
    )
    context = derived_context(
        item,
        tuple(p for p in parents if p is not None),
        contexts,
        metric=metric,
        report_type=current_form,
    )
    required = [
        ContextDimension.METRIC,
        ContextDimension.BASIS,
        ContextDimension.UNIT,
        ContextDimension.SCOPE,
        ContextDimension.ISSUER,
        ContextDimension.CURRENCY,
        ContextDimension.SCALE,
    ]
    if metric.endswith("_yoy"):
        required += [
            ContextDimension.GROWTH_FORMULA,
            ContextDimension.GROWTH_CURRENT,
            ContextDimension.GROWTH_BASELINE,
            ContextDimension.FISCAL_ALIGNMENT,
        ]
    if metric in {"roe", "roa"}:
        required.append(ContextDimension.DENOMINATOR_CONVENTION)
    return tuple(
        "SEC_DERIVED_CONTEXT_UNPROVEN:" + d.value
        for d in required
        if context.dimensions[d].status != "KNOWN"
    )


def evaluate_pit(envelope: PitEvidenceInput) -> PitEvaluation:
    """Validate every supplied binding before walking all facts, then all Claims."""
    envelope = PitEvidenceInput.model_validate_json(envelope.model_dump_json())
    if quality_hash(authority("profile")) != PROFILE_IDENTITY:
        raise ValueError("FROZEN_PROFILE_HASH")
    from src.schemas.production_descriptors import descriptor_hash

    if descriptor_hash(authority("definition")) != DEFINITION_IDENTITY:
        raise ValueError("FROZEN_DEFINITION_HASH")
    inputs, closure = envelope.original_input, envelope.closure
    validate_closure(inputs, closure, comparisons=closure.comparisons)
    # Reuse State/Episode/Claim creation-order and exact producer binding checks.
    build_information_density(
        inputs,
        quality_policy="research_data_quality_contract_v1/1.0.0",
        requirement_profile=inventory_profile(),
        comparisons=closure.comparisons,
        closure=closure,
    )
    nodes = {n.canonical_id: n for n in closure.nodes}
    authorities = {p.evidence_id: p for p in envelope.authorities}
    facts = {p.evidence_id: p for p in envelope.fact_proofs}
    if (
        len(authorities) != len(envelope.authorities)
        or len(facts) != len(envelope.fact_proofs)
        or not set(authorities) <= nodes.keys()
        or not set(facts) <= nodes.keys()
    ):
        raise ValueError("ORPHAN_DUPLICATE_AUTHORITY_OR_FACT")
    for key, fact_proof in facts.items():
        receipt_bytes(fact_proof.acquisition)
        item = nodes[key].structured_payload
        if (
            item is None
            or item.source.provider_name != "sec_edgar"
            or fact_proof.acquisition.owner != nodes[key].owner_subject
            or fact_proof.acquisition.provider != "sec_edgar"
        ):
            raise ValueError("FACT_PROOF_SOURCE_OWNER_BINDING")
    results: dict[str, EvidenceValidity] = {}
    resolver = FrozenTemporalPolicyResolver()

    def walk(key: str) -> EvidenceValidity:
        if key in results:
            return results[key]
        node = nodes[key]
        parents = (
            node.structured_payload.parent_evidence_ids
            if node.structured_payload
            else (
                (node.document_payload.source_evidence_id,)
                if node.document_payload
                else ()
            )
        )
        parent_results = [walk(p) for p in parents]
        proof = authorities.get(key)
        available: datetime | None = None
        reasons: list[str] = []
        # Verify a supplied proof even for diagnostic/unusable nodes. Never filter it.
        if proof:
            available, temporal_reasons = verify_temporal(
                envelope,
                node,
                proof,
                parent_availability={
                    r.evidence_id: r.available_at if r.independently_valid else None
                    for r in parent_results
                },
                resolver=resolver,
            )
            reasons.extend(temporal_reasons)
        else:
            reasons.append("TEMPORAL_AUTHORITY_NOT_PROVEN")
        item = node.structured_payload
        provider = node.source_identity.provider
        if provider == "financial_modeling_prep":
            reasons.append("FMP_DIAGNOSTIC_ONLY_REQUIRED_CLOCK_UNPROVEN")
        elif (
            item
            and provider == "sec_edgar"
            and node.capability not in ("filings", "news_evidence")
        ):
            if item.parent_evidence_ids:
                if key in facts:
                    raise ValueError("DERIVED_METRIC_CANNOT_USE_SCALAR_FACT_PROOF")
                reasons.extend(
                    _sec_derived(
                        envelope,
                        key,
                        all(r.independently_valid for r in parent_results),
                    )
                )
            else:
                reasons.extend(_sec_fact(envelope, key, facts.get(key), proof))
        elif key in facts:
            raise ValueError("UNRELATED_FACT_PROOF")
        if item and item.quality != DataQualityStatus.PASS:
            reasons.append("APPLICABLE_ITEM_QUALITY_UNMET")
        if any(not r.independently_valid for r in parent_results):
            reasons.append("REQUIRED_DEPENDENCY_UNUSABLE")
        valid = not reasons and available is not None
        participation: Participation = (
            "DEPENDENCY_WITNESS"
            if node.membership == "DEPENDENCY_WITNESS"
            else (
                "DIAGNOSTIC_EVIDENCE"
                if provider == "financial_modeling_prep"
                else "PIT_COUNTED_EVIDENCE" if valid else "UNUSABLE_EVIDENCE"
            )
        )
        result = EvidenceValidity(
            evidence_id=key,
            participation=participation,
            independently_valid=valid,
            available_at=available,
            authority_identity=proof.content_identity if proof else None,
            reason_codes=tuple(sorted(set(reasons))),
            required_slot_satisfied=valid and participation == "PIT_COUNTED_EVIDENCE",
        )
        results[key] = result
        return result

    for node in closure.nodes:
        if any(
            c is not None and c > inputs.generated_at
            for c in (
                node.temporal_provenance.observed_at,
                node.temporal_provenance.ingested_at,
            )
        ):
            raise ValueError("LEGACY_OBSERVATION_INGESTION_AFTER_GENERATION")
    for key in nodes:
        walk(key)
    rows = {str(r.claim.claim_id): r for r in inputs.accepted_claims}

    def canonical_citation(node: ClosureNodeV2) -> SourceReference:
        if node.structured_payload is not None:
            return node.structured_payload.to_source_reference()
        assert node.document_payload is not None
        return node.document_payload.exact_citation_reference

    refs = {
        quality_hash(
            canonical_citation(node).model_dump(mode="json")
        ): node.canonical_id
        for node in closure.nodes
    }
    citation_keys = {}
    for key, row in rows.items():
        hashes = [
            quality_hash(ref.model_dump(mode="json"))
            for ref in row.claim.source_references
        ]
        if any(digest not in refs for digest in hashes):
            raise ValueError("UNBOUND_REQUIRED_CLAIM_CITATION")
        if row.claim.evidence_ids:
            expected = [
                quality_hash(canonical_citation(nodes[e]).model_dump(mode="json"))
                for e in row.claim.evidence_ids
            ]
            if not Counter(expected) <= Counter(hashes):
                raise ValueError("INVALID_REQUIRED_CLAIM_CITATION")
        citation_keys[key] = tuple(
            sorted(set(row.claim.evidence_ids) | {refs[h] for h in hashes})
        )
    claim_results: dict[str, ClaimEligibility] = {}
    visiting: set[str] = set()

    def claim_walk(key: str) -> ClaimEligibility:
        if key in visiting:
            raise ValueError("CLAIM_DEPENDENCY_CYCLE")
        if key in claim_results:
            return claim_results[key]
        visiting.add(key)
        claim = rows[key].claim
        reasons = []
        if not countable_claim(claim):
            reasons.append("NOT_DIRECT_FACT_WITH_CITATIONS")
        if any(
            results[e].participation != "PIT_COUNTED_EVIDENCE"
            or not results[e].independently_valid
            for e in citation_keys[key]
        ):
            reasons.append("REQUIRED_CITATION_UNUSABLE")
        if any(
            not claim_walk(p).eligible_for_pit_count for p in claim.upstream_claim_ids
        ):
            reasons.append("REQUIRED_UPSTREAM_CLAIM_UNUSABLE")
        result = ClaimEligibility(
            claim_id=key,
            required_evidence=citation_keys[key],
            eligible_for_pit_count=not reasons,
            reason_codes=tuple(reasons),
        )
        claim_results[key] = result
        visiting.remove(key)
        return result

    for key in rows:
        claim_walk(key)
    quality = assess_requirements(
        inputs,
        profile=inventory_profile(),
        comparisons=closure.comparisons,
        closure=closure,
    )
    failures = []
    requirement_rows = []
    for req in quality.requirements:
        successor_proven = False
        if req.requirement_id.startswith("document_clock:"):
            successor_proven = bool(req.evidence_refs) and all(
                results[e].independently_valid for e in req.evidence_refs
            )
        if successor_proven:
            req = RequirementAssessmentV1(
                **{
                    **req.model_dump(exclude={"content_identity"}),
                    "status": "SATISFIED",
                    "reason": "independent successor temporal authority proved",
                }
            )
        requirement_rows.append(req)
        if req.status in {"UNMET", "UNUSABLE"} and req.required:
            failures.append(req.requirement_id)
        if (
            req.required
            and req.status != "EXEMPT"
            and any(
                not results[e].required_slot_satisfied
                for e in req.evidence_refs
                if e in results and nodes[e].membership == "COUNTED_EVIDENCE"
            )
        ):
            failures.append("PIT_REQUIRED_SLOT:" + req.requirement_id)
    if any(a.disposition in {"CONFLICT", "INVALID_INPUT"} for a in closure.comparisons):
        failures.append("REGISTERED_COMPARISON_QUALITY_UNUSABLE")
    from src.models.enums import AgentStatus
    from src.schemas.research_episode import ResearchEpisodeTraceQuality

    if (
        inputs.research_episode.trace_quality != ResearchEpisodeTraceQuality.COMPLETE
        or not inputs.research_episode.agent_traces
        or any(t.status != AgentStatus.OK for t in inputs.research_episode.agent_traces)
    ):
        failures.append("INCOMPLETE_EPISODE_TRACE")
    if any(row.claim.claim_type is None for row in rows.values()):
        failures.append("UNKNOWN_CLAIM_TYPE")
    return PitEvaluation(
        input_identity=envelope.content_identity,
        evidence=tuple(results[k] for k in sorted(results)),
        claims=tuple(claim_results[k] for k in sorted(claim_results)),
        requirement_assessments=tuple(requirement_rows),
        mandatory_failures=tuple(sorted(set(failures))),
    )


def build_information_density_v2(envelope: PitEvidenceInput) -> DensityObservationV2:
    """Project the frozen C/E transform; missing required slots remain missing."""
    evaluation = evaluate_pit(envelope)
    evidence = tuple(
        sorted(
            r.evidence_id
            for r in evaluation.evidence
            if r.participation == "PIT_COUNTED_EVIDENCE"
        )
    )
    claims = tuple(
        sorted(r.claim_id for r in evaluation.claims if r.eligible_for_pit_count)
    )
    excluded = tuple(
        sorted(
            r.evidence_id
            for r in evaluation.evidence
            if r.participation != "PIT_COUNTED_EVIDENCE"
            and next(
                n for n in envelope.closure.nodes if n.canonical_id == r.evidence_id
            ).membership
            == "COUNTED_EVIDENCE"
        )
    )
    missing = bool(evaluation.mandatory_failures) or not evidence
    partial = (
        bool(excluded)
        or any(r.status in {"GAP", "UNMET"} for r in evaluation.requirement_assessments)
        or any(
            c.numeric_outcome == "NOT_EVALUATED" for c in envelope.closure.comparisons
        )
    )
    inputs = envelope.original_input
    return DensityObservationV2(
        profile_identity=PROFILE_IDENTITY,
        policy_registry_identity=REGISTRY_IDENTITY,
        source_input_identity=envelope.content_identity,
        evaluation_identity=evaluation.content_identity,
        asset_id=str(inputs.data_bundle.asset_id),
        source_run_id=envelope.closure.binding.source_run_id,
        research_as_of=inputs.data_bundle.as_of,
        generated_at=inputs.generated_at,
        available_at=inputs.generated_at,
        status="MISSING_INPUT" if missing else "PARTIAL" if partial else "PRESENT",
        value=None if missing else len(claims) / len(evidence),
        numerator=len(claims),
        denominator=len(evidence),
        eligible_claim_ids=claims,
        eligible_evidence_ids=evidence,
        excluded_evidence_ids=excluded,
        mandatory_failures=evaluation.mandatory_failures,
    )
