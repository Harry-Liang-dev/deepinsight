"""The four Phase One role-specialized analyst Agents."""

from __future__ import annotations

from src.agents.base import BaseAgent
from src.models.enums import AgentName
from src.schemas.agents import (
    AgentRequest,
    AnalystResponse,
    FundamentalAnalystResponse,
)


class FundamentalAnalystAgent(BaseAgent):
    """Interpret deterministic fundamental features and cited evidence."""

    agent_name = AgentName.FUNDAMENTAL_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = FundamentalAnalystResponse
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    scalar_claim_paths = (
        "analysis.quality_score",
        "analysis.growth_score",
        "analysis.valuation_score",
    )
    response_citation_path = "analysis.supporting_citations"
    uncertainty_path = "analysis.uncertainties"


class TechnicalTextAnalystAgent(BaseAgent):
    """Interpret deterministic technical features with text evidence."""

    agent_name = AgentName.TECHNICAL_TEXT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    uncertainty_path = "analysis.uncertainties"


class SentimentAnalystAgent(BaseAgent):
    """Analyze supplied sentiment evidence and its sampling limits."""

    agent_name = AgentName.SENTIMENT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    uncertainty_path = "analysis.uncertainties"


class NewsEventAnalystAgent(BaseAgent):
    """Analyze supplied news events and possible impact paths."""

    agent_name = AgentName.NEWS_EVENT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    uncertainty_path = "analysis.uncertainties"
