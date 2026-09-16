"""Day40 Learning Memory integration tests over existing DuckDB and FAISS."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    MemoryService,
    ResearchContextRequest,
    RetrievalStatus,
    SemanticMemoryLifecycleStatus,
)
from src.models.enums import Market, MemoryLevel, ResearchScopeType
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.schemas.common import SourceReference
from src.schemas.memory import MemorySearchRequest, MemoryWriteRequest
from src.schemas.temporal import TemporalMetadata, TemporalSourceKind
from src.services import FakeEmbeddingService

pytestmark = pytest.mark.integration

RESEARCH_AS_OF = datetime(2026, 8, 31, 12, tzinfo=UTC)
CREATED_AT = RESEARCH_AS_OF - timedelta(minutes=5)
EPISODE_ID = "research_episode_0123456789abcdef01234567"
STATE_ID = "research_state_0123456789abcdef01234567"
QUERY = "learning memory query"
VECTORS = {
    QUERY: [1.0, 0.0, 0.0],
    "Sector thesis claim": [1.0, 0.0, 0.0],
    "Chain risk claim": [0.9, 0.1, 0.0],
    "Macro episode claim": [1.0, 0.0, 0.0],
    "Research Episode reference": [1.0, 0.0, 0.0],
    "Available asset catalyst": [1.0, 0.0, 0.0],
    "Future asset catalyst": [1.0, 0.0, 0.0],
}


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return one isolated migrated DuckDB database."""

    database = DuckDBDatabase(tmp_path / "learning-memory.duckdb")
    database.bootstrap()
    return database


def _ids(*values: str) -> Iterator[str]:
    return iter(values)


def _service(
    database: DuckDBDatabase,
    root: Path,
    *,
    ids: Iterator[str],
) -> MemoryService:
    embedder = FakeEmbeddingService(VECTORS)
    return MemoryService(
        MemoryItemRepository(database),
        FaissVectorRepository(
            root,
            embedder_model=embedder.model_name,
            embedding_dim=embedder.dimension,
        ),
        embedder,
        clock=lambda: CREATED_AT,
        memory_id_factory=lambda: next(ids),
    )


def _metadata(
    *,
    scope_type: ResearchScopeType,
    scope_id: str,
    parent_scope_id: str,
    content_kind: EpisodicMemoryContentKind,
    available_at: datetime = CREATED_AT,
    source_claim_ids: tuple[str, ...] = ("claim:accepted:1",),
    source_event_ids: tuple[str, ...] = (),
) -> LearningMemoryMetadata:
    return LearningMemoryMetadata(
        usage_class=LearningMemoryUsageClass.EPISODIC,
        scope_type=scope_type,
        scope_id=scope_id,
        parent_scope_id=parent_scope_id,
        episode_id=EPISODE_ID,
        research_state_id=STATE_ID,
        source_claim_ids=source_claim_ids,
        source_event_ids=source_event_ids,
        temporal=TemporalMetadata(
            source_kind=TemporalSourceKind.MEMORY,
            event_time=RESEARCH_AS_OF - timedelta(days=1),
            available_at=available_at,
            effective_from=RESEARCH_AS_OF - timedelta(days=1),
        ),
        content_kind=content_kind,
    )


def _write(
    service: MemoryService,
    *,
    text: str,
    metadata: LearningMemoryMetadata,
    memory_type: str,
) -> str:
    result = service.write(
        MemoryWriteRequest(
            memory_level=MemoryLevel.L3,
            namespace_key=metadata.scope_id,
            asset_id=(
                AssetId(metadata.scope_id.removeprefix("ASSET:"))
                if metadata.scope_type is ResearchScopeType.ASSET
                else None
            ),
            effective_ts=RESEARCH_AS_OF - timedelta(days=1),
            summary_text=text,
            memory_type=memory_type,
            importance_score=0.9,
            source_ref_json=SourceReference(
                document_id=f"episode-source-{memory_type}",
                excerpt_ref=metadata.source_claim_ids[0],
                provider="research_episode_v1",
            ),
            created_by="learning_memory_v1",
            metadata=metadata,
        )
    )
    return result.memory_id


def _context_request(**updates: object) -> ResearchContextRequest:
    values: dict[str, object] = {
        "query_text": QUERY,
        "as_of": RESEARCH_AS_OF,
        "market": Market.US,
        "namespace_keys": ["SECTOR:S03", "CHAIN:APPLE_ECOSYSTEM"],
        "memory_levels": [MemoryLevel.L3],
        "scope_types": [
            ResearchScopeType.SECTOR,
            ResearchScopeType.INDUSTRY_CHAIN,
        ],
        "usage_classes": [LearningMemoryUsageClass.EPISODIC],
        "episode_ids": [EPISODE_ID],
    }
    values.update(updates)
    return ResearchContextRequest.model_validate(values)


