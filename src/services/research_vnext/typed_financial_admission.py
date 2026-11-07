"""G91 explicit text-to-aspects extraction; supplemental to original validators.

Not a semantic similarity scorer or a replacement source authority. Unknown
language is rejected, and no missing amount/date/unit is filled from SEC values.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, localcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_v2_shared import digest
from src.services.research_vnext.real_native_source import NativeSource


class TypedFactReference(BaseModel):
    """Extracted model aspects plus separately identified source resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[
        "G91_TYPED_FINANCIAL_REFERENCE_V1", "G92_TYPED_FINANCIAL_REFERENCE_V1"
    ] = "G91_TYPED_FINANCIAL_REFERENCE_V1"
    agent_claim_id: str
    model_claim_id: str | None = None
    original_text: str
    evidence_ids: tuple[str, ...]
    entity: str
    entity_basis: Literal["EXPLICIT_TEXT", "EXPLICIT_TASK_SCOPE"]
    concept_local: str
    full_qname: str
    qname_basis: Literal["EXACT_CITED_NATIVE_NAMESPACE"] = (
        "EXACT_CITED_NATIVE_NAMESPACE"
    )
    value: Decimal
    unit: Literal["USD"]
    scale: Literal[6]
    period_type: Literal["instant", "duration"]
    start: date | None
    end: date
    period_description: str
    native_proof_identity: str


# This vocabulary is fixed before live inference. It describes reported facts,
# not causal explanation, performance, safety, recommendations or comparisons.
WORDS = frozenset(
    (
        "a an the apple inc aapl us gaap us-gaap total assets gross profit "
        "grossprofit as of at on for from to through ended ending period date "
        "instant duration quarter quarterly three three-month months month "
        "nine nine-month year ytd "
        "year-to-date cumulative accumulated fiscal reported reports reporting "
        "report were was is are amounted amounting amounts amount recorded "
        "disclosed in million millions usd dollars u s and balance statement "
        "with value equals equal financial consolidated respectively"
    ).split()
)

DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MONEY = re.compile(
    rf"(?:(?P<a>{NUM})\s+(?:USD\s+millions?|millions?\s+(?:USD|U\.S\. dollars))"
    rf"|USD\s+(?P<b>{NUM})\s+millions?)\b",
    re.I,
)


