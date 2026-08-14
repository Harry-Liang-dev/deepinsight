"""The four Phase One synthesis and review Manager Agents."""

from __future__ import annotations

from typing import cast

from src.agents.base import BaseAgent
from src.agents.claim_policy import (
    CLAIM_POLICY_VERSION,
)
from src.agents.claim_policy import (
    minimum_valid_claims as configured_minimum_valid_claims,
)
from src.models.enums import AgentName, ClaimIntent
from src.models.types import DomainModel, JsonObject, JsonValue
from src.schemas.agents import (
    BearClaimResponse,
    BearDraftResponse,
    BearManagerRequest,
    BearManagerResponse,
    BullClaimResponse,
    BullDraftResponse,
    BullManagerRequest,
    BullManagerResponse,
    ResearchManagerDraftResponse,
    ResearchManagerRequest,
    ResearchManagerResponse,
    RiskManagerDraftResponse,
    RiskManagerRequest,
    RiskManagerResponse,
)


class ResearchManagerAgent(BaseAgent):
    """Synthesize analyst agreements, conflicts, and uncertainties."""

    agent_name = AgentName.RESEARCH_MANAGER
    agent_role = "manager"
    request_model = ResearchManagerRequest
    response_model = ResearchManagerResponse
    gateway_response_model = ResearchManagerDraftResponse
    claim_collection_path = "analysis.claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.RESEARCH_MANAGER)
    provenance_mode = "upstream_claims"
    claim_list_paths = ("analysis.summary_points", "analysis.conflicts")
    response_citation_path = "analysis.supporting_citations"
    claim_evidence_path = "analysis.claim_evidence"
    uncertainty_path = "analysis.uncertainties"

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble presentation lists from accepted Research Claims."""

        analysis = output.get("analysis")
        if not isinstance(analysis, dict) or "claims" not in analysis:
            return output
        draft = ResearchManagerDraftResponse.model_validate(output)
        sections: dict[str, list[JsonValue]] = {"summary_points": [], "conflicts": []}
        bindings: list[JsonValue] = []
        counters = {section: 0 for section in sections}
        for claim in draft.analysis.claims:
            section = claim.claim_path.split(".", 1)[1].split("[", 1)[0]
            index = counters[section]
            counters[section] += 1
            sections[section].append(claim.claim_text)
            bindings.append(
                {
                    **claim.model_dump(mode="json"),
                    "claim_path": f"analysis.{section}[{index}]",
                    "claim_id": claim.claim_id or f"research:{section}:{index}",
                    "claim_type": claim.claim_type or "analytical",
                    "claim_intent": ClaimIntent.ANALYTICAL_INFERENCE,
                    "status": "accepted",
                    "source_references": [],
                }
            )
        return {
            "agent_name": draft.agent_name.value,
            "status": draft.status.value,
            "analysis": {
                **sections,
                "uncertainties": cast(
                    list[JsonValue], list(draft.analysis.uncertainties)
                ),
                "supporting_citations": [],
                "claim_evidence": bindings,
            },
        }


class BullManagerAgent(BaseAgent):
    """Construct the strongest evidence-bounded constructive thesis."""

    agent_name = AgentName.BULL_MANAGER
    agent_role = "manager"
    request_model = BullManagerRequest
    response_model = BullManagerResponse
    gateway_response_model = BullDraftResponse
    claim_collection_path = "claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.BULL_MANAGER)
    provenance_mode = "upstream_claims"
    claim_list_paths = ("bull_thesis", "conditions_required", "invalidators")
    claim_evidence_path = "claim_evidence"

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim objects for the versioned role-manifest contract."""

        del input_payload
        return BullDraftResponse

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble public Bull lists and bindings from Claim objects."""

        if "claims" not in output:
            return output
        draft = BullClaimResponse.model_validate(output)
        sections: dict[str, list[JsonValue]] = {
            "bull_thesis": [],
            "conditions_required": [],
            "invalidators": [],
        }
        bindings: list[JsonValue] = []
        counters = {section: 0 for section in sections}
        for claim in draft.claims:
            section = claim.claim_path.split("[", 1)[0]
            index = counters[section]
            counters[section] += 1
            sections[section].append(claim.claim_text)
            bindings.append(
                claim.model_copy(
                    update={
                        "claim_path": f"{section}[{index}]",
                        "claim_id": claim.claim_id or f"bull:{section}:{index}",
                        "claim_type": claim.claim_type
                        or (
                            "invalidator" if section == "invalidators" else "analytical"
                        ),
                        "claim_intent": ClaimIntent.ANALYTICAL_INFERENCE,
                    }
                ).model_dump(mode="json")
            )
        return {
            **sections,
            "confidence": draft.confidence,
            "claim_evidence": bindings,
            "uncertainties": cast(list[JsonValue], list(draft.uncertainties)),
        }


class BearManagerAgent(BaseAgent):
    """Construct the strongest evidence-bounded cautious thesis."""

    agent_name = AgentName.BEAR_MANAGER
    agent_role = "manager"
    request_model = BearManagerRequest
    response_model = BearManagerResponse
    gateway_response_model = BearDraftResponse
    claim_collection_path = "claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.BEAR_MANAGER)
    provenance_mode = "upstream_claims"
    claim_list_paths = ("bear_thesis", "conditions_required", "invalidators")
    claim_evidence_path = "claim_evidence"

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim objects for the versioned role-manifest contract."""

        del input_payload
        return BearDraftResponse

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble public Bear lists and bindings from Claim objects."""

        if "claims" not in output:
            return output
        draft = BearClaimResponse.model_validate(output)
        sections: dict[str, list[JsonValue]] = {
            "bear_thesis": [],
            "conditions_required": [],
            "invalidators": [],
        }
        bindings: list[JsonValue] = []
        counters = {section: 0 for section in sections}
        for claim in draft.claims:
            section = claim.claim_path.split("[", 1)[0]
            index = counters[section]
            counters[section] += 1
            sections[section].append(claim.claim_text)
            bindings.append(
                claim.model_copy(
                    update={
                        "claim_path": f"{section}[{index}]",
                        "claim_id": claim.claim_id or f"bear:{section}:{index}",
                        "claim_type": claim.claim_type
                        or ("invalidator" if section == "invalidators" else "downside"),
                        "confidence": (
                            claim.confidence if claim.confidence is not None else 0.5
                        ),
                    }
                ).model_dump(mode="json")
            )
        return {
            **sections,
            "confidence": draft.confidence,
            "claim_evidence": bindings,
            "metadata": {},
            "uncertainties": cast(list[JsonValue], list(draft.uncertainties)),
        }

    def _attach_rejected_claims(
        self,
        output: JsonObject,
        rejected_claims: list[JsonObject],
    ) -> JsonObject:
        if not rejected_claims:
            return output
        metadata = output.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["rejected_claims"] = cast(JsonValue, rejected_claims)
        metadata["claim_policy_version"] = CLAIM_POLICY_VERSION
        output["metadata"] = metadata
        return output


class RiskManagerAgent(BaseAgent):
    """Challenge both theses and distinguish confirmed from scenario risk."""

    agent_name = AgentName.RISK_MANAGER
    agent_role = "manager"
    request_model = RiskManagerRequest
    response_model = RiskManagerResponse
    gateway_response_model = RiskManagerDraftResponse
    claim_collection_path = "claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.RISK_MANAGER)
    provenance_mode = "upstream_claims"
    claim_list_paths = ("confirmed_risks", "scenario_risks", "watch_items")
    claim_evidence_path = "claim_evidence"

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble Risk presentation lists from accepted Claims."""

        if "claims" not in output:
            return output
        draft = RiskManagerDraftResponse.model_validate(output)
        sections: dict[str, list[JsonValue]] = {
            "confirmed_risks": [],
            "scenario_risks": [],
            "watch_items": [],
        }
        bindings: list[JsonValue] = []
        counters = {section: 0 for section in sections}
        for claim in draft.claims:
            section = claim.claim_path.split("[", 1)[0]
            index = counters[section]
            counters[section] += 1
            sections[section].append(claim.claim_text)
            bindings.append(
                {
                    **claim.model_dump(mode="json"),
                    "claim_path": f"{section}[{index}]",
                    "claim_id": claim.claim_id or f"risk:{section}:{index}",
                    "claim_type": claim.claim_type or "analytical",
                    "claim_intent": ClaimIntent.ANALYTICAL_INFERENCE,
                    "status": "accepted",
                    "source_references": [],
                }
            )
        return {
            **sections,
            "narrative_risk_score": draft.narrative_risk_score,
            "claim_evidence": bindings,
            "uncertainties": cast(list[JsonValue], list(draft.uncertainties)),
        }
