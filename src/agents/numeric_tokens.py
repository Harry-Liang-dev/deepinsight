"""Bounded numeric lexing: preserve whole quantities, never a valid prefix.

This is representation validation, not magnitude/unit conversion or arithmetic.
Unsupported adjacent notations survive as invalid tokens for fail-closed callers.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, DecimalException, DefaultContext

_DATE_TEXT = (
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)?"
)
_DATE = re.compile(_DATE_TEXT)
_DATE_RANGE = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})\.\.([0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?=$|[\s;,:)]|\.(?![\w.]))"
)
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?%?")
_GROUPED = re.compile(
    r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?%?"
)
_START = re.compile(
    r"(?<!\w)(?:USD|EUR|GBP|JPY|CNY|HKD)(?=[+\-−]*[0-9]|[+\-−]*\.[0-9])[+\-−]*|"
    rf"(?:(?<![\w.])|(?<=[A-Za-z])(?=[+\-−]))(?:{_DATE_TEXT}|"
    r"[+\-−]*(?:[0-9][0-9,]*(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:(?!EUR\b)[eE][+\-−]*[0-9]*)?|[+-]?(?i:NaN|sNaN|Infinity|Inf)"
    r"(?=$|[^\w]|USD\b|EUR\b|GBP\b|JPY\b|CNY\b|HKD\b))"
)
_ATTACHED = re.compile(r"(?:[\w%‰⁰¹²³⁴⁵⁶⁷⁸⁹]+|[.,]+(?=[0-9eE])|[+−][0-9]*)+")
_MAGNITUDE = re.compile(
    r"\s+(?:thousand|million|billion|trillion|bn|mn|bps?|basis points?|[kKMBT])\b",
    re.IGNORECASE,
)
_POWER = re.compile(
    r"\s*(?:[xX×*]\s*10\s*(?:\*\*|\^)?\s*[+\-−]?[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+"
    r"|[xX]\s*[+\-−]?[0-9]+|(?:\^|\*\*|[×*/])\s*[+\-−]?[0-9]*)"
)
_SPACED_EXPONENT = re.compile(r"\s+[eE](?:\s*[+\-−]\s*[0-9]*|\s*[0-9]+|(?=$|[^\w]))")
_AMBIGUOUS_GROUP = re.compile(r"(?:[ \u00a0\u202f_'’][0-9]{3})+(?![0-9])")
# These are unit delimiters only; no conversion or identifier exemption.
_ATTACHED_UNITS = frozenset({"USD", "EUR", "GBP", "JPY", "CNY", "HKD", "x", "X"})


def decimal_value(token: str) -> Decimal | None:
    """Parse a finite, complete decimal safely within Decimal's default range."""
    if not _NUMBER.fullmatch(token):
        return None
    try:
        value = Decimal(token.removesuffix("%"))
        exponent = value.as_tuple().exponent
        if (
            not value.is_finite()
            or not isinstance(exponent, int)
            or not DefaultContext.Emin <= exponent <= DefaultContext.Emax
            or not DefaultContext.Emin <= value.adjusted() <= DefaultContext.Emax
        ):
            return None
        return value
    except (DecimalException, ValueError, OverflowError):
        return None


def valid_numeric_literal(token: str) -> bool:
    """Allow an exact date token or finite supported decimal representation."""
    return bool(_DATE.fullmatch(token)) or decimal_value(token) is not None


def numeric_literals(value: str) -> tuple[str, ...]:
    """Extract complete tokens, retaining unsupported notation as invalid data.

    Only well-grouped commas normalize. A malformed exponent, magnitude suffix,
    power expression or ambiguous grouping cannot degrade to its mantissa.
    Word-prefixed identifiers/versions retain the existing nonnumeric boundary.
    """
    tokens: dict[str, None] = {}
    cursor = 0
    while match := _START.search(value, cursor):
        start, end = match.span()
        token = match.group()
        # A complete ISO date interval is two independently grounded dates,
        # not a malformed decimal. Never accept a numeric range or partial date.
        interval = _DATE_RANGE.match(value, start)
        if interval:
            try:
                for endpoint in interval.groups():
                    date.fromisoformat(endpoint)
            except ValueError:
                interval = None
        if interval:
            for endpoint in interval.groups():
                tokens.setdefault(endpoint, None)
            cursor = interval.end()
            continue
        # A comma that terminates a phrase is punctuation, not a group separator.
        if token.endswith(","):
            end -= len(token) - len(token.rstrip(","))
            token = value[start:end]
        is_date = bool(_DATE.fullmatch(token))
        if is_date:
            tail = _ATTACHED.match(value, end)
            if tail and tail.group() not in _ATTACHED_UNITS:
                end = tail.end()
                token = value[start:end]
        else:
            # Consume malformed exponent continuations (e.g. 1e-+6, 1e6.2).
            tail = _ATTACHED.match(value, end)
            if tail and tail.group() not in _ATTACHED_UNITS:
                end = tail.end()
            elif tail:
                # The following quantity still needs its own independent token.
                cursor = tail.end()
            for pattern in (_POWER, _SPACED_EXPONENT, _MAGNITUDE, _AMBIGUOUS_GROUP):
                suffix = pattern.match(value, end)
                if suffix:
                    end = suffix.end()
            token = value[start:end]
            if _GROUPED.fullmatch(token):
                token = token.replace(",", "")
        tokens.setdefault(token, None)
        cursor = max(cursor, end)
    return tuple(tokens)
