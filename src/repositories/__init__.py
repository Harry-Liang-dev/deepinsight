"""Public DuckDB persistence boundary for Phase One."""

from src.repositories.base import RepositoryError
from src.repositories.database import (
    DatabaseInitializationError,
    DuckDBDatabase,
)
from src.repositories.documents import DocumentRepository
from src.repositories.llm_cache import LLMCacheRepository
from src.repositories.market_data import (
    InstrumentRepository,
    MarketDataRepository,
    SourceRegistryRepository,
)
from src.repositories.memory import MemoryItemRepository
from src.repositories.records import (
    AgentRunRecord,
    IngestionJobRecord,
    LLMCacheRecord,
    MemoryItemRecord,
    SourceRegistryRecord,
)
from src.repositories.reports import ReportRepository
from src.repositories.runs import AgentRunRepository, IngestionJobRepository
from src.repositories.schema import CORE_INDEXES, CORE_TABLES

__all__ = [
    "CORE_INDEXES",
    "CORE_TABLES",
    "AgentRunRecord",
    "AgentRunRepository",
    "DatabaseInitializationError",
    "DocumentRepository",
    "DuckDBDatabase",
    "IngestionJobRecord",
    "IngestionJobRepository",
    "InstrumentRepository",
    "LLMCacheRecord",
    "LLMCacheRepository",
    "MarketDataRepository",
    "MemoryItemRecord",
    "MemoryItemRepository",
    "ReportRepository",
    "RepositoryError",
    "SourceRegistryRecord",
    "SourceRegistryRepository",
]
