"""Public five-level Memory boundary with cycle-safe lazy service exports."""

from typing import TYPE_CHECKING, Any

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
from src.schemas.memory import (
    EpisodicMemoryContentKind,
    LearningMemoryMetadata,
    LearningMemoryUsageClass,
    SemanticMemoryLifecycleStatus,
)

if TYPE_CHECKING:
    from src.memory.retrieval import ResearchContextRetrievalError
    from src.memory.service import (
        MemoryConsistencyError,
        MemoryService,
        MemoryServiceError,
        MemoryWriteError,
    )

_LAZY_EXPORTS = {
    "ResearchContextRetrievalError": (
        "src.memory.retrieval",
        "ResearchContextRetrievalError",
    ),
    "MemoryConsistencyError": ("src.memory.service", "MemoryConsistencyError"),
    "MemoryService": ("src.memory.service", "MemoryService"),
    "MemoryServiceError": ("src.memory.service", "MemoryServiceError"),
    "MemoryWriteError": ("src.memory.service", "MemoryWriteError"),
}


def __getattr__(name: str) -> Any:
    """Load runtime Memory services only when the public name is requested."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "EpisodicMemoryContentKind",
    "LearningMemoryMetadata",
    "LearningMemoryUsageClass",
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
    "SemanticMemoryLifecycleStatus",
]
