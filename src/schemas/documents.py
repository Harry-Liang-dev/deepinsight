"""Text document, chunk, and retrieval schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from src.models.enums import DocumentType, MarketScope
from src.models.identifiers import AssetId
from src.models.types import DomainModel, JsonObject


class TextDocumentRecord(DomainModel):
    """Canonical text document metadata."""

    document_id: str = Field(min_length=1)
    asset_id: AssetId | None = None
    market: MarketScope
    doc_type: DocumentType
    title: str = Field(min_length=1)
    language: str = Field(default="en", min_length=2)
    publisher: str | None = None
    publish_ts: datetime | None = None
    source_id: str = Field(min_length=1)
    source_url: str | None = None
    raw_text_path: str | None = None
    checksum_sha256: str | None = None
    metadata_json: JsonObject | None = None
    created_at: datetime
    p2_label_json: JsonObject | None = None
    p2_training_split: str | None = None

    @model_validator(mode="after")
    def validate_asset_market(self) -> Self:
        """Ensure an optional asset belongs to the document market."""

        if self.asset_id is not None and self.market is not MarketScope(
            self.asset_id.market.value
        ):
            raise ValueError("asset_id market does not match document market")
        return self


class DocumentChunkRecord(DomainModel):
    """Persisted text chunk and vector mapping metadata."""

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    asset_id: AssetId | None = None
    market: MarketScope
    chunk_index: int = Field(ge=0)
    chunk_text: str = Field(min_length=1)
    token_count: int | None = Field(default=None, ge=0)
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    faiss_namespace: str = Field(min_length=1)
    faiss_vector_id: int = Field(ge=0)
    metadata_json: JsonObject | None = None
    created_at: datetime
    p2_ranker_features: JsonObject | None = None


class RetrievedDocument(DomainModel):
    """Document evidence supplied to an analyst agent."""

    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    chunk_id: str | None = None
