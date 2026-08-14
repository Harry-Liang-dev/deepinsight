"""Versioned role-level policy for Claim-first producer quarantine."""

from __future__ import annotations

from typing import Final

from src.models.enums import AgentName

CLAIM_POLICY_VERSION: Final[str] = "claim_policy_v1"

# These are producer acceptance floors, not validator relaxations. Every retained
# Claim is still validated with the same exact namespace and numeric rules.
MINIMUM_VALID_CLAIMS: Final[dict[AgentName, int]] = {
    AgentName.FUNDAMENTAL_ANALYST: 2,
    AgentName.TECHNICAL_TEXT_ANALYST: 0,
    AgentName.SENTIMENT_ANALYST: 0,
    AgentName.NEWS_EVENT_ANALYST: 0,
    AgentName.RESEARCH_MANAGER: 1,
    AgentName.BULL_MANAGER: 1,
    AgentName.BEAR_MANAGER: 2,
    AgentName.RISK_MANAGER: 1,
}


def minimum_valid_claims(agent_name: AgentName) -> int:
    """Return the configured minimum retained Claims for one quarantined role."""

    return MINIMUM_VALID_CLAIMS.get(agent_name, 0)
