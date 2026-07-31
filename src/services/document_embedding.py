"""Embedding orchestration for pending document chunks."""

from __future__ import annotations

from src.models.types import JsonObject
from src.repositories.base import RepositoryError
from src.repositories.documents import DocumentRepository
from src.repositories.vector import VectorRepository, VectorRepositoryError
from src.schemas.documents import DocumentChunkRecord
from src.services.embedding import (
    EmbeddingInputError,
    EmbeddingService,
    EmbeddingServiceError,
)


class DocumentEmbeddingError(RuntimeError):
    """Raised when document chunk embedding cannot be completed."""


class DocumentEmbeddingConsistencyError(DocumentEmbeddingError):
    """Raised when document and vector sidecars cannot be reconciled."""


class DocumentEmbeddingService:
    """Embed pending chunks while retaining document source mappings."""

    def __init__(
        self,
        documents: DocumentRepository,
        vector_repo: VectorRepository,
        embedder: EmbeddingService,
    ) -> None:
        """Bind existing document metadata, vector, and embedding boundaries."""

        self._documents = documents
        self._vector_repo = vector_repo
        self._embedder = embedder

    def index_document(self, document_id: str) -> list[DocumentChunkRecord]:
        """Embed and persist all pending chunks belonging to a document.

        Args:
            document_id: Existing canonical document identifier.

        Returns:
            All document chunks after indexing, in chunk order.
        """

        if not document_id.strip():
            raise ValueError("document_id cannot be empty")
        chunks = self._documents.list_chunks(document_id)
        pending = [
            chunk
            for chunk in chunks
            if (chunk.metadata_json or {}).get("embedding_status") != "indexed"
        ]
        for chunk in pending:
            if (
                chunk.embedding_model != self._embedder.model_name
                or chunk.embedding_dim != self._embedder.dimension
            ):
                raise EmbeddingInputError(
                    "document chunk embedding contract does not match embedder"
                )
        try:
            vectors = self._embedder.embed_batch(
                [chunk.chunk_text for chunk in pending]
            )
        except EmbeddingServiceError as exc:
            raise DocumentEmbeddingError("document embedding failed") from exc

        updated_by_id: dict[str, DocumentChunkRecord] = {}
        for chunk, vector in zip(pending, vectors, strict=True):
            metadata: JsonObject = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "asset_id": (None if chunk.asset_id is None else str(chunk.asset_id)),
            }
            try:
                self._vector_repo.add(
                    namespace=chunk.faiss_namespace,
                    vector=vector,
                    vector_id=chunk.faiss_vector_id,
                    metadata=metadata,
                    source_table="document_chunks",
                )
            except VectorRepositoryError as exc:
                raise DocumentEmbeddingError("document vector write failed") from exc

            chunk_metadata = dict(chunk.metadata_json or {})
            chunk_metadata["embedding_status"] = "indexed"
            updated = chunk.model_copy(update={"metadata_json": chunk_metadata})
            try:
                self._documents.upsert_chunk(updated)
            except RepositoryError as exc:
                try:
                    removed = self._vector_repo.remove(
                        namespace=chunk.faiss_namespace,
                        vector_id=chunk.faiss_vector_id,
                    )
                except VectorRepositoryError as compensation_error:
                    raise DocumentEmbeddingConsistencyError(
                        "document sidecar write and vector compensation failed"
                    ) from compensation_error
                if not removed:
                    raise DocumentEmbeddingConsistencyError(
                        "document sidecar write failed and vector was not found"
                    ) from exc
                raise DocumentEmbeddingError(
                    "document sidecar write failed; vector was rolled back"
                ) from exc
            updated_by_id[chunk.chunk_id] = updated

        return [updated_by_id.get(chunk.chunk_id, chunk) for chunk in chunks]
