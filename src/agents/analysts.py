"""The four Phase One role-specialized analyst Agents."""

from __future__ import annotations

from typing import cast

from src.agents.base import BaseAgent
from src.agents.claim_policy import (
    CLAIM_POLICY_VERSION,
)
from src.agents.claim_policy import (
    minimum_valid_claims as configured_minimum_valid_claims,
)
from src.agents.evidence import numeric_literals
from src.models.enums import AgentName
from src.models.types import DomainModel, JsonObject, JsonValue
from src.schemas.agents import (
    AgentRequest,
    AnalystClaimAnalysis,
    AnalystResponse,
    FundamentalAnalystResponse,
    FundamentalClaimResponse,
    FundamentalDraftResponse,
    FundamentalNormalizedScores,
    NewsClaimResponse,
    NewsDraftResponse,
    RoleEvidenceManifest,
    SentimentClaimResponse,
    SentimentDraftResponse,
    TechnicalClaimResponse,
    TechnicalDraftResponse,
)

_FUNDAMENTAL_CLAIM_GROUPS = (
    ("Growth", ("fundamentals.revenue_yoy", "fundamentals.net_income_yoy")),
    (
        "Margins",
        (
            "fundamentals.gross_margin",
            "fundamentals.operating_margin",
            "fundamentals.net_margin",
        ),
    ),
    ("Profitability", ("fundamentals.roe", "fundamentals.roa")),
    (
        "Balance Sheet and Liquidity",
        ("fundamentals.debt_to_equity", "fundamentals.current_ratio"),
    ),
    (
        "Valuation",
        (
            "fundamentals.eps_ttm",
            "fundamentals.book_value_per_share",
            "fundamentals.market_cap",
            "fundamentals.pe_ttm",
            "fundamentals.pb",
            "fundamentals.earnings_yield",
        ),
    ),
)

_MACRO_CLAIM_GROUPS = (
    (
        "Rates",
        (
            "macro_indicators.fed_funds",
            "macro_indicators.yield_2y",
            "macro_indicators.yield_10y",
            "macro_indicators.yield_spread_10y2y",
        ),
    ),
    ("Inflation", ("macro_indicators.cpi", "macro_indicators.core_pce")),
    (
        "Labor",
        ("macro_indicators.unemployment", "macro_indicators.payrolls"),
    ),
    (
        "Growth",
        ("macro_indicators.gdp", "macro_indicators.industrial_production"),
    ),
    (
        "Financial Stress",
        ("macro_indicators.vix", "macro_indicators.high_yield_spread"),
    ),
)

_TECHNICAL_CLAIM_GROUPS = (
    (
        "Trend",
        (
            "technical_features.trend_label",
            "technical_features.sma_20",
            "technical_features.sma_60",
        ),
    ),
    (
        "Momentum",
        (
            "technical_features.return_20d",
            "technical_features.rsi_14",
            "technical_features.macd",
        ),
    ),
    (
        "Volatility",
        (
            "technical_features.realized_vol_20d",
            "technical_features.realized_vol_60d",
            "technical_features.atr_14",
        ),
    ),
    ("Volume", ("technical_features.volume_ratio_20d",)),
    (
        "Relative Strength",
        (
            "technical_features.relative_strength_vs_spy",
            "technical_features.relative_strength_vs_qqq",
            "technical_features.relative_strength_vs_xlk",
        ),
    ),
    ("Drawdown", ("technical_features.max_drawdown_60d",)),
)


