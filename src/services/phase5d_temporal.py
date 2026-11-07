"""Offline resolution of frozen policies and actual raw normalization witnesses."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from src.schemas.evidence_closure import ClosureNodeV2
from src.schemas.phase5d_authority import REGISTRY_IDENTITY, authority
from src.schemas.phase5d_evidence import (
    AcquisitionReceipt,
    PitEvidenceInput,
    TemporalAuthority,
)
from src.schemas.research_data_quality import quality_hash


class TemporalPolicyResolver(Protocol):
    """Only local immutable reviewed policies can establish source clock meaning."""

    def resolve(self, reference: str, identity: str) -> dict[str, Any]:
        """Return exact policy content or reject a claimed unresolvable authority."""
        ...


class FrozenTemporalPolicyResolver:
    """Closed Main registry; no remote lookup or nonempty-string permission."""

    def resolve(self, reference: str, identity: str) -> dict[str, Any]:
        """Verify registry and independently hash selected policy bytes."""
        registry = authority("policies")
        if quality_hash(registry) != REGISTRY_IDENTITY:
            raise ValueError("TEMPORAL_REGISTRY_HASH")
        for policy in registry["policies"]:
            if reference == f"policy://{policy['policy_id']}/{policy['version']}":
                if quality_hash(policy) != identity:
                    raise ValueError("CLOCK_POLICY_HASH")
                return dict(policy)
        raise ValueError("UNRESOLVABLE_CLOCK_POLICY")


def parser_identity() -> str:
    """Bind normalization to this actual deterministic parser implementation."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def receipt_bytes(receipt: AcquisitionReceipt) -> bytes:
    """Verify exact retained bytes before decoding; compression is explicit."""
    receipt = AcquisitionReceipt.model_validate_json(receipt.model_dump_json())
    raw = base64.b64decode(receipt.body_base64, validate=True)
    if (
        len(raw) != receipt.size_bytes
        or hashlib.sha256(raw).hexdigest() != receipt.body_sha256
    ):
        raise ValueError("RAW_RECEIPT_HASH")
    return (
        gzip.decompress(raw)
        if receipt.content_encoding == "gzip"
        else (zlib.decompress(raw) if receipt.content_encoding == "deflate" else raw)
    )


