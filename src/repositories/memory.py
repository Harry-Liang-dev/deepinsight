"""DuckDB sidecar Repository for Memory metadata."""

from __future__ import annotations

from src.repositories.base import (
    BaseRepository,
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
        values = dict(zip(_MEMORY_COLUMNS, row, strict=True))
        raw_source = values.pop("source_ref_json")
        values["source_ref"] = (
            None
            if raw_source is None
            else SourceReference.model_validate(decode_json_object(raw_source))
        )
        return MemoryItemRecord.model_validate(values)


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))
