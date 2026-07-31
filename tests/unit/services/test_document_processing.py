"""Tests for raw-text storage and deterministic document chunking."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.models.enums import DocumentType, MarketScope
from src.models.identifiers import AssetId
from src.schemas.documents import TextDocumentRecord
from src.services import DocumentChunker, RawTextStore

NOW = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)


def _document() -> TextDocumentRecord:
    return TextDocumentRecord(
        document_id="doc-1",
        asset_id=AssetId("US:AAPL"),
        market=MarketScope.US,
        doc_type=DocumentType.FILING,
        title="10-Q",
        source_id="sec_edgar",
        created_at=NOW,
    )


def _chunker() -> DocumentChunker:
    return DocumentChunker(
        chunk_size=8,
        overlap=2,
        embedding_model="fixture-embedding",
        embedding_dim=3,
        faiss_namespace="docs_fixture",
    )


def test_chunker_handles_empty_and_short_text() -> None:
    """Empty text produces no fabricated chunk; short text stays intact."""

    assert _chunker().chunk(_document(), "   ", created_at=NOW) == []

    chunks = _chunker().chunk(_document(), "short", created_at=NOW)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_text == "short"
    assert chunks[0].token_count is None
    assert chunks[0].metadata_json is not None
    assert chunks[0].metadata_json["embedding_status"] == "pending"


def test_multichunk_output_is_stable_and_traceable() -> None:
    """Repeated chunking yields stable IDs, indexes, and document links."""

    first = _chunker().chunk(_document(), "abcdefghijklmnop", created_at=NOW)
    second = _chunker().chunk(_document(), "abcdefghijklmnop", created_at=NOW)

    assert len(first) == 3
    assert [item.chunk_index for item in first] == [0, 1, 2]
    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    assert all(item.document_id == "doc-1" for item in first)
    assert all(item.faiss_vector_id >= 0 for item in first)


def test_raw_text_store_writes_verbatim_utf8(tmp_path: Path) -> None:
    """Raw source text is retained below an injected storage root."""

    path = RawTextStore(tmp_path / "raw").write(
        "sec_edgar",
        "doc/unsafe-id",
        "原始 filing text",
    )

    stored = Path(path)
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8") == "原始 filing text"
    assert stored.is_relative_to(tmp_path / "raw")
