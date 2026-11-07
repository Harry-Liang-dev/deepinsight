"""G108 experimental P1 view adaptation; no Claim/State/Memory authority.

The exact G106 decoder is reused below (provenance in artifacts/g108).
References are checked against authenticated original views and native source text.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from src.adapters.providers import _html_to_text
from src.services.native_preservation import blob_hash
from src.services.phase5d_temporal import pointer
from src.services.research_vnext.radar_pilot import encoded
from tools.g106_d1_experiment import FREEZE, INPUT, inputs_verified


def decode_model_projection(projected: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct and hash-check the exact audit view before any future use."""
    rows = json.loads(json.dumps(projected["views"], ensure_ascii=False))
    for row in rows:
        if "content_pool_key" in row:
            row["content"] = projected["text_pool"][row.pop("content_pool_key")]
        if "quote_pool_key" in row["locator"]:
            row["locator"]["quote"] = projected["text_pool"][
                row["locator"].pop("quote_pool_key")
            ]
    view = {**projected["view_metadata"], "views": rows}
    if blob_hash(encoded(view)) != projected["audit_view_identity"]:
        raise ValueError("G106_POOL_IDENTITY")
    return view


def load_authority() -> tuple[dict[str, Any], dict[str, str]]:
    """Reuse original pinned input/native verification and exact normalizer."""
    inputs_verified()
    audit = json.loads((FREEZE / "EVIDENCE_VIEW.json").read_bytes())
    readset = json.loads((FREEZE / "SOURCE_READSET.json").read_bytes())
    texts = {}
    for source in readset["sources"]:
        directory = (INPUT / source["source_receipt_path"]).parent
        raw = (directory / (source["raw_sha256"] + ".raw")).read_bytes()
        if blob_hash(raw) != source["raw_sha256"]:
            raise ValueError("SOURCE_RAW_IDENTITY")
        # Native acquisition/encoding was validated by inputs_verified above.
        decoded = (
            gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
        ).decode()
        views = [v for v in audit["views"] if v["source_id"] == source["id"]]
        if any(v["locator"]["kind"] == "NORMALIZED_UNICODE" for v in views):
            text = _html_to_text(decoded)
            for view in views:
                loc = view["locator"]
                if blob_hash(text.encode()) != loc["normalization_sha256"]:
                    raise ValueError("SOURCE_NORMALIZATION_IDENTITY")
            texts[source["id"]] = text
        else:
            for view in views:
                if (
                    pointer(json.loads(decoded), view["locator"]["pointer"])
                    != view["content"]
                ):
                    raise ValueError("SOURCE_JSON_POINTER_IDENTITY")
    return audit, texts


def _matches(text: str, quote: str, offset: int) -> list[list[int]]:
    found = []
    start = 0
    while quote and (position := text.find(quote, start)) >= 0:
        found.append([offset + position, offset + position + len(quote)])
        start = position + 1
    return found


def reference_diagnostic(
    ref: dict[str, Any], view: dict[str, Any] | None, texts: dict[str, str]
) -> dict[str, Any]:
    """Check identity, coordinates and literal quote independently, without repair."""
    row: dict[str, Any] = {
        "SOURCE_AUTHORITY_RESULT": "FAIL",
        "LOCATOR_RESULT": "NOT_EVALUATED",
        "QUOTE_RESULT": "NOT_EVALUATED",
        "reasons": [],
    }
    if view is None:
        row["reasons"].append("UNKNOWN_VIEW_ID")
        return row
    if ref.get("SourceID") != view["source_id"]:
        row["reasons"].append("SOURCE_VIEW_IDENTITY_MISMATCH")
        return row
    row["SOURCE_AUTHORITY_RESULT"] = "PASS"
    row["authority"] = "SOURCE_ATTRIBUTION_ONLY_NOT_CANONICAL_EVIDENCE"
    expected = {k: v for k, v in view["locator"].items() if k not in {"quote", "page"}}
    actual = ref.get("Locator", {})
    quote = ref.get("Quote")
    row["LOCATOR_RESULT"] = "FAIL"
    row["QUOTE_RESULT"] = "FAIL"
    if not isinstance(actual, dict) or set(actual) != set(expected):
        row["reasons"].append("LOCATOR_FIELDS")
    elif any(actual[k] != expected[k] for k in expected if k not in {"start", "end"}):
        row["reasons"].append("LOCATOR_KIND_HASH_OR_POINTER")
    elif expected["kind"] == "NORMALIZED_UNICODE":
        start, end = actual["start"], actual["end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not expected["start"] <= start < end <= expected["end"]
        ):
            row["reasons"].append("LOCATOR_OUTSIDE_NAMED_VIEW")
        else:
            row["LOCATOR_RESULT"] = "PASS"
            row["locator_mode"] = (
                "FULL_VIEW" if actual == expected else "EXACT_QUOTE_SUBSPAN"
            )
            row["declared_source_span"] = [start, end]
    elif expected["kind"] == "JSON_POINTER" and actual == expected:
        row["LOCATOR_RESULT"] = "PASS"
        row["locator_mode"] = "JSON_POINTER"
    else:
        row["reasons"].append("UNSUPPORTED_LOCATOR")
    if not isinstance(quote, str) or not quote:
        row["reasons"].append("EMPTY_OR_NONSTRING_QUOTE")
        return row
    if expected["kind"] == "NORMALIZED_UNICODE":
        text = texts[view["source_id"]]
        span_text = text[expected["start"] : expected["end"]]
        if (
            span_text != view["content"]
            or blob_hash(text.encode()) != expected["normalization_sha256"]
        ):
            row.update(SOURCE_AUTHORITY_RESULT="FAIL", LOCATOR_RESULT="FAIL")
            row["reasons"].append("TRUSTED_SOURCE_TEXT_MISMATCH")
            return row
        hits = _matches(span_text, quote, expected["start"])
        row["literal_quote_spans"] = hits
        if len(hits) == 1:
            row["QUOTE_RESULT"] = "PASS"
        else:
            row["reasons"].append(
                "QUOTE_AMBIGUOUS" if hits else "QUOTE_NOT_VERBATIM_IN_NAMED_VIEW"
            )
        if row.get("locator_mode") == "EXACT_QUOTE_SUBSPAN":
            if text[actual["start"] : actual["end"]] != quote:
                row["LOCATOR_RESULT"] = "FAIL"
                row["reasons"].append("SUBSPAN_BOUNDARIES_DO_NOT_MATCH_QUOTE")
            else:
                # Explicit coordinates disambiguate a repeated exact literal.
                row["QUOTE_RESULT"] = "PASS"
                row["literal_quote_spans"] = [[actual["start"], actual["end"]]]
                row["reasons"] = [x for x in row["reasons"] if x != "QUOTE_AMBIGUOUS"]
    else:
        content = view["content"]
        representation = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False)
        )
        if (
            isinstance(content, str) and quote in representation
        ) or quote == representation:
            row["QUOTE_RESULT"] = "PASS"
            row["quote_encoding"] = "DECODED_JSON_VALUE_NOT_RAW_BYTE_SPAN"
        else:
            row["reasons"].append("QUOTE_NOT_EXACT_JSON_VALUE")
    return row