def test_sector_and_chain_episode_memory_round_trip(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Sector and Industry Chain scopes persist and retrieve with lineage."""

    service = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-sector", "mem-chain"),
    )
    _write(
        service,
        text="Sector thesis claim",
        memory_type="episode_thesis",
        metadata=_metadata(
            scope_type=ResearchScopeType.SECTOR,
            scope_id="SECTOR:S03",
            parent_scope_id="MACRO:US",
            content_kind=EpisodicMemoryContentKind.THESIS,
        ),
    )
    _write(
        service,
        text="Chain risk claim",
        memory_type="episode_risk",
        metadata=_metadata(
            scope_type=ResearchScopeType.INDUSTRY_CHAIN,
            scope_id="CHAIN:APPLE_ECOSYSTEM",
            parent_scope_id="SECTOR:S03",
            content_kind=EpisodicMemoryContentKind.RISK,
            source_claim_ids=("claim:accepted:2",),
        ),
    )

    bundle = service.retrieve_context(_context_request())

    assert [item.memory_id for item in bundle.prior_research] == ["mem-sector"]
    assert [item.memory_id for item in bundle.prior_risk] == ["mem-chain"]
    assert bundle.retrieval_metadata.status is RetrievalStatus.PARTIAL
    assert bundle.retrieval_metadata.empty_valid is False
    items = (*bundle.prior_research, *bundle.prior_risk)
    assert {item.metadata.scope_type for item in items if item.metadata} == {
        ResearchScopeType.SECTOR,
        ResearchScopeType.INDUSTRY_CHAIN,
    }
    assert all(item.metadata is not None for item in items)
    assert all(
        item.metadata.episode_id == EPISODE_ID for item in items if item.metadata
    )
    assert all(
        item.metadata.research_state_id == STATE_ID for item in items if item.metadata
    )
    assert all(item.source.document_id for item in items)
    assert all(item.retrieval_score > 0 for item in items)
    assert all("usage=episodic" in item.retrieval_reason for item in items)
    assert bundle.historical_analogs == []


def test_episode_linkage_and_metadata_survive_restart(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Episode/State references remain structured after DuckDB/FAISS reload."""

    root = tmp_path / "faiss"
    service = _service(database, root, ids=_ids("mem-persistent-episode"))
    metadata = _metadata(
        scope_type=ResearchScopeType.SECTOR,
        scope_id="SECTOR:S03",
        parent_scope_id="MACRO:US",
        content_kind=EpisodicMemoryContentKind.THESIS,
    )
    _write(
        service,
        text="Sector thesis claim",
        memory_type="episode_thesis",
        metadata=metadata,
    )

    restarted = _service(database, root, ids=_ids("unused"))
    response = restarted.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L3],
            namespace_keys=["SECTOR:S03"],
            query_text=QUERY,
            scope_ids=["SECTOR:S03"],
            usage_classes=[LearningMemoryUsageClass.EPISODIC],
            episode_ids=[EPISODE_ID],
            as_of=RESEARCH_AS_OF,
        )
    )

    assert [item.memory_id for item in response.results] == ["mem-persistent-episode"]
    assert response.results[0].metadata == metadata
    assert response.results[0].available_at == CREATED_AT


@pytest.mark.parametrize(
    ("scope_type", "scope_id", "parent_scope_id", "content_kind", "text"),
    (
        (
            ResearchScopeType.MACRO,
            "MACRO:US",
            "GLOBAL:ROOT",
            EpisodicMemoryContentKind.VALIDATED_CLAIM,
            "Macro episode claim",
        ),
        (
            ResearchScopeType.RESEARCH_EPISODE,
            f"EPISODE:{EPISODE_ID}",
            "ASSET:US:AAPL",
            EpisodicMemoryContentKind.EPISODE_REFERENCE,
            "Research Episode reference",
        ),
    ),
)
def test_macro_and_research_episode_scopes_are_retrievable(
    database: DuckDBDatabase,
    tmp_path: Path,
    scope_type: ResearchScopeType,
    scope_id: str,
    parent_scope_id: str,
    content_kind: EpisodicMemoryContentKind,
    text: str,
) -> None:
    """Macro context and the Episode node itself use the existing hierarchy."""

    service = _service(database, tmp_path / scope_type.value, ids=_ids("mem-scope"))
    _write(
        service,
        text=text,
        memory_type=f"episode_{content_kind.value}",
        metadata=_metadata(
            scope_type=scope_type,
            scope_id=scope_id,
            parent_scope_id=parent_scope_id,
            content_kind=content_kind,
        ),
    )

    bundle = service.retrieve_context(
        _context_request(
            namespace_keys=[scope_id],
            scope_ids=[scope_id],
            scope_types=[scope_type],
        )
    )

    assert [item.memory_id for item in bundle.prior_research] == ["mem-scope"]
    assert bundle.prior_research[0].metadata is not None
    assert bundle.prior_research[0].metadata.scope_id == scope_id
    assert bundle.prior_research[0].metadata.episode_id == EPISODE_ID


