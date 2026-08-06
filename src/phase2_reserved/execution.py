"""Reserved non-operational execution contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseExecutionEngine(ABC):
    """Represent a future execution boundary that Phase One cannot call."""

    @abstractmethod
    def submit(self, order_payload: JsonObject) -> JsonObject:
        """Return future execution metadata."""
        ...
