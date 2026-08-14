"""Time-safe assembly of structured research context from L0–L4 Memory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime

from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextRequest,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.models.enums import MarketScope, MemoryLevel
from src.repositories.base import RepositoryError
from src.repositories.memory import MemoryItemRepository
from src.repositories.records import MemoryItemRecord
from src.repositories.vector import (
    VectorRepository,
    VectorRepositoryError,
    VectorSearchCandidate,
)
from src.services.embedding import EmbeddingService, EmbeddingServiceError

_SECTION_LEVEL = {
    ResearchContextSection.CURRENT_SNAPSHOT: MemoryLevel.L0,
    ResearchContextSection.MACRO_EVENTS: MemoryLevel.L1,
    ResearchContextSection.ASSET_EVENTS: MemoryLevel.L2,
    ResearchContextSection.PRIOR_RESEARCH: MemoryLevel.L3,
    ResearchContextSection.PRIOR_RISK: MemoryLevel.L3,
    ResearchContextSection.HISTORICAL_ANALOGS: MemoryLevel.L4,
    ResearchContextSection.REGIME_CONTEXT: MemoryLevel.L4,
}
_HISTORICAL_ANALOG_TYPES = frozenset({"historical_analog", "historical_analogue"})


class ResearchContextRetrievalError(RuntimeError):
    """Raised when an attributable point-in-time bundle cannot be built."""


def build_research_context(
    *,
    request: ResearchContextRequest,
    memory_repository: MemoryItemRepository,
    vector_repository: VectorRepository,
    embedder: EmbeddingService,
) -> ResearchContextBundle:
    """Build one structured bundle without exposing vector implementation state.

    Args:
        request: Validated point-in-time query and isolation filters.
        memory_repository: Authoritative structured Memory metadata.
        vector_repository: Provider-independent semantic retrieval boundary.
        embedder: Replaceable query embedding service.

    Returns:
        A source-preserving research context bundle with explicit gaps.

    Raises:
        ResearchContextRetrievalError: If embedding, vector persistence, or
            DuckDB/vector consistency prevents safe retrieval.
    """

    namespaces = [
        _namespace_for_level(level) for level in dict.fromkeys(request.memory_levels)
    ]
    try:
        snapshot_id = vector_repository.snapshot_id(namespaces)
        query_vector = embedder.embed(request.query_text)
        candidates = vector_repository.search_across(
            namespaces=namespaces,
            query_vector=query_vector,
            top_k=None,
        )
    except (EmbeddingServiceError, VectorRepositoryError) as exc:
        raise ResearchContextRetrievalError(
            "research context semantic retrieval failed"
        ) from exc
    if len(query_vector) != embedder.dimension:
        raise ResearchContextRetrievalError(
            "embedder returned an inconsistent dimension"
        )

    buckets: dict[ResearchContextSection, list[ResearchContextMemory]] = {
        section: [] for section in ResearchContextSection
    }
    excluded = {
        "future": 0,
        "namespace": 0,
        "asset": 0,
        "market": 0,
        "importance": 0,
        "expired": 0,
        "current_report": 0,
    }
    eligible_count = 0
    as_of = _as_utc(request.as_of)
    requested_levels = set(request.memory_levels)

    for candidate in candidates:
        record = _resolve_record(memory_repository, candidate, requested_levels)
        effective_ts = _as_utc(record.effective_ts)
        if effective_ts > as_of:
            excluded["future"] += 1
            continue
        if _is_current_report(record, request.current_report_id):
            excluded["current_report"] += 1
            continue

        namespace_match = _namespace_match(record, request)
        if namespace_match is None:
            excluded["namespace"] += 1
            continue
        record_market = _record_market(record)
        if record_market not in (
            MarketScope.GLOBAL,
            MarketScope(request.market.value),
        ):
            excluded["market"] += 1
            continue
        if not _matches_asset(record, request, record_market):
            excluded["asset"] += 1
            continue
        if record.importance_score < request.min_importance_score:
            excluded["importance"] += 1
            continue
        if record.expires_at is not None and _as_utc(record.expires_at) <= as_of:
            excluded["expired"] += 1
            continue
        if record.source_ref is None:
            raise ResearchContextRetrievalError(
                "eligible Memory has no attributable source reference"
            )

        section = _section_for(record)
        buckets[section].append(
            ResearchContextMemory(
                memory_id=record.memory_id,
                section=section,
                memory_level=record.memory_level,
                namespace_key=record.namespace_key,
                asset_id=record.asset_id,
                market=record_market,
                memory_type=record.memory_type,
                summary_text=record.summary_text,
                effective_ts=effective_ts,
                importance_score=record.importance_score,
                retrieval_score=candidate.score,
                retrieval_reason=_retrieval_reason(
                    record,
                    section,
                    namespace_match,
                    request,
                ),
                source=record.source_ref,
                created_by=record.created_by,
            )
        )
        eligible_count += 1

    for section, items in buckets.items():
        items.sort(key=_relevance_order)
        buckets[section] = items[: request.top_k_per_section]

    missing_context = _missing_context(request, buckets)
    section_counts = {section: len(items) for section, items in buckets.items()}
    result_count = sum(section_counts.values())
    status = (
        RetrievalStatus.EMPTY
        if result_count == 0
        else RetrievalStatus.PARTIAL if missing_context else RetrievalStatus.COMPLETE
    )
    metadata = RetrievalMetadata(
        query_id=_query_id(request),
        query_text=request.query_text,
        as_of=as_of,
        market=request.market,
        asset_id=request.asset_id,
        namespace_keys=list(request.namespace_keys),
        requested_levels=list(request.memory_levels),
        current_report_id=request.current_report_id,
        min_importance_score=request.min_importance_score,
        top_k_per_section=request.top_k_per_section,
        snapshot_id=snapshot_id,
        candidate_count=len(candidates),
        eligible_count=eligible_count,
        result_count=result_count,
        excluded_future_count=excluded["future"],
        excluded_namespace_count=excluded["namespace"],
        excluded_asset_count=excluded["asset"],
        excluded_market_count=excluded["market"],
        excluded_importance_count=excluded["importance"],
        excluded_expired_count=excluded["expired"],
        excluded_current_report_count=excluded["current_report"],
        section_counts=section_counts,
        status=status,
        no_relevant_memory=result_count == 0,
    )
    return ResearchContextBundle(
        current_snapshot=buckets[ResearchContextSection.CURRENT_SNAPSHOT],
        macro_events=buckets[ResearchContextSection.MACRO_EVENTS],
        asset_events=buckets[ResearchContextSection.ASSET_EVENTS],
        prior_research=buckets[ResearchContextSection.PRIOR_RESEARCH],
        prior_risk=buckets[ResearchContextSection.PRIOR_RISK],
        historical_analogs=buckets[ResearchContextSection.HISTORICAL_ANALOGS],
        regime_context=buckets[ResearchContextSection.REGIME_CONTEXT],
        retrieval_metadata=metadata,
        missing_context=missing_context,
    )


def _resolve_record(
    repository: MemoryItemRepository,
    candidate: VectorSearchCandidate,
    requested_levels: set[MemoryLevel],
) -> MemoryItemRecord:
    try:
        record = repository.get_by_vector(candidate.namespace, candidate.vector_id)
    except RepositoryError as exc:
        raise ResearchContextRetrievalError(
            "Memory vector mapping could not be resolved"
        ) from exc
    if record is None:
        raise ResearchContextRetrievalError(
            "Memory vector has no DuckDB sidecar mapping"
        )
    if record.memory_level not in requested_levels:
        raise ResearchContextRetrievalError(
            "Memory vector namespace maps to an unexpected level"
        )
    if candidate.metadata.get("memory_id") != record.memory_id:
        raise ResearchContextRetrievalError(
            "vector metadata does not match its DuckDB Memory record"
        )
    return record


def _namespace_match(
    record: MemoryItemRecord,
    request: ResearchContextRequest,
) -> str | None:
    if record.namespace_key in set(request.namespace_keys):
        return "exact_namespace"
    if (
        request.include_prior_reports
        and request.asset_id is not None
        and record.asset_id == request.asset_id
        and record.memory_level is MemoryLevel.L3
        and _normalized_type(record.memory_type) == "report_trace"
        and record.namespace_key.startswith("REPORT:")
    ):
        return "historical_report_asset_match"
    return None


def _matches_asset(
    record: MemoryItemRecord,
    request: ResearchContextRequest,
    record_market: MarketScope,
) -> bool:
    if request.asset_id is None:
        return True
    if record.asset_id is not None:
        return record.asset_id == request.asset_id
    return record_market is MarketScope.GLOBAL or record.namespace_key in {
        request.market.value,
        str(request.asset_id),
        "GLOBAL",
    }


def _record_market(record: MemoryItemRecord) -> MarketScope | None:
    if record.asset_id is not None:
        return MarketScope(record.asset_id.market.value)
    if record.namespace_key == "GLOBAL":
        return MarketScope.GLOBAL
    prefix = record.namespace_key.split(":", maxsplit=1)[0]
    if prefix in {"CN", "HK", "US"}:
        return MarketScope(prefix)
    return None


def _is_current_report(
    record: MemoryItemRecord,
    current_report_id: str | None,
) -> bool:
    return (
        current_report_id is not None
        and record.memory_level is MemoryLevel.L3
        and record.namespace_key == f"REPORT:{current_report_id}"
    )


def _section_for(record: MemoryItemRecord) -> ResearchContextSection:
    if record.memory_level is MemoryLevel.L0:
        return ResearchContextSection.CURRENT_SNAPSHOT
    if record.memory_level is MemoryLevel.L1:
        return ResearchContextSection.MACRO_EVENTS
    if record.memory_level is MemoryLevel.L2:
        return ResearchContextSection.ASSET_EVENTS
    if record.memory_level is MemoryLevel.L3:
        return (
            ResearchContextSection.PRIOR_RISK
            if "risk" in _normalized_type(record.memory_type)
            else ResearchContextSection.PRIOR_RESEARCH
        )
    if _normalized_type(record.memory_type) in _HISTORICAL_ANALOG_TYPES:
        return ResearchContextSection.HISTORICAL_ANALOGS
    return ResearchContextSection.REGIME_CONTEXT


def _retrieval_reason(
    record: MemoryItemRecord,
    section: ResearchContextSection,
    namespace_match: str,
    request: ResearchContextRequest,
) -> str:
    asset_reason = (
        "global_or_market_context"
        if record.asset_id is None
        else f"asset={record.asset_id}"
    )
    return (
        f"semantic_relevance;section={section.value};"
        f"namespace_match={namespace_match};{asset_reason};"
        f"market={request.market.value};effective_ts<=as_of;"
        f"importance>={request.min_importance_score:.6f}"
    )


def _relevance_order(item: ResearchContextMemory) -> tuple[float, float, float, str]:
    return (
        -item.retrieval_score,
        -item.importance_score,
        -item.effective_ts.timestamp(),
        item.memory_id,
    )


def _missing_context(
    request: ResearchContextRequest,
    buckets: Mapping[ResearchContextSection, list[ResearchContextMemory]],
) -> list[MissingContext]:
    requested_levels = set(request.memory_levels)
    missing: list[MissingContext] = []
    for section in ResearchContextSection:
        if buckets[section]:
            continue
        level = _SECTION_LEVEL[section]
        reason = (
            MissingContextReason.NO_RELEVANT_MEMORY
            if level in requested_levels
            else MissingContextReason.NOT_REQUESTED
        )
        detail = (
            f"No relevant {section.value} Memory existed at or before "
            f"{_as_utc(request.as_of).isoformat()} after namespace, asset, "
            "market, importance, expiry, and current-report filters."
            if reason is MissingContextReason.NO_RELEVANT_MEMORY
            else f"Memory level {level.value} was not requested."
        )
        missing.append(
            MissingContext(
                section=section,
                reason=reason,
                detail=detail,
                requested_levels=[level],
            )
        )
    return missing


def _query_id(request: ResearchContextRequest) -> str:
    encoded = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"memquery_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _normalized_type(memory_type: str) -> str:
    return memory_type.strip().lower().replace("-", "_").replace(" ", "_")


def _namespace_for_level(level: MemoryLevel) -> str:
    return f"memory_{level.value}_v1"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
