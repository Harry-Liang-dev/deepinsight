"""Reserved non-operational market-router contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseMarketRouter(ABC):
    """Select future expert routes without a Phase One implementation."""

    @abstractmethod
    def select_experts(self, context: JsonObject) -> JsonObject:
        """Return a future routing decision."""
        ...
