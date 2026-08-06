"""Reserved non-operational backtest contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseBacktestEngine(ABC):
    """Evaluate future strategies without Phase One runtime behavior."""

    @abstractmethod
    def run(self, config: JsonObject) -> JsonObject:
        """Return future backtest metadata."""
        ...
