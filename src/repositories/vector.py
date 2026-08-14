"""Persistent FAISS indexes hidden behind a repository boundary."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol, cast
from uuid import uuid4

import duckdb
import faiss
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from src.models.types import JsonObject

_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_INDEX_FILE = "index.faiss"
_METADATA_FILE = "vector_meta.parquet"
_MANIFEST_FILE = "manifest.json"


class VectorRepositoryError(RuntimeError):
    """Base error for provider-independent vector persistence failures."""


class VectorNamespaceError(VectorRepositoryError):
    """Raised when a namespace is unsafe or has incompatible metadata."""


class VectorDimensionError(VectorRepositoryError):
    """Raised when a vector does not match the configured dimension."""


class VectorPersistenceError(VectorRepositoryError):
    """Raised when a persisted namespace is missing or inconsistent."""


class VectorIndexManifest(BaseModel):
    """Validated metadata required to safely reload one FAISS namespace."""

    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(min_length=1)
    embedder_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    distance_metric: str = "cosine"
    source_table: str = Field(min_length=1)
    faiss_index_type: str = "IndexFlatIP"
    created_at: datetime


@dataclass(frozen=True, slots=True)
class VectorEntry:
    """One vector and its internal lookup metadata used during rebuild."""

    vector_id: int
    vector: list[float]
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class VectorSearchCandidate:
    """Provider-independent similarity candidate returned to services."""

    namespace: str
    vector_id: int
    score: float
    metadata: JsonObject


class VectorRepository(Protocol):
    """Narrow vector boundary consumed by Memory and document services."""

    def add(
        self,
        *,
        namespace: str,
        vector: list[float],
        vector_id: int,
        metadata: JsonObject,
        source_table: str,
    ) -> int:
        """Persist one vector and return its explicit identifier."""
        ...

    def remove(self, *, namespace: str, vector_id: int) -> bool:
        """Remove one vector, returning whether it existed."""
        ...

    def search_across(
        self,
        *,
        namespaces: list[str],
        query_vector: list[float],
        top_k: int | None,
    ) -> list[VectorSearchCandidate]:
        """Search namespaces without exposing the underlying index."""
        ...

    def rebuild(
        self,
        *,
        namespace: str,
        entries: list[VectorEntry],
        source_table: str,
    ) -> None:
        """Replace one namespace from authoritative source records."""
        ...

    def snapshot_id(self, namespaces: list[str]) -> str:
        """Return a stable provider-independent identity for namespace state."""
        ...


@dataclass(slots=True)
class _NamespaceState:
    index: faiss.Index
    manifest: VectorIndexManifest
    metadata: dict[int, JsonObject]


class FaissVectorRepository:
    """Store isolated cosine-similarity namespaces on the local filesystem.

    FAISS objects remain private. Callers receive stable integer identifiers
    and provider-independent candidates only.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        embedder_model: str,
        embedding_dim: int,
    ) -> None:
        """Configure the persistent vector root and embedding contract.

        Args:
            root: Explicit local directory containing namespace folders.
            embedder_model: Model identifier recorded in every manifest.
            embedding_dim: Required vector dimension.
        """

        if not str(root).strip():
            raise ValueError("FAISS root cannot be empty")
        if not embedder_model.strip():
            raise ValueError("embedder_model cannot be empty")
        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        self._root = Path(root)
        self._embedder_model = embedder_model
        self._embedding_dim = embedding_dim
        self._states: dict[str, _NamespaceState] = {}
        self._lock = RLock()

    @property
    def embedder_model(self) -> str:
        """Return the configured embedding model identifier."""

        return self._embedder_model

    @property
    def embedding_dim(self) -> int:
        """Return the required embedding dimension."""

        return self._embedding_dim

    def add(
        self,
        *,
        namespace: str,
        vector: list[float],
        vector_id: int,
        metadata: JsonObject,
        source_table: str,
    ) -> int:
        """Add and persist one explicitly identified vector.

        Replaying the same vector ID with identical metadata is idempotent.

        Args:
            namespace: Safe namespace folder name.
            vector: Dense embedding matching the configured dimension.
            vector_id: Non-negative signed 63-bit identifier.
            metadata: Internal lookup metadata; never exposed as a FAISS object.
            source_table: Authoritative DuckDB sidecar table.

        Returns:
            The supplied vector identifier.

        Raises:
            VectorRepositoryError: If validation or persistence fails.
        """

        self._validate_vector_id(vector_id)
        if not source_table.strip():
            raise VectorNamespaceError("source_table cannot be empty")
        normalized = self._normalize_vector(vector)
        with self._lock:
            state = self._get_or_create(namespace, source_table)
            existing = state.metadata.get(vector_id)
            if existing is not None:
                if existing != metadata:
                    raise VectorRepositoryError(
                        "vector ID already exists with different metadata"
                    )
                return vector_id

            identifiers = np.asarray([vector_id], dtype=np.int64)
            state.index.add_with_ids(normalized, identifiers)
            state.metadata[vector_id] = dict(metadata)
            try:
                self._persist(namespace, state)
            except Exception as exc:
                state.index.remove_ids(faiss.IDSelectorBatch(identifiers))
                state.metadata.pop(vector_id, None)
                if isinstance(exc, VectorRepositoryError):
                    raise
                raise VectorPersistenceError(
                    f"failed to persist vector namespace {namespace}"
                ) from exc
        return vector_id

    def remove(self, *, namespace: str, vector_id: int) -> bool:
        """Remove and persist one vector if it exists.

        Args:
            namespace: Existing vector namespace.
            vector_id: Explicit vector identifier.

        Returns:
            ``True`` when a vector was removed, otherwise ``False``.
        """

        self._validate_vector_id(vector_id)
        with self._lock:
            state = self._load(namespace)
            if state is None or vector_id not in state.metadata:
                return False
            identifiers = np.asarray([vector_id], dtype=np.int64)
            removed_metadata = state.metadata.pop(vector_id)
            removed_count = state.index.remove_ids(faiss.IDSelectorBatch(identifiers))
            if removed_count != 1:
                state.metadata[vector_id] = removed_metadata
                raise VectorPersistenceError(
                    "FAISS index and vector metadata are inconsistent"
                )
            try:
                self._persist(namespace, state)
            except Exception:
                raise VectorPersistenceError(
                    "vector removal could not be persisted; rebuild is required"
                ) from None
            return True

    def search_across(
        self,
        *,
        namespaces: list[str],
        query_vector: list[float],
        top_k: int | None,
    ) -> list[VectorSearchCandidate]:
        """Search one or more namespaces using cosine similarity.

        Args:
            namespaces: Isolated namespace names to inspect.
            query_vector: Dense query embedding.
            top_k: Global result limit. ``None`` returns all candidates.

        Returns:
            Similarity candidates ordered by descending score.
        """

        if top_k is not None and top_k <= 0:
            raise ValueError("top_k must be positive when supplied")
        normalized = self._normalize_vector(query_vector)
        candidates: list[VectorSearchCandidate] = []
        with self._lock:
            for namespace in dict.fromkeys(namespaces):
                state = self._load(namespace)
                if state is None or state.index.ntotal == 0:
                    continue
                namespace_limit = (
                    int(state.index.ntotal)
                    if top_k is None
                    else min(top_k, int(state.index.ntotal))
                )
                scores, identifiers = state.index.search(
                    normalized,
                    namespace_limit,
                )
                for raw_score, raw_identifier in zip(
                    scores[0],
                    identifiers[0],
                    strict=True,
                ):
                    vector_id = int(raw_identifier)
                    if vector_id < 0:
                        continue
                    metadata = state.metadata.get(vector_id)
                    if metadata is None:
                        raise VectorPersistenceError(
                            "FAISS result has no vector metadata"
                        )
                    candidates.append(
                        VectorSearchCandidate(
                            namespace=namespace,
                            vector_id=vector_id,
                            score=float(raw_score),
                            metadata=dict(metadata),
                        )
                    )
        candidates.sort(key=lambda item: (-item.score, item.namespace, item.vector_id))
        return candidates if top_k is None else candidates[:top_k]

    def count(self, namespace: str) -> int:
        """Return the number of vectors in a namespace."""

        with self._lock:
            state = self._load(namespace)
            return 0 if state is None else int(state.index.ntotal)

    def snapshot_id(self, namespaces: list[str]) -> str:
        """Return a stable identity for the persisted requested namespaces.

        The identity contains validated manifest values and vector IDs only.
        It does not expose FAISS objects, vectors, or source content.
        """

        namespace_states: list[object] = []
        with self._lock:
            for namespace in sorted(set(namespaces)):
                state = self._load(namespace)
                if state is None:
                    namespace_states.append(
                        {"namespace": namespace, "status": "missing"}
                    )
                    continue
                namespace_states.append(
                    {
                        "manifest": state.manifest.model_dump(mode="json"),
                        "vector_ids": sorted(state.metadata),
                    }
                )
        encoded = json.dumps(
            {"namespaces": namespace_states},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"vecsnap_{digest}"

    def rebuild(
        self,
        *,
        namespace: str,
        entries: list[VectorEntry],
        source_table: str,
    ) -> None:
        """Replace one namespace from authoritative source records.

        Args:
            namespace: Namespace to replace.
            entries: Complete replacement vector set.
            source_table: Authoritative DuckDB table name.
        """

        self._validate_namespace(namespace)
        if not source_table.strip():
            raise VectorNamespaceError("source_table cannot be empty")
        index = self._new_index()
        metadata: dict[int, JsonObject] = {}
        if entries:
            vectors: list[np.ndarray] = []
            identifiers: list[int] = []
            for entry in entries:
                self._validate_vector_id(entry.vector_id)
                if entry.vector_id in metadata:
                    raise VectorRepositoryError("rebuild contains duplicate vector IDs")
                vectors.append(self._normalize_vector(entry.vector)[0])
                identifiers.append(entry.vector_id)
                metadata[entry.vector_id] = dict(entry.metadata)
            index.add_with_ids(
                np.stack(vectors).astype(np.float32, copy=False),
                np.asarray(identifiers, dtype=np.int64),
            )
        state = _NamespaceState(
            index=index,
            manifest=self._new_manifest(namespace, source_table),
            metadata=metadata,
        )
        with self._lock:
            self._persist(namespace, state)
            self._states[namespace] = state

    def manifest(self, namespace: str) -> VectorIndexManifest | None:
        """Return a copy of a namespace manifest, if the namespace exists."""

        with self._lock:
            state = self._load(namespace)
            if state is None:
                return None
            return state.manifest.model_copy(deep=True)

    def _get_or_create(
        self,
        namespace: str,
        source_table: str,
    ) -> _NamespaceState:
        state = self._load(namespace)
        if state is None:
            state = _NamespaceState(
                index=self._new_index(),
                manifest=self._new_manifest(namespace, source_table),
                metadata={},
            )
            self._states[namespace] = state
        elif state.manifest.source_table != source_table:
            raise VectorNamespaceError(
                "namespace source_table does not match its manifest"
            )
        return state

    def _load(self, namespace: str) -> _NamespaceState | None:
        self._validate_namespace(namespace)
        cached = self._states.get(namespace)
        if cached is not None:
            return cached

        directory = self._root / namespace
        if not directory.exists():
            return None
        paths = (
            directory / _INDEX_FILE,
            directory / _METADATA_FILE,
            directory / _MANIFEST_FILE,
        )
        if not all(path.is_file() for path in paths):
            raise VectorPersistenceError(
                f"namespace {namespace} is missing required persistence files"
            )
        try:
            manifest = VectorIndexManifest.model_validate_json(
                paths[2].read_text(encoding="utf-8")
            )
            index = faiss.read_index(str(paths[0]))
            metadata = self._read_metadata(paths[1])
        except VectorRepositoryError:
            raise
        except Exception as exc:
            raise VectorPersistenceError(
                f"failed to load vector namespace {namespace}"
            ) from exc

        self._validate_loaded_state(namespace, manifest, index, metadata)
        state = _NamespaceState(
            index=index,
            manifest=manifest,
            metadata=metadata,
        )
        self._states[namespace] = state
        return state

    def _validate_loaded_state(
        self,
        namespace: str,
        manifest: VectorIndexManifest,
        index: faiss.Index,
        metadata: dict[int, JsonObject],
    ) -> None:
        if manifest.namespace != namespace:
            raise VectorNamespaceError("manifest namespace does not match its folder")
        if manifest.embedder_model != self._embedder_model:
            raise VectorNamespaceError(
                "manifest embedder model does not match repository configuration"
            )
        if manifest.embedding_dim != self._embedding_dim or index.d != (
            self._embedding_dim
        ):
            raise VectorDimensionError(
                "persisted index dimension does not match repository configuration"
            )
        if (
            manifest.distance_metric != "cosine"
            or manifest.faiss_index_type != "IndexFlatIP"
        ):
            raise VectorNamespaceError("unsupported persisted index configuration")
        if int(index.ntotal) != len(metadata):
            raise VectorPersistenceError(
                "FAISS index count does not match vector metadata"
            )
        persisted_ids = set(
            int(value)
            for value in faiss.vector_to_array(cast(faiss.IndexIDMap2, index).id_map)
        )
        if persisted_ids != set(metadata):
            raise VectorPersistenceError(
                "FAISS identifiers do not match vector metadata"
            )

    def _persist(self, namespace: str, state: _NamespaceState) -> None:
        directory = self._root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        nonce = uuid4().hex
        temporary_index = directory / f".{_INDEX_FILE}.{nonce}.tmp"
        temporary_metadata = directory / f".{_METADATA_FILE}.{nonce}.tmp"
        temporary_manifest = directory / f".{_MANIFEST_FILE}.{nonce}.tmp"
        temporary_paths = (
            temporary_index,
            temporary_metadata,
            temporary_manifest,
        )
        try:
            faiss.write_index(state.index, str(temporary_index))
            self._write_metadata(temporary_metadata, state.metadata)
            temporary_manifest.write_text(
                state.manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_index, directory / _INDEX_FILE)
            os.replace(temporary_metadata, directory / _METADATA_FILE)
            os.replace(temporary_manifest, directory / _MANIFEST_FILE)
        except Exception as exc:
            raise VectorPersistenceError(
                f"failed to save vector namespace {namespace}"
            ) from exc
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    @staticmethod
    def _write_metadata(path: Path, metadata: dict[int, JsonObject]) -> None:
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute("""
                CREATE TABLE vector_meta (
                    faiss_vector_id BIGINT NOT NULL,
                    metadata_json VARCHAR NOT NULL
                )
                """)
            if metadata:
                connection.executemany(
                    "INSERT INTO vector_meta VALUES (?, ?)",
                    [
                        (
                            vector_id,
                            json.dumps(
                                value,
                                allow_nan=False,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        )
                        for vector_id, value in sorted(metadata.items())
                    ],
                )
            escaped_path = str(path).replace("'", "''")
            connection.execute(f"COPY vector_meta TO '{escaped_path}' (FORMAT PARQUET)")
        finally:
            connection.close()

    @staticmethod
    def _read_metadata(path: Path) -> dict[int, JsonObject]:
        connection = duckdb.connect(database=":memory:")
        try:
            rows = connection.execute(
                """
                SELECT faiss_vector_id, metadata_json
                FROM read_parquet(?)
                ORDER BY faiss_vector_id
                """,
                (str(path),),
            ).fetchall()
        finally:
            connection.close()
        metadata: dict[int, JsonObject] = {}
        for raw_id, raw_metadata in rows:
            decoded = json.loads(str(raw_metadata))
            if not isinstance(decoded, dict):
                raise VectorPersistenceError(
                    "persisted vector metadata is not a JSON object"
                )
            metadata[int(raw_id)] = cast(JsonObject, decoded)
        return metadata

    def _normalize_vector(self, vector: list[float]) -> np.ndarray:
        try:
            array = np.asarray(vector, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise VectorDimensionError("vector must contain numeric values") from exc
        if array.ndim != 1 or array.shape[0] != self._embedding_dim:
            raise VectorDimensionError(
                f"expected vector dimension {self._embedding_dim}"
            )
        if not bool(np.isfinite(array).all()):
            raise VectorDimensionError("vector values must be finite")
        norm = float(np.linalg.norm(array))
        if not math.isfinite(norm) or norm <= 0.0:
            raise VectorDimensionError("vector norm must be positive")
        return (array / norm).reshape(1, self._embedding_dim)

    def _new_index(self) -> faiss.Index:
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self._embedding_dim))

    def _new_manifest(
        self,
        namespace: str,
        source_table: str,
    ) -> VectorIndexManifest:
        return VectorIndexManifest(
            namespace=namespace,
            embedder_model=self._embedder_model,
            embedding_dim=self._embedding_dim,
            distance_metric="cosine",
            source_table=source_table,
            faiss_index_type="IndexFlatIP",
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise VectorNamespaceError("invalid vector namespace")

    @staticmethod
    def _validate_vector_id(vector_id: int) -> None:
        if not 0 <= vector_id < (1 << 63):
            raise VectorRepositoryError(
                "vector_id must be a non-negative signed 63-bit integer"
            )
