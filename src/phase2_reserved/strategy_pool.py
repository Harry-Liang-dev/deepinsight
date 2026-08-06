"""Reserved non-operational strategy-pool contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseStrategyPool(ABC):
    """Store future strategy descriptions without Phase One implementation."""

    @abstractmethod
    def register(self, strategy: JsonObject) -> JsonObject:
        """Return future strategy registration metadata."""
        ...
