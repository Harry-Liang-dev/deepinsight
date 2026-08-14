"""Single deterministic policy for research-claim trading compliance."""

from __future__ import annotations

import re

from src.models.enums import ClaimIntent

_THIRD_PARTY_ATTRIBUTION = re.compile(
    r"\b(?:analysts?|brokers?|banks?|media|jefferies|goldman(?:\s+sachs)?|"
    r"morgan\s+stanley|jpmorgan|ubs|barclays|citigroup|citi|bofa|"
    r"deutsche\s+bank|wells\s+fargo)\b",
    re.IGNORECASE,
)
_THIRD_PARTY_OPINION = re.compile(
    r"\b(?:price\s+target|target\s+price|(?:buy|sell|hold|underperform|"
    r"outperform|overweight|underweight)\s+rating|rated|downgraded|"
    r"upgraded|reiterated|maintained)\b",
    re.IGNORECASE,
)
_SYSTEM_RECOMMENDATION = re.compile(
    r"\b(?:deepinsight|we|our)\s+(?:recommends?|recommend|suggests?|"
    r"suggest|rates?|rate|sets?|set|assigns?|assign|has|have)\b",
    re.IGNORECASE,
)
_USER_ACTION_RECOMMENDATION = re.compile(
    r"\b(?:investors?|users?|you)\s+should\s+(?:buy|sell|short|allocate|"
    r"enter|exit)\b",
    re.IGNORECASE,
)
_IMPERATIVE_EXECUTION = re.compile(
    r"(?:^|[.!?]\s+|\n)(?:[-*]\s*)?"
    r"(?:buy|sell|short|allocate|enter|exit|place|execute|"
    r"submit)\b",
    re.IGNORECASE,
)
_ORDER_OR_POSITION = re.compile(
    r"\b(?:allocate\s+\d+(?:\.\d+)?%|position\s+size|stop[- ]loss|"
    r"(?:place|execute|submit)\s+(?:an?\s+)?(?:buy|sell|market|limit)?"
    r"\s*order)\b",
    re.IGNORECASE,
)
_TARGET_PRICE = re.compile(r"\b(?:price\s+target|target\s+price)\b", re.IGNORECASE)
_CHINESE_PROHIBITED = re.compile(r"(?:买入|卖出|做空|目标价|仓位|下单|止损)")


def infer_claim_intent(
    text: str,
    *,
    analytical: bool = False,
) -> ClaimIntent:
    """Classify claim intent without treating attributed opinions as advice."""

    normalized = text.strip()
    if (
        _IMPERATIVE_EXECUTION.search(normalized)
        or _ORDER_OR_POSITION.search(normalized)
        or _CHINESE_PROHIBITED.search(normalized)
    ):
        return ClaimIntent.EXECUTION_INSTRUCTION
    if _SYSTEM_RECOMMENDATION.search(normalized) or _USER_ACTION_RECOMMENDATION.search(
        normalized
    ):
        return ClaimIntent.SYSTEM_RECOMMENDATION
    if _TARGET_PRICE.search(normalized) and not _THIRD_PARTY_ATTRIBUTION.search(
        normalized
    ):
        return ClaimIntent.SYSTEM_RECOMMENDATION
    if _THIRD_PARTY_ATTRIBUTION.search(normalized) and _THIRD_PARTY_OPINION.search(
        normalized
    ):
        return ClaimIntent.THIRD_PARTY_OPINION
    if analytical:
        return ClaimIntent.ANALYTICAL_INFERENCE
    return ClaimIntent.FACT


def claim_intent_is_allowed(intent: ClaimIntent) -> bool:
    """Return whether one intent is allowed in the current research phase."""

    return intent not in {
        ClaimIntent.SYSTEM_RECOMMENDATION,
        ClaimIntent.EXECUTION_INSTRUCTION,
    }


def prohibited_claim_intent(text: str) -> ClaimIntent | None:
    """Return the prohibited intent in text, if any."""

    intent = infer_claim_intent(text)
    return None if claim_intent_is_allowed(intent) else intent


def prohibited_narrative_intent(text: str) -> ClaimIntent | None:
    """Audit rendered narrative line by line through the same intent policy."""

    for line in text.splitlines():
        intent = prohibited_claim_intent(line)
        if intent is not None:
            return intent
    return None
