"""Versioned prompt loading from explicit configuration files."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.agents.contracts import PromptTemplate
from src.models.enums import AgentName


class PromptLoadError(RuntimeError):
    """Raised when a configured prompt is missing or invalid."""


class PromptLoader:
    """Load strict, versioned Agent prompts from one injected directory."""

    def __init__(self, prompt_root: Path) -> None:
        """Initialize the loader without reading files eagerly.

        Args:
            prompt_root: Directory containing ``<agent_name>.yaml`` files.
        """

        self._prompt_root = prompt_root

    def load(self, agent_name: AgentName) -> PromptTemplate:
        """Load and validate one Agent prompt.

        Args:
            agent_name: Closed Phase One Agent identifier.

        Returns:
            Validated prompt name, version, and system text.

        Raises:
            PromptLoadError: If the file is missing, unreadable, or invalid.
        """

        path = self._prompt_root / f"{agent_name.value}.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            prompt = PromptTemplate.model_validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError):
            raise PromptLoadError(
                f"prompt configuration is unavailable for {agent_name.value}"
            ) from None
        if prompt.name is not agent_name:
            raise PromptLoadError(
                f"prompt configuration name does not match {agent_name.value}"
            )
        if not prompt.version.strip() or not prompt.system_prompt.strip():
            raise PromptLoadError(
                f"prompt configuration is blank for {agent_name.value}"
            )
        return prompt
