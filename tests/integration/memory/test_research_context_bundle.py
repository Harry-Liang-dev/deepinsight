"""Point-in-time integration tests for structured Memory context bundles."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.memory import (
    MissingContextReason,
    ResearchContextRequest,
    ResearchContextSection,
    RetrievalStatus,
)
from src.memory.service import MemoryService
from src.models.enums import Market, MemoryLevel
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, FaissVectorRepository, MemoryItemRepository
from src.schemas.common import SourceReference
from src.schemas.memory import MemoryWriteRequest
from src.services import FakeEmbeddingService

pytestmark = pytest.mark.integration

AS_OF = datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
AAPL = AssetId("US:AAPL")
MSFT = AssetId("US:MSFT")
QUERY = "research context query"
VECTORS = {
    QUERY: [1.0, 0.0, 0.0],
    "before cutoff": [1.0, 0.0, 0.0],
    "after cutoff": [1.0, 0.0, 0.0],
    "AAPL event": [1.0, 0.0, 0.0],
    "MSFT event": [1.0, 0.0, 0.0],
    "US macro": [1.0, 0.0, 0.0],
    "HK macro": [1.0, 0.0, 0.0],
    "Global macro": [1.0, 0.0, 0.0],
    "most relevant": [1.0, 0.0, 0.0],
    "less relevant": [0.8, 0.6, 0.0],
    "least relevant": [0.0, 1.0, 0.0],
    "persistent snapshot": [1.0, 0.0, 0.0],
    "regime to rebuild": [1.0, 0.0, 0.0],
    "prior report": [1.0, 0.0, 0.0],
    "future report": [1.0, 0.0, 0.0],
    "current report": [1.0, 0.0, 0.0],
    "other asset report": [1.0, 0.0, 0.0],
    "snapshot": [1.0, 0.0, 0.0],
    "macro event": [1.0, 0.0, 0.0],
    "asset event": [1.0, 0.0, 0.0],
    "research trace": [1.0, 0.0, 0.0],
    "risk trace": [1.0, 0.0, 0.0],
    "explicit analog": [1.0, 0.0, 0.0],
    "market regime": [1.0, 0.0, 0.0],
}


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return an initialized isolated Memory database."""

    database = DuckDBDatabase(tmp_path / "context.duckdb")
    database.bootstrap()
    return database


def _ids(*values: str) -> Iterator[str]:
    return iter(values)


