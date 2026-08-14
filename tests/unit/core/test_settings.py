"""Tests for application settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.settings import (
    AppEnvironment,
    AppSettings,
    LLMProviderName,
    LogLevel,
    StorageSettings,
    load_settings,
)


def test_default_settings_use_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default settings should be local and environment independent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_MODEL_NAME", raising=False)
    monkeypatch.delenv(
        "DEEPINSIGHT_PROVIDER_SEC_USER_AGENT",
        raising=False,
    )
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("STOCKTWITS_MCP_ENABLED", raising=False)
    monkeypatch.delenv("STOCKTWITS_MCP_URL", raising=False)
    monkeypatch.delenv("STOCKTWITS_MCP_TOKEN_STORE", raising=False)
    monkeypatch.delenv("STOCKTWITS_MCP_TRUST_ENV", raising=False)
    settings = load_settings()

    assert settings.env is AppEnvironment.DEVELOPMENT
    assert settings.timezone == "UTC"
    assert settings.logging.level is LogLevel.INFO
    assert settings.openai.api_key is None
    assert settings.providers.alpaca_api_key_id is None
    assert settings.providers.alpaca_api_secret_key is None
    assert settings.providers.sec_user_agent is None
    assert settings.providers.stocktwits_mcp_enabled is False
    assert settings.providers.stocktwits_mcp_url == ("https://mcp.stocktwits.com/mcp")
    assert settings.providers.stocktwits_mcp_token_store == Path("data/auth/stocktwits")
    assert settings.providers.stocktwits_mcp_trust_env is False
    assert not settings.storage.duckdb_path.is_absolute()
    assert not settings.storage.faiss_root.is_absolute()
    assert not settings.storage.raw_root.is_absolute()
    assert not settings.storage.snapshot_root.is_absolute()
    assert not settings.storage.backup_root.is_absolute()


def test_settings_read_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables should override default settings."""
    monkeypatch.setenv("DEEPINSIGHT_ENV", "test")
    monkeypatch.setenv("DEEPINSIGHT_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("DEEPINSIGHT_DUCKDB_PATH", "tmp/test.duckdb")
    monkeypatch.setenv("DEEPINSIGHT_FAISS_ROOT", "tmp/faiss")
    monkeypatch.setenv("DEEPINSIGHT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL_DEFAULT", "test-model")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("OPENAI_EMBEDDING_DIMENSION", "256")
    monkeypatch.setenv("DEEPINSIGHT_LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-secret")
    monkeypatch.setenv("QWEN_MODEL_NAME", "qwen-test-model")
    monkeypatch.setenv("QWEN_ENABLE_THINKING", "false")
    monkeypatch.setenv("DEEPINSIGHT_REDIS_URL", "redis://queue:6379/1")
    monkeypatch.setenv(
        "DEEPINSIGHT_PROVIDER_SEC_CIK_MAP",
        '{"US:AAPL":"0000320193"}',
    )
    monkeypatch.setenv(
        "DEEPINSIGHT_PROVIDER_SEC_REQUEST_TIMEOUT_SECONDS",
        "12",
    )
    monkeypatch.setenv("DEEPINSIGHT_PROVIDER_SEC_MAX_RETRIES", "1")
    monkeypatch.setenv(
        "DEEPINSIGHT_PROVIDER_SEC_REQUESTS_PER_SECOND",
        "4",
    )
    monkeypatch.setenv("APCA_API_KEY_ID", "alpaca-key-fixture")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "alpaca-secret-fixture")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://alpaca.test")
    monkeypatch.setenv(
        "DEEPINSIGHT_PROVIDER_ALPACA_REQUESTS_PER_MINUTE",
        "120",
    )
    monkeypatch.setenv("DEEPINSIGHT_PROVIDER_ALPACA_FEED", "sip")
    monkeypatch.setenv("STOCKTWITS_MCP_ENABLED", "true")
    monkeypatch.setenv("STOCKTWITS_MCP_URL", "https://stocktwits.test/mcp")
    monkeypatch.setenv("STOCKTWITS_MCP_TOKEN_STORE", "tmp/stocktwits-auth")
    monkeypatch.setenv("STOCKTWITS_MCP_TRUST_ENV", "true")
    monkeypatch.setenv(
        "STOCKTWITS_MCP_REDIRECT_URI",
        "http://localhost:9876/callback",
    )
    monkeypatch.setenv("DEEPINSIGHT_SCHEDULER_ASSET_IDS", '["US:AAPL"]')

    settings = load_settings()

    assert settings.env is AppEnvironment.TEST
    assert settings.timezone == "Asia/Shanghai"
    assert settings.storage.duckdb_path == Path("tmp/test.duckdb")
    assert settings.storage.faiss_root == Path("tmp/faiss")
    assert settings.logging.level is LogLevel.DEBUG
    assert settings.openai.api_key is not None
    assert settings.openai.api_key.get_secret_value() == "test-secret"
    assert settings.openai.model_default == "test-model"
    assert settings.openai.timeout_seconds == 15
    assert settings.openai.embedding_dimension == 256
    assert settings.llm.provider is LLMProviderName.QWEN
    assert settings.qwen.api_key is not None
    assert settings.qwen.api_key.get_secret_value() == "qwen-secret"
    assert settings.qwen.model_default == "qwen-test-model"
    assert settings.qwen.enable_thinking is False
    assert settings.redis.url == "redis://queue:6379/1"
    assert settings.providers.sec_cik_map == {"US:AAPL": "0000320193"}
    assert settings.providers.sec_request_timeout_seconds == 12
    assert settings.providers.sec_max_retries == 1
    assert settings.providers.sec_requests_per_second == 4
    assert settings.providers.alpaca_api_key_id is not None
    assert settings.providers.alpaca_api_key_id.get_secret_value() == (
        "alpaca-key-fixture"
    )
    assert settings.providers.alpaca_api_secret_key is not None
    assert settings.providers.alpaca_api_secret_key.get_secret_value() == (
        "alpaca-secret-fixture"
    )
    assert settings.providers.alpaca_api_base_url == "https://alpaca.test"
    assert settings.providers.alpaca_requests_per_minute == 120
    assert settings.providers.alpaca_feed == "sip"
    assert settings.providers.stocktwits_mcp_enabled is True
    assert settings.providers.stocktwits_mcp_url == "https://stocktwits.test/mcp"
    assert settings.providers.stocktwits_mcp_token_store == Path("tmp/stocktwits-auth")
    assert settings.providers.stocktwits_mcp_redirect_uri == (
        "http://localhost:9876/callback"
    )
    assert settings.providers.stocktwits_mcp_trust_env is True
    assert settings.scheduler.asset_ids == ["US:AAPL"]


