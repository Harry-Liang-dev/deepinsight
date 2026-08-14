"""Public five-level Memory service boundary."""

from src.memory.contracts import (
    MissingContext,
    MissingContextReason,
    ResearchContextBundle,
    ResearchContextMemory,
    ResearchContextRequest,
    ResearchContextSection,
    RetrievalMetadata,
    RetrievalStatus,
)
from src.memory.retrieval import ResearchContextRetrievalError
from src.memory.service import (
    MemoryConsistencyError,
    MemoryService,
    MemoryServiceError,
    MemoryWriteError,
)

__all__ = [
    "MemoryConsistencyError",
    "MemoryService",
    "MemoryServiceError",
    "MemoryWriteError",
    "MissingContext",
    "MissingContextReason",
    "ResearchContextBundle",
    "ResearchContextMemory",
    "ResearchContextRequest",
    "ResearchContextRetrievalError",
    "ResearchContextSection",
    "RetrievalMetadata",
    "RetrievalStatus",
]