class FundamentalAnalystAgent(BaseAgent):
    """Interpret deterministic fundamental features and cited evidence."""

    agent_name = AgentName.FUNDAMENTAL_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = FundamentalAnalystResponse
    gateway_response_model = FundamentalDraftResponse
    claim_collection_path = "analysis.claims"
    minimum_valid_claims = configured_minimum_valid_claims(
        AgentName.FUNDAMENTAL_ANALYST
    )
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
    claim_evidence_path = "analysis.claim_evidence"
    uncertainty_path = "analysis.uncertainties"

    def _quarantine_inference_output(
        self,
        input_payload: JsonObject,
        raw_output: JsonObject,
    ) -> tuple[JsonObject, list[JsonObject]]:
        """Promote provider-standardized facts before strict local validation."""

        enriched = _append_deterministic_manifest_claims(
            input_payload,
            raw_output,
            groups=_FUNDAMENTAL_CLAIM_GROUPS,
            claim_id_prefix="fundamental:canonical",
        )
        return super()._quarantine_inference_output(input_payload, enriched)

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim-first Fundamental schema for role-manifest calls."""

        context = input_payload.get("input_context")
        if isinstance(context, dict) and context.get("role_evidence_manifest"):
            return FundamentalDraftResponse
        return self.response_model

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble legacy public fields from the authoritative Claim collection."""

        analysis = output.get("analysis")
        if not isinstance(analysis, dict) or "claims" not in analysis:
            return output
        draft = FundamentalClaimResponse.model_validate(output)
        sections: dict[str, list[JsonValue]] = {
            "facts": [],
            "key_points": [],
            "risk_points": [],
        }
        bindings: list[JsonValue] = []
        counters = {section: 0 for section in sections}
        for claim in draft.analysis.claims:
            section = claim.claim_path.split(".", 1)[1].split("[", 1)[0]
            index = counters[section]
            counters[section] += 1
            sections[section].append(claim.claim_text)
            bindings.append(
                claim.model_copy(
                    update={
                        "claim_path": f"analysis.{section}[{index}]",
                        "claim_id": claim.claim_id or f"fundamental:{section}:{index}",
                        "confidence": (
                            claim.confidence if claim.confidence is not None else 0.5
                        ),
                        "claim_type": claim.claim_type or "factual",
                    }
                ).model_dump(mode="json")
            )
        scores: FundamentalNormalizedScores = draft.analysis.normalized_scores
        return {
            "agent_name": draft.agent_name.value,
            "status": draft.status.value,
            "analysis": {
                "quality_score": scores.quality_score,
                "growth_score": scores.growth_score,
                "valuation_score": scores.valuation_score,
                **sections,
                "uncertainties": list(draft.analysis.uncertainties),
                "supporting_citations": [],
                "claim_evidence": bindings,
                "metadata": {
                    **draft.analysis.metadata,
                    "score_metadata": {
                        key: value.model_dump(mode="json")
                        for key, value in scores.metadata.items()
                    },
                },
            },
        }

    def _attach_rejected_claims(
        self,
        output: JsonObject,
        rejected_claims: list[JsonObject],
    ) -> JsonObject:
        if not rejected_claims:
            return output
        analysis = output.get("analysis")
        if not isinstance(analysis, dict):
            return output
        metadata = analysis.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["rejected_claims"] = cast(JsonValue, rejected_claims)
        metadata["claim_policy_version"] = CLAIM_POLICY_VERSION
        analysis["metadata"] = metadata
        return output


class TechnicalTextAnalystAgent(BaseAgent):
    """Interpret deterministic technical features with text evidence."""

    agent_name = AgentName.TECHNICAL_TEXT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    gateway_response_model = TechnicalDraftResponse
    claim_collection_path = "analysis.claims"
    minimum_valid_claims = configured_minimum_valid_claims(
        AgentName.TECHNICAL_TEXT_ANALYST
    )
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    claim_evidence_path = "analysis.claim_evidence"
    uncertainty_path = "analysis.uncertainties"

    def _quarantine_inference_output(
        self,
        input_payload: JsonObject,
        raw_output: JsonObject,
    ) -> tuple[JsonObject, list[JsonObject]]:
        """Promote deterministic technical categories before validation."""

        enriched = _append_deterministic_manifest_claims(
            input_payload,
            raw_output,
            groups=_TECHNICAL_CLAIM_GROUPS,
            claim_id_prefix="technical:canonical",
        )
        return super()._quarantine_inference_output(input_payload, enriched)

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim objects for the versioned role-manifest contract."""

        context = input_payload.get("input_context")
        if isinstance(context, dict) and context.get("role_evidence_manifest"):
            return TechnicalDraftResponse
        return AnalystResponse

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble public Technical prose and bindings from Claim objects."""

        return _normalize_claim_response(output, TechnicalClaimResponse)


class SentimentAnalystAgent(BaseAgent):
    """Analyze supplied sentiment evidence and its sampling limits."""

    agent_name = AgentName.SENTIMENT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    gateway_response_model = SentimentDraftResponse
    claim_collection_path = "analysis.claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.SENTIMENT_ANALYST)
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    claim_evidence_path = "analysis.claim_evidence"
    uncertainty_path = "analysis.uncertainties"

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim objects for the versioned role-manifest contract."""

        context = input_payload.get("input_context")
        if isinstance(context, dict) and context.get("role_evidence_manifest"):
            return SentimentDraftResponse
        return AnalystResponse

    def _inference_input_payload(self, input_payload: JsonObject) -> JsonObject:
        """Hide non-evidentiary source locators from Sentiment generation."""

        projected = super()._inference_input_payload(input_payload)
        context = projected.get("input_context")
        if not isinstance(context, dict):
            return projected
        manifest = context.get("role_evidence_manifest")
        if not isinstance(manifest, dict):
            return projected
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            return projected
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            if isinstance(source, dict):
                source.pop("document_id", None)
                source.pop("excerpt_ref", None)
                source.pop("source_url", None)
        return projected

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble public prose and bindings from validated Claim objects."""

        return _normalize_claim_response(output, SentimentClaimResponse)


