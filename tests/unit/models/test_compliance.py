"""Regression tests for the shared deterministic claim-intent policy."""

import pytest

from src.models.compliance import claim_intent_is_allowed, infer_claim_intent
from src.models.enums import ClaimIntent
from src.schemas.agents import ClaimEvidenceBinding


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        (
            "Jefferies lowered its price target for Apple to $250.",
            ClaimIntent.THIRD_PARTY_OPINION,
        ),
        (
            "Goldman Sachs reiterated its Buy rating on Apple.",
            ClaimIntent.THIRD_PARTY_OPINION,
        ),
        (
            "Morgan Stanley raised its target price from $220 to $240.",
            ClaimIntent.THIRD_PARTY_OPINION,
        ),
    ],
)
def test_attributed_third_party_opinions_are_allowed(
    text: str,
    intent: ClaimIntent,
) -> None:
    """Attributed ratings and targets are evidence, not system advice."""

    actual = infer_claim_intent(text)
    assert actual is intent
    assert claim_intent_is_allowed(actual)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        (
            "DeepInsight recommends buying AAPL.",
            ClaimIntent.SYSTEM_RECOMMENDATION,
        ),
        ("Our price target for AAPL is $320.", ClaimIntent.SYSTEM_RECOMMENDATION),
        ("Buy AAPL at $300.", ClaimIntent.EXECUTION_INSTRUCTION),
        (
            "Allocate 20% of the portfolio to AAPL.",
            ClaimIntent.EXECUTION_INSTRUCTION,
        ),
        (
            "Short AAPL with a stop loss at $330.",
            ClaimIntent.EXECUTION_INSTRUCTION,
        ),
    ],
)
def test_system_recommendations_and_execution_instructions_are_blocked(
    text: str,
    intent: ClaimIntent,
) -> None:
    """System recommendations and execution actions remain forbidden."""

    actual = infer_claim_intent(text)
    assert actual is intent
    assert not claim_intent_is_allowed(actual)


def test_claim_intent_roundtrip() -> None:
    """Claim intent survives the authoritative binding serialization boundary."""

    binding = ClaimEvidenceBinding(
        claim_path="analysis.facts[0]",
        claim_text="Jefferies lowered its price target for Apple to $250.",
        numeric_literals=("250",),
        evidence_ids=("ev-1",),
        claim_intent=ClaimIntent.THIRD_PARTY_OPINION,
    )

    restored = ClaimEvidenceBinding.model_validate_json(binding.model_dump_json())

    assert restored == binding
    assert restored.claim_intent is ClaimIntent.THIRD_PARTY_OPINION
