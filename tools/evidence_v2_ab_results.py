"""Paired mechanical frontier on immutable captures, without semantic admission."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from time import perf_counter
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from evidence_v2.registry import AccessChecker, Registry, resolve
from src.services.native_preservation import blob_hash
from tools import evidence_v2_ab_inputs as inputs
from tools import evidence_v2_runtime as base
from tools.g107_matrix import strict_object


def selections(obj: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Enumerate only declared selection paths; do not repair wrong container types."""
    result: list[tuple[str, dict[str, Any]]] = []
    proposals = obj.get("proposals")
    if not isinstance(proposals, list):
        return result
    for i, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            continue
        groups = [
            (f"/proposals/{i}/{k}", proposal.get(k))
            for k in ("evidence", "counterevidence")
        ]
        for k in ("premises", "supported_subfacts"):
            values = proposal.get(k)
            if isinstance(values, list):
                groups += [
                    (f"/proposals/{i}/{k}/{j}/evidence", v.get("evidence"))
                    for j, v in enumerate(values)
                    if isinstance(v, dict)
                ]
        for path, group in groups:
            if isinstance(group, list):
                result += [
                    (f"{path}/{j}", item)
                    for j, item in enumerate(group)
                    if isinstance(item, dict)
                ]
    return result


def common_view(
    obj: dict[str, Any], schema: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """W5 evaluation-only carrier erasure; never produces a repaired candidate."""
    view, shape = deepcopy(obj), deepcopy(schema)
    for _, selection in selections(view):
        for k in ("quote", "fragment_id", "handle"):
            selection.pop(k, None)
    selector = shape["$defs"]["Selection"]
    for k in ("quote", "fragment_id", "handle"):
        selector["properties"].pop(k, None)
    selector["required"] = [
        k for k in selector["required"] if k not in {"quote", "fragment_id", "handle"}
    ]
    return view, shape


def errors(obj: Any, schema: dict[str, Any]) -> list[dict[str, str]]:
    """Return deterministic JSON Pointer diagnostics without coercion."""
    return [
        dict(
            pointer="/"
            + "/".join(
                str(p).replace("~", "~0").replace("/", "~1") for p in e.absolute_path
            ),
            validator=str(e.validator),
        )
        for e in Draft202012Validator(schema).iter_errors(obj)
    ]


def exact_quote(
    selection: dict[str, Any],
    registry: Registry,
    packet: dict[str, Any],
    checker: AccessChecker,
    at: str,
) -> dict[str, Any]:
    """Legacy exact unique substring within one selected original root only."""
    fragment = next(
        (
            f
            for f in packet["source_fragments"]
            if f["fragment_id"] == selection["fragment_id"]
        ),
        None,
    )
    if fragment is None:
        return dict(resolution_state="UNRESOLVED", reason="UNKNOWN_ORIGINAL_FRAGMENT")
    text, quote = fragment["text"], selection["quote"]
    offset = text.find(quote)
    if offset < 0 or text.find(quote, offset + 1) >= 0:
        return dict(resolution_state="UNRESOLVED", reason="QUOTE_NOT_EXACT_AND_UNIQUE")
    roots = [
        e
        for e in registry.entries.values()
        if e.fragment_id == fragment["fragment_id"] and e.text == text
    ]
    if len(roots) != 1:
        return dict(
            resolution_state="UNRESOLVED", reason="ORIGINAL_ROOT_IDENTITY_AMBIGUOUS"
        )
    result = resolve(
        registry,
        roots[0].handle,
        checker,
        scope=base.SCOPE,
        research_as_of=base.CUTOFF,
        checked_at=at,
    )
    if result["resolution_state"] == "EVIDENCE_RESOLVED":
        location = dict(fragment["binding"])
        location.update(
            fragment_unicode_start=offset, fragment_unicode_end=offset + len(quote)
        )
        if fragment["kind"] == "SOURCE_SPAN":
            start = fragment["binding"]["locator"]["start"] + offset
            location.update(
                source_unicode_start=start, source_unicode_end=start + len(quote)
            )
        result["exact_quote_location"] = location
        result["selected_original_quote"] = quote
        result["system_selected_extra_evidence"] = False
    return result


def diagnose(
    raw: bytes,
    case: str,
    arm: str,
    registry: Registry,
    packet: dict[str, Any],
    checker: AccessChecker,
    at: str,
    *,
    preflight_valid: bool,
    capture_valid: bool,
) -> dict[str, Any]:
    """Separate common semantics, native carrier, resolution and scientific truth."""
    started = perf_counter()
    result: dict[str, Any] = dict(
        case_id=case,
        arm=arm,
        original_claim=asdict(inputs.fixed(case, arm)),
        raw_sha256=blob_hash(raw),
        I_pre=preflight_valid,
        M_shared=False,
        C_shared=None,
        R_arm=False,
        E_link=False,
        native_schema_valid=False,
        declared_semantic_prediction=None,
        candidate_semantic_prediction=None,
        prediction_state="NO_PREDICTION",
        claim_support_independently_evaluated=False,
        actual_scientific_admission=False,
        would_pass_scientific_gate=None,
        independent_gold=None,
        resolutions=[],
    )
    shape = inputs.schema(case, arm)
    try:
        obj = strict_object(raw.decode("utf-8", errors="strict"))
    except (ValueError, UnicodeError) as exc:
        result["parse_error"] = type(exc).__name__
        return result
    view, common_shape = common_view(obj, shape)
    result["common_errors"] = errors(view, common_shape)
    result["native_errors"] = errors(obj, shape)
    result["native_schema_valid"] = not result["native_errors"]
    result["M_shared"] = capture_valid and not result["common_errors"]
    if not result["M_shared"]:
        return result
    proposal = obj["proposals"][0]
    prediction = proposal["judgment"]["original_complete_claim"]
    result["declared_semantic_prediction"] = prediction
    result["prediction_state"] = "EVALUATION_ONLY_PRE_RESOLUTION"
    result["model_authored_proposal"] = proposal
    parent_missing = bool(proposal["missing_necessary_premises"]) or any(
        p["required_for"] == "ORIGINAL_COMPLETE_CLAIM" and p["support"] != "SUPPORTED"
        for p in proposal["premises"]
    )
    result["C_shared"] = not (prediction == "SUPPORTED" and parent_missing)
    if result["native_schema_valid"]:
        for path, selection in selections(obj):
            bound = (
                exact_quote(selection, registry, packet, checker, at)
                if arm == "A"
                else resolve(
                    registry,
                    selection["handle"],
                    checker,
                    scope=base.SCOPE,
                    research_as_of=base.CUTOFF,
                    checked_at=at,
                )
            )
            result["resolutions"].append(
                dict(path=path, model_selected=selection, **bound)
            )
        result["R_arm"] = all(
            x["resolution_state"] == "EVIDENCE_RESOLVED" for x in result["resolutions"]
        )
    result["E_link"] = bool(
        preflight_valid
        and result["M_shared"]
        and result["C_shared"]
        and result["R_arm"]
        and proposal["evidence"]
    )
    if result["E_link"]:
        result["candidate_semantic_prediction"] = prediction
        result["prediction_state"] = "NATIVE_CANDIDATE_NOT_GOLD"
    result["evidence_selected_count"] = len(selections(obj))
    result["evidence_resolved_count"] = sum(
        x["resolution_state"] == "EVIDENCE_RESOLVED" for x in result["resolutions"]
    )
    result["resolution_elapsed_seconds"] = perf_counter() - started
    return result