class NewsEventAnalystAgent(BaseAgent):
    """Analyze supplied news events and possible impact paths."""

    agent_name = AgentName.NEWS_EVENT_ANALYST
    agent_role = "analyst"
    request_model = AgentRequest
    response_model = AnalystResponse
    gateway_response_model = NewsDraftResponse
    claim_collection_path = "analysis.claims"
    minimum_valid_claims = configured_minimum_valid_claims(AgentName.NEWS_EVENT_ANALYST)
    claim_list_paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
    )
    response_citation_path = "analysis.supporting_citations"
    claim_evidence_path = "analysis.claim_evidence"
    uncertainty_path = "analysis.uncertainties"

    def _quarantine_inference_output(
        self,
        input_payload: JsonObject,
        raw_output: JsonObject,
    ) -> tuple[JsonObject, list[JsonObject]]:
        """Promote the canonical MacroSnapshot into attributable facts."""

        enriched = _append_deterministic_manifest_claims(
            input_payload,
            raw_output,
            groups=_MACRO_CLAIM_GROUPS,
            claim_id_prefix="news_event:macro",
        )
        return super()._quarantine_inference_output(input_payload, enriched)

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Use Claim objects for the versioned role-manifest contract."""

        context = input_payload.get("input_context")
        if isinstance(context, dict) and context.get("role_evidence_manifest"):
            return NewsDraftResponse
        return AnalystResponse

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Assemble public News/Event prose and bindings from Claim objects."""

        return _normalize_claim_response(output, NewsClaimResponse)


def _normalize_claim_response(
    output: JsonObject,
    response_model: (
        type[TechnicalClaimResponse]
        | type[SentimentClaimResponse]
        | type[NewsClaimResponse]
    ),
) -> JsonObject:
    """Build one public Analyst response from authoritative Claim objects."""

    analysis = output.get("analysis")
    if not isinstance(analysis, dict) or "claims" not in analysis:
        return output
    draft = response_model.model_validate(output)
    claim_analysis: AnalystClaimAnalysis = draft.analysis
    sections: dict[str, list[JsonValue]] = {
        "facts": [],
        "key_points": [],
        "risk_points": [],
    }
    bindings: list[JsonValue] = []
    counters = {section: 0 for section in sections}
    for claim in claim_analysis.claims:
        section = claim.claim_path.split(".", 1)[1].split("[", 1)[0]
        index = counters[section]
        counters[section] += 1
        sections[section].append(claim.claim_text)
        bindings.append(
            claim.model_copy(
                update={
                    "claim_path": f"analysis.{section}[{index}]",
                    "claim_id": claim.claim_id
                    or f"{draft.agent_name.value}:{section}:{index}",
                    "confidence": (
                        claim.confidence if claim.confidence is not None else 0.5
                    ),
                    "claim_type": claim.claim_type or "factual",
                }
            ).model_dump(mode="json")
        )
    return {
        "agent_name": draft.agent_name.value,
        "status": draft.status.value,
        "analysis": {
            **sections,
            "uncertainties": list(claim_analysis.uncertainties),
            "supporting_citations": [],
            "claim_evidence": bindings,
        },
    }


def _append_deterministic_manifest_claims(
    input_payload: JsonObject,
    raw_output: JsonObject,
    *,
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    claim_id_prefix: str,
) -> JsonObject:
    """Add exact canonical Evidence descriptions as deterministic facts.

    Provider-standardized metrics and MacroSnapshot observations are already
    computed outside the LLM. Their factual projection must not depend on a
    model preserving numeric formatting. The appended Claims still traverse
    the unchanged Evidence-ID and exact-literal validator.
    """

    context = input_payload.get("input_context")
    if not isinstance(context, dict):
        return raw_output
    manifest_payload = context.get("role_evidence_manifest")
    if not isinstance(manifest_payload, dict):
        return raw_output
    manifest = RoleEvidenceManifest.model_validate(manifest_payload)
    by_path = {
        entry.short_description.split(" ", 1)[0]: entry for entry in manifest.entries
    }
    selected_ids = {
        by_path[path].evidence_id
        for _, paths in groups
        for path in paths
        if path in by_path
    }

    analysis_value = raw_output.get("analysis")
    if not isinstance(analysis_value, dict):
        return raw_output
    claims_value = analysis_value.get("claims")
    if not isinstance(claims_value, list):
        return raw_output
    retained: list[JsonObject] = []
    for item in claims_value:
        if not isinstance(item, dict):
            continue
        raw_ids = item.get("evidence_ids")
        item_ids = (
            {value for value in raw_ids if isinstance(value, str)}
            if isinstance(raw_ids, list)
            else set()
        )
        if not selected_ids.intersection(item_ids):
            retained.append(dict(item))
    next_index = 1 + max(
        (
            int(path.rsplit("[", 1)[1][:-1])
            for item in retained
            if isinstance((path := item.get("claim_path")), str)
            and path.startswith("analysis.facts[")
        ),
        default=-1,
    )
    for label, paths in groups:
        entries = [by_path[path] for path in paths if path in by_path]
        if not entries:
            continue
        text = f"{label}: " + "; ".join(entry.short_description for entry in entries)
        retained.append(
            {
                "claim_id": f"{claim_id_prefix}:{label.lower().replace(' ', '_')}",
                "claim_type": "factual",
                "claim_intent": "fact",
                "claim_path": f"analysis.facts[{next_index}]",
                "claim_text": text,
                "numeric_literals": list(numeric_literals(text)),
                "evidence_ids": [entry.evidence_id for entry in entries],
                "upstream_claim_ids": [],
            }
        )
        next_index += 1

    normalized = dict(raw_output)
    analysis = dict(analysis_value)
    analysis["claims"] = cast(JsonValue, retained)
    normalized["analysis"] = analysis
    return normalized
