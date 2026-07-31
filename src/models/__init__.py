"""Shared domain values and module interface contracts."""

from src.models.enums import (
    AgentName,
    AgentStatus,
    DocumentType,
    EventSeverity,
    IngestionJobType,
    Market,
    MarketScope,
    MemoryLevel,
    ReportMarketScope,
    ReportType,
    TaskStatus,
)
from src.models.identifiers import AssetId
from src.models.protocols import (
    AgentProtocol,
    LLMGatewayProtocol,
    MemoryServiceProtocol,
    ProviderAdapterProtocol,
    ReportPipelineProtocol,
)
from src.models.types import DomainModel, JsonObject, JsonScalar, JsonValue

__all__ = [
    "AgentName",
    "AgentProtocol",
    "AgentStatus",
    "AssetId",
    "DocumentType",
    "DomainModel",
    "EventSeverity",
    "IngestionJobType",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "LLMGatewayProtocol",
    "Market",
    "MarketScope",
    "MemoryLevel",
    "MemoryServiceProtocol",
    "ProviderAdapterProtocol",
    "ReportPipelineProtocol",
    "ReportMarketScope",
    "ReportType",
    "TaskStatus",
]
