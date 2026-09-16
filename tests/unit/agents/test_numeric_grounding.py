"""Numeric Grounding Semantics v2 regressions."""

from __future__ import annotations

from src.agents.numeric_grounding import (
    NumericSemanticKind,
    validate_numeric_grounding,
)
from src.schemas.agents import RoleEvidenceManifestEntry
from src.schemas.common import SourceReference


def _entry(
    description: str,
    numeric_tokens: tuple[str, ...] = (),
    *,
    evidence_id: str = "evidence:macro",
) -> RoleEvidenceManifestEntry:
    return RoleEvidenceManifestEntry(
        evidence_id=evidence_id,
        evidence_type="structured_direct",
        source=SourceReference(document_id="doc", excerpt_ref=evidence_id),
        short_description=description,
        numeric_tokens=numeric_tokens,
    )


def test_allowed_canonical_identifier_digit_is_not_numeric_fact() -> None:
    result = validate_numeric_grounding(
        "DGS10 is rising.",
        (_entry("rates series=DGS10"),),
    )

    assert result.numeric_literals == ()
    assert result.identifier_components == ("10",)
    assert result.ungrounded_literals == ()


def test_unknown_identifier_digit_is_not_exempt() -> None:
    result = validate_numeric_grounding(
        "ABC10 is rising.",
        (_entry("rates series=DGS10"),),
    )

    assert result.numeric_literals == ("10",)
    assert result.ungrounded_literals == ("10",)


def test_identifier_does_not_ground_human_readable_tenor() -> None:
    result = validate_numeric_grounding(
        "The 10-year yield DGS10 is rising.",
        (_entry("rates series=DGS10"),),
    )

    assert result.identifier_components == ("10",)
    assert result.ungrounded_literals == ("10",)


def test_explicit_window_metadata_grounds_human_readable_window() -> None:
    result = validate_numeric_grounding(
        "The 5-day return is weak.",
        (_entry("window_value=5; window_unit=DAY"),),
    )

    assert result.ungrounded_literals == ()
    assert result.matches[0].kind is NumericSemanticKind.STRUCTURED_METADATA_NUMBER


def test_opaque_metric_key_does_not_ground_window() -> None:
    result = validate_numeric_grounding(
        "The 5-day return is weak.",
        (_entry("metric=change_5d"),),
    )

    assert result.ungrounded_literals == ("5",)


def test_deterministic_high_precision_rounding_is_grounded() -> None:
    result = validate_numeric_grounding(
        "Correlation is 0.23787131.",
        (_entry("correlation", ("0.2378713081074654",)),),
    )

    assert result.ungrounded_literals == ()
    assert result.matches[0].kind is NumericSemanticKind.FORMATTED_GROUNDED_NUMBER
    assert result.matches[0].source_token == "0.2378713081074654"


def test_decimal_rendering_normalization_preserves_same_fact() -> None:
    result = validate_numeric_grounding(
        "Coverage is 1.00.",
        (_entry("coverage", ("1",)),),
    )

    assert result.ungrounded_literals == ()
    assert result.matches[0].source_token == "1"


def test_exact_date_token_remains_grounded() -> None:
    result = validate_numeric_grounding(
        "The filing was available on 2026-07-31.",
        (_entry("filing", ("2026-07-31",)),),
    )

    assert result.ungrounded_literals == ()


def test_low_precision_rounded_value_is_rejected() -> None:
    result = validate_numeric_grounding(
        "Correlation is 0.24.",
        (_entry("correlation", ("0.2378713081074654",)),),
    )

    assert result.ungrounded_literals == ("0.24",)


def test_new_numeric_fact_is_rejected() -> None:
    result = validate_numeric_grounding(
        "Correlation is 99.9.",
        (_entry("correlation", ("0.2378713081074654",)),),
    )

    assert result.ungrounded_literals == ("99.9",)
