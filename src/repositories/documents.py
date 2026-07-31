"""DuckDB Repository for document metadata and chunk sidecars."""

from __future__ import annotations

from src.repositories.base import (
    BaseRepository,
    decode_json_object,
    encode_json,
)
from src.schemas.documents import DocumentChunkRecord, TextDocumentRecord

_DOCUMENT_COLUMNS = (
    "document_id",
    "asset_id",
    "market",
    "doc_type",
    "title",
    "language",
    "publisher",
    "publish_ts",
    "source_id",
    "source_url",
    "raw_text_path",
    "checksum_sha256",
    "metadata_json",
    "created_at",
)

_CHUNK_COLUMNS = (
    "chunk_id",
    "document_id",
    "asset_id",
    "market",
    "chunk_index",
    "chunk_text",
    "token_count",
    "embedding_model",
    "embedding_dim",
    "faiss_namespace",
    "faiss_vector_id",
    "metadata_json",
    "created_at",
)


class DocumentRepository(BaseRepository):
    """Persist document metadata separately from document business services."""

    def upsert_document(self, record: TextDocumentRecord) -> None:
        """Insert or update one document metadata record.

        Args:
            record: Validated document metadata.
        """

        self._execute(
            f"""
            INSERT INTO text_documents ({", ".join(_DOCUMENT_COLUMNS)})
            VALUES ({_placeholders(len(_DOCUMENT_COLUMNS))})
            ON CONFLICT (document_id) DO UPDATE SET
                asset_id = excluded.asset_id,
                market = excluded.market,
                doc_type = excluded.doc_type,
                title = excluded.title,
                language = excluded.language,
                publisher = excluded.publisher,
                publish_ts = excluded.publish_ts,
                source_id = excluded.source_id,
                source_url = excluded.source_url,
                raw_text_path = excluded.raw_text_path,
                checksum_sha256 = excluded.checksum_sha256,
                metadata_json = excluded.metadata_json
            """,
            (
                record.document_id,
                None if record.asset_id is None else str(record.asset_id),
                record.market.value,
                record.doc_type.value,
                record.title,
                record.language,
                record.publisher,
                record.publish_ts,
                record.source_id,
                record.source_url,
                record.raw_text_path,
                record.checksum_sha256,
                (
                    None
                    if record.metadata_json is None
                    else encode_json(record.metadata_json)
                ),
                record.created_at,
            ),
        )

    def get_document(self, document_id: str) -> TextDocumentRecord | None:
        """Return one document metadata record.

        Args:
            document_id: Stable document identifier.

        Returns:
            The matching document, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_DOCUMENT_COLUMNS)}
            FROM text_documents
            WHERE document_id = ?
            """,
            (document_id,),
        )
        if row is None:
            return None
        values = dict(zip(_DOCUMENT_COLUMNS, row, strict=True))
        if values["metadata_json"] is not None:
            values["metadata_json"] = decode_json_object(values["metadata_json"])
        return TextDocumentRecord.model_validate(values)

    def upsert_chunk(self, record: DocumentChunkRecord) -> None:
        """Insert or update one document chunk and FAISS sidecar mapping.

        This method stores mapping metadata only and never opens a FAISS index.

        Args:
            record: Validated persisted chunk metadata.
        """

        self._execute(
            f"""
            INSERT INTO document_chunks ({", ".join(_CHUNK_COLUMNS)})
            VALUES ({_placeholders(len(_CHUNK_COLUMNS))})
            ON CONFLICT (chunk_id) DO UPDATE SET
                document_id = excluded.document_id,
                asset_id = excluded.asset_id,
                market = excluded.market,
                chunk_index = excluded.chunk_index,
                chunk_text = excluded.chunk_text,
                token_count = excluded.token_count,
                embedding_model = excluded.embedding_model,
                embedding_dim = excluded.embedding_dim,
                faiss_namespace = excluded.faiss_namespace,
                faiss_vector_id = excluded.faiss_vector_id,
                metadata_json = excluded.metadata_json
            """,
            (
                record.chunk_id,
                record.document_id,
                None if record.asset_id is None else str(record.asset_id),
                record.market.value,
                record.chunk_index,
                record.chunk_text,
                record.token_count,
                record.embedding_model,
                record.embedding_dim,
                record.faiss_namespace,
                record.faiss_vector_id,
                (
                    None
                    if record.metadata_json is None
                    else encode_json(record.metadata_json)
                ),
                record.created_at,
            ),
        )

    def list_chunks(self, document_id: str) -> list[DocumentChunkRecord]:
        """Return all chunks for a document in deterministic order.

        Args:
            document_id: Stable document identifier.

        Returns:
            Ordered persisted chunks.
        """

        rows = self._fetch_all(
            f"""
            SELECT {", ".join(_CHUNK_COLUMNS)}
            FROM document_chunks
            WHERE document_id = ?
            ORDER BY chunk_index, chunk_id
            """,
            (document_id,),
        )
        records: list[DocumentChunkRecord] = []
        for row in rows:
            values = dict(zip(_CHUNK_COLUMNS, row, strict=True))
            if values["metadata_json"] is not None:
                values["metadata_json"] = decode_json_object(values["metadata_json"])
            records.append(DocumentChunkRecord.model_validate(values))
        return records


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))
