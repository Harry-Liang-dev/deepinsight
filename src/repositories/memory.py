"""DuckDB sidecar Repository for Memory metadata."""

from __future__ import annotations

from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_object,
    encode_json,
)
from src.repositories.records import MemoryItemRecord
from src.schemas.common import SourceReference

_MEMORY_COLUMNS = (
    "memory_id",
    "memory_level",
    "namespace_key",
    "asset_id",
    "effective_ts",
    "memory_type",
    "importance_score",
    "summary_text",
    "source_ref_json",
    "embedding_model",
    "embedding_dim",
    "faiss_namespace",
    "faiss_vector_id",
    "created_by",
    "created_at",
    "expires_at",
)


class MemoryItemRepository(BaseRepository):
    """Persist Memory metadata without performing embedding or retrieval."""

    def insert(self, record: MemoryItemRecord) -> None:
        """Insert one complete Memory sidecar record.

        Args:
            record: Validated persistence record containing vector metadata.

        Raises:
            RepositoryError: If the identifier already exists or DuckDB rejects
                the record.
        """

        columns = _MEMORY_COLUMNS[:14] + ("expires_at",)
        self._execute(
            f"""
            INSERT INTO memory_items ({", ".join(columns)})
            VALUES ({_placeholders(len(columns))})
            """,
            (
                record.memory_id,
                record.memory_level.value,
                record.namespace_key,
                None if record.asset_id is None else str(record.asset_id),
                record.effective_ts,
                record.memory_type,
                record.importance_score,
                record.summary_text,
                (
                    None
                    if record.source_ref is None
                    else encode_json(record.source_ref.model_dump(mode="json"))
                ),
                record.embedding_model,
                record.embedding_dim,
                record.faiss_namespace,
                record.faiss_vector_id,
                record.created_by,
                record.expires_at,
            ),
        )

    def get(self, memory_id: str) -> MemoryItemRecord | None:
        """Return one Memory sidecar record.

        Args:
            memory_id: Stable Memory identifier.

        Returns:
            The matching record, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_MEMORY_COLUMNS)}
            FROM memory_items
            WHERE memory_id = ?
            """,
            (memory_id,),
        )
        if row is None:
            return None
        return _map_memory_row(row)

    def get_by_vector(
        self,
        faiss_namespace: str,
        faiss_vector_id: int,
    ) -> MemoryItemRecord | None:
        """Return the Memory record mapped to one vector candidate.

        Args:
            faiss_namespace: Persisted vector namespace.
            faiss_vector_id: Explicit FAISS vector identifier.

        Returns:
            The matching Memory record, or ``None``.

        Raises:
            RepositoryError: If multiple records map to the same vector.
        """

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_MEMORY_COLUMNS)}
            FROM memory_items
            WHERE faiss_namespace = ? AND faiss_vector_id = ?
            """,
            (faiss_namespace, faiss_vector_id),
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise RepositoryError("multiple Memory records map to one vector")
        return _map_memory_row(rows[0])

    def list_namespace(self, faiss_namespace: str) -> list[MemoryItemRecord]:
        """Return Memory records for one FAISS namespace in stable order."""

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_MEMORY_COLUMNS)}
            FROM memory_items
            WHERE faiss_namespace = ?
            ORDER BY faiss_vector_id, memory_id
            """,
            (faiss_namespace,),
        )
        return [_map_memory_row(row) for row in rows]

    def delete(self, memory_id: str) -> None:
        """Delete one Memory sidecar during failed-write compensation."""

        self._execute(
            "DELETE FROM memory_items WHERE memory_id = ?",
            (memory_id,),
        )


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _map_memory_row(row: tuple[object, ...]) -> MemoryItemRecord:
    values = dict(zip(_MEMORY_COLUMNS, row, strict=True))
    raw_source = values.pop("source_ref_json")
    values["source_ref"] = (
        None
        if raw_source is None
        else SourceReference.model_validate(decode_json_object(raw_source))
    )
    return MemoryItemRecord.model_validate(values)
