"""Offline tests for configuration-selected live LLM providers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from src.core import (
    AppSettings,
    LLMProviderName,
    LLMSettings,
    OpenAISettings,
    QwenSettings,
)
from src.services import CredentialNotConfigured, build_configured_llm_provider


class _ResponsesStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="response-test",
            model=kwargs["model"],
            output_text=json.dumps({"status": "ok"}),
            usage=SimpleNamespace(input_tokens=5, output_tokens=2),
        )


class _ClientStub:
    def __init__(self) -> None:
        self.responses = _ResponsesStub()


def test_factory_selects_openai_by_default() -> None:
    """Default production selection should remain OpenAI."""

    client = _ClientStub()
    settings = AppSettings(openai=OpenAISettings(api_key=SecretStr("offline-secret")))

    runtime = build_configured_llm_provider(settings, client=cast(Any, client))

    assert runtime.provider_name is LLMProviderName.OPENAI
    assert runtime.provider.provider_name == "openai"
    assert runtime.model_default == settings.openai.model_default


def test_factory_selects_qwen_and_gateway_payload_extension() -> None:
    """Qwen should reuse the provider contract with its compatible extension."""

    client = _ClientStub()
    settings = AppSettings(
        llm=LLMSettings(provider=LLMProviderName.QWEN),
        qwen=QwenSettings.model_validate(
            {
                "api_key": SecretStr("offline-qwen-secret"),
                "QWEN_MODEL_NAME": "qwen-offline",
                "enable_thinking": False,
            }
        ),
    )

    runtime = build_configured_llm_provider(settings, client=cast(Any, client))
    result = runtime.provider.invoke_json(
        runtime.model_default,
        "return JSON",
        {"input": "value"},
    )

    assert runtime.provider_name is LLMProviderName.QWEN
    assert runtime.provider.provider_name == "qwen"
    assert result.content == {"status": "ok"}
    assert client.responses.calls[0]["extra_body"] == {"enable_thinking": False}
    assert "text" not in client.responses.calls[0]
    assert runtime.provider.capabilities.native_json_schema is False
    assert runtime.model_default == "qwen-offline"
    assert runtime.endpoint == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    )
    assert runtime.settings is settings.qwen


def test_qwen_without_key_fails_without_fake_fallback() -> None:
    """A selected live provider must never silently become Fake."""

    settings = AppSettings(
        llm=LLMSettings(provider=LLMProviderName.QWEN),
        qwen=QwenSettings(api_key=None),
    )
    with pytest.raises(CredentialNotConfigured) as raised:
        build_configured_llm_provider(settings)

    assert raised.value.code == "credential_not_configured"
    assert raised.value.configuration_stage == "credential_resolution"
