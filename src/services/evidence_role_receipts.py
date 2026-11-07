"""Field-level retained response witnesses; no live source imports or retrieval."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import zlib
from datetime import datetime
from typing import Any

from src.schemas.evidence_closure import (
    MetricReceiptWitnessV2,
    ResearchEvidenceClosureV2,
)
from src.schemas.production_descriptors import ProductionDescriptorInput
from src.schemas.research_data_quality import MetricComparisonContextV1


def receipt_witness(
    context: MetricComparisonContextV1,
    metric: str,
    metadata: dict[str, Any],
    receipt: dict[str, Any],
) -> MetricReceiptWitnessV2:
    """Bind actual retained endpoint metadata, never infer a source clock."""
    return MetricReceiptWitnessV2(
        context_identity=context.content_identity,
        evidence_id=context.evidence_id,
        metric_id=metric,
        endpoint=metadata["endpoint"],
        field_locator=metadata["field_locator"],
        response_sha256=metadata["response_sha256"],
        size_bytes=receipt["size_bytes"],
        body_base64=receipt["body_base64"],
        content_encoding=receipt["content_encoding"],
        acquired_at=datetime.fromisoformat(receipt["acquired_at"]),
        raw_value=metadata["raw_value"],
        raw_unit=metadata["raw_unit"],
        normalization=metadata["normalization"],
    )


def validate_metric_receipts(
    inputs: ProductionDescriptorInput, closure: ResearchEvidenceClosureV2
) -> None:
    """Verify bytes, aliases, metric ownership and complete role binding."""
    from src.adapters.fmp import _GROWTH_FIELDS, _KEY_METRIC_FIELDS, _RATIOS_FIELDS

    mappings = {
        "ratios-ttm": _RATIOS_FIELDS,
        "key-metrics-ttm": _KEY_METRIC_FIELDS,
        "income-statement-growth": _GROWTH_FIELDS,
    }
    roles = {
        r.context.content_identity: r
        for r in closure.roles
        if r.context and r.provider == "financial_modeling_prep"
    }
    witnesses = {r.context_identity: r for r in closure.metric_receipts}
    if len(witnesses) != len(closure.metric_receipts) or set(roles) != set(witnesses):
        raise ValueError("FMP_ROLE_RECEIPT_CENSUS")
    nodes = {n.canonical_id: n for n in closure.nodes}
    for identity, witness in witnesses.items():
        raw = base64.b64decode(witness.body_base64, validate=True)
        if (
            hashlib.sha256(raw).hexdigest() != witness.response_sha256
            or len(raw) != witness.size_bytes
        ):
            raise ValueError("FMP_RECEIPT_HASH")
        decoded = (
            gzip.decompress(raw)
            if witness.content_encoding == "gzip"
            else zlib.decompress(raw) if witness.content_encoding == "deflate" else raw
        )
        body = json.loads(decoded)
        field = mappings[witness.endpoint].get(witness.metric_id)
        if (
            not field
            or witness.field_locator != "$[0]." + field
            or body[0].get(field) != witness.raw_value
        ):
            raise ValueError("FMP_LITERAL_METRIC_BINDING")
        role = roles[identity]
        node = nodes.get(witness.evidence_id)
        context = role.context
        if (
            context is None
            or node is None
            or node.structured_payload is None
            or node.structured_payload.value != witness.raw_value
            or node.structured_payload.field_path.rsplit(".", 1)[-1]
            != witness.metric_id
            or witness.acquired_at != context.observed_at
            or context.field_locator != witness.field_locator
            or context.evidence_id != witness.evidence_id
            or role.endpoint != witness.endpoint
            or role.response_identity != witness.response_sha256
            or role.revision_identity != witness.revision_identity
            or witness.response_sha256 not in context.clock_evidence_refs
        ):
            raise ValueError("FMP_RECEIPT_ROLE_BINDING")
        if body[0].get("symbol") != str(inputs.data_bundle.asset_id).split(":", 1)[1]:
            raise ValueError("FMP_RECEIPT_SUBJECT")
