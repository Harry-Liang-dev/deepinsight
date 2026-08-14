"""Replaceable embedding boundary for documents and Memory."""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Protocol, cast

import openai
from openai import OpenAI
from openai.types import CreateEmbeddingResponse
from pydantic import SecretStr

from src.core.settings import QwenSettings


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


class _EmbeddingProviderSettings(Protocol):
    """Shared settings surface for OpenAI-compatible embedding providers."""

    api_key: SecretStr | None
    embedding_model: str
    timeout_seconds: int
    max_retries: int


class OpenAIEmbeddingService:
    """Official OpenAI Embeddings API implementation."""

    def __init__(
        self,
        settings: _EmbeddingProviderSettings,
        *,
        dimension: int,
        batch_size: int | None = None,
        base_url: str | None = None,
        provider_label: str = "OpenAI",
        client: OpenAI | _OpenAIEmbeddingClient | None = None,
    ) -> None:
        """Initialize an independently injectable embedding service.

        Args:
            settings: Existing OpenAI credential, model, and timeout settings.
            dimension: Explicit output dimension expected by FAISS.
            batch_size: Optional provider request batch limit.
            base_url: Optional OpenAI-compatible API root.
            provider_label: Safe provider name used in public errors.
            client: Optional injected client for offline tests.
        """

        if dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        if not settings.embedding_model.strip():
            raise ValueError("embedding model cannot be empty")
        if batch_size is not None and batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        self._settings = settings
        self._dimension = dimension
        self._batch_size = batch_size
        self._base_url = base_url
        self._provider_label = provider_label
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
        batches = (
            [texts]
            if self._batch_size is None
            else [
                texts[index : index + self._batch_size]
                for index in range(0, len(texts), self._batch_size)
            ]
        )
        vectors: list[list[float]] = []
        try:
            for batch in batches:
                response = self._get_client().embeddings.create(
                    input=batch,
                    model=self.model_name,
                    dimensions=self.dimension,
                    timeout=float(self._settings.timeout_seconds),
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                if len(ordered) != len(batch):
                    raise EmbeddingRemoteError(
                        "embedding provider returned an unexpected vector count"
                    )
                vectors.extend(
                    _validate_vector(item.embedding, self.dimension) for item in ordered
                )
        except openai.APITimeoutError:
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding request timed out"
            ) from None
        except openai.RateLimitError:
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding request exceeded its rate limit"
            ) from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding credentials or permissions "
                "were rejected"
            ) from None
        except openai.APIConnectionError:
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding service could not be reached"
            ) from None
        except (openai.APIStatusError, openai.APIError):
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding request failed"
            ) from None
        except EmbeddingServiceError:
            raise
        except Exception:
            raise EmbeddingRemoteError(
                f"{self._provider_label} embedding request failed"
            ) from None

        return vectors

    def _get_client(self) -> _OpenAIEmbeddingClient:
        if self._client is not None:
            return self._client
        secret = self._settings.api_key
        if secret is None or not secret.get_secret_value().strip():
            raise EmbeddingConfigurationError(
                f"{self._provider_label} API key is not configured"
            )
        try:
            if self._base_url is None:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=self._settings.max_retries,
                )
            else:
                sdk_client = OpenAI(
                    api_key=secret.get_secret_value(),
                    base_url=self._base_url,
                    timeout=float(self._settings.timeout_seconds),
                    max_retries=self._settings.max_retries,
                )
            self._client = cast(
                _OpenAIEmbeddingClient,
                sdk_client,
            )
        except Exception:
            raise EmbeddingConfigurationError(
                f"{self._provider_label} client initialization failed"
            ) from None
        return self._client


class QwenEmbeddingService(OpenAIEmbeddingService):
    """DashScope embedding implementation through the compatible boundary."""

    def __init__(
        self,
        settings: QwenSettings,
        *,
        dimension: int,
        batch_size: int | None = None,
        client: OpenAI | _OpenAIEmbeddingClient | None = None,
    ) -> None:
        """Initialize the configured DashScope embedding service.

        Args:
            settings: Validated DashScope embedding settings.
            dimension: Explicit output dimension expected by FAISS.
            batch_size: Optional provider request batch limit.
            client: Optional injected compatible client for offline tests.
        """

        super().__init__(
            settings,
            dimension=dimension,
            batch_size=batch_size,
            base_url=settings.embedding_base_url,
            provider_label="Qwen",
            client=client,
        )


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
