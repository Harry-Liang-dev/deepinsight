"""Evidence-bound context from retained operands, never from scalar inference."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.schemas.market_data import FundamentalRecord
from src.schemas.research_data import ResearchEvidenceItem
from src.schemas.research_data_quality import (
    ContextDimension as D,
)
from src.schemas.research_data_quality import (
    MetricComparisonContextV1,
    known,
    quality_hash,
    unknown,
)


def fundamental_context(
    item: ResearchEvidenceItem,
    record: FundamentalRecord,
) -> MetricComparisonContextV1:
    """Read only metric-local facts/metadata; absent proof remains unknown."""
    field = item.field_path.rsplit(".", 1)[-1]
    metadata = (
        json.loads(record.metric_context_json) if record.metric_context_json else {}
    )
    metric: dict[str, Any] = metadata.get("metrics", {}).get(field, {})
    snapshot = str(metadata.get("provider_snapshot") or "UNRETAINED_PROVIDER_SNAPSHOT")
    refs = (
        str(
            metric.get("response_sha256")
            or metric.get("raw_fact_sha256")
            or item.content_hash
        ),
    )
    dimensions = {dimension: unknown("not retained for this metric") for dimension in D}
    dimensions[D.SUBJECT] = known(str(record.asset_id), item.evidence_id)
    if metadata.get("issuer_cik"):
        dimensions[D.ISSUER] = known(str(metadata["issuer_cik"]), *refs)
    dimensions[D.UNIT] = (
        known(str(item.unit), item.evidence_id) if item.unit else unknown("unit absent")
    )
    dimensions[D.PERIOD_END] = unknown("metric endpoint period not retained")
    # SEC retains the fiscal endpoint; it is not an FMP endpoint date.
    if record.source_id != "financial_modeling_prep":
        dimensions[D.PERIOD_END] = known(record.fiscal_period_end.isoformat(), *refs)
        if metric.get("period_start"):
            dimensions[D.PERIOD_START] = known(str(metric["period_start"]), *refs)
        if metric.get("concept"):
            dimensions[D.ACCOUNTING] = known(str(metric["concept"]), *refs)
        if metric.get("unit"):
            dimensions[D.UNIT] = known(str(metric["unit"]), *refs)
        if metric.get("accession"):
            dimensions[D.REVISION] = unknown(
                "accession retained; cross-source revision equivalence unproved"
            )
    returned = metric.get("returned_context", {})
    if returned.get("date"):
        dimensions[D.PERIOD_END] = known(str(returned["date"]), *refs)
    if (
        metric.get("declared_endpoint_basis") == "TTM"
        or record.source_id == "financial_modeling_prep"
        and record.report_type == "TTM_STANDARDIZED"
        and field in {"roe", "roa"}
    ):
        dimensions[D.BASIS] = known("TTM", *refs)
    available = _clock(metric.get("accepted_at") or returned.get("acceptedDate"))
    acquired = _clock(metric.get("acquired_at"))
    # A normalized row's shared clock does not prove endpoint-local publication.
    observed = acquired or (
        item.observed_at if record.source_id != "financial_modeling_prep" else None
    )
    ingested = _clock(metadata.get("normalized_ingested_at"))
    if ingested is None and record.ingestion_ts.tzinfo:
        ingested = record.ingestion_ts
    if metadata.get("normalized_ingested_at"):
        observed = acquired or ingested
    clock_refs = (*refs, quality_hash(metadata)) if metadata else ()
    return MetricComparisonContextV1(
        evidence_id=item.evidence_id,
        evidence_content_hash=item.content_hash,
        provider=item.source.provider_name,
        provider_snapshot=snapshot,
        field_locator=str(metric.get("field_locator") or item.field_path),
        computation_version=str(
            metric.get("normalization") or "historical_normalization_context_unretained"
        ),
        dimensions=dimensions,
        available_at=available,
        observed_at=observed,
        ingested_at=ingested,
        clock_evidence_refs=clock_refs,
        grounding_refs=refs,
        closure_refs=(item.source.provider_locator,),
        independent_source_refs=(item.source.provider_name,),
        filing_refs=tuple(
            str(metric[k]) for k in ("accession", "form", "filed") if metric.get(k)
        ),
    )


def derived_context(
    item: ResearchEvidenceItem,
    parents: tuple[ResearchEvidenceItem, ...],
    contexts: dict[str, MetricComparisonContextV1],
    *,
    metric: str,
    report_type: str,
) -> MetricComparisonContextV1:
    """Trace selected SEC operands; do not borrow unrelated historical parents."""
    selected = tuple(contexts[p.evidence_id] for p in parents)
    dims = {dimension: unknown("derived operand context incomplete") for dimension in D}
    dims[D.SUBJECT] = known(item.subject_id, *item.parent_evidence_ids)
    dims[D.PERIOD_END] = known(
        item.effective_at.date().isoformat(), *item.parent_evidence_ids
    )
    dims[D.METRIC] = known(
        f"fundamental_features_v2/{metric}", *item.parent_evidence_ids
    )
    supplied_fallback = len(parents) == 1 and parents[0].field_path == item.field_path
    if supplied_fallback:
        dims = dict(selected[0].dimensions)
    if (
        not supplied_fallback
        and report_type in {"annual", "10-K"}
        and metric not in {"current_ratio", "debt_to_equity"}
    ):
        dims[D.BASIS] = known("ANNUAL", *item.parent_evidence_ids)
    if not supplied_fallback and metric in {"roe", "roa"}:
        dims[D.DENOMINATOR_CONVENTION] = known(
            "ENDING_BALANCE", *item.parent_evidence_ids
        )
    if metric.endswith("_yoy") and len(parents) == 2:
        dims[D.GROWTH_FORMULA] = known("current/prior-1", *item.parent_evidence_ids)
        for dimension, parent in zip(
            (D.GROWTH_CURRENT, D.GROWTH_BASELINE), parents, strict=True
        ):
            dims[dimension] = known(
                f"{parent.field_path}|{parent.effective_at.date()}", parent.evidence_id
            )
        dims[D.FISCAL_ALIGNMENT] = known(
            "same_form_nearest_year_within_45_days_v2", *item.parent_evidence_ids
        )
    if item.unit:
        dims[D.UNIT] = known(item.unit, *item.parent_evidence_ids)
    for dimension in (
        D.ISSUER,
        D.PERIOD_START,
        D.DURATION,
        D.ACCOUNTING,
        D.SCOPE,
        D.CURRENCY,
        D.REVISION,
        D.SCALE,
    ):
        values = {c.dimensions[dimension].value for c in selected}
        if len(values) == 1 and all(
            c.dimensions[dimension].status == "KNOWN" for c in selected
        ):
            dims[dimension] = selected[0].dimensions[dimension]
    clocks = [c.available_at for c in selected]
    available = (
        max(c for c in clocks if c is not None)
        if all(c is not None for c in clocks)
        else None
    )
    return MetricComparisonContextV1(
        evidence_id=item.evidence_id,
        evidence_content_hash=item.content_hash,
        provider=item.source.provider_name,
        provider_snapshot="derived:" + item.content_hash,
        field_locator=item.field_path,
        computation_version="fundamental_features_v2",
        dimensions=dims,
        available_at=available,
        observed_at=(
            max(c.observed_at for c in selected if c.observed_at)
            if all(c.observed_at is not None for c in selected)
            else None
        ),
        ingested_at=(
            max(c.ingested_at for c in selected if c.ingested_at)
            if all(c.ingested_at is not None for c in selected)
            else None
        ),
        clock_evidence_refs=tuple(
            ref for c in selected for ref in c.clock_evidence_refs
        ),
        grounding_refs=item.parent_evidence_ids,
        closure_refs=item.parent_evidence_ids,
        independent_source_refs=tuple(
            sorted({r for c in selected for r in c.independent_source_refs})
        ),
        operand_evidence_ids=item.parent_evidence_ids,
        filing_refs=tuple(ref for c in selected for ref in c.filing_refs),
    )


def _clock(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo and result.utcoffset() is not None else None
