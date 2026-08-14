"""Application settings loaded from environment variables."""

from __future__ import annotations

from datetime import date
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


class LLMProviderName(StrEnum):
    """Supported live LLM provider selections."""

    OPENAI = "openai"
    QWEN = "qwen"


class LLMSettings(BaseSettings):
    """Provider-independent LLM runtime selection."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPINSIGHT_LLM_",
        extra="ignore",
    )

    provider: LLMProviderName = LLMProviderName.OPENAI


class OpenAISettings(BaseSettings):
    """OpenAI model and request settings."""

    model_config = SettingsConfigDict(
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


class QwenSettings(BaseSettings):
    """DashScope Qwen OpenAI-compatible request settings."""

    model_config = SettingsConfigDict(
        env_prefix="QWEN_",
        extra="ignore",
    )

    api_key_env: str = "QWEN_API_KEY"
    api_key: SecretStr | None = None
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=1,
    )
    model_default: str = Field(
        default="qwen3.7-flash",
        validation_alias="QWEN_MODEL_NAME",
        min_length=1,
    )
    model_fast: str = Field(
        default="qwen3.7-flash",
        validation_alias="QWEN_MODEL_NAME",
        min_length=1,
    )
    embedding_model: str = Field(default="text-embedding-v4", min_length=1)
    embedding_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=1,
    )
    embedding_dimension: int = Field(default=256, gt=0)
    embedding_batch_size: int = Field(default=10, gt=0)
    timeout_seconds: int = Field(default=90, gt=0)
    max_retries: int = Field(default=0, ge=0)
    store_remote: bool = False
    enable_thinking: bool = False


class StorageSettings(BaseSettings):
    """Local storage paths used by Phase One services."""

    model_config = SettingsConfigDict(
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
        env_prefix="DEEPINSIGHT_LOG_",
        extra="ignore",
    )

    level: LogLevel = LogLevel.INFO


class RedisSettings(BaseSettings):
    """Redis queue settings for the single Phase One Worker."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPINSIGHT_REDIS_",
        extra="ignore",
    )

    url: str = "redis://127.0.0.1:6379/0"
    report_queue_name: str = "deepinsight:report_jobs"
    poll_timeout_seconds: int = Field(default=5, ge=0)