def test_explicit_test_settings_override_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tests should be able to inject settings without global mutation."""
    monkeypatch.setenv("DEEPINSIGHT_ENV", "production")
    database_path = tmp_path / "test.duckdb"

    settings = AppSettings(
        env=AppEnvironment.TEST,
        storage=StorageSettings(duckdb_path=database_path),
    )

    assert settings.env is AppEnvironment.TEST
    assert settings.storage.duckdb_path == database_path


def test_secret_is_masked_in_settings_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sensitive values should not appear in settings representations."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    settings = load_settings()

    assert "test-secret" not in repr(settings)
    assert "**********" in repr(settings.openai.api_key)


def test_local_dotenv_file_is_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Settings must read the process environment, never a local .env file."""

    monkeypatch.delenv("DEEPINSIGHT_TIMEZONE", raising=False)
    (tmp_path / ".env").write_text(
        "DEEPINSIGHT_TIMEZONE=Asia/Shanghai\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert load_settings().timezone == "UTC"


@pytest.mark.parametrize(
    ("variable_name", "invalid_value"),
    [
        ("DEEPINSIGHT_ENV", "staging"),
        ("DEEPINSIGHT_LOG_LEVEL", "VERBOSE"),
        ("OPENAI_TIMEOUT_SECONDS", "0"),
        ("OPENAI_MAX_RETRIES", "-1"),
        ("DEEPINSIGHT_LLM_PROVIDER", "unsupported"),
        ("DEEPINSIGHT_PROVIDER_SEC_REQUESTS_PER_SECOND", "11"),
        ("DEEPINSIGHT_PROVIDER_ALPACA_REQUESTS_PER_MINUTE", "201"),
        ("DEEPINSIGHT_PROVIDER_ALPACA_FEED", "unknown"),
        ("STOCKTWITS_MCP_URL", "http://mcp.stocktwits.test/mcp"),
        ("STOCKTWITS_MCP_REDIRECT_URI", "http://external.test/callback"),
    ],
)
def test_invalid_environment_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    invalid_value: str,
) -> None:
    """Invalid environment values should fail during settings loading."""
    monkeypatch.setenv(variable_name, invalid_value)

    with pytest.raises(ValidationError):
        load_settings()
