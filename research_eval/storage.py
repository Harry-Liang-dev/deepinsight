"""Exclusive durable artifacts and immutable prompt registration."""

from pathlib import Path
from typing import Any

from research_eval.models import PromptVariant, encoded, identity
from src.services.research_vnext.real_memory_meter import durable


class TraceRecorder:
    """Raw artifacts precede diagnostics; exclusive writes prevent replacement."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, data: bytes) -> None:
        """Write once within one controlled run root."""
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("ARCHIVE_PATH_ESCAPE")
        durable(path, data)

    def record(self, relative: str, value: Any) -> None:
        """Serialize program-owned audit objects deterministically."""
        self.write(relative, encoded(value))


class PromptRegistry:
    """Content-addressed candidate files, shared only through explicit ingestion."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def register(self, variant: PromptVariant) -> str:
        """Reject reuse of an existing name with different content."""
        path = self.root / (variant.variant_id + ".json")
        raw = encoded(variant)
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("IMMUTABLE_PROMPT_NAME")
        else:
            durable(path, raw)
        return identity(variant)

    def load(self, name: str) -> PromptVariant:
        """Load a registered variant, checking the self-declared hash again."""
        path = (self.root / (name + ".json")).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("PROMPT_PATH_ESCAPE")
        return PromptVariant.model_validate_json(path.read_bytes())
