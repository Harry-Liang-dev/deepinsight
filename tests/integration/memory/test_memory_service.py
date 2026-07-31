"""Integration tests for DuckDB-backed, persistent semantic Memory."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.memory import MemoryService, MemoryWriteError
from src.models.enums import MemoryLevel
from src.models.identifiers import AssetId
from src.repositories import (
    DuckDBDatabase,
    FaissVectorRepository,
    MemoryItemRepository,
    RepositoryError,
    VectorPersistenceError,
)
from src.repositories.records import MemoryItemRecord
from src.schemas.common import SourceReference
from src.schemas.memory import MemorySearchRequest, MemoryWriteRequest
from src.services import FakeEmbeddingService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)
QUERY = "guidance query"
VECTORS = {
    QUERY: [1.0, 0.0, 0.0],
    "L0 memory": [1.0, 0.0, 0.0],
    "L1 memory": [1.0, 0.0, 0.0],
    "L2 memory": [1.0, 0.0, 0.0],
    "L3 memory": [1.0, 0.0, 0.0],
    "L4 memory": [1.0, 0.0, 0.0],
    "low importance": [0.9, 0.1, 0.0],
    "other task": [1.0, 0.0, 0.0],
}


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return an initialized temporary DuckDB database."""

    database = DuckDBDatabase(tmp_path / "memory.duckdb")
    database.bootstrap()
    return database


def _ids(*values: str) -> Iterator[str]:
    return iter(values)


def _service(
    database: DuckDBDatabase,
    root: Path,
    *,
    ids: Iterator[str],
) -> tuple[MemoryService, FaissVectorRepository, MemoryItemRepository]:
    embedder = FakeEmbeddingService(VECTORS)
    vectors = FaissVectorRepository(
        root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    memories = MemoryItemRepository(database)
    service = MemoryService(
        memories,
        vectors,
        embedder,
        clock=lambda: NOW,
        memory_id_factory=lambda: next(ids),
    )
    return service, vectors, memories


def _request(
    level: MemoryLevel,
    *,
    text: str | None = None,
    namespace_key: str = "US:AAPL",
    asset_id: AssetId | None = AssetId("US:AAPL"),
    importance: float = 0.8,
    document_id: str = "doc-source",
) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        memory_level=level,
        namespace_key=namespace_key,
        asset_id=asset_id,
        effective_ts=NOW,
        memory_type="research_memory",
        importance_score=importance,
        summary_text=text or f"{level.value} memory",
        source_ref_json=SourceReference(
            document_id=document_id,
            excerpt_ref=f"{document_id}:chunk-1",
        ),
        created_by="system",
    )


def test_all_memory_levels_write_search_and_map_to_duckdb(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """L0–L4 each use a private namespace with attributable results."""

    memory_ids = [f"mem-{index}" for index in range(5)]
    service, vectors, memories = _service(
        database,
        tmp_path / "faiss",
        ids=_ids(*memory_ids),
    )

    for level, memory_id in zip(MemoryLevel, memory_ids, strict=True):
        written = service.write(_request(level))
        assert written.memory_id == memory_id
        assert written.faiss_namespace == f"memory_{level.value}_v1"
        stored = memories.get(memory_id)
        assert stored is not None
        assert stored.faiss_vector_id == written.faiss_vector_id
        assert stored.source_ref is not None
        assert vectors.count(written.faiss_namespace) == 1

        response = service.search(
            MemorySearchRequest(
                memory_levels=[level],
                namespace_keys=["US:AAPL"],
                query_text=QUERY,
                top_k=1,
            )
        )
        assert len(response.results) == 1
        assert response.results[0].memory_id == memory_id
        assert response.results[0].source_ref_json.document_id == "doc-source"
        assert response.results[0].created_by == "system"


def test_search_filters_namespace_asset_importance_and_top_k(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Research-task, asset, importance, and result-count filters are strict."""

    service, _, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-target", "mem-low", "mem-other"),
    )
    service.write(
        _request(
            MemoryLevel.L3,
            namespace_key="REPORT:task-1",
            text="L3 memory",
            importance=0.9,
        )
    )
    service.write(
        _request(
            MemoryLevel.L3,
            namespace_key="REPORT:task-1",
            text="low importance",
            importance=0.2,
        )
    )
    service.write(
        _request(
            MemoryLevel.L3,
            namespace_key="REPORT:task-2",
            text="other task",
            asset_id=AssetId("US:MSFT"),
            importance=1.0,
        )
    )

    response = service.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L3],
            namespace_keys=["REPORT:task-1", "REPORT:task-2"],
            asset_ids=[AssetId("US:AAPL")],
            query_text=QUERY,
            min_importance_score=0.5,
            time_decay_days=3650,
            top_k=1,
        )
    )

    assert [result.memory_id for result in response.results] == ["mem-target"]


def test_empty_index_and_filtered_search_return_no_results(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Empty and non-matching namespaces do not fabricate evidence."""

    service, _, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("unused"),
    )
    empty = service.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L1],
            namespace_keys=["GLOBAL"],
            query_text=QUERY,
        )
    )
    assert empty.results == []

    service.write(_request(MemoryLevel.L1, namespace_key="US"))
    filtered = service.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L1],
            namespace_keys=["GLOBAL"],
            query_text=QUERY,
        )
    )
    assert filtered.results == []


