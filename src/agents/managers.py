"""The four Phase One synthesis and review Manager Agents."""

from __future__ import annotations

from src.agents.base import BaseAgent
from src.models.enums import AgentName
from src.schemas.agents import (
    BearManagerRequest,
    BearManagerResponse,
    BullManagerRequest,
    BullManagerResponse,
    ResearchManagerRequest,
    ResearchManagerResponse,
    RiskManagerRequest,
    RiskManagerResponse,
)


class ResearchManagerAgent(BaseAgent):
    """Synthesize analyst agreements, conflicts, and uncertainties."""

    agent_name = AgentName.RESEARCH_MANAGER
    agent_role = "manager"
    request_model = ResearchManagerRequest
    response_model = ResearchManagerResponse
    claim_list_paths = ("analysis.summary_points", "analysis.conflicts")
    response_citation_path = "analysis.supporting_citations"
    uncertainty_path = "analysis.uncertainties"


class BullManagerAgent(BaseAgent):
    """Construct the strongest evidence-bounded constructive thesis."""

    agent_name = AgentName.BULL_MANAGER
    agent_role = "manager"
    request_model = BullManagerRequest
    response_model = BullManagerResponse
    claim_list_paths = ("bull_thesis", "conditions_required", "invalidators")
    scalar_claim_paths = ("confidence",)
    inherit_input_citations = True


class BearManagerAgent(BaseAgent):
    """Construct the strongest evidence-bounded cautious thesis."""

    agent_name = AgentName.BEAR_MANAGER
    agent_role = "manager"
    request_model = BearManagerRequest
    response_model = BearManagerResponse
    claim_list_paths = ("bear_thesis", "conditions_required", "invalidators")
    scalar_claim_paths = ("confidence",)
    inherit_input_citations = True


class RiskManagerAgent(BaseAgent):
    """Challenge both theses and distinguish confirmed from scenario risk."""

    agent_name = AgentName.RISK_MANAGER
    agent_role = "manager"
    request_model = RiskManagerRequest
    response_model = RiskManagerResponse
    claim_list_paths = ("confirmed_risks", "scenario_risks", "watch_items")
    scalar_claim_paths = ("narrative_risk_score",)
    inherit_input_citations = True
