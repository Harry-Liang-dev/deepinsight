"""Reserved non-operational factor-mining contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseFactorMiner(ABC):
    """Propose future factors without Phase One runtime behavior."""

    @abstractmethod
    def propose_factors(self, context: JsonObject) -> list[JsonObject]:
        """Return future factor proposals."""
        ...