def pointer(document: Any, locator: str) -> Any:
    """Resolve strict RFC6901 pointers against actual supplied source fields."""
    if not locator.startswith("/"):
        raise ValueError("UNRESOLVABLE_RAW_FIELD")
    value = document
    try:
        for part in locator[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("UNRESOLVABLE_RAW_FIELD") from exc
    return value


def source_time(literal: str) -> tuple[datetime | None, str, str]:
    """Preserve exact precision; naive/date-only literals remain ineligible."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", literal):
        return None, "DATE", "UNPROVEN"
    if not re.search(r"(Z|[+-]\d{2}:\d{2})$", literal):
        return None, "UNZONED", "UNPROVEN"
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", literal
    ):
        raise ValueError("INVALID_SOURCE_TIMESTAMP_LITERAL")
    fraction = re.search(r"\.(\d+)(?:Z|[+-]\d{2}:\d{2})$", literal)
    if fraction and len(fraction.group(1)) > 6:
        # Python datetime cannot represent nanoseconds: never round availability down.
        return None, "FRACTIONAL_SECOND", "Z" if literal.endswith("Z") else literal[-6:]
    result = datetime.fromisoformat(literal.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("SOURCE_OFFSET_UNPROVEN")
    zone = "Z" if literal.endswith("Z") else literal[-6:]
    precision = "FRACTIONAL_SECOND" if "." in literal.split("T")[-1] else "SECOND"
    return result.astimezone(UTC), precision, zone


def operator_identity(name: str, version: str) -> str:
    """Resolve existing deterministic operators, never an arbitrary declaration."""
    from src.services.research_data_quality import TRANSFORM_VERSIONS

    prefix = name.split(".")[0]
    if f"{prefix}/{version}" not in TRANSFORM_VERSIONS:
        raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    names = {
        "technical_feature": "technical_features.py",
        "fundamental_features": "fundamental_features.py",
        "valuation": "valuation.py",
        "benchmark_context": "market_context.py",
        "macro_snapshot": "../services/research_data_bundle.py",
        "market_context": "market_context.py",
    }
    field = name.removeprefix(prefix + ".")
    if prefix == "fundamental_features":
        from src.operators.fundamental_features import _OUTPUT_KEYS

        if field not in _OUTPUT_KEYS:
            raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    elif prefix == "technical_feature":
        from src.operators.technical_features import _OUTPUT_KEYS as technical_keys

        if field not in technical_keys and field not in {
            "relative_strength_vs_spy",
            "relative_strength_vs_qqq",
            "relative_strength_vs_xlk",
        }:
            raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    elif prefix in {"benchmark_context", "market_context"}:
        allowed = {
            "asset_return_20d",
            "market_return_20d",
            "growth_return_20d",
            "sector_return_20d",
            "excess_return_vs_market",
            "excess_return_vs_growth",
            "excess_return_vs_sector",
            "relative_strength_market",
            "relative_strength_growth",
            "relative_strength_sector",
            "benchmark_trend",
            "market_volatility",
            "sector_volatility",
        }
        if field not in allowed:
            raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    elif prefix == "valuation" and field not in {
        "market_cap",
        "eps_ttm",
        "book_value_per_share",
        "pe_ttm",
        "pb",
        "earnings_yield",
    }:
        raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    elif prefix == "macro_snapshot":
        from src.services.research_data_bundle import _MACRO_SNAPSHOT_FIELDS

        if field not in _MACRO_SNAPSHOT_FIELDS.values():
            raise ValueError("UNREVIEWED_DERIVATION_OPERATOR")
    path = Path(__file__).resolve().parents[1] / "operators" / names[prefix]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_temporal(
    envelope: PitEvidenceInput,
    node: ClosureNodeV2,
    proof: TemporalAuthority,
    *,
    parent_availability: dict[str, datetime | None],
    resolver: TemporalPolicyResolver,
) -> tuple[datetime | None, tuple[str, ...]]:
    """Recompute raw clock proof; reject tampering/chronology before eligibility."""
    proof = TemporalAuthority.model_validate_json(proof.model_dump_json())
    binding = envelope.closure.binding
    inputs = envelope.original_input
    if (
        (
            proof.namespace,
            proof.object_type,
            proof.evidence_id,
            proof.content_hash,
            proof.owner,
            proof.consumer_asset,
            proof.capture_id,
            proof.consumer_run_id,
            proof.data_bundle_id,
            proof.usage_identity,
        )
        != (
            node.namespace,
            node.object_type,
            node.canonical_id,
            node.content_hash,
            node.owner_subject,
            binding.consumer_asset,
            binding.capture_id,
            binding.source_run_id,
            binding.data_bundle_id,
            binding.state_episode_usage_binding,
        )
        or proof.research_as_of != inputs.data_bundle.as_of
        or proof.generated_at != inputs.generated_at
    ):
        raise ValueError("TEMPORAL_OWNER_RUN_CAPTURE_BINDING")
    policy = resolver.resolve(proof.policy_reference, proof.policy_identity)
    if (
        policy["policy_id"] != proof.policy_id
        or policy["version"] != proof.policy_version
    ):
        raise ValueError("CLOCK_POLICY_VERSION_BINDING")
    cutoff, generated = proof.research_as_of, proof.generated_at
    if cutoff > generated:
        raise ValueError("CUTOFF_AFTER_GENERATION")
    if proof.policy_id == "DETERMINISTIC_PARENT_MAX_V1":
        item = node.structured_payload
        if item is None or not item.parent_evidence_ids:
            raise ValueError("DERIVATION_WITHOUT_CANONICAL_OPERANDS")
        prefix = (item.transformation_name or "").split(".")[0]
        expected_capability = {
            "technical_feature": "technical_features",
            "fundamental_features": "fundamentals",
            "valuation": "valuation",
            "benchmark_context": "market_context",
            "market_context": "market_context",
            "macro_snapshot": "macro_indicators",
        }.get(prefix)
        if node.capability != expected_capability:
            raise ValueError("DERIVATION_CAPABILITY_SCOPE")
        parent_nodes = {n.canonical_id: n for n in envelope.closure.nodes}
        allowed_parent_caps = {
            "technical_feature": {"ohlcv"},
            "fundamental_features": {"fundamentals"},
            "valuation": {"fundamentals", "ohlcv"},
            "benchmark_context": {"ohlcv"},
            "market_context": {"ohlcv"},
            "macro_snapshot": {"macro_indicators"},
        }
        if any(
            parent_nodes[key].capability not in allowed_parent_caps[prefix]
            for key in item.parent_evidence_ids
        ):
            raise ValueError("DERIVATION_OPERAND_METRIC_SCOPE")
        authorities = {p.evidence_id: p for p in envelope.authorities}
        expected = tuple(
            authorities[key].content_identity
            for key in item.parent_evidence_ids
            if key in authorities
        )
        if proof.operand_authorities != expected or (
            proof.operator_name != item.transformation_name
            or proof.operator_version != item.transformation_version
            or proof.operator_name is None
            or proof.operator_version is None
            or proof.operator_identity
            != operator_identity(proof.operator_name, proof.operator_version)
            or proof.acquisition is not None
            or proof.normalization is not None
        ):
            raise ValueError("DERIVATION_OPERATOR_OPERAND_BINDING")
        if proof.computed_at is None or proof.computed_at > generated:
            raise ValueError("DERIVATION_MATERIALIZATION_CAUSALITY")
        if len(expected) != len(item.parent_evidence_ids):
            if proof.available_at is not None:
                raise ValueError("DERIVED_AVAILABILITY_WITH_UNPROVEN_OPERANDS")
            return None, ("REQUIRED_OPERAND_AUTHORITY_MISSING",)
        parents = [parent_availability.get(key) for key in item.parent_evidence_ids]
        if any(p is None for p in parents):
            return None, ("REQUIRED_OPERAND_UNUSABLE",)
        available = max(p for p in parents if p is not None)
        if proof.available_at != available:
            raise ValueError("DERIVED_AVAILABILITY_NOT_PARENT_MAX")
        for key in item.parent_evidence_ids:
            parent = authorities[key]
            materialized = parent.computed_at or (
                parent.normalization.materialized_at if parent.normalization else None
            )
            if materialized is None or materialized > proof.computed_at:
                raise ValueError("DERIVATION_BEFORE_OPERAND_MATERIALIZATION")
        return available, () if available <= cutoff else ("NOT_AVAILABLE_AT_CUTOFF",)
    raw, normalized = proof.acquisition, proof.normalization
    if raw is None or normalized is None:
        raise ValueError("CLAIMED_AUTHORITY_WITHOUT_RECEIPTS")
    body = receipt_bytes(raw)
    if (
        raw.owner != node.owner_subject
        or normalized.acquisition_identity != raw.content_identity
        or normalized.parser_build_identity != parser_identity()
        or normalized.revision_literal != raw.revision_id
    ):
        raise ValueError("NORMALIZATION_SOURCE_RECEIPT_BINDING")
    observed, ingested = raw.observed_at, normalized.ingested_at
    if not observed <= ingested <= normalized.materialized_at <= generated:
        raise ValueError("OBSERVATION_INGESTION_GENERATION_CAUSALITY")
    if raw.provider != node.source_identity.provider:
        raise ValueError("SOURCE_PROVIDER_BINDING")
    if proof.policy_id == "DOCUMENT_RETRIEVAL_WITNESS_V1":
        if proof.available_at is not None or normalized.clocks:
            raise ValueError("RETRIEVAL_IS_NOT_PUBLICATION")
        if node.document_payload is not None:
            verify_document(envelope, node, proof)
        return None, ("PUBLICATION_NOT_PROVEN_RETRIEVAL_ONLY",)
    if raw.provider != policy["provider"]:
        raise ValueError("CROSS_ENDPOINT_SOURCE_CLOCK")
    payload = json.loads(body)
    if str(pointer(payload, normalized.revision_locator)) != raw.revision_id:
        raise ValueError("SOURCE_REVISION_MISMATCH")
    expected_semantics: tuple[str, ...]
    required_fields: tuple[str, ...]
    expected_locators: tuple[str, ...]
    if proof.policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1":
        if (
            not raw.endpoint.startswith("https://data.sec.gov/submissions/")
            or not raw.revision_id
        ):
            raise ValueError("SEC_ACCESSION_ENDPOINT_BINDING")
        if (
            normalized.primary_document_locator is None
            or normalized.primary_document_literal is None
            or (
                pointer(payload, normalized.primary_document_locator)
                != normalized.primary_document_literal
            )
        ):
            raise ValueError("SEC_PRIMARY_DOCUMENT_REVISION")
        cik_match = re.fullmatch(
            r"https://data.sec.gov/submissions/CIK(\d{10})\.json", raw.endpoint
        )
        if cik_match is None or str(payload.get("cik", "")).lstrip(
            "0"
        ) != cik_match.group(1).lstrip("0"):
            raise ValueError("SEC_SUBMISSIONS_CIK_RECEIPT_BINDING")
        expected_semantics = ("SEC_ACCESSION_ACCEPTANCE",)
        required_fields = ("acceptanceDateTime",)
        if not normalized.revision_locator.endswith(
            "/accessionNumber/" + normalized.revision_locator.split("/")[-1]
        ):
            raise ValueError("SEC_ACCESSION_FIELD")
        prefix, index = normalized.revision_locator.rsplit("/accessionNumber/", 1)
        if normalized.primary_document_locator != prefix + "/primaryDocument/" + index:
            raise ValueError("SEC_DOCUMENT_INDEX_BINDING")
        expected_locators = (prefix + "/acceptanceDateTime/" + index,)
    else:
        if raw.endpoint != "https://data.alpaca.markets/v1beta1/news":
            raise ValueError("NEWS_ENDPOINT_BINDING")
        expected_semantics = ("NEWS_PUBLICATION", "RETURNED_REVISION_AVAILABILITY")
        required_fields = ("created_at", "updated_at")
        if not normalized.revision_locator.endswith("/id"):
            raise ValueError("NEWS_ID_FIELD")
        prefix = normalized.revision_locator.removesuffix("/id")
        expected_locators = (prefix + "/created_at", prefix + "/updated_at")
        if (
            node.structured_payload is not None
            and node.structured_payload.source.normalized_record_key != raw.revision_id
        ):
            raise ValueError("NEWS_CANONICAL_ID_REVISION_BINDING")
        if (
            node.document_payload is not None
            and node.document_payload.document_id != "alpaca-news-" + raw.revision_id
        ):
            raise ValueError("NEWS_CANONICAL_DOCUMENT_REVISION_BINDING")
        if node.capability != "news_evidence":
            raise ValueError("NEWS_POLICY_NOT_OTHER_METRIC_AUTHORITY")
    if tuple(c.semantics for c in normalized.clocks) != expected_semantics:
        raise ValueError("SOURCE_CLOCK_SEMANTICS")
    times = []
    for clock, field, locator in zip(
        normalized.clocks, required_fields, expected_locators, strict=True
    ):
        if clock.field_locator != locator:
            raise ValueError("CROSS_RECORD_CLOCK_BORROWING")
        if (
            field not in clock.field_locator.split("/")
            or pointer(payload, clock.field_locator) != clock.literal
        ):
            raise ValueError("RAW_TIMESTAMP_FIELD_LITERAL")
        actual, precision, zone = source_time(clock.literal)
        if (actual, precision, zone) != (
            clock.normalized_at,
            clock.precision,
            clock.native_zone,
        ):
            raise ValueError("INDEPENDENT_CLOCK_NORMALIZATION_MISMATCH")
        times.append(actual)
    if node.document_payload is not None:
        verify_document(envelope, node, proof)
    if any(t is None for t in times):
        if proof.available_at is not None:
            raise ValueError("UNZONED_CLOCK_FABRICATED_AS_AVAILABILITY")
        return None, ("UNUSABLE_FOR_EXACT_TIME_REQUIREMENT",)
    if (
        len(times) == 2
        and times[0] is not None
        and times[1] is not None
        and times[1] < times[0]
    ):
        raise ValueError("NEWS_REVISION_BEFORE_PUBLICATION")
    available = max(t for t in times if t is not None)
    if proof.available_at != available or available > observed:
        raise ValueError("SOURCE_AVAILABILITY_CAUSALITY")
    if (
        node.document_payload is None
        and node.structured_payload is not None
        and not node.structured_payload.parent_evidence_ids
    ):
        if (
            proof.policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1"
            and node.capability not in ("filings", "news_evidence")
            and normalized.canonical_value_locator is None
        ):
            # SEC acceptance and financial value have distinct native endpoints.
            # The independent fact validator also proves their exact association.
            from src.services.phase5d_evidence import _sec_fact

            facts = [
                p for p in envelope.fact_proofs if p.evidence_id == node.canonical_id
            ]
            if len(facts) != 1:
                return available, ("SEC_PER_METRIC_FACT_CONTEXT_UNPROVEN",)
            reasons = _sec_fact(envelope, node.canonical_id, facts[0], proof)
            if reasons:
                return available, reasons
        elif normalized.canonical_value_locator is None:
            return available, ("EXACT_SOURCE_VALUE_UNPROVEN",)
        elif (
            pointer(payload, normalized.canonical_value_locator)
            != node.structured_payload.value
        ):
            raise ValueError("RAW_CANONICAL_VALUE_BINDING")
        if (
            proof.policy_id == "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1"
            and normalized.canonical_value_locator is not None
            and not normalized.canonical_value_locator.startswith(prefix + "/")
        ):
            raise ValueError("NEWS_FACT_REVISION_BINDING")
    if available > cutoff:
        return available, ("NOT_AVAILABLE_AT_CUTOFF",)
    if proof.mode == "HISTORICAL_REPLAY" and ingested > cutoff:
        return available, ("HISTORICAL_INGESTION_AFTER_CUTOFF",)
    return available, ()


def verify_document(
    envelope: PitEvidenceInput, node: ClosureNodeV2, proof: TemporalAuthority
) -> None:
    """Verify HTTP bytes, exact extraction, document revision and chunk association."""
    from src.adapters.providers import _html_to_text

    doc, extraction = node.document_payload, proof.document
    if (
        doc is None
        or extraction is None
        or proof.acquisition is None
        or proof.normalization is None
    ):
        raise ValueError("DOCUMENT_HTTP_EXTRACTION_PROOF_MISSING")
    raw = extraction.receipt
    body = receipt_bytes(raw).decode("utf-8")
    if (
        raw.owner != node.owner_subject
        or raw.provider != proof.acquisition.provider
        or raw.revision_id != proof.acquisition.revision_id
    ):
        raise ValueError("DOCUMENT_REVISION_OWNER_SOURCE")
    if (
        not raw.observed_at
        <= extraction.ingested_at
        <= extraction.materialized_at
        <= extraction.chunk_materialized_at
        <= proof.generated_at
    ):
        raise ValueError("DOCUMENT_MATERIALIZATION_CAUSALITY")
    if proof.available_at is not None and proof.available_at > raw.observed_at:
        raise ValueError("DOCUMENT_AVAILABILITY_AFTER_ACTUAL_RECEIPT")
    if (
        node.temporal_provenance.available_at is not None
        and node.temporal_provenance.available_at != proof.available_at
    ):
        raise ValueError("CANONICAL_DOCUMENT_AVAILABILITY_MISMATCH")
    if extraction.extraction == "JSON_HTML_TEXT_V1":
        if extraction.text_locator is None or raw != proof.acquisition:
            raise ValueError("NEWS_EXTRACTION_REVISION_RECEIPT")
        prefix = proof.normalization.revision_locator.removesuffix("/id")
        if extraction.text_locator != prefix + "/content":
            raise ValueError("DOCUMENT_REVISION_CONTENT_FIELD")
        text = _html_to_text(str(pointer(json.loads(body), extraction.text_locator)))
    else:
        text = _html_to_text(body) if extraction.extraction == "HTML_TEXT_V1" else body
    if proof.policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1" and (
        proof.acquisition.revision_id.replace("-", "") not in raw.endpoint
        or proof.normalization.primary_document_literal is None
        or not raw.endpoint.endswith("/" + proof.normalization.primary_document_literal)
    ):
        raise ValueError("SEC_DOCUMENT_ACCESSION_ASSOCIATION")
    if (
        proof.policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1"
        and proof.acquisition.revision_id.replace("-", "")
        not in doc.document_id.replace("-", "")
    ):
        raise ValueError("SEC_CANONICAL_DOCUMENT_ACCESSION_BINDING")
    source = next(
        d for d in envelope.closure.source_documents if d.document_id == doc.document_id
    )
    digest = hashlib.sha256(text.encode()).hexdigest()
    if (
        extraction.document_id != doc.document_id
        or text != source.raw_text
        or digest != extraction.extracted_text_sha256
        or digest != source.raw_document_sha256
    ):
        raise ValueError("DOCUMENT_EXTRACTION_RAW_TEXT_HASH")