def test_learning_memory_reuses_unified_temporal_cutoff(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """A future structured availability time is rejected by both retrieval APIs."""

    service = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-available", "mem-future"),
    )
    for text, available_at in (
        ("Available asset catalyst", CREATED_AT),
        (
            "Future asset catalyst",
            RESEARCH_AS_OF + timedelta(seconds=1),
        ),
    ):
        _write(
            service,
            text=text,
            memory_type="episode_catalyst",
            metadata=_metadata(
                scope_type=ResearchScopeType.ASSET,
                scope_id="ASSET:US:AAPL",
                parent_scope_id="CHAIN:APPLE_ECOSYSTEM",
                content_kind=EpisodicMemoryContentKind.CATALYST,
                available_at=available_at,
            ),
        )

    request = _context_request(
        namespace_keys=["ASSET:US:AAPL"],
        scope_types=[ResearchScopeType.ASSET],
        scope_ids=["ASSET:US:AAPL"],
        asset_id="US:AAPL",
    )
    bundle = service.retrieve_context(request)
    search = service.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L3],
            namespace_keys=["ASSET:US:AAPL"],
            query_text=QUERY,
            usage_classes=[LearningMemoryUsageClass.EPISODIC],
            as_of=RESEARCH_AS_OF,
        )
    )

    assert [item.memory_id for item in bundle.prior_research] == ["mem-available"]
    assert bundle.retrieval_metadata.excluded_future_count == 1
    assert [item.memory_id for item in search.results] == ["mem-available"]
    assert all(
        item.available_at <= RESEARCH_AS_OF
        for item in search.results
        if item.available_at
    )


def test_learning_memory_empty_is_explicitly_valid(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """No matching Episode Memory remains a legal, non-fabricated state."""

    service = _service(database, tmp_path / "faiss", ids=_ids("unused"))

    bundle = service.retrieve_context(_context_request())

    assert bundle.retrieval_metadata.status is RetrievalStatus.EMPTY
    assert bundle.retrieval_metadata.no_relevant_memory is True
    assert bundle.retrieval_metadata.empty_valid is True
    assert bundle.prior_research == []
    assert bundle.historical_analogs == []


def test_single_episode_cannot_become_validated_semantic_truth() -> None:
    """One Episode may create a candidate, never an automatic semantic truth."""

    common: dict[str, object] = {
        "usage_class": LearningMemoryUsageClass.SEMANTIC,
        "scope_type": ResearchScopeType.SECTOR,
        "scope_id": "SECTOR:S03",
        "parent_scope_id": "MACRO:US",
        "episode_id": EPISODE_ID,
        "research_state_id": STATE_ID,
        "source_claim_ids": ("claim:accepted:1",),
        "temporal": TemporalMetadata(
            source_kind=TemporalSourceKind.MEMORY,
            available_at=CREATED_AT,
        ),
    }
    candidate = LearningMemoryMetadata.model_validate(
        {
            **common,
            "semantic_status": SemanticMemoryLifecycleStatus.CANDIDATE,
        }
    )

    assert candidate.semantic_status is SemanticMemoryLifecycleStatus.CANDIDATE
    with pytest.raises(ValidationError, match="single-Episode semantic Memory"):
        LearningMemoryMetadata.model_validate(
            {
                **common,
                "semantic_status": SemanticMemoryLifecycleStatus.VALIDATED,
            }
        )


def test_performance_memory_schema_reserves_references_without_outcome_data() -> None:
    """Performance schema stores identities only and does not invent an Outcome."""

    metadata = LearningMemoryMetadata(
        usage_class=LearningMemoryUsageClass.PERFORMANCE,
        scope_type=ResearchScopeType.RESEARCH_EPISODE,
        scope_id=f"EPISODE:{EPISODE_ID}",
        parent_scope_id="ASSET:US:AAPL",
        episode_id=EPISODE_ID,
        research_state_id=STATE_ID,
        temporal=TemporalMetadata(
            source_kind=TemporalSourceKind.MEMORY,
            available_at=CREATED_AT,
        ),
    )

    assert metadata.outcome_id is None
    assert metadata.factor_reference is None
    assert metadata.research_reference is None
