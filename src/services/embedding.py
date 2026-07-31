"""Replaceable embedding boundary for documents and Memory."""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Protocol, cast

import openai
from openai import OpenAI
from openai.types import CreateEmbeddingResponse

from src.core.settings import OpenAISettings


class EmbeddingServiceError(RuntimeError):
    """Base error for safe, provider-independent embedding failures."""


class EmbeddingConfigurationError(EmbeddingServiceError):
    """Raised when required embedding configuration is missing."""


class EmbeddingInputError(EmbeddingServiceError):
    """Raised when input text or a returned vector is invalid."""


class EmbeddingRemoteError(EmbeddingServiceError):
    """Raised when a remote embedding provider cannot complete a request."""


class EmbeddingService(Protocol):
    """Provider-independent embedding contract used by upper services."""

    @property
    def model_name(self) -> str:
        """Return the stable embedding model identifier."""
        ...

    @property
    def dimension(self) -> int:
        """Return the exact vector dimension."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed one non-empty text value."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed ordered non-empty text values."""
        ...


class _EmbeddingsClient(Protocol):
    """Narrow synchronous Embeddings API surface used for injection."""

    def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
        timeout: float,
    ) -> CreateEmbeddingResponse:
        """Create embeddings for an ordered text batch."""
        ...


class _OpenAIEmbeddingClient(Protocol):
    """Narrow OpenAI client surface required by the embedding service."""

    @property
    def embeddings(self) -> _EmbeddingsClient:
        """Return the synchronous Embeddings API resource."""
        ...


class OpenAIEmbeddingService:
    """Official OpenAI Embeddings API implementation."""

    def __init__(
        self,
        settings: OpenAISettings,
        *,
        dimension: int,
        client: OpenAI | _OpenAIEmbeddingClient | None = None,
    ) -> None:
        """Initialize an independently injectable embedding service.

        Args:
            settings: Existing OpenAI credential, model, and timeout settings.
            dimension: Explicit output dimension expected by FAISS.
            client: Optional injected client for offline tests.
        """

        if dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        if not settings.embedding_model.strip():
            raise ValueError("embedding model cannot be empty")
        self._settings = settings
        self._dimension = dimension
        self._client = cast(_OpenAIEmbeddingClient | None, client)

    @property
    def model_name(self) -> str:
        """Return the configured OpenAI embedding model."""

        return self._settings.embedding_model

    @property
    def dimension(self) -> int:
        """Return the explicitly configured output dimension."""

        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Embed one non-empty text value."""

        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed an ordered batch and validate every provider vector."""

        _validate_texts(texts)
        if not texts:
            return []
        try:
            response = self._get_client().embeddings.create(
                input=texts,
                model=self.model_name,
                dimensions=self.dimension,
                timeout=float(self._settings.timeout_seconds),
            )
        except openai.APITimeoutError:
            raise EmbeddingRemoteError("OpenAI embedding request timed out") from None
        except openai.RateLimitError:
            raise EmbeddingRemoteError(
                "OpenAI embedding request exceeded its rate limit"
            ) from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise EmbeddingRemoteError(
                "OpenAI embedding credentials or permissions were rejected"
            ) from None
        except openai.APIConnectionError:
            raise EmbeddingRemoteError(
                "OpenAI embedding service could not be reached"
            ) from None
        except (openai.APIStatusError, openai.APIError):
            raise EmbeddingRemoteError("OpenAI embedding request failed") from None
        except EmbeddingServiceError:
            raise
        except Exception:
            raise EmbeddingRemoteError("OpenAI embedding request failed") from None

        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise EmbeddingRemoteError(
                "embedding provider returned an unexpected vector count"
            )
        return [_validate_vector(item.embedding, self.dimension) for item in ordered]

    def _get_client(self) -> _OpenAIEmbeddingClient:
        if self._client is not None:
            return self._client
        secret = self._settings.api_key
        if secret is None or not secret.get_secret_value().strip():
            raise EmbeddingConfigurationError("OpenAI API key is not configured")
        try:
            self._client = cast(
                _OpenAIEmbeddingClient,
                OpenAI(
                    api_key=secret.get_secret_value(),
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=self._settings.max_retries,
                ),
            )
        except Exception:
            raise EmbeddingConfigurationError(
                "OpenAI client initialization failed"
            ) from None
        return self._client


class FakeEmbeddingService:
    """Deterministic offline embedding service for tests and local fixtures."""

    def __init__(
        self,
        vectors: Mapping[str, list[float]],
        *,
        model_name: str = "fake-embedding-v1",
    ) -> None:
        """Configure exact text-to-vector responses without network access."""

        if not model_name.strip():
            raise ValueError("fake embedding model cannot be empty")
        if not vectors:
            raise ValueError("fake embedding vectors cannot be empty")
        first_dimension = len(next(iter(vectors.values())))
        if first_dimension <= 0:
            raise ValueError("fake embedding dimension must be positive")
        self._vectors = {
            text: _validate_vector(vector, first_dimension)
            for text, vector in vectors.items()
        }
        self._model_name = model_name
        self._dimension = first_dimension
        self.calls: list[list[str]] = []

    @property
    def model_name(self) -> str:
        """Return the configured fake model identifier."""

        return self._model_name

    @property
    def dimension(self) -> int:
        """Return the configured fake vector dimension."""

        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Return the exact configured vector for one text."""

        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return configured vectors in request order and capture the call."""

        _validate_texts(texts)
        self.calls.append(list(texts))
        missing = [text for text in texts if text not in self._vectors]
        if missing:
            raise EmbeddingInputError("fake embedding has no vector for input text")
        return [deepcopy(self._vectors[text]) for text in texts]


def _validate_texts(texts: list[str]) -> None:
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingInputError("embedding text must be non-empty")


def _validate_vector(vector: list[float], dimension: int) -> list[float]:
    if len(vector) != dimension:
        raise EmbeddingInputError("embedding vector dimension is inconsistent")
    validated: list[float] = []
    for value in vector:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise EmbeddingInputError("embedding vector values must be finite")
        validated.append(numeric)
    if not any(value != 0.0 for value in validated):
        raise EmbeddingInputError("embedding vector norm must be positive")
    return validated