def diagnose_p1(
    result: dict[str, Any], schema: dict[str, Any], projected: dict[str, Any]
) -> dict[str, Any]:
    """Decode and source-bind a P1 diagnostic; never emit scientific acceptance."""
    report: dict[str, Any] = {
        "contract": "G108_P1_EXPANDED_VIEW_DIAGNOSTIC_V1",
        "schema_valid": False,
        "scientific_admission": False,
        "canonical_evidence_count": 0,
        "world_fact_authority": False,
        "POOLED_VIEW_DECODING": "FAIL",
        "SOURCE_AUTHORITY_RESULT": "FAIL",
        "LOCATOR_RESULT": "NOT_EVALUATED",
        "QUOTE_RESULT": "NOT_EVALUATED",
        "LOCAL_INDEX_RESULT": "NOT_EVALUATED",
        "references": [],
        "local_indices": [],
    }
    try:
        expanded = decode_model_projection(projected)
        original, texts = load_authority()
        if encoded(expanded) != encoded(original):
            raise ValueError("DECODED_VIEW_NOT_ORIGINAL_AUTHORITY")
    except Exception as exc:
        report["source_error"] = type(exc).__name__ + ":" + str(exc)
        return report
    report.update(POOLED_VIEW_DECODING="PASS", SOURCE_AUTHORITY_RESULT="PASS")
    errors = list(Draft202012Validator(schema).iter_errors(result))
    report["JSON_SCHEMA_RESULT"] = "FAIL" if errors else "PASS"
    report["schema_errors"] = [
        {"path": list(e.absolute_path), "reason": e.message} for e in errors
    ]
    if errors:
        return report
    by_id = {v["view_id"]: v for v in expanded["views"]}
    for i, item in enumerate(result["items"]):
        refs = item["EvidenceLocator"]
        for j, ref in enumerate(refs):
            row = reference_diagnostic(ref, by_id.get(ref["ViewID"]), texts)
            report["references"].append({"item": i, "reference": j, **row})
        for j, premise in enumerate(item["SourcePremises"]):
            index = premise["EvidenceLocatorIndex"]
            report["local_indices"].append(
                {
                    "item": i,
                    "premise": j,
                    "index": index,
                    "local_count": len(refs),
                    "valid": type(index) is int and 0 <= index < len(refs),
                }
            )
    for name in ("SOURCE_AUTHORITY_RESULT", "LOCATOR_RESULT", "QUOTE_RESULT"):
        refs = report["references"]
        report[name] = (
            "FAIL"
            if any(row[name] != "PASS" for row in refs)
            else (
                "PASS"
                if refs or name == "SOURCE_AUTHORITY_RESULT"
                else "NOT_APPLICABLE"
            )
        )
    report["LOCAL_INDEX_RESULT"] = (
        "FAIL"
        if any(not x["valid"] for x in report["local_indices"])
        else "PASS" if report["local_indices"] else "NOT_APPLICABLE"
    )
    report["schema_valid"] = not any(
        report[k] == "FAIL"
        for k in (
            "SOURCE_AUTHORITY_RESULT",
            "LOCATOR_RESULT",
            "QUOTE_RESULT",
            "LOCAL_INDEX_RESULT",
        )
    )
    return report
