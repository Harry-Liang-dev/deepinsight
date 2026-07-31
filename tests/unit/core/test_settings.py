"""Tests for application settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.settings import (
    AppEnvironment,
    AppSettings,
    LogLevel,
    StorageSettings,
    load_settings,
)


def test_default_settings_use_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default settings should be local and environment independent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = load_settings()

    assert settings.env is AppEnvironment.DEVELOPMENT
    assert settings.timezone == "UTC"
    assert settings.logging.level is LogLevel.INFO
    assert settings.openai.api_key is None
    assert not settings.storage.duckdb_path.is_absolute()
    assert not settings.storage.faiss_root.is_absolute()
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


@pytest.mark.parametrize(
    ("variable_name", "invalid_value"),
    [
        ("DEEPINSIGHT_ENV", "staging"),
        ("DEEPINSIGHT_LOG_LEVEL", "VERBOSE"),
        ("OPENAI_TIMEOUT_SECONDS", "0"),
        ("OPENAI_MAX_RETRIES", "-1"),
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
