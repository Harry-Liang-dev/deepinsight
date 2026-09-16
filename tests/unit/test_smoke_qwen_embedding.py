"""Offline tests for the explicit Qwen embedding smoke artifact."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_qwen_embedding
from src.services import EmbeddingConfigurationError


class _SuccessfulEmbedding:
    provider_name = "qwen"
    model_name = "text-embedding-v4"
    dimension = 2
    request_count = 0
    embedding_count = 0
    proxy_mode = "protocol_http_over_conflicting_socks"
    transport_mode = "explicit_httpx_trust_env_false"

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def embed(self, text: str) -> list[float]:
        assert "public" in text.casefold()
        self.request_count = 1
        self.embedding_count = 1
        return [1.0, 0.0]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        qwen=SimpleNamespace(
            embedding_dimension=2,
            embedding_batch_size=1,
            max_retries=0,
        )
    )


def test_embedding_smoke_persists_success_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Success artifact must identify model, dimensions, and safe transport."""

    monkeypatch.setattr(smoke_qwen_embedding, "load_settings", _settings)
    monkeypatch.setattr(
        smoke_qwen_embedding,
        "QwenEmbeddingService",
        _SuccessfulEmbedding,
    )

    assert smoke_qwen_embedding.main(["--output-root", str(tmp_path)]) == 0

    manifest_path = next(tmp_path.glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "ok"
    assert manifest["provider"] == "qwen"
    assert manifest["model"] == "text-embedding-v4"
    assert manifest["request_count"] == 1
    assert manifest["embedding_count"] == 1
    assert manifest["vector_dimension"] == 2
    assert manifest["retry_count"] == 0
    assert manifest["remote_storage"] is False
    assert manifest["transport_mode"] == "explicit_httpx_trust_env_false"


def test_embedding_smoke_persists_safe_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure artifact must retain RCA fields without proxy credentials."""

    proxy_secret = "proxy-secret-must-not-leak"

    class FailedEmbedding(_SuccessfulEmbedding):
        request_count = 0
        embedding_count = 0
        proxy_mode = "socks_only"
        transport_mode = "sdk_default_fail_closed"

        def embed(self, text: str) -> list[float]:
            del text
            raise EmbeddingConfigurationError(
                "Qwen embedding client initialization requires a supported "
                "HTTPX SOCKS transport",
                configuration_stage="client_initialization",
                provider="qwen",
                model=self.model_name,
                proxy_mode=self.proxy_mode,
                transport_mode=self.transport_mode,
            )

    monkeypatch.setenv("ALL_PROXY", f"socks://user:{proxy_secret}@proxy.invalid")
    monkeypatch.setattr(smoke_qwen_embedding, "load_settings", _settings)
    monkeypatch.setattr(
        smoke_qwen_embedding,
        "QwenEmbeddingService",
        FailedEmbedding,
    )

    assert smoke_qwen_embedding.main(["--output-root", str(tmp_path)]) == 2

    manifest_path = next(tmp_path.glob("*/manifest.json"))
    serialized = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(serialized)
    assert manifest["error_code"] == "embedding_configuration_error"
    assert manifest["configuration_stage"] == "client_initialization"
    assert manifest["provider"] == "qwen"
    assert manifest["model"] == "text-embedding-v4"
    assert manifest["proxy_mode"] == "socks_only"
    assert manifest["transport_mode"] == "sdk_default_fail_closed"
    assert manifest["request_count"] == 0
    assert proxy_secret not in serialized
