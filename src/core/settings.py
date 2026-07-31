"""Application settings loaded from environment variables."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Supported application runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class OpenAISettings(BaseSettings):
    """OpenAI model and request settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OPENAI_",
        extra="ignore",
    )

    api_key_env: str = "OPENAI_API_KEY"
    api_key: SecretStr | None = None
    model_default: str = "gpt-5"
    model_fast: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    timeout_seconds: int = Field(default=60, gt=0)
    max_retries: int = Field(default=3, ge=0)
    store_remote: bool = False


class StorageSettings(BaseSettings):
    """Local storage paths used by Phase One services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_",
        extra="ignore",
    )

    duckdb_path: Path = Path("data/duckdb/platform.duckdb")
    faiss_root: Path = Path("data/faiss")
    snapshot_root: Path = Path("data/snapshots")
    backup_root: Path = Path("data/backups")


class LoggingSettings(BaseSettings):
    """Application logging settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_LOG_",
        extra="ignore",
    )

    level: LogLevel = LogLevel.INFO


class AppSettings(BaseSettings):
    """Unified settings object for the DeepInsight application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_",
        extra="ignore",
    )

    env: AppEnvironment = AppEnvironment.DEVELOPMENT
    timezone: str = "UTC"
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_settings() -> AppSettings:
    """Load a fresh settings object from the current process environment.

    Returns:
        A fully validated application settings object.
    """

    return AppSettings()