def test_saved_memory_is_searchable_after_repository_restart(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """A new FAISS Repository instance loads durable Memory vectors."""

    root = tmp_path / "faiss"
    service, _, _ = _service(database, root, ids=_ids("mem-persisted"))
    service.write(_request(MemoryLevel.L2))

    restarted, _, _ = _service(database, root, ids=_ids("unused"))
    response = restarted.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L2],
            namespace_keys=["US:AAPL"],
            query_text=QUERY,
        )
    )

    assert [item.memory_id for item in response.results] == ["mem-persisted"]


class _FailingMemoryRepository(MemoryItemRepository):
    def insert(self, record: MemoryItemRecord) -> None:
        raise RepositoryError("simulated structured write failure")


def test_duckdb_failure_is_visible_and_vector_write_is_compensated(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """A failed structured write leaves no undiscoverable vector orphan."""

    embedder = FakeEmbeddingService(VECTORS)
    vectors = FaissVectorRepository(
        tmp_path / "faiss",
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    service = MemoryService(
        _FailingMemoryRepository(database),
        vectors,
        embedder,
        memory_id_factory=lambda: "mem-failed",
    )

    with pytest.raises(MemoryWriteError, match="rolled back"):
        service.write(_request(MemoryLevel.L0))

    assert vectors.count("memory_L0_v1") == 0
    assert MemoryItemRepository(database).get("mem-failed") is None


def test_vector_dimension_mismatch_rejects_memory_write(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """An incompatible FAISS dimension is rejected before DuckDB insertion."""

    embedder = FakeEmbeddingService(VECTORS)
    vectors = FaissVectorRepository(
        tmp_path / "faiss",
        embedder_model=embedder.model_name,
        embedding_dim=2,
    )
    repository = MemoryItemRepository(database)
    service = MemoryService(
        repository,
        vectors,
        embedder,
        memory_id_factory=lambda: "mem-wrong-dimension",
    )

    with pytest.raises(MemoryWriteError, match="vector write"):
        service.write(_request(MemoryLevel.L0))

    assert repository.get("mem-wrong-dimension") is None


def test_vector_failure_is_visible_and_prevents_duckdb_write(
    database: DuckDBDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vector persistence failure cannot create searchable-looking metadata."""

    service, vectors, repository = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-vector-failed"),
    )

    def fail_add(**_: object) -> int:
        raise VectorPersistenceError("simulated vector write failure")

    monkeypatch.setattr(vectors, "add", fail_add)

    with pytest.raises(MemoryWriteError, match="vector write"):
        service.write(_request(MemoryLevel.L0))

    assert repository.get("mem-vector-failed") is None


def test_memory_level_can_be_rebuilt_from_duckdb(
    database: DuckDBDatabase,
    tmp_path: Path,
) -> None:
    """Authoritative Memory records can replace a lost namespace index."""

    service, vectors, _ = _service(
        database,
        tmp_path / "faiss",
        ids=_ids("mem-rebuild"),
    )
    written = service.write(_request(MemoryLevel.L4))
    assert vectors.remove(
        namespace=written.faiss_namespace,
        vector_id=written.faiss_vector_id,
    )

    assert service.rebuild_level(MemoryLevel.L4) == 1
    response = service.search(
        MemorySearchRequest(
            memory_levels=[MemoryLevel.L4],
            namespace_keys=["US:AAPL"],
            query_text=QUERY,
        )
    )
    assert [item.memory_id for item in response.results] == ["mem-rebuild"]