class ProviderSettings(BaseSettings):
    """Explicit production Provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPINSIGHT_PROVIDER_",
        extra="ignore",
    )

    sec_user_agent: str | None = Field(
        default=None,
        validation_alias="DEEPINSIGHT_PROVIDER_SEC_USER_AGENT",
    )
    sec_cik_map: dict[str, str] = Field(default_factory=dict)
    sec_request_timeout_seconds: float = Field(default=30.0, gt=0)
    sec_max_retries: int = Field(default=2, ge=0, le=5)
    sec_requests_per_second: float = Field(default=5.0, gt=0, le=10)
    sec_backoff_base_seconds: float = Field(default=0.5, ge=0)
    sec_max_backoff_seconds: float = Field(default=30.0, gt=0)
    sec_max_documents: int = Field(default=1, gt=0)
    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="FRED_API_KEY",
    )
    fred_user_agent: str = Field(default="DeepInsight/0.1", min_length=1)
    fred_request_timeout_seconds: float = Field(default=30.0, gt=0)
    fred_max_retries: int = Field(default=2, ge=0, le=5)
    fred_requests_per_second: float = Field(default=2.0, gt=0)
    fred_backoff_base_seconds: float = Field(default=0.5, ge=0)
    fred_max_backoff_seconds: float = Field(default=30.0, gt=0)
    fmp_enabled: bool = Field(default=False, validation_alias="FMP_ENABLED")
    fmp_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="FMP_API_KEY",
    )
    fmp_base_url: str = Field(
        default="https://financialmodelingprep.com/stable",
        validation_alias="FMP_BASE_URL",
        pattern=r"^https://",
    )
    fmp_user_agent: str = Field(default="DeepInsight/0.1", min_length=1)
    fmp_request_timeout_seconds: float = Field(default=30.0, gt=0)
    fmp_max_retries: int = Field(default=2, ge=0, le=5)
    fmp_requests_per_second: float = Field(default=2.0, gt=0)
    alpaca_api_key_id: SecretStr | None = Field(
        default=None,
        validation_alias="APCA_API_KEY_ID",
    )
    alpaca_api_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="APCA_API_SECRET_KEY",
    )
    alpaca_api_base_url: str = Field(
        default="https://data.alpaca.markets",
        validation_alias="APCA_API_BASE_URL",
        min_length=1,
    )
    alpaca_user_agent: str = Field(default="DeepInsight/0.1", min_length=1)
    alpaca_request_timeout_seconds: float = Field(default=30.0, gt=0)
    alpaca_max_retries: int = Field(default=2, ge=0, le=5)
    alpaca_requests_per_minute: float = Field(default=180.0, gt=0, le=200)
    alpaca_backoff_base_seconds: float = Field(default=1.0, ge=0)
    alpaca_max_backoff_seconds: float = Field(default=60.0, gt=0)
    alpaca_feed: str = Field(default="iex", pattern=r"^(iex|sip)$")
    alpaca_adjustment: str = Field(
        default="raw",
        pattern=r"^(raw|split|dividend|spin-off|all)$",
    )
    alpaca_page_limit: int = Field(default=10_000, ge=1, le=10_000)
    alpaca_max_pages: int = Field(default=100, gt=0)
    alpaca_news_page_limit: int = Field(default=50, ge=1, le=50)
    alpaca_include_news_content: bool = False
    stocktwits_history_zoom: str = Field(
        default="1M",
        pattern=r"^(1D|1W|1M|3M|6M|1Y|5Y|YTD|All)$",
    )
    stocktwits_message_limit: int = Field(default=50, ge=1, le=50)
    stocktwits_max_message_pages: int = Field(default=5, gt=0)
    stocktwits_mcp_enabled: bool = Field(
        default=False,
        validation_alias="STOCKTWITS_MCP_ENABLED",
    )
    stocktwits_mcp_url: str = Field(
        default="https://mcp.stocktwits.com/mcp",
        validation_alias="STOCKTWITS_MCP_URL",
        pattern=r"^https://",
    )
    stocktwits_mcp_token_store: Path = Field(
        default=Path("data/auth/stocktwits"),
        validation_alias="STOCKTWITS_MCP_TOKEN_STORE",
    )
    stocktwits_mcp_redirect_uri: str = Field(
        default="http://127.0.0.1:8765/callback",
        validation_alias="STOCKTWITS_MCP_REDIRECT_URI",
        pattern=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?/",
    )
    stocktwits_mcp_timeout_seconds: float = Field(default=60.0, gt=0)
    stocktwits_mcp_trust_env: bool = Field(
        default=False,
        validation_alias="STOCKTWITS_MCP_TRUST_ENV",
    )


class LiveBaselineSettings(BaseSettings):
    """Explicit reproducibility settings for an opt-in live baseline."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPINSIGHT_LIVE_",
        extra="ignore",
    )

    dataset_version: str | None = None
    as_of_date: date | None = None
    data_start: date | None = None
    data_end: date | None = None
    root: Path | None = None
    evaluation_rules_version: str = "report_quality_v2"
    llm_max_retries: int = Field(default=1, ge=0, le=2)


class SchedulerSettings(BaseSettings):
    """One daily single-asset Phase One report schedule."""

    model_config = SettingsConfigDict(
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
        env_prefix="DEEPINSIGHT_WEB_",
        extra="ignore",
    )

    api_base_url: str = "http://127.0.0.1:8000"
    request_timeout_seconds: int = Field(default=10, gt=0)


class AppSettings(BaseSettings):
    """Unified settings object for the DeepInsight application."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPINSIGHT_",
        extra="ignore",
    )

    env: AppEnvironment = AppEnvironment.DEVELOPMENT
    timezone: str = "UTC"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    qwen: QwenSettings = Field(default_factory=QwenSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    live: LiveBaselineSettings = Field(default_factory=LiveBaselineSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    web: WebSettings = Field(default_factory=WebSettings)


def load_settings() -> AppSettings:
    """Load a fresh settings object from the current process environment.

    Returns:
        A fully validated application settings object.
    """

    return AppSettings()
