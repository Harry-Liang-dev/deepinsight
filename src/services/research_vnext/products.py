"""First-class unverified role products without altering original Claim gates."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from src.agents.contracts import AgentExecutionResult
from src.memory.vnext_contracts import Frozen, Role, Text
from src.models.enums import AgentName


class ResearchProduct(Frozen):
    """A conditional research product; never a validated factual assertion."""

    kind: Literal[
        "HYPOTHESIS", "RESEARCH_QUESTION", "BULL_CASE", "BEAR_CASE", "RISK_REVIEW"
    ]
    text: Text
    supporting_input_ids: tuple[Text, ...]
    counter_input_ids: tuple[Text, ...]
    missing_evidence: tuple[Text, ...]
    falsification_conditions: tuple[Text, ...] = Field(min_length=1)
    authority: Literal["UNVERIFIED_RESEARCH_NOT_FACT"] = "UNVERIFIED_RESEARCH_NOT_FACT"


class SpecialistIncrement(Frozen):
    """Original success/failure and research products remain independent."""

    schema_version: Literal["g86_specialist_increment_v1"] = (
        "g86_specialist_increment_v1"
    )
    original_result: AgentExecutionResult
    research_products: tuple[ResearchProduct, ...]
    original_claim_gate_changed: Literal[False] = False


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_RESEARCH_PRODUCT_KEY")
        result[key] = value
    return result


def specialist_increment(
    original: AgentExecutionResult,
    uncertainty_strings: tuple[str, ...],
    *,
    supplied_input_ids: frozenset[str],
) -> SpecialistIncrement:
    """Faithfully parse versioned uncertainty sidecars; never repair old output.

    These strings must come from the archived raw role response. Existing Agent
    result/error and Claim minimum remain exactly as recorded. W1 binds that
    archive at composition; this function cannot promote a sidecar to a Claim.
    """
    products = []
    ownership: dict[str, Role] = {
        "BULL_CASE": AgentName.BULL_MANAGER,
        "BEAR_CASE": AgentName.BEAR_MANAGER,
        "RISK_REVIEW": AgentName.RISK_MANAGER,
    }
    for line in uncertainty_strings:
        if not line.startswith("RESEARCH_PRODUCT:"):
            continue
        raw = json.loads(line.split(":", 1)[1], object_pairs_hook=_unique)
        product = ResearchProduct.model_validate(raw)
        if product.kind in ownership and original.agent_name != ownership[product.kind]:
            raise ValueError("RESEARCH_PRODUCT_ROLE_MISMATCH")
        if (
            not set((*product.supporting_input_ids, *product.counter_input_ids))
            <= supplied_input_ids
        ):
            raise ValueError("RESEARCH_PRODUCT_UNKNOWN_INPUT")
        products.append(product)
    return SpecialistIncrement(
        original_result=original, research_products=tuple(products)
    )
