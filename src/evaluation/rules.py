"""Strict loading of versioned report-evaluation rules."""

from __future__ import annotations

import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.schemas.evaluation import EvaluationRuleSet

_RULE_VERSION = re.compile(r"^[a-z0-9_]+$")


class EvaluationRuleLoadError(RuntimeError):
    """Raised when one requested evaluation rule set cannot be loaded."""


class EvaluationRuleLoader:
    """Load one explicit version without falling back to another rule set."""

    def __init__(self, rule_root: Path) -> None:
        """Bind the directory containing versioned YAML rule files."""

        self._rule_root = rule_root

    def load(self, version: str) -> EvaluationRuleSet:
        """Load and validate one exact rule version."""

        if _RULE_VERSION.fullmatch(version) is None:
            raise EvaluationRuleLoadError("evaluation rule version is invalid")
        path = self._rule_root / f"{version}.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            rules = EvaluationRuleSet.model_validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError):
            raise EvaluationRuleLoadError(
                f"evaluation rules are unavailable for {version}"
            ) from None
        if rules.version != version:
            raise EvaluationRuleLoadError(
                f"evaluation rule content does not match {version}"
            )
        return rules
