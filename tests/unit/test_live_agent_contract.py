"""Offline tests for the fixed live Agent Contract gate semantics."""

from __future__ import annotations

from scripts.live_agent_contract import _AGENT_CLASSES, _pre_risk_gate_passed
from src.agents.contracts import AgentExecutionResult
from src.models.enums import AgentName, AgentStatus
from src.schemas.common import ErrorInfo


def _result(role: AgentName, status: AgentStatus) -> AgentExecutionResult:
    """Build the smallest valid result envelope for gate testing."""

    if status is AgentStatus.OK:
        return AgentExecutionResult(
            run_id=f"run:{role.value}",
            agent_name=role,
            status=status,
            output={"status": "ok"},
        )
    return AgentExecutionResult(
        run_id=f"run:{role.value}",
        agent_name=role,
        status=status,
        error=ErrorInfo(code="schema_validation", message="safe failure"),
    )


def test_risk_is_not_allowed_when_any_pre_risk_agent_failed() -> None:
    """One failed prerequisite must short-circuit the Risk invocation."""

    results = {role: _result(role, AgentStatus.OK) for role in _AGENT_CLASSES}
    results[AgentName.NEWS_EVENT_ANALYST] = _result(
        AgentName.NEWS_EVENT_ANALYST,
        AgentStatus.ERROR,
    )

    assert not _pre_risk_gate_passed(results)


def test_risk_is_allowed_only_after_all_seven_agents_pass() -> None:
    """The complete seven-role prerequisite set unlocks the Risk invocation."""

    results = {role: _result(role, AgentStatus.OK) for role in _AGENT_CLASSES}

    assert len(results) == 7
    assert _pre_risk_gate_passed(results)
