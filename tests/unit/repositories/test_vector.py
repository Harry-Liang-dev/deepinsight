"""Tests for the provider-independent persistent FAISS Repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.repositories import (
    FaissVectorRepository,
    VectorDimensionError,
    VectorEntry,
    VectorNamespaceError,
)


def _repository(root: Path, dimension: int = 3) -> FaissVectorRepository:
    return FaissVectorRepository(
        root,
        embedder_model="fake-embedding-v1",
        embedding_dim=dimension,
    )


def test_faiss_repository_persists_and_reloads_namespace(tmp_path: Path) -> None:
    """A new Repository instance can search saved index and metadata files."""

    root = tmp_path / "faiss"
    repository = _repository(root)
    repository.add(
        namespace="memory_L2_v1",
        vector=[1.0, 0.0, 0.0],
        vector_id=41,
        metadata={"memory_id": "mem-41", "namespace_key": "US:AAPL"},
        source_table="memory_items",
    )

    namespace_root = root / "memory_L2_v1"
    assert (namespace_root / "index.faiss").is_file()
    assert (namespace_root / "vector_meta.parquet").is_file()
    assert (namespace_root / "manifest.json").is_file()

    reloaded = _repository(root)
    candidates = reloaded.search_across(
        namespaces=["memory_L2_v1"],
        query_vector=[1.0, 0.0, 0.0],
        top_k=1,
    )

    assert reloaded.count("memory_L2_v1") == 1
    assert candidates[0].vector_id == 41
    assert candidates[0].metadata["memory_id"] == "mem-41"
    manifest = reloaded.manifest("memory_L2_v1")
    assert manifest is not None
    assert manifest.source_table == "memory_items"
    assert manifest.distance_metric == "cosine"
    assert manifest.faiss_index_type == "IndexFlatIP"


def test_faiss_repository_isolates_namespaces_and_handles_empty(
    tmp_path: Path,
) -> None:
    """Search only observes requested namespaces and missing indexes are empty."""

    repository = _repository(tmp_path)
    assert (
        repository.search_across(
            namespaces=["memory_L0_v1"],
            query_vector=[1.0, 0.0, 0.0],
            top_k=2,
        )
        == []
    )
    repository.add(
        namespace="memory_L0_v1",
        vector=[1.0, 0.0, 0.0],
        vector_id=1,
        metadata={"memory_id": "one"},
        source_table="memory_items",
    )
    repository.add(
        namespace="memory_L1_v1",
        vector=[1.0, 0.0, 0.0],
        vector_id=2,
        metadata={"memory_id": "two"},
        source_table="memory_items",
    )

    candidates = repository.search_across(
        namespaces=["memory_L1_v1"],
        query_vector=[1.0, 0.0, 0.0],
        top_k=None,
    )

    assert [candidate.vector_id for candidate in candidates] == [2]


def test_faiss_repository_rejects_dimension_and_unsafe_namespace(
    tmp_path: Path,
) -> None:
    """Vector dimensions and namespace paths are validated before writes."""

    repository = _repository(tmp_path)
    with pytest.raises(VectorDimensionError):
        repository.add(
            namespace="memory_L0_v1",
            vector=[1.0, 0.0],
            vector_id=1,
            metadata={"memory_id": "one"},
            source_table="memory_items",
        )
    with pytest.raises(VectorNamespaceError):
        repository.count("../outside")


def test_faiss_repository_rebuild_replaces_existing_vectors(
    tmp_path: Path,
) -> None:
    """Rebuild writes an authoritative replacement namespace."""

    repository = _repository(tmp_path)
    repository.add(
        namespace="memory_L4_v1",
        vector=[1.0, 0.0, 0.0],
        vector_id=1,
        metadata={"memory_id": "old"},
        source_table="memory_items",
    )
    repository.rebuild(
        namespace="memory_L4_v1",
        entries=[
            VectorEntry(
                vector_id=2,
                vector=[0.0, 1.0, 0.0],
                metadata={"memory_id": "new"},
            )
        ],
        source_table="memory_items",
    )

    assert repository.count("memory_L4_v1") == 1
    result = repository.search_across(
        namespaces=["memory_L4_v1"],
        query_vector=[0.0, 1.0, 0.0],
        top_k=1,
    )
    assert result[0].metadata["memory_id"] == "new"
