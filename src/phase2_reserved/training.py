"""Reserved non-operational model-training contract."""

from abc import ABC, abstractmethod

from src.models.types import JsonObject


class BaseTrainingPipeline(ABC):
    """Train future models outside the Phase One runtime."""

    @abstractmethod
    def fit(self, config: JsonObject) -> JsonObject:
        """Return future training metadata."""
        ...
