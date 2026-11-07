"""Reusable candidate semantics output contract, never a scientific authority."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Support = Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED"]


class Frozen(BaseModel):
    """Reject extra fields, coercions and model-generated authority fields."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Citation(Frozen):
    """Select one delivered fragment and an exact quote, not invented hashes."""

    fragment_id: Text
    quote: Text
    role: Literal["SUPPORT", "COUNTEREVIDENCE", "LIMITATION"]


class Part(Frozen):
    """A bounded proposed supported part, not permission for the parent claim."""

    text: Text
    evidence_indexes: list[int] = Field(json_schema_extra={"uniqueItems": True})


class PremiseAssessment(Frozen):
    """The model may identify premises; these remain candidate judgments."""

    statement: Text
    kind: Literal["EXPLICIT", "INFERRED_REQUIRED"]
    support_status: Support
    evidence_indexes: list[int] = Field(json_schema_extra={"uniqueItems": True})


class CounterEffect(Frozen):
    """Explain whether a counter-source changes, limits or leaves the judgment."""

    effect: Literal[
        "CHANGES_SUPPORT",
        "LIMITS_SCOPE",
        "DOES_NOT_CHANGE",
        "NOT_IDENTIFIED",
        "UNDETERMINED",
    ]
    explanation: Text


class VerifierOutput(Frozen):
    """Model-owned S/U/D only. Technical no-prediction is owned by the program."""

    case_id: Text
    support_status: Support
    observed_assertion_strength: Literal[
        "ATTRIBUTED", "DEFINITE", "CONDITIONAL", "UNKNOWN"
    ]
    evidence: list[Citation]
    supported_parts: list[Part]
    premise_assessments: list[PremiseAssessment]
    missing_necessary_premises: list[Text]
    counterevidence: CounterEffect
    reasoning: Text
    limitations: list[Text]

    @model_validator(mode="after")
    def structured_consistency(self) -> VerifierOutput:
        """Reject contradictory structure without silently changing a prediction."""
        if self.support_status == "SUPPORTED" and (
            not self.evidence or self.missing_necessary_premises
        ):
            raise ValueError(
                "SUPPORTED_WITHOUT_EVIDENCE_OR_WITH_MISSING_NECESSARY_PREMISE"
            )
        items: list[Part | PremiseAssessment] = [
            *self.supported_parts,
            *self.premise_assessments,
        ]
        for item in items:
            if any(i < 0 or i >= len(self.evidence) for i in item.evidence_indexes):
                raise ValueError("UNBOUND_EVIDENCE_INDEX")
        return self
