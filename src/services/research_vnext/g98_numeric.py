"""Opt-in disclosure magnitudes via the existing G92 trusted-binding protocol.

These are prose disclosure quantities, NOT invented Inline XBRL proofs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from src.agents.numeric_grounding import (
    NumericEvidenceEntry,
    NumericGroundingMatch,
    NumericSemanticKind,
)
from src.agents.numeric_tokens import numeric_literals
from src.schemas.research_v2_shared import Frozen, digest
from src.services.research_vnext.g97_sources import AVGOSources
from src.services.research_vnext.native_numeric_binding import scaled_decimal

_MONEY = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(billion|B)\b(?:\s+USD\b)?|\b(\d+(?:\.\d+)?)\s*(billion|B)\s+USD\b"
)


class QuantityReference(Frozen):
    """Model fields checked against one frozen disclosure-local fact, never guessed."""

    fact_id: str
    evidence_id: str
    issuer: Literal["US:AVGO"]
    metric: str
    facility: str
    period: str
    unit: str
    lexical: str
    value: Decimal
    date_role: Literal["NOT_DATE", "REPORT_PERIOD", "PUBLICATION_DATE"] = "NOT_DATE"


@dataclass(frozen=True)
class DisclosureAspect:
    """Source-only exact Decimal and semantic identity, separate from SEC iXBRL."""

    fact_id: str
    evidence_id: str
    metric: str
    facility: str
    period: str
    unit: str | None
    value: Decimal | None
    source_sha256: str
    receipt: str
    quote: str


def amount(lexical: str) -> Decimal:
    """Accept explicit USD/$ billion notation only; no contextual currency guess."""
    match = _MONEY.fullmatch(lexical)
    if match is None:
        raise ValueError("G98_EXPLICIT_USD_MAGNITUDE_REQUIRED")
    return scaled_decimal(match[1] or match[3], 9, "")


def surface(text: str) -> str:
    """Canonicalize only explicit supported USD amounts, preserving all other text."""
    return _MONEY.sub(
        lambda m: "<USD:" + str(amount(m.group()).normalize()) + ">", text
    )


class DisclosureNumericBinding:
    """Reverify pinned source bytes and cited chunk identity before every match."""

    def __init__(self, source: AVGOSources, root: Path) -> None:
        self.source, self.root, self.at = source, root, source.at
        self.pin = digest(source.projection())
        self.aspects = MappingProxyType(self._aspects(source))

    def _aspects(self, source: AVGOSources) -> dict[str, DisclosureAspect]:
        result = {}
        for fid, f in source.facts.items():
            value = f.get("reported_value")
            numeric = None
            if value is not None and f.get("unit") not in (
                "DATE",
                "EXPECTED_CALENDAR_YEAR",
            ):
                numeric = Decimal(value)
            result[fid] = DisclosureAspect(
                fid,
                source.fact_chunks[fid].canonical_id,
                f["meaning"],
                f["facility_identity"],
                f["effective_period"],
                f.get("unit"),
                numeric,
                source.sources[f["source_id"]]["raw_sha256"],
                source.sources[f["source_id"]]["receipt"]["manifest_sha256"],
                f["quote"],
            )
        return result

    def verify(self) -> AVGOSources:
        """Resolve actual retained source bytes, not model-created digest fields."""
        current = AVGOSources(self.root, self.at)
        if (
            digest(current.projection()) != self.pin
            or digest(self.source.projection()) != self.pin
        ):
            raise ValueError("G98_SOURCE_DRIFT")
        return current

    def quantity(self, ref: QuantityReference) -> DisclosureAspect:
        """Bind metric, issuer, facility, period, value and actual Evidence identity."""
        current = self.verify()
        a = self._aspects(current)[ref.fact_id]
        if ref.issuer != "US:AVGO":
            raise ValueError("G98_ISSUER")
        if (ref.evidence_id, ref.metric, ref.facility, ref.period, ref.unit) != (
            a.evidence_id,
            a.metric,
            a.facility,
            a.period,
            a.unit,
        ):
            raise ValueError("G98_QUANTITY_SEMANTIC_IDENTITY")
        if ref.date_role != "NOT_DATE" or a.value is None or ref.value != a.value:
            raise ValueError("G98_NOT_VERIFIED_ECONOMIC_AMOUNT")
        if a.unit in ("USD_MAXIMUM", "USD_TRANSACTION_SIZE"):
            if amount(ref.lexical) != a.value:
                raise ValueError("G98_MAGNITUDE")
        elif a.unit == "PERCENT_BASIS":
            if (
                not re.fullmatch(r"\d+(?:\.\d+)?%", ref.lexical)
                or Decimal(ref.lexical[:-1]) != a.value
            ):
                raise ValueError("G98_PERCENT")
        else:
            raise ValueError("G98_UNSUPPORTED_UNIT")
        return a

    def date_value(self, fact_id: str, lexical: str, role: str) -> date:
        """Check calendar dates against their exact publication/report metadata role."""
        s = self.verify()
        f = s.facts[fact_id]
        source = s.sources[f["source_id"]]
        key = {
            "REPORT_PERIOD": "report_date",
            "PUBLICATION_DATE": "publication_date",
        }.get(role)
        if key is None or lexical != source.get(key):
            raise ValueError("G98_DATE_ROLE_OR_SOURCE")
        return date.fromisoformat(lexical)

    def ground(
        self, claim_text: str, entries: tuple[NumericEvidenceEntry, ...]
    ) -> tuple[NumericGroundingMatch, ...]:
        """Preserve meaning, period and contract; change numeric notation only."""
        s = self.verify()
        if len(entries) != 1:
            raise ValueError("G98_SINGLE_EXACT_DISCLOSURE_REQUIRED")
        entry = entries[0]
        original = next(
            (e for e in s.entries if e.evidence_id == entry.evidence_id), None
        )
        if (
            original is None
            or entry.short_description != original.short_description
            or entry.numeric_tokens != original.numeric_tokens
            or getattr(entry, "source", None) != original.source
        ):
            raise ValueError("G98_EVIDENCE_IDENTITY")
        candidates = [
            a for a in self._aspects(s).values() if a.evidence_id == entry.evidence_id
        ]
        if len(candidates) != 1 or surface(claim_text) != surface(candidates[0].quote):
            raise ValueError("G98_MEANING_PERIOD_OR_CONTRACT_NOT_EXACT")
        a = candidates[0]
        for match in _MONEY.finditer(claim_text):
            if (
                a.unit not in ("USD_MAXIMUM", "USD_TRANSACTION_SIZE")
                or amount(match.group()) != a.value
            ):
                raise ValueError("G98_MONETARY_AUTHORITY")
        # Whole-text equality preserves dates and negation; no numeral is ignored.
        source_tokens = numeric_literals(a.quote)
        literals = numeric_literals(claim_text)
        if len(literals) != len(source_tokens):
            raise ValueError("G98_NUMERIC_POPULATION")
        return tuple(
            NumericGroundingMatch(
                x, NumericSemanticKind.FORMATTED_GROUNDED_NUMBER, entry.evidence_id, y
            )
            for x, y in zip(literals, source_tokens, strict=True)
        )