def extract(
    claim: ClaimEvidenceBinding,
    source: NativeSource,
    *,
    memory_id: str | None = None,
    allowed_proof: str | None = None,
    typed: dict[str, Any] | None = None,
    profile: Literal["G91", "G92"] = "G91",
) -> TypedFactReference:
    """Extract explicit aspects then require exact cited native compatibility."""
    if profile not in ("G91", "G92"):
        raise ValueError("UNKNOWN_TYPED_PROFILE")
    text = claim.claim_text
    if source.available > source.at or source.document.ingested_at > source.at:
        raise ValueError("FUTURE_EVIDENCE")
    # Resolve citation first, but never extract a missing textual value from it.
    matches = [
        p
        for p in source.proofs
        if (
            digest(p) == allowed_proof
            if memory_id
            else set(claim.evidence_ids) == set(source.proof_chunks[digest(p)])
        )
    ]
    if len(matches) != 1 or (memory_id and set(claim.evidence_ids) != {memory_id}):
        raise ValueError("SOURCE_REFERENCE_MISSING_OR_AMBIGUOUS")
    p = matches[0]
    if memory_id:
        if any(
            s.document_id != source.proof_chunks[digest(p)][0]
            or s.excerpt_ref != memory_id
            for s in claim.source_references
        ):
            raise ValueError("MEMORY_SOURCE_LINEAGE")
    elif any(
        s.document_id != source.document_id
        or s.provider != "sec_edgar"
        or s.source_url != source.registration.document_url
        for s in claim.source_references
    ):
        raise ValueError("SOURCE_DOCUMENT_OR_ISSUER")
    low = text.lower()
    if re.search(r"\b(msft|microsoft|abus|achc|acadia)\b", low):
        raise ValueError("WRONG_ISSUER")
    concepts = []
    if re.search(r"\bassets\b", low):
        concepts.append("Assets")
    if re.search(r"\bgross\s*profit\b", low):
        concepts.append("GrossProfit")
    if len(concepts) != 1:
        raise ValueError("CONCEPT_MISSING_OR_MULTIPLE")
    local = concepts[0]
    money = list(MONEY.finditer(text))
    if len(money) != 1:
        raise ValueError("VALUE_UNIT_SCALE_MISSING_OR_MULTIPLE")
    value = Decimal((money[0].group("a") or money[0].group("b")).replace(",", ""))
    ds = DATES.findall(text)
    instant = bool(re.search(r"\binstant\b|\bas of\b|\bbalance\b", low))
    duration = bool(
        re.search(
            r"\bduration\b|\bfrom\b|\bquarter\b|\bmonths\b|\bytd\b|year.to.date", low
        )
    )
    if instant == duration:
        raise ValueError("PERIOD_TYPE_AMBIGUOUS_OR_MISSING")
    if len(ds) != (1 if instant else 2):
        raise ValueError("PERIOD_BOUNDARIES_MISSING")
    start = None if instant else date.fromisoformat(ds[0])
    end = date.fromisoformat(ds[-1])
    days = (end - start).days + 1 if start else 0
    if not instant and not 1 <= days <= 371:
        raise ValueError("INVALID_PERIOD")
    if (
        re.search(r"\b(annual|full.year|fiscal year(?!-to-date| to date))\b", low)
        and days < 350
    ):
        raise ValueError("AMBIGUOUS_ANNUAL_VERSUS_YTD")
    if re.search(r"quarter|three.month", low) and not 75 <= days <= 105:
        raise ValueError("QUARTER_VERSUS_YTD")
    if re.search(r"nine.month", low) and not 250 <= days <= 290:
        raise ValueError("YTD_VERSUS_QUARTER")
    # One supported financial proposition only. Unconsumed numbers/words cannot
    # silently carry an extra financial or causal assertion.
    residual = DATES.sub(" ", text)
    residual = MONEY.sub(" ", residual)
    words = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", residual.lower())
    vocabulary = WORDS | {"single"} if profile == "G92" else WORDS
    if (
        profile == "G92"
        and "single" in words
        and not re.search(r"\bsingle quarter\b", low)
    ):
        raise ValueError("AMBIGUOUS_SINGLE_PERIOD")
    if (
        profile == "G92"
        and re.search(r"\b(six|nine)[ -]months?\b", low)
        and days <= 105
    ):
        raise ValueError("YTD_VERSUS_QUARTER")
    if set(words) - vocabulary or re.search(r"[\d%<>~=*/]", residual):
        raise ValueError("UNSUPPORTED_EXTRA_ASSERTION_OR_LEXICON")
    c = p.context
    with localcontext() as ctx:
        ctx.prec = max(80, len(value.as_tuple().digits) + 6)
        amount_matches = (
            (value.scaleb(6) == Decimal(c.value))
            if profile == "G92"
            else (
                value == Decimal(c.lexical_value.replace(",", ""))
                and c.scale == 6
                and c.sign == ""
            )
        )
    if (
        c.currency != "USD"
        or c.cik != "0000320193"
        or bool(c.dimensions)
        or local != c.concept.rsplit("}", 1)[-1]
        or not amount_matches
        or c.period_kind != ("instant" if instant else "duration")
        or str(end) != str(c.end)
        or (str(start) if start else None) != (str(c.start) if c.start else None)
    ):
        raise ValueError("MODEL_NATIVE_CONCEPT_VALUE_UNIT_OR_PERIOD_MISMATCH")
    fact = TypedFactReference(
        schema_version=(
            "G92_TYPED_FINANCIAL_REFERENCE_V1"
            if profile == "G92"
            else "G91_TYPED_FINANCIAL_REFERENCE_V1"
        ),
        agent_claim_id=str(claim.claim_id),
        original_text=text,
        evidence_ids=tuple(claim.evidence_ids),
        entity="US:AAPL",
        entity_basis=(
            "EXPLICIT_TEXT" if re.search(r"apple|aapl", low) else "EXPLICIT_TASK_SCOPE"
        ),
        concept_local=local,
        full_qname=c.concept,
        value=value,
        unit="USD",
        scale=6,
        period_type="instant" if instant else "duration",
        start=start,
        end=end,
        period_description=(
            "instant" if instant else ("quarter" if days <= 105 else "nine-month-YTD")
        ),
        native_proof_identity=digest(p),
    )
    if typed is not None and TypedFactReference.model_validate(typed) != fact:
        raise ValueError("TEXT_TYPED_FIELD_CONFLICT")
    return fact


def census(
    claims: tuple[ClaimEvidenceBinding, ...],
    source: NativeSource,
    *,
    profile: Literal["G91", "G92"] = "G91",
) -> tuple[tuple[ClaimEvidenceBinding, ...], list[dict[str, Any]]]:
    """Keep complete accepted/rejected population; never edit a model Claim."""
    accepted = []
    records = []
    for claim in claims:
        try:
            fact = extract(claim, source, profile=profile)
            accepted.append(claim)
            records.append(
                dict(
                    claim_id=str(claim.claim_id),
                    status="TYPED_ELIGIBLE_NOT_V2_DECISION",
                    typed=fact.model_dump(mode="json"),
                )
            )
        except ValueError as error:
            records.append(
                dict(
                    claim_id=str(claim.claim_id),
                    status="REJECTED",
                    original_text=claim.claim_text,
                    evidence_ids=list(claim.evidence_ids),
                    reason=str(error),
                )
            )
    return tuple(accepted), records
