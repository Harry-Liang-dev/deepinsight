"""Central Phase One domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    """Supported equity markets."""

    CN = "CN"
    HK = "HK"
    US = "US"


class MarketScope(StrEnum):
    """Supported data and report market scopes."""

    CN = "CN"
    HK = "HK"
    US = "US"
    GLOBAL = "GLOBAL"
    MIXED = "MIXED"


class ReportMarketScope(StrEnum):
    """Market scopes accepted by the report API."""

    CN = "CN"
    HK = "HK"
    US = "US"
    MIXED = "MIXED"


class MemoryLevel(StrEnum):
    """Five-level global memory hierarchy."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class ReportType(StrEnum):
    """Phase One report types declared by the report API."""

    SINGLE_ASSET = "single_asset"
    MARKET_DAILY = "market_daily"
    WATCHLIST = "watchlist"
    MACRO_WEEKLY = "macro_weekly"


class DocumentType(StrEnum):
    """Text document categories stored by the data layer."""

    FILING = "filing"
    NEWS = "news"
    RESEARCH = "research"
    MACRO = "macro"
    SOCIAL = "social"
    POLICY = "policy"


class AgentName(StrEnum):
    """Phase One analyst and manager agent names."""

    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    TECHNICAL_TEXT_ANALYST = "technical_text_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    NEWS_EVENT_ANALYST = "news_event_analyst"
    RESEARCH_MANAGER = "research_manager"
    BULL_MANAGER = "bull_manager"
    BEAR_MANAGER = "bear_manager"
    RISK_MANAGER = "risk_manager"


class AgentStatus(StrEnum):
    """Agent or operation result status."""

    OK = "ok"
    ERROR = "error"


class TaskStatus(StrEnum):
    """Background job and report lifecycle status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJobType(StrEnum):
    """Supported data ingestion modes."""

    FULL = "full"
    INCREMENTAL = "incremental"
    REPAIR = "repair"


class EventSeverity(StrEnum):
    """Corporate event severity values."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
