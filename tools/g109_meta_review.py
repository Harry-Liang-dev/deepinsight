"""Offline source-tag observations for G109; never Native FactProof admission."""

from __future__ import annotations

import gzip
import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, cast

from src.services.sec_native_financial import _Tree


def local_name(tag: str) -> str:
    """Read the local name resolved by the existing SEC parser."""
    return tag.rsplit("}", 1)[-1]


def observations(raw: bytes, source_id: str) -> dict[str, Any]:
    """Observe original tags and complete contexts without minting proofs."""
    decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    tree = _Tree(decoded.decode())
    nodes = list(tree.root.iter())
    contexts = {e.attrib.get("id"): e for e in nodes if local_name(e.tag) == "context"}
    units = {e.attrib.get("id"): e for e in nodes if local_name(e.tag) == "unit"}
    rows: list[dict[str, Any]] = []
    dei: dict[str, str] = {}
    wanted = {
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetIncomeLoss",
        "us-gaap:AccruedLiabilitiesCurrent",
        "us-gaap:OtherLiabilitiesNoncurrent",
        "us-gaap:IncreaseDecreaseInAccruedLiabilities",
        "us-gaap:IncreaseDecreaseInOtherNoncurrentLiabilities",
        "meta:LegalRelatedAccruedLiabilitiesCurrent",
        "meta:LegalRelatedAccruedLiabilitiesNoncurrent",
    }
    for ordinal, e in enumerate(nodes):
        attrs = e.attrib
        name = attrs.get("name", "")
        if local_name(e.tag) == "nonnumeric" and name in {
            "dei:EntityCentralIndexKey",
            "dei:DocumentType",
            "dei:DocumentPeriodEndDate",
        }:
            dei[name] = "".join(e.itertext())
        if local_name(e.tag) != "nonfraction" or name not in wanted:
            continue
        context = contexts[attrs["contextref"]]
        period = {
            local_name(v.tag): "".join(v.itertext())
            for v in context.iter()
            if local_name(v.tag) in {"identifier", "startdate", "enddate", "instant"}
        }
        dimensions = sorted(
            (
                tree.qname(v.attrib["dimension"], tree.namespaces[v]),
                tree.qname("".join(v.itertext()), tree.namespaces[v]),
            )
            for v in context.iter()
            if local_name(v.tag) == "explicitmember"
        )
        if dimensions or not (
            period.get("enddate", "").startswith("2026")
            or period.get("instant", "").startswith("2026")
        ):
            continue
        unit = units[attrs["unitref"]]
        measure = next(v for v in unit.iter() if local_name(v.tag) == "measure")
        unit_qname = tree.qname("".join(measure.itertext()), tree.namespaces[measure])
        if period["identifier"] != "0001326801" or not unit_qname.endswith("}USD"):
            raise ValueError("SOURCE_ISSUER_UNIT")
        literal = "".join(e.itertext())
        value = Decimal(literal.replace(",", "")) * Decimal(10) ** int(attrs["scale"])
        if attrs.get("sign") == "-":
            value = -value
        rows.append(
            dict(
                source_id=source_id,
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                native_element_id=attrs["id"],
                element_ordinal=ordinal,
                context_id=attrs["contextref"],
                concept=tree.qname(name, tree.namespaces[e]),
                lexical_concept=name,
                cik=period["identifier"],
                period=period,
                dimensions=dimensions,
                unit=unit_qname,
                literal=literal,
                scale=attrs["scale"],
                decimals=attrs["decimals"],
                sign=attrs.get("sign", ""),
                reported_value_usd=str(value),
                authority="SOURCE_TAG_OBSERVATION_NOT_NATIVE_FACTPROOF",
                scientific_admitted=False,
            )
        )
    return {"source_id": source_id, "dei": dei, "observations": rows}


def pick(data: dict[str, Any], concept: str, start: str, end: str) -> dict[str, Any]:
    """Bind an exact consolidated duration or report it missing/ambiguous."""
    matches = [
        r
        for r in data["observations"]
        if r["lexical_concept"] == concept
        and r["period"].get("startdate") == start
        and r["period"].get("enddate") == end
    ]
    if not matches or len({r["reported_value_usd"] for r in matches}) != 1:
        raise ValueError("MISSING_OR_AMBIGUOUS_REPORTED_DURATION")
    return cast(dict[str, Any], matches[0])


def quarter_delta(half: dict[str, Any], nine: dict[str, Any]) -> dict[str, Any]:
    """Subtract compatible reported YTD values for baseline audit only."""
    keys = ("concept", "cik", "unit", "dimensions", "scale")
    if any(half[k] != nine[k] for k in keys):
        raise ValueError("INCOMPATIBLE_REPORTED_OPERANDS")
    a, b = half["period"], nine["period"]
    if (
        a.get("startdate") != b.get("startdate")
        or a.get("startdate") != "2026-01-01"
        or a.get("enddate") != "2026-06-30"
        or b.get("enddate") != "2026-09-30"
        or half["dimensions"]
    ):
        raise ValueError("INCOMPATIBLE_REPORTED_PERIOD")
    date.fromisoformat(a["startdate"])
    value = Decimal(nine["reported_value_usd"]) - Decimal(half["reported_value_usd"])
    return {
        "period_start": "2026-07-01",
        "period_end": "2026-09-30",
        "concept": half["concept"],
        "cik": half["cik"],
        "unit": half["unit"],
        "reported_amount_difference_usd": str(value),
        "formula": "reported_nine_month_YTD - reported_six_month_YTD",
        "operands": [half, nine],
        "precision": (
            "Difference of reported amounts; underlying exact cash is not asserted"
        ),
        "native_financial_proof": None,
        "scientific_admission": "BLOCKED",
        "case_specific_payment": None,
    }


def legal_opening(data: dict[str, Any]) -> dict[str, Any]:
    """Missing legal-category disclosure remains null, never zero or a total."""
    rows = [
        r
        for r in data["observations"]
        if r["lexical_concept"]
        in {
            "meta:LegalRelatedAccruedLiabilitiesCurrent",
            "meta:LegalRelatedAccruedLiabilitiesNoncurrent",
        }
        and r["period"].get("instant") == "2026-06-30"
    ]
    if rows:
        raise ValueError("SOURCE_POPULATION_CHANGED_REVIEW_REQUIRED")
    return {
        "instant": "2026-06-30",
        "current": None,
        "noncurrent": None,
        "total": None,
        "matching_source_tag_observations": rows,
        "status": "NO_MATCHING_LEGAL_CATEGORY_TAGS_OR_REVIEWED_NOTE_TABLE",
        "case_specific_AG_payment": None,
        "broad_liabilities_are_not_substitutes": True,
    }
