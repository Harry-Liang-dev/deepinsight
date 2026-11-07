"""Mechanical R9 money display and original-JSON checks; no scientific inference."""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from tools.g107_matrix import strict_object

UNITS = {0: "units", 3: "thousand", 6: "million", 9: "billion", 12: "trillion"}
_SCALE = r"(?:trillion|billion|million|thousand|bn|mn|mm|[TBMK])"
_CURRENCY = r"(?:USD|EUR|GBP|JPY|CNY|CAD|AUD|CHF|HKD)"
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT = re.compile(
    rf"(?<![\w.])(?:{_CURRENCY}\s*(?:{_SCALE}\s+)?)?[+−-]?[$€£¥]?{_NUMBER}"
    rf"(?:\s*(?:{_SCALE}(?![A-Za-z])|{_CURRENCY}(?![A-Za-z]))){{1,4}}",
    re.IGNORECASE,
)
_SCALE_TOKEN = re.compile(rf"(?<![A-Za-z]){_SCALE}(?![A-Za-z])", re.IGNORECASE)
_SCALE_VALUES = {
    "t": 12,
    "trillion": 12,
    "b": 9,
    "bn": 9,
    "billion": 9,
    "m": 6,
    "mn": 6,
    "mm": 6,
    "million": 6,
    "k": 3,
    "thousand": 3,
}


def amount_display(
    value: str,
    *,
    currency: str,
    native_scale: int,
    display_scale: int,
    decimal_places: int,
) -> dict[str, Any]:
    """Format supplied Decimal operands once; caller must independently bind source."""
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value)
        or not re.fullmatch(_CURRENCY, currency)
        or type(native_scale) is not int
        or native_scale not in UNITS
        or type(display_scale) is not int
        or display_scale not in UNITS
        or type(decimal_places) is not int
        or not 0 <= decimal_places <= 12
        or len(value) > 100
    ):
        raise ValueError("R9_INVALID_AMOUNT_COMPONENT")
    with localcontext() as ctx:
        ctx.prec = 150
        exact = Decimal(value).scaleb(native_scale - display_scale)
        rounded = exact.quantize(
            Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP
        )
    coefficient = format(rounded, f".{decimal_places}f")
    unit = UNITS[display_scale]
    return dict(
        value=coefficient,
        currency=currency,
        unit=unit,
        scale=display_scale,
        canonical_text=f"{currency} {coefficient}"
        + (f" {unit}" if display_scale else ""),
        rounding="ROUND_HALF_UP",
        decimal_places=decimal_places,
    )


def validate_amount_display(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Reject any display component mismatch, including fiscal/source binding."""

    def exact(left: Any, right: Any) -> bool:
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(
                exact(left[k], right[k]) for k in left
            )
        if isinstance(left, list):
            return len(left) == len(right) and all(
                exact(a, b) for a, b in zip(left, right, strict=True)
            )
        return bool(left == right)

    if not exact(actual, expected):
        raise ValueError("R9_AMOUNT_DISPLAY_MISMATCH")


def amount_errors(text: str) -> list[dict[str, Any]]:
    """Flag only local explicit multiple-scale/currency conflicts, without repair.

    Not a complete numeric grounder or a semantic truth test. Unicode offsets refer
    to the original decoded string; prose outside this narrow grammar stays W5-owned.
    """
    errors = []
    for match in _AMOUNT.finditer(text):
        literal = match.group()
        scales = [
            _SCALE_VALUES[t.group().lower()] for t in _SCALE_TOKEN.finditer(literal)
        ]
        currencies = set(re.findall(_CURRENCY, literal, flags=re.IGNORECASE))
        code = None
        if len(set(scales)) > 1:
            code = "R9_AMOUNT_SCALE_CONFLICT"
        elif len(scales) > 1:
            code = "R9_AMOUNT_REPEATED_SCALE"
        elif len({x.upper() for x in currencies}) > 1:
            code = "R9_AMOUNT_CURRENCY_CONFLICT"
        if code:
            errors.append(
                dict(
                    code=code,
                    unicode_start=match.start(),
                    unicode_end=match.end(),
                    original_span=literal,
                )
            )
    return errors


def prose_errors(value: Any, pointer: str = "") -> list[dict[str, Any]]:
    """Check every string value, preserving exact JSON pointer and string spans."""
    if isinstance(value, str):
        return [dict(e, json_pointer=pointer) for e in amount_errors(value)]
    if isinstance(value, dict):
        return [
            e
            for k, v in value.items()
            for e in prose_errors(
                v, pointer + "/" + str(k).replace("~", "~0").replace("/", "~1")
            )
        ]
    if isinstance(value, list):
        return [
            e for i, v in enumerate(value) for e in prose_errors(v, f"{pointer}/{i}")
        ]
    return []


def strict_json_diagnostic(text: str) -> dict[str, Any]:
    """Classify strict parser errors without extracting or retrying JSON."""
    try:
        strict_object(text)
    except json.JSONDecodeError as exc:
        stripped = text.lstrip()
        if stripped.startswith("```"):
            code = "R9_JSON_MARKDOWN_FENCE"
        elif not stripped.startswith("{"):
            code = "R9_JSON_NON_JSON_PREFIX"
        elif exc.msg == "Extra data":
            code = (
                "R9_JSON_MULTIPLE_ROOTS"
                if text[exc.pos :].lstrip().startswith("{")
                else "R9_JSON_TRAILING_CONTENT"
            )
        elif "escape" in exc.msg:
            code = "R9_JSON_INVALID_ESCAPE"
        elif exc.pos >= len(text.rstrip()):
            code = "R9_JSON_INCOMPLETE"
        else:
            code = "R9_JSON_SYNTAX"
        return dict(
            valid=False,
            errors=[
                dict(
                    code=code,
                    json_pointer="",
                    position=exc.pos,
                    line=exc.lineno,
                    column=exc.colno,
                )
            ],
        )
    except (ValueError, TypeError) as exc:
        code = (
            str(exc)
            if str(exc)
            in {"DUPLICATE_JSON_KEY", "NONFINITE_JSON_NUMBER", "JSON_ROOT_NOT_OBJECT"}
            else "JSON_INVALID"
        )
        return dict(valid=False, errors=[dict(code=code, json_pointer="")])
    return dict(valid=True, errors=[])
