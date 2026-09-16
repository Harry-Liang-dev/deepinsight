"""Shared semantic numeric-grounding rules for accepted research Claims."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

from src.agents.evidence import numeric_literals

NUMERIC_GROUNDING_EQUIVALENCE_VERSION = "numeric_grounding_equivalence_v1"
_MINIMUM_ROUNDED_SIGNIFICANT_DIGITS = 6
_CANONICAL_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*\d[A-Z0-9_]*(?![A-Za-z0-9_])"
)
_IDENTIFIER_DIGITS = re.compile(r"\d+")
_FORMAL_WINDOW_VALUE = re.compile(
    r"\bwindow_value\s*=\s*(\d+)\s*;?\s*window_unit\s*=\s*"
    r"(DAY|DAYS|MONTH|MONTHS|QUARTER|QUARTERS|YEAR|YEARS)\b",
    re.IGNORECASE,
)
_FORMAL_WINDOW_SHORTHAND = re.compile(
    r"\bwindow_(days|months|quarters|years)\s*=\s*(\d+)\b",
    re.IGNORECASE,
)


class NumericSemanticKind(StrEnum):
    """Meaning of a numeral found in one Claim."""

    NUMERIC_FACT = "numeric_fact"
    IDENTIFIER_COMPONENT = "identifier_component"
    STRUCTURED_METADATA_NUMBER = "structured_metadata_number"
    FORMATTED_GROUNDED_NUMBER = "formatted_grounded_number"


class NumericEvidenceEntry(Protocol):
    """Minimum Evidence surface required by the shared grounder."""

    evidence_id: str
    short_description: str
    numeric_tokens: tuple[str, ...]


@dataclass(frozen=True)
class NumericGroundingMatch:
    """One Claim numeral bound to one exact upstream Evidence entry."""

    literal: str
    kind: NumericSemanticKind
    evidence_id: str
    source_token: str


@dataclass(frozen=True)
class NumericGroundingResult:
    """Deterministic classification and provenance for Claim numerals."""

    numeric_literals: tuple[str, ...]
    identifier_components: tuple[str, ...]
    matches: tuple[NumericGroundingMatch, ...]
    ungrounded_literals: tuple[str, ...]


def validate_numeric_grounding(
    claim_text: str,
    evidence_entries: Iterable[NumericEvidenceEntry],
) -> NumericGroundingResult:
    """Validate Claim numerals against only their bound Evidence entries."""

    entries = tuple(evidence_entries)
    allowed_identifiers = _allowed_identifiers(entries)
    identifier_components: list[str] = []
    unknown_identifier_digits: list[str] = []
    for identifier_match in _CANONICAL_IDENTIFIER.finditer(claim_text):
        identifier = identifier_match.group(0)
        digits = _IDENTIFIER_DIGITS.findall(identifier)
        if identifier in allowed_identifiers:
            identifier_components.extend(digits)
        else:
            unknown_identifier_digits.extend(digits)

    literals = tuple(
        dict.fromkeys((*numeric_literals(claim_text), *unknown_identifier_digits))
    )
    matches: list[NumericGroundingMatch] = []
    ungrounded: list[str] = []
    for literal in literals:
        window_units = _claim_window_units(claim_text, literal)
        grounding_match = (
            _match_window(literal, window_units, entries)
            if window_units
            else _match_numeric_value(literal, entries)
        )
        if grounding_match is None:
            ungrounded.append(literal)
        else:
            matches.append(grounding_match)
    return NumericGroundingResult(
        numeric_literals=literals,
        identifier_components=tuple(dict.fromkeys(identifier_components)),
        matches=tuple(matches),
        ungrounded_literals=tuple(ungrounded),
    )


def _allowed_identifiers(
    entries: tuple[NumericEvidenceEntry, ...],
) -> set[str]:
    values: set[str] = set()
    for entry in entries:
        values.update(_CANONICAL_IDENTIFIER.findall(entry.evidence_id))
        values.update(_CANONICAL_IDENTIFIER.findall(entry.short_description))
    return values


def _claim_window_units(claim_text: str, literal: str) -> tuple[str, ...]:
    escaped = re.escape(literal)
    pattern = re.compile(
        rf"(?<![\w.]){escaped}\s*[- ]\s*"
        r"(day|days|month|months|quarter|quarters|year|years)\b",
        re.IGNORECASE,
    )
    return tuple(match.group(1).lower() for match in pattern.finditer(claim_text))


def _match_window(
    literal: str,
    claim_units: tuple[str, ...],
    entries: tuple[NumericEvidenceEntry, ...],
) -> NumericGroundingMatch | None:
    normalized_claim_units = {_singular(unit) for unit in claim_units}
    for entry in entries:
        for value, unit in _formal_windows(entry.short_description):
            if value == literal and _singular(unit) in normalized_claim_units:
                return NumericGroundingMatch(
                    literal=literal,
                    kind=NumericSemanticKind.STRUCTURED_METADATA_NUMBER,
                    evidence_id=entry.evidence_id,
                    source_token=value,
                )
    return None


def _formal_windows(description: str) -> tuple[tuple[str, str], ...]:
    values = [
        (match.group(1), match.group(2))
        for match in _FORMAL_WINDOW_VALUE.finditer(description)
    ]
    values.extend(
        (match.group(2), match.group(1))
        for match in _FORMAL_WINDOW_SHORTHAND.finditer(description)
    )
    return tuple(values)


def _singular(unit: str) -> str:
    normalized = unit.lower()
    return normalized[:-1] if normalized.endswith("s") else normalized


def _match_numeric_value(
    literal: str,
    entries: tuple[NumericEvidenceEntry, ...],
) -> NumericGroundingMatch | None:
    for entry in entries:
        for source_token in entry.numeric_tokens:
            if literal == source_token or _decimal_equal(literal, source_token):
                return NumericGroundingMatch(
                    literal=literal,
                    kind=NumericSemanticKind.NUMERIC_FACT,
                    evidence_id=entry.evidence_id,
                    source_token=source_token,
                )
            if _deterministic_rounding_equal(literal, source_token):
                return NumericGroundingMatch(
                    literal=literal,
                    kind=NumericSemanticKind.FORMATTED_GROUNDED_NUMBER,
                    evidence_id=entry.evidence_id,
                    source_token=source_token,
                )
    return None


def _decimal_equal(left: str, right: str) -> bool:
    if left.endswith("%") != right.endswith("%"):
        return False
    try:
        return Decimal(left.removesuffix("%")) == Decimal(right.removesuffix("%"))
    except InvalidOperation:
        return False


def _deterministic_rounding_equal(rendered: str, source: str) -> bool:
    if rendered.endswith("%") != source.endswith("%"):
        return False
    rendered_value = rendered.removesuffix("%")
    source_value = source.removesuffix("%")
    if "." not in rendered_value:
        return False
    significant_digits = len(rendered_value.lstrip("+-0").replace(".", ""))
    if significant_digits < _MINIMUM_ROUNDED_SIGNIFICANT_DIGITS:
        return False
    try:
        rendered_decimal = Decimal(rendered_value)
        source_decimal = Decimal(source_value)
    except InvalidOperation:
        return False
    if not source_decimal.is_finite() or not rendered_decimal.is_finite():
        return False
    source_exponent = source_decimal.as_tuple().exponent
    rendered_exponent = rendered_decimal.as_tuple().exponent
    if not isinstance(source_exponent, int) or not isinstance(rendered_exponent, int):
        return False
    if source_exponent >= rendered_exponent:
        return False
    quantum = Decimal(1).scaleb(rendered_exponent)
    return source_decimal.quantize(quantum) == rendered_decimal
