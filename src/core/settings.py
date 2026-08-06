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
    embedding_dimension: int = Field(default=1536, gt=0)
    embedding_batch_size: int = Field(default=20, gt=0)
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
    raw_root: Path = Path("data/raw")
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


class RedisSettings(BaseSettings):
    """Redis queue settings for the single Phase One Worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_REDIS_",
        extra="ignore",
    )

    url: str = "redis://127.0.0.1:6379/0"
    report_queue_name: str = "deepinsight:report_jobs"
    poll_timeout_seconds: int = Field(default=5, ge=0)


class ProviderSettings(BaseSettings):
    """Explicit production Provider configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_PROVIDER_",
        extra="ignore",
    )

    sec_user_agent: str | None = None
    sec_cik_map: dict[str, str] = Field(default_factory=dict)


class SchedulerSettings(BaseSettings):
    """One daily single-asset Phase One report schedule."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_SCHEDULER_",
        extra="ignore",
    )

    enabled: bool = False
    report_hour_utc: int = Field(default=7, ge=0, le=23)
    report_minute_utc: int = Field(default=0, ge=0, le=59)
    asset_ids: list[str] = Field(default_factory=lambda: ["US:AAPL"])


class WebSettings(BaseSettings):
    """Read-only report Web application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPINSIGHT_WEB_",
        extra="ignore",
    )

    api_base_url: str = "http://127.0.0.1:8000"
    request_timeout_seconds: int = Field(default=10, gt=0)


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
    redis: RedisSettings = Field(default_factory=RedisSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    web: WebSettings = Field(default_factory=WebSettings)


def load_settings() -> AppSettings:
    """Load a fresh settings object from the current process environment.

    Returns:
        A fully validated application settings object.
    """

    return AppSettings()
