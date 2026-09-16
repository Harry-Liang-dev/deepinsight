"""Offline tests for OpenAI-compatible embedding provider boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from src.core import QwenSettings
from src.services import EmbeddingConfigurationError, QwenEmbeddingService


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
    assert service.model_name == "embedding-offline"
    assert service.request_count == 1
    assert service.embedding_count == 2


def test_qwen_embedding_uses_http_transport_over_conflicting_socks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding must reuse the Chat policy for ambiguous proxy environments."""

    captured_http: dict[str, object] = {}
    captured_sdk: dict[str, object] = {}
    client = _ClientStub()

    def fake_http_client(**kwargs: object) -> object:
        captured_http.update(kwargs)
        return object()

    def fake_sdk_client(**kwargs: object) -> _ClientStub:
        captured_sdk.update(kwargs)
        return client

    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.unit.test:8080")
    monkeypatch.setenv("ALL_PROXY", "socks://proxy.unit.test:1080")
    monkeypatch.setattr(
        "src.services.provider_transport.openai.DefaultHttpxClient",
        fake_http_client,
    )
    monkeypatch.setattr("src.services.embedding.OpenAI", fake_sdk_client)
    service = QwenEmbeddingService(
        QwenSettings(api_key=SecretStr("offline-secret")),
        dimension=2,
    )

    assert cast(Any, service._get_client()) is client
    assert captured_http == {
        "proxy": "http://proxy.unit.test:8080",
        "trust_env": False,
    }
    assert captured_sdk["http_client"] is not None
    assert service.proxy_mode == "protocol_http_over_conflicting_socks"
    assert service.transport_mode == "explicit_httpx_trust_env_false"


def test_qwen_embedding_socks_only_failure_is_explicit_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported SOCKS-only transport must fail without direct fallback."""

    proxy_secret = "proxy-secret-must-not-leak"

    def unsupported_socks_client(**kwargs: object) -> object:
        del kwargs
        raise ValueError(f"Unknown SOCKS proxy scheme with {proxy_secret}")

    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv(
        "ALL_PROXY",
        f"socks://user:{proxy_secret}@proxy.unit.test:1080",
    )
    monkeypatch.setattr("src.services.embedding.OpenAI", unsupported_socks_client)
    service = QwenEmbeddingService(
        QwenSettings(api_key=SecretStr("offline-secret")),
        dimension=2,
    )

    with pytest.raises(EmbeddingConfigurationError) as raised:
        service.embed("public test text")

    error = raised.value
    assert error.code == "embedding_configuration_error"
    assert error.configuration_stage == "client_initialization"
    assert error.provider == "qwen"
    assert error.model == "text-embedding-v4"
    assert error.proxy_mode == "socks_only"
    assert error.transport_mode == "sdk_default_fail_closed"
    assert proxy_secret not in str(error)
    assert "SOCKS transport" in str(error)
    assert service.request_count == 0
    assert service.embedding_count == 0


def test_qwen_embedding_no_proxy_uses_normal_sdk_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-proxy environments must retain normal SDK construction."""

    captured: dict[str, object] = {}
    client = _ClientStub()

    def fake_sdk_client(**kwargs: object) -> _ClientStub:
        captured.update(kwargs)
        return client

    _clear_proxy_environment(monkeypatch)
    monkeypatch.setattr("src.services.embedding.OpenAI", fake_sdk_client)
    service = QwenEmbeddingService(
        QwenSettings(api_key=SecretStr("offline-secret")),
        dimension=2,
    )

    assert cast(Any, service._get_client()) is client
    assert "http_client" not in captured
    assert service.proxy_mode == "no_proxy"
    assert service.transport_mode == "sdk_default"


def _clear_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
