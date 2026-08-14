"""Offline structured-output parity tests for OpenAI, Qwen, and Fake."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.core.settings import OpenAISettings, QwenSettings
from src.models.types import JsonObject
from src.repositories.records import LLMCacheRecord
from src.services import (
    FakeLLMProvider,
    LLMGateway,
    LLMProvider,
    OpenAIProvider,
    QwenProvider,
)


class ParityResponse(BaseModel):
    """Strict contract shared by all provider parity cases."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)


class ResponsesStub:
    """Capture OpenAI-compatible calls without network access."""

    def __init__(self, content: JsonObject) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="response-parity",
            model=kwargs["model"],
            output_text=json.dumps(self.content),
            usage=SimpleNamespace(input_tokens=4, output_tokens=3),
        )


class ClientStub:
    """Minimal synchronous Responses client."""

    def __init__(self, responses: ResponsesStub) -> None:
        self.responses = responses


class CacheStub:
    """In-process Gateway cache for parity tests."""

    def __init__(self) -> None:
        self.records: dict[str, LLMCacheRecord] = {}

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        return self.records.get(cache_key)

    def put(self, record: LLMCacheRecord) -> None:
        self.records[record.cache_key] = record


def test_openai_adapter_uses_native_json_schema() -> None:
    """OpenAI receives strict native JSON Schema when one is requested."""

    responses = ResponsesStub({"answer": "ok", "confidence": 0.9})
    provider = OpenAIProvider(
        OpenAISettings(store_remote=True),
        client=cast(Any, ClientStub(responses)),
    )
    schema = cast(JsonObject, ParityResponse.model_json_schema(mode="validation"))

    result = provider.invoke_json(
        "openai-model",
        "return JSON",
        {"input": "value"},
        response_schema=schema,
        schema_name="ParityResponse",
    )

    assert result.content == {"answer": "ok", "confidence": 0.9}
    assert responses.calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "ParityResponse",
            "schema": schema,
            "strict": True,
        }
    }
    assert responses.calls[0]["store"] is True
    assert provider.capabilities.native_json_schema is True


def test_qwen_adapter_absorbs_missing_native_json_schema() -> None:
    """Qwen omits unsupported OpenAI text options but keeps the same contract."""

    responses = ResponsesStub({"answer": "ok", "confidence": 0.9})
    provider = QwenProvider(
        QwenSettings(api_key=SecretStr("offline-secret"), store_remote=False),
        client=cast(Any, ClientStub(responses)),
    )
    schema = cast(JsonObject, ParityResponse.model_json_schema(mode="validation"))

    result = provider.invoke_json(
        "qwen-model",
        "return JSON",
        {"input": "value"},
        response_schema=schema,
        schema_name="ParityResponse",
    )

    assert result.content == {"answer": "ok", "confidence": 0.9}
    assert "text" not in responses.calls[0]
    assert responses.calls[0]["extra_body"] == {"enable_thinking": False}
    assert responses.calls[0]["store"] is False
    assert provider.capabilities.native_json_schema is False


@pytest.mark.parametrize("provider_name", ["openai", "qwen", "fake"])
def test_gateway_returns_same_validated_shape_for_every_provider(
    provider_name: str,
) -> None:
    """Provider capability differences cannot change the Agent-facing result."""

    response: JsonObject = {"answer": "ok", "confidence": 1}
    provider: LLMProvider
    if provider_name == "fake":
        provider = FakeLLMProvider(response)
    else:
        responses = ResponsesStub(response)
        if provider_name == "openai":
            provider = OpenAIProvider(
                OpenAISettings(),
                client=cast(Any, ClientStub(responses)),
            )
        else:
            provider = QwenProvider(
                QwenSettings(api_key=SecretStr("offline-secret")),
                client=cast(Any, ClientStub(responses)),
            )
    gateway = LLMGateway(CacheStub(), provider=cast(Any, provider))

    result = gateway.invoke_json(
        "model-version",
        "return JSON",
        {"input": "value"},
        prompt_version="parity-prompt-v1",
        schema_version="parity-response-v1",
        response_model=ParityResponse,
    )

    assert result == {"answer": "ok", "confidence": 1.0}
