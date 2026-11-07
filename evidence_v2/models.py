"""Model-authored semantic proposals, separated from system-owned provenance."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Support = Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED"]
Dimension = Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED", "NOT_ASSERTED"]


class Frozen(BaseModel):
    """Forbid hidden provenance and automatic extra fields in model submissions."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Selection(Frozen):
    """Select a preissued handle, never generate quote/hash/offset/permissions."""

    handle: Text
    purpose: Literal["SUPPORT", "COUNTEREVIDENCE", "LIMITATION"]
    explanation: Text


class Subfact(Frozen):
    """Model-authored subfact; support never lifts to its causal parent."""

    statement: Text
    evidence: list[Selection]


class Premise(Frozen):
    """Preserve explicit/inferred premises and their candidate support judgments."""

    statement: Text
    origin: Literal["EXPLICIT_IN_CLAIM", "MODEL_INFERRED_NECESSARY"]
    support: Support
    required_for: Literal[
        "ORIGINAL_COMPLETE_CLAIM", "CONDITION_HOLDS", "ACTUAL_OCCURRENCE"
    ]
    evidence: list[Selection]


class Judgment(Frozen):
    """Keep theoretical possibility, condition and actual occurrence separate."""

    original_complete_claim: Support
    theoretical_mechanism: Dimension
    condition_holds: Dimension
    actual_occurrence: Dimension


class ClaimProposal(Frozen):
    """Interpretation does not replace the system-owned original claim object."""

    claim_id: Text
    interpretation: Text
    evidence: list[Selection]
    supported_subfacts: list[Subfact]
    premises: list[Premise]
    missing_necessary_premises: list[Text]
    counterevidence: list[Selection]
    judgment: Judgment
    reasoning: Text
    limitations: list[Text]
