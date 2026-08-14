"""Offline tests for OpenAI-compatible embedding provider boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from pydantic import SecretStr

from src.core import QwenSettings
from src.services import QwenEmbeddingService


class _EmbeddingsStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
            ]
        )


class _ClientStub:
    def __init__(self) -> None:
        self.embeddings = _EmbeddingsStub()


def test_qwen_embedding_reuses_compatible_service_boundary() -> None:
    """Qwen embeddings should remain hidden behind EmbeddingService."""

    client = _ClientStub()
    service = QwenEmbeddingService(
        QwenSettings(
            api_key=SecretStr("offline-secret"),
            embedding_model="embedding-offline",
        ),
        dimension=2,
        batch_size=2,
        client=cast(Any, client),
    )

    assert service.embed_batch(["first", "second"]) == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    assert client.embeddings.calls == [
        {
            "input": ["first", "second"],
            "model": "embedding-offline",
            "dimensions": 2,
            "timeout": 90.0,
        }
    ]
