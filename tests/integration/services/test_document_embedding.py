"""Integration tests for pending document chunk embedding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.enums import DocumentType, MarketScope
from src.models.identifiers import AssetId
from src.repositories import DocumentRepository, DuckDBDatabase, FaissVectorRepository
from src.schemas.documents import DocumentChunkRecord, TextDocumentRecord
from src.services import DocumentEmbeddingService, FakeEmbeddingService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)


def test_pending_document_chunk_is_embedded_and_persisted(tmp_path: Path) -> None:
    """Document chunk status and durable vector metadata advance together."""

    database = DuckDBDatabase(tmp_path / "documents.duckdb")
    database.bootstrap()
    documents = DocumentRepository(database)
    document = TextDocumentRecord(
        document_id="doc-1",
        asset_id=AssetId("US:AAPL"),
        market=MarketScope.US,
        doc_type=DocumentType.FILING,
        title="10-Q",
        source_id="sec_edgar",
        source_url="https://example.test/filing",
        created_at=NOW,
    )
    chunk = DocumentChunkRecord(
        chunk_id="chunk-1",
        document_id=document.document_id,
        asset_id=document.asset_id,
        market=document.market,
        chunk_index=0,
        chunk_text="Revenue increased.",
        embedding_model="fake-doc-embedding",
        embedding_dim=3,
        faiss_namespace="docs_v1",
        faiss_vector_id=17,
        metadata_json={"embedding_status": "pending"},
        created_at=NOW,
    )
    documents.upsert_document(document)
    documents.upsert_chunk(chunk)
    embedder = FakeEmbeddingService(
        {chunk.chunk_text: [1.0, 0.0, 0.0]},
        model_name=chunk.embedding_model,
    )
    root = tmp_path / "faiss"
    vectors = FaissVectorRepository(
        root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )

    indexed = DocumentEmbeddingService(
        documents,
        vectors,
        embedder,
    ).index_document(document.document_id)

    assert indexed[0].metadata_json is not None
    assert indexed[0].metadata_json["embedding_status"] == "indexed"
    restarted = FaissVectorRepository(
        root,
        embedder_model=embedder.model_name,
        embedding_dim=embedder.dimension,
    )
    candidates = restarted.search_across(
        namespaces=["docs_v1"],
        query_vector=[1.0, 0.0, 0.0],
        top_k=1,
    )
    assert candidates[0].metadata == {
        "asset_id": "US:AAPL",
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
    }
    stored_document = documents.get_document("doc-1")
    assert stored_document is not None
    assert stored_document.source_url == "https://example.test/filing"