def _service(
    database: DuckDBDatabase,
    root: Path,
    *,
    ids: Iterator[str],
) -> tuple[MemoryService, FaissVectorRepository]:
    embedder = FakeEmbeddingService(VECTORS)
    vectors = FaissVectorRepository(
        root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    return (
        MemoryService(
            MemoryItemRepository(database),
            vectors,
            embedder,
            clock=lambda: AS_OF,
            memory_id_factory=lambda: next(ids),
        ),
        vectors,
    )


def _write(
    service: MemoryService,
    *,
    level: MemoryLevel,
    text: str,
    effective_ts: datetime,
    namespace_key: str,
    asset_id: AssetId | None,
    memory_type: str,
    importance: float = 0.8,
) -> str:
    result = service.write(
        MemoryWriteRequest(
            memory_level=level,
            namespace_key=namespace_key,
            asset_id=asset_id,
            effective_ts=effective_ts,
            memory_type=memory_type,
            importance_score=importance,
            summary_text=text,
            source_ref_json=SourceReference(
                document_id=f"source-{text.replace(' ', '-')}",
                excerpt_ref="chunk-1",
            ),
            created_by="context-test",
        )
    )
    return result.memory_id


def _request(**updates: object) -> ResearchContextRequest:
    values: dict[str, object] = {
        "query_text": QUERY,
        "as_of": AS_OF,
        "market": Market.US,
        "namespace_keys": ["GLOBAL", "US", "US:AAPL", "ASSET:US:AAPL"],
        "asset_id": AAPL,
        "top_k_per_section": 4,
        "min_importance_score": 0.0,
    }
    values.update(updates)
    return ResearchContextRequest.model_validate(values)


def test_bundle_classifies_l0_to_l4_without_inventing_analogs(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Stored Memory types populate stable sections and preserve evidence."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids(*(f"mem-{index}" for index in range(7))),
    )
    records = (
        (MemoryLevel.L0, "snapshot", "US:AAPL", AAPL, "market_snapshot"),
        (MemoryLevel.L1, "macro event", "US", None, "macro_event"),
        (MemoryLevel.L2, "asset event", "US:AAPL", AAPL, "issuer_event"),
        (
            MemoryLevel.L3,
            "research trace",
            "ASSET:US:AAPL",
            AAPL,
            "report_trace",
        ),
        (
            MemoryLevel.L3,
            "risk trace",
            "ASSET:US:AAPL",
            AAPL,
            "risk_review",
        ),
        (
            MemoryLevel.L4,
            "explicit analog",
            "US",
            None,
            "historical_analog",
        ),
        (MemoryLevel.L4, "market regime", "US", None, "market_regime"),
    )
    for level, text, namespace, asset, memory_type in records:
        _write(
            service,
            level=level,
            text=text,
            effective_ts=AS_OF - timedelta(days=1),
            namespace_key=namespace,
            asset_id=asset,
            memory_type=memory_type,
        )

    bundle = service.retrieve_context(_request())

    assert bundle.retrieval_metadata.status is RetrievalStatus.COMPLETE
    assert bundle.missing_context == []
    for section in ResearchContextSection:
        items = bundle.items_for_section(section)
        assert len(items) == 1
        assert items[0].source.document_id is not None
        assert items[0].effective_ts <= AS_OF
        assert items[0].retrieval_score == pytest.approx(1.0)
        assert "semantic_relevance" in items[0].retrieval_reason
    assert bundle.historical_analogs[0].summary_text == "explicit analog"
    assert bundle.regime_context[0].summary_text == "market regime"


def test_temporal_leakage_excludes_future_effective_memory(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """No result can cross the request's effective-time cutoff."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-before", "mem-after"),
    )
    _write(
        service,
        level=MemoryLevel.L2,
        text="before cutoff",
        effective_ts=AS_OF - timedelta(seconds=1),
        namespace_key="US:AAPL",
        asset_id=AAPL,
        memory_type="issuer_event",
    )
    _write(
        service,
        level=MemoryLevel.L2,
        text="after cutoff",
        effective_ts=AS_OF + timedelta(seconds=1),
        namespace_key="US:AAPL",
        asset_id=AAPL,
        memory_type="issuer_event",
    )

    bundle = service.retrieve_context(_request())

    assert [item.memory_id for item in bundle.asset_events] == ["mem-before"]
    assert bundle.retrieval_metadata.excluded_future_count == 1
    assert [
        item.memory_id for item in bundle.retrieval_metadata.eligible_candidates
    ] == ["mem-before"]


def test_temporal_leakage_excludes_memory_created_after_cutoff(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Backdated effective time cannot hide a future Memory creation time."""

    embedder = FakeEmbeddingService(VECTORS)
    service = MemoryService(
        MemoryItemRepository(database),
        FaissVectorRepository(
            tmp_path / "future-created-faiss",
            embedder_model=embedder.model_name,
            embedding_dim=embedder.dimension,
        ),
        embedder,
        clock=lambda: AS_OF + timedelta(seconds=1),
        memory_id_factory=lambda: "mem-future-created",
    )
    _write(
        service,
        level=MemoryLevel.L2,
        text="asset event",
        effective_ts=AS_OF - timedelta(days=1),
        namespace_key="US:AAPL",
        asset_id=AAPL,
        memory_type="issuer_event",
    )

    bundle = service.retrieve_context(_request())

    assert bundle.asset_events == []
    assert bundle.retrieval_metadata.excluded_future_count == 1
    assert all(item.effective_ts <= AS_OF for item in bundle.asset_events)


def test_asset_isolation_excludes_other_issuer(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """An exact asset filter excludes another issuer in the same namespace."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-aapl", "mem-msft"),
    )
    for text, asset in (("AAPL event", AAPL), ("MSFT event", MSFT)):
        _write(
            service,
            level=MemoryLevel.L2,
            text=text,
            effective_ts=AS_OF - timedelta(days=1),
            namespace_key="US",
            asset_id=asset,
            memory_type="issuer_event",
        )

    bundle = service.retrieve_context(_request(namespace_keys=["US"]))

    assert [item.memory_id for item in bundle.asset_events] == ["mem-aapl"]
    assert bundle.retrieval_metadata.excluded_asset_count == 1


def test_market_isolation_allows_global_but_excludes_other_market(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """US retrieval may use GLOBAL context but cannot consume HK Memory."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-us", "mem-hk", "mem-global"),
    )
    for text, namespace in (
        ("US macro", "US"),
        ("HK macro", "HK"),
        ("Global macro", "GLOBAL"),
    ):
        _write(
            service,
            level=MemoryLevel.L1,
            text=text,
            effective_ts=AS_OF - timedelta(days=1),
            namespace_key=namespace,
            asset_id=None,
            memory_type="macro_event",
        )

    bundle = service.retrieve_context(_request(namespace_keys=["GLOBAL", "US", "HK"]))

    assert {item.memory_id for item in bundle.macro_events} == {
        "mem-us",
        "mem-global",
    }
    assert bundle.retrieval_metadata.excluded_market_count == 1


def test_empty_retrieval_explicitly_reports_no_relevant_memory(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """An empty index returns a complete explicit absence description."""

    service, _ = _service(database, tmp_path / "faiss", ids=_ids("unused"))

    bundle = service.retrieve_context(_request())

    assert bundle.retrieval_metadata.status is RetrievalStatus.EMPTY
    assert bundle.retrieval_metadata.no_relevant_memory is True
    assert bundle.retrieval_metadata.result_count == 0
    assert len(bundle.missing_context) == len(ResearchContextSection)
    assert {missing.reason for missing in bundle.missing_context} == {
        MissingContextReason.NO_RELEVANT_MEMORY
    }
    assert bundle.historical_analogs == []


def test_relevance_ordering_and_importance_filter_are_deterministic(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Semantic score orders eligible evidence after importance filtering."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-best", "mem-mid", "mem-low-score"),
    )
    for text, importance in (
        ("most relevant", 0.8),
        ("less relevant", 0.9),
        ("least relevant", 0.1),
    ):
        _write(
            service,
            level=MemoryLevel.L2,
            text=text,
            effective_ts=AS_OF - timedelta(days=1),
            namespace_key="US:AAPL",
            asset_id=AAPL,
            memory_type="issuer_event",
            importance=importance,
        )

    bundle = service.retrieve_context(
        _request(min_importance_score=0.5, top_k_per_section=2)
    )

    assert [item.memory_id for item in bundle.asset_events] == [
        "mem-best",
        "mem-mid",
    ]
    assert [item.retrieval_score for item in bundle.asset_events] == sorted(
        [item.retrieval_score for item in bundle.asset_events],
        reverse=True,
    )
    assert bundle.retrieval_metadata.excluded_importance_count == 1
    assert [
        (item.memory_id, item.rank, item.selected)
        for item in bundle.retrieval_metadata.eligible_candidates
    ] == [("mem-best", 1, True), ("mem-mid", 2, True)]


def test_bundle_persists_across_vector_repository_restart(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Context content and snapshot identity survive a Repository restart."""

    root = tmp_path / "faiss"
    service, _ = _service(database, root, ids=_ids("mem-persistent"))
    _write(
        service,
        level=MemoryLevel.L0,
        text="persistent snapshot",
        effective_ts=AS_OF - timedelta(minutes=1),
        namespace_key="US:AAPL",
        asset_id=AAPL,
        memory_type="market_snapshot",
    )
    before = service.retrieve_context(_request())

    restarted, _ = _service(database, root, ids=_ids("unused"))
    after = restarted.retrieve_context(_request())

    assert [item.memory_id for item in after.current_snapshot] == ["mem-persistent"]
    assert after.current_snapshot[0].source == before.current_snapshot[0].source
    assert after.retrieval_metadata.snapshot_id == before.retrieval_metadata.snapshot_id


def test_rebuild_restores_research_context_retrieval(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """DuckDB-authoritative rebuild restores a missing L4 context vector."""

    service, vectors = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-regime"),
    )
    memory_id = _write(
        service,
        level=MemoryLevel.L4,
        text="regime to rebuild",
        effective_ts=AS_OF - timedelta(days=30),
        namespace_key="US",
        asset_id=None,
        memory_type="market_regime",
    )
    record = MemoryItemRepository(database).get(memory_id)
    assert record is not None
    assert vectors.remove(
        namespace=record.faiss_namespace,
        vector_id=record.faiss_vector_id,
    )

    assert service.rebuild_level(MemoryLevel.L4) == 1
    bundle = service.retrieve_context(_request())

    assert [item.memory_id for item in bundle.regime_context] == ["mem-regime"]


def test_historical_report_retrieval_excludes_future_current_and_other_asset(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Only prior same-asset report traces may enter prior research."""

    service, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-old", "mem-future", "mem-current", "mem-other"),
    )
    reports = (
        (
            "prior report",
            "REPORT:prior",
            AAPL,
            AS_OF - timedelta(days=30),
        ),
        (
            "future report",
            "REPORT:future",
            AAPL,
            AS_OF + timedelta(seconds=1),
        ),
        (
            "current report",
            "REPORT:current",
            AAPL,
            AS_OF - timedelta(seconds=1),
        ),
        (
            "other asset report",
            "REPORT:other",
            MSFT,
            AS_OF - timedelta(days=30),
        ),
    )
    for text, namespace, asset, effective_ts in reports:
        _write(
            service,
            level=MemoryLevel.L3,
            text=text,
            effective_ts=effective_ts,
            namespace_key=namespace,
            asset_id=asset,
            memory_type="report_trace",
        )

    bundle = service.retrieve_context(_request(current_report_id="current"))

    assert [item.memory_id for item in bundle.prior_research] == ["mem-old"]
    assert "historical_report_asset_match" in (
        bundle.prior_research[0].retrieval_reason
    )
    assert bundle.retrieval_metadata.excluded_future_count == 1
    assert bundle.retrieval_metadata.excluded_current_report_count == 1
    assert "mem-other" not in {
        item.memory_id
        for section in ResearchContextSection
        for item in bundle.items_for_section(section)
    }
