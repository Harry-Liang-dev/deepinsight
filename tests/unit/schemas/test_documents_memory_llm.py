"""Tests for documents, memory, and LLM contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import AgentStatus, DocumentType, MarketScope, MemoryLevel
from src.models.identifiers import AssetId
from src.schemas.documents import DocumentChunkRecord, TextDocumentRecord
from src.schemas.llm import LLMRequest, LLMResponse, LLMUsage
from src.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryWriteRequest,
)

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def test_document_and_chunk_preserve_source_mapping() -> None:
    """A normalized document should map to a traceable vector chunk."""
    document = TextDocumentRecord(
        document_id="doc-1",
        asset_id=AssetId("US:AAPL"),
        market=MarketScope.US,
        doc_type=DocumentType.FILING,
        title="10-Q filing",
        source_id="sec_edgar",
        created_at=NOW,
    )
    chunk = DocumentChunkRecord(
        chunk_id="chunk-1",
        document_id=document.document_id,
        asset_id=document.asset_id,
        market=document.market,
        chunk_index=0,
        chunk_text="Revenue increased year over year.",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        faiss_namespace="docs_v1",
        faiss_vector_id=1,
        created_at=NOW,
    )

    assert chunk.document_id == document.document_id
    assert chunk.p2_ranker_features is None


def test_document_rejects_asset_market_mismatch() -> None:
    """Document market scope should agree with its optional asset."""
    with pytest.raises(ValidationError, match="document market"):
        TextDocumentRecord(
            document_id="doc-1",
            asset_id=AssetId("US:AAPL"),
            market=MarketScope.CN,
            doc_type=DocumentType.NEWS,
            title="News",
            source_id="provider",
            created_at=NOW,
        )


def test_memory_contracts_validate_levels_and_scores() -> None:
    """Memory requests and ranked results should serialize together."""
    write_request = MemoryWriteRequest(
        memory_level=MemoryLevel.L2,
        namespace_key="US:AAPL",
        asset_id=AssetId("US:AAPL"),
        effective_ts=NOW,
        memory_type="issuer_event",
        importance_score=0.92,
        summary_text="Guidance was reduced.",
        created_by="news_event_analyst",
    )
    result = MemorySearchResult(
        memory_id="mem-1",
        memory_level=MemoryLevel.L2,
        namespace_key=write_request.namespace_key,
        asset_id=write_request.asset_id,
        summary_text=write_request.summary_text,
        score=0.883,
        effective_ts=NOW,
    )
    response = MemorySearchResponse(results=[result])

    assert response.results[0].memory_level is MemoryLevel.L2
    assert response.model_dump(mode="json")["results"][0]["asset_id"] == "US:AAPL"


@pytest.mark.parametrize("importance_score", [-0.01, 1.01])
def test_memory_rejects_invalid_importance(importance_score: float) -> None:
    """Memory importance must remain within the declared range."""
    with pytest.raises(ValidationError):
        MemoryWriteRequest(
            memory_level=MemoryLevel.L1,
            namespace_key="US",
            effective_ts=NOW,
            summary_text="Macro event",
            importance_score=importance_score,
        )


def test_memory_search_requires_nonempty_filters() -> None:
    """Search requests must identify at least one level and namespace."""
    with pytest.raises(ValidationError):
        MemorySearchRequest(
            memory_levels=[],
            namespace_keys=[],
            query_text="guidance cut",
        )


def test_llm_request_and_response_use_json_contracts() -> None:
    """LLM boundaries should remain provider-independent and structured."""
    request = LLMRequest(
        model="gpt-5",
        system_prompt="Return valid JSON.",
        input_payload={"asset_id": "US:AAPL"},
    )
    response = LLMResponse(
        status=AgentStatus.OK,
        model=request.model,
        content={"summary": "Constructive"},
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
    )

    assert response.content["summary"] == "Constructive"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 10
