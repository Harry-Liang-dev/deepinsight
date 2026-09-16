"""Neutral Sector-context usage diagnostic shared by runs and Episodes."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from src.models.enums import AgentName
from src.models.types import DomainModel


class SectorContextUsageDiagnostic(DomainModel):
    """Minimal Day36 usage trace, deliberately not an Agent trajectory."""

    sector_context_id: str = Field(pattern=r"^sector_context_[0-9a-f]{24}$")
    agent_role: AgentName
    provided_sector_claim_ids: tuple[str, ...] = ()
    used_sector_claim_ids: tuple[str, ...] = ()
    provided_event_ids: tuple[str, ...] = ()
    used_event_ids: tuple[str, ...] = ()
    serialized_context_chars: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_usage_subsets(self) -> Self:
        """Usage can only reference context actually projected to the role."""

        if not set(self.used_sector_claim_ids) <= set(self.provided_sector_claim_ids):
            raise ValueError("used Sector Claim was not provided")
        if not set(self.used_event_ids) <= set(self.provided_event_ids):
            raise ValueError("used Sector event was not provided")
        return self
