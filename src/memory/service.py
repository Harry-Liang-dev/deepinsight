"""Five-level attributable Memory write and semantic retrieval service."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from src.models.enums import MemoryLevel
from src.models.types import JsonObject
from src.repositories.base import RepositoryError
from src.repositories.memory import MemoryItemRepository
from src.repositories.records import MemoryItemRecord
from src.repositories.vector import (
    VectorEntry,
    VectorRepository,
    VectorRepositoryError,
)
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.services.embedding import EmbeddingService, EmbeddingServiceError


class MemoryServiceError(RuntimeError):
    """Base error for Memory orchestration failures."""


class MemoryWriteError(MemoryServiceError):
    """Raised when a Memory write fails without leaving a hidden partial write."""


class MemoryConsistencyError(MemoryServiceError):
    """Raised when DuckDB and vector persistence disagree."""


class MemoryService:
    """Coordinate attributable Memory metadata and private vector indexes."""

    def __init__(
        self,
        duckdb_repo: MemoryItemRepository,
        vector_repo: VectorRepository,
        embedder: EmbeddingService,
        *,
        clock: Callable[[], datetime] | None = None,
        memory_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Bind replaceable structured, vector, and embedding dependencies."""

        self._duckdb_repo = duckdb_repo
        self._vector_repo = vector_repo
        self._embedder = embedder
        self._clock = clock or (lambda: datetime.now(UTC))
        self._memory_id_factory = memory_id_factory or (lambda: f"mem_{uuid4().hex}")

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Write one attributable Memory item to vector and structured stores.

        The vector write occurs first. A later DuckDB failure triggers a vector
        deletion. If compensation itself fails, a consistency error makes the
        repair requirement explicit.
        """

        memory_id = self._memory_id_factory()
        if not memory_id.strip():
            raise MemoryWriteError("memory ID factory returned an empty identifier")
        namespace = self.namespace_for_level(request.memory_level)
        try:
            vector = self._embedder.embed(request.summary_text)
        except EmbeddingServiceError as exc:
            raise MemoryWriteError("Memory embedding failed") from exc
        if len(vector) != self._embedder.dimension:
            raise MemoryWriteError("embedder returned an inconsistent dimension")

        vector_id = _stable_vector_id(memory_id)
        metadata = _vector_metadata(
            memory_id=memory_id,
            namespace_key=request.namespace_key,
            asset_id=None if request.asset_id is None else str(request.asset_id),
        )
        try:
            self._vector_repo.add(
                namespace=namespace,
                vector=vector,
                vector_id=vector_id,
                metadata=metadata,
                source_table="memory_items",
            )
        except VectorRepositoryError as exc:
            raise MemoryWriteError("Memory vector write failed") from exc

        record = MemoryItemRecord(
            memory_id=memory_id,
            memory_level=request.memory_level,
            namespace_key=request.namespace_key,
            asset_id=request.asset_id,
            effective_ts=request.effective_ts,
            memory_type=request.memory_type,
            importance_score=request.importance_score,
            summary_text=request.summary_text,
            source_ref=request.source_ref_json,
            embedding_model=self._embedder.model_name,
            embedding_dim=self._embedder.dimension,
            faiss_namespace=namespace,
            faiss_vector_id=vector_id,
            created_by=request.created_by,
            created_at=self._clock(),
        )
        try:
            self._duckdb_repo.insert(record)
        except RepositoryError as exc:
            try:
                removed = self._vector_repo.remove(
                    namespace=namespace,
                    vector_id=vector_id,
                )
            except VectorRepositoryError as compensation_error:
                raise MemoryConsistencyError(
                    "DuckDB write failed and vector compensation failed; "
                    "namespace rebuild is required"
                ) from compensation_error
            if not removed:
                raise MemoryConsistencyError(
                    "DuckDB write failed and the inserted vector was not found"
                ) from exc
            raise MemoryWriteError(
                "DuckDB write failed; vector write was rolled back"
            ) from exc

        return MemoryWriteResult(
            memory_id=memory_id,
            faiss_namespace=namespace,
            faiss_vector_id=vector_id,
        )

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Search isolated Memory levels and return attributable evidence.

        ``time_decay_days`` is validated by the request contract but does not
        alter scores in this version because MASTER_SPEC does not define the
        decay formula.
        """

        try:
            query_vector = self._embedder.embed(request.query_text)
        except EmbeddingServiceError as exc:
            raise MemoryServiceError("Memory query embedding failed") from exc
        if len(query_vector) != self._embedder.dimension:
            raise MemoryServiceError("embedder returned an inconsistent dimension")

        requested_levels = set(request.memory_levels)
        namespaces = [
            self.namespace_for_level(level)
            for level in dict.fromkeys(request.memory_levels)
        ]
        try:
            candidates = self._vector_repo.search_across(
                namespaces=namespaces,
                query_vector=query_vector,
                top_k=None,
            )
        except VectorRepositoryError as exc:
            raise MemoryServiceError("Memory vector search failed") from exc

        namespace_keys = set(request.namespace_keys)
        asset_ids = (
            None
            if request.asset_ids is None
            else {str(asset_id) for asset_id in request.asset_ids}
        )
        now = self._clock()
        results: list[MemorySearchResult] = []
        for candidate in candidates:
            try:
                record = self._duckdb_repo.get_by_vector(
                    candidate.namespace,
                    candidate.vector_id,
                )
            except RepositoryError as exc:
                raise MemoryConsistencyError(
                    "Memory vector mapping could not be resolved"
                ) from exc
            if record is None:
                raise MemoryConsistencyError(
                    "Memory vector has no DuckDB sidecar mapping"
                )
            if record.memory_level not in requested_levels:
                raise MemoryConsistencyError(
                    "Memory vector namespace maps to an unexpected level"
                )
            if record.namespace_key not in namespace_keys:
                continue
            if record.importance_score < request.min_importance_score:
                continue
            if asset_ids is not None:
                record_asset = None if record.asset_id is None else str(record.asset_id)
                if record_asset not in asset_ids:
                    continue
            if record.expires_at is not None and _as_utc(record.expires_at) <= _as_utc(
                now
            ):
                continue
            if record.source_ref is None:
                raise MemoryConsistencyError(
                    "Memory result has no attributable source reference"
                )
            expected_memory_id = candidate.metadata.get("memory_id")
            if expected_memory_id != record.memory_id:
                raise MemoryConsistencyError(
                    "vector metadata does not match its DuckDB Memory record"
                )
            results.append(
                MemorySearchResult(
                    memory_id=record.memory_id,
                    memory_level=record.memory_level,
                    namespace_key=record.namespace_key,
                    summary_text=record.summary_text,
                    score=candidate.score,
                    effective_ts=record.effective_ts,
                    asset_id=record.asset_id,
                    memory_type=record.memory_type,
                    importance_score=record.importance_score,
                    source_ref_json=record.source_ref,
                    created_by=record.created_by,
                )
            )
            if len(results) == request.top_k:
                break
        return MemorySearchResponse(results=results)

    def delete(self, memory_id: str) -> None:
        """Delete one Memory vector and sidecar during compensation."""

        try:
            record = self._duckdb_repo.get(memory_id)
        except RepositoryError as exc:
            raise MemoryConsistencyError("Memory compensation lookup failed") from exc
        if record is None:
            return
        try:
            removed = self._vector_repo.remove(
                namespace=record.faiss_namespace,
                vector_id=record.faiss_vector_id,
            )
        except VectorRepositoryError as exc:
            raise MemoryConsistencyError("Memory vector compensation failed") from exc
        if not removed:
            raise MemoryConsistencyError(
                "Memory compensation could not find the vector"
            )
        try:
            self._duckdb_repo.delete(memory_id)
        except RepositoryError as exc:
            raise MemoryConsistencyError(
                "Memory sidecar compensation failed; namespace rebuild is required"
            ) from exc

    def rebuild_level(self, level: MemoryLevel) -> int:
        """Rebuild one Memory level from authoritative DuckDB records.

        Args:
            level: L0–L4 namespace to replace.

        Returns:
            Number of vectors rebuilt.

        Raises:
            MemoryServiceError: If embedding or persistence fails.
        """

        namespace = self.namespace_for_level(level)
        try:
            records = self._duckdb_repo.list_namespace(namespace)
            vectors = self._embedder.embed_batch(
                [record.summary_text for record in records]
            )
            entries = [
                VectorEntry(
                    vector_id=record.faiss_vector_id,
                    vector=vector,
                    metadata=_vector_metadata(
                        memory_id=record.memory_id,
                        namespace_key=record.namespace_key,
                        asset_id=(
                            None if record.asset_id is None else str(record.asset_id)
                        ),
                    ),
                )
                for record, vector in zip(records, vectors, strict=True)
            ]
            self._vector_repo.rebuild(
                namespace=namespace,
                entries=entries,
                source_table="memory_items",
            )
        except (EmbeddingServiceError, RepositoryError, VectorRepositoryError) as exc:
            raise MemoryServiceError(
                f"failed to rebuild Memory namespace {namespace}"
            ) from exc
        return len(records)

    @staticmethod
    def namespace_for_level(level: MemoryLevel) -> str:
        """Map one validated Memory level to its private FAISS namespace."""

        return f"memory_{level.value}_v1"


def _stable_vector_id(memory_id: str) -> int:
    digest = hashlib.sha256(memory_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _vector_metadata(
    *,
    memory_id: str,
    namespace_key: str,
    asset_id: str | None,
) -> JsonObject:
    return {
        "memory_id": memory_id,
        "namespace_key": namespace_key,
        "asset_id": asset_id,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
