"""Raw-text persistence and deterministic pre-embedding document chunking."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from src.models.types import JsonObject
from src.schemas.documents import DocumentChunkRecord, TextDocumentRecord


class VectorIdAllocator(Protocol):
    """Allocate a stable FAISS-compatible integer for one chunk identifier."""

    def allocate(self, chunk_id: str) -> int:
        """Return a non-negative stable vector identifier."""
        ...


class HashVectorIdAllocator:
    """Derive stable 63-bit identifiers without opening a FAISS index."""

    def allocate(self, chunk_id: str) -> int:
        """Return a deterministic non-negative identifier."""

        digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


class RawTextStore:
    """Persist provider text verbatim below an explicitly configured root."""

    def __init__(self, root: str | Path) -> None:
        """Initialize the store without creating directories."""

        if not str(root).strip():
            raise ValueError("raw text root cannot be empty")
        self._root = Path(root)

    def write(self, source_id: str, document_id: str, raw_text: str) -> str:
        """Write UTF-8 source text and return its traceable path."""

        if not source_id.strip() or not document_id.strip():
            raise ValueError("source_id and document_id are required")
        source_directory = self._root / _safe_source_directory(source_id)
        source_directory.mkdir(parents=True, exist_ok=True)
        file_name = hashlib.sha256(document_id.encode("utf-8")).hexdigest() + ".txt"
        path = source_directory / file_name
        path.write_text(raw_text, encoding="utf-8")
        return str(path)


class DocumentChunker:
    """Build stable chunk sidecars without generating embeddings."""

    def __init__(
        self,
        *,
        chunk_size: int,
        overlap: int,
        embedding_model: str,
        embedding_dim: int,
        faiss_namespace: str,
        vector_ids: VectorIdAllocator | None = None,
    ) -> None:
        """Configure an explicit character-window chunking policy."""

        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be non-negative and below chunk_size")
        if not embedding_model.strip() or not faiss_namespace.strip():
            raise ValueError("embedding model and namespace are required")
        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim
        self._faiss_namespace = faiss_namespace
        self._vector_ids = vector_ids or HashVectorIdAllocator()

    def chunk(
        self,
        document: TextDocumentRecord,
        raw_text: str,
        *,
        created_at: datetime | None = None,
    ) -> list[DocumentChunkRecord]:
        """Split text into stable, ordered, explicitly pending chunks."""

        if not isinstance(raw_text, str):
            raise TypeError("raw_text must be a string")
        if not raw_text.strip():
            return []

        records: list[DocumentChunkRecord] = []
        step = self._chunk_size - self._overlap
        for start in range(0, len(raw_text), step):
            end = min(start + self._chunk_size, len(raw_text))
            chunk_text = raw_text[start:end].strip()
            if chunk_text:
                index = len(records)
                chunk_id = _chunk_id(document.document_id, index, chunk_text)
                metadata: JsonObject = {
                    "embedding_status": "pending",
                    "char_start": start,
                    "char_end": end,
                }
                records.append(
                    DocumentChunkRecord(
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        asset_id=document.asset_id,
                        market=document.market,
                        chunk_index=index,
                        chunk_text=chunk_text,
                        token_count=None,
                        embedding_model=self._embedding_model,
                        embedding_dim=self._embedding_dim,
                        faiss_namespace=self._faiss_namespace,
                        faiss_vector_id=self._vector_ids.allocate(chunk_id),
                        metadata_json=metadata,
                        created_at=created_at or datetime.now(UTC),
                    )
                )
            if end == len(raw_text):
                break
        return records


def _safe_source_directory(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
    return f"source_{digest}"


def _chunk_id(document_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{document_id}|{index}|{text}".encode()).hexdigest()
    return f"chunk_{digest[:32]}"
