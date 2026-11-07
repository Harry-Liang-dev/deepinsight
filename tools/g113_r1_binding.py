"""G113-R1 verified handoff composition; no dispatch or scientific admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.native_preservation import blob_hash
from tools.g112_task_freeze import check_span
from tools.g113_contract import Calculation, TaskCatalog, arithmetic, calculate
from tools.g113_prepare import build_catalog, pinned

ROOT = Path(__file__).resolve().parents[1]
INPUT = "artifacts/g113-r1/inputs"
MANIFESTS = {
    "w3": (
        "artifacts/g113-w3/SOURCE_MANIFEST.json",
        "5cf1fb34567a736160bb942dcb20a0da845d0bfd7d76619764cef3e89cae1974",
    ),
    "w6": (
        "artifacts/g113/MANIFEST.json",
        "ab8203b4520914611acdc0adcba03f28f43fac3ca7dece9944d09691cea5dc64",
    ),
}


def retained(root: Path, window: str, path: str) -> Any:
    """Check exact original handoff manifest and selected bytes before parsing."""
    base = root / INPUT / window
    name, identity = MANIFESTS[window]
    raw = (base / name).read_bytes()
    if blob_hash(raw) != identity:
        raise ValueError("R1_HANDOFF_MANIFEST")
    manifest = json.loads(raw)
    entries = {e["path"]: e for e in manifest.get("files", manifest.get("members"))}
    body = (base / path).read_bytes()
    if blob_hash(body) != entries[path]["sha256"]:
        raise ValueError("R1_HANDOFF_MEMBER")
    return json.loads(body)


def w3(root: Path, name: str) -> Any:
    """Read an identity-verified W3 member."""
    return retained(root, "w3", "artifacts/g113-w3/" + name)


def w6(root: Path, name: str) -> Any:
    """Read an identity-verified W6 member."""
    return retained(root, "w6", "artifacts/g113/" + name)


def exact_view(value: dict[str, Any]) -> dict[str, Any]:
    """Project existing representations, never search or alter source content."""
    content = value.get("content", value.get("quote", value.get("returned_text")))
    loc = dict(value["locator"])
    if ("quote" in loc and loc["quote"] != content) or loc.get("page") is not None:
        raise ValueError("R1_LOCATOR_REDUNDANT_CONTENT_CONFLICT")
    # Existing G108 locator contract keeps literal quote separate from coordinates.
    loc.pop("quote", None)
    loc.pop("page", None)
    return dict(
        source_id=value["source_id"],
        raw_sha256=value.get("raw_sha256", value.get("source_sha256")),
        locator=loc,
        content=content,
    )


def covers(outer: dict[str, Any], inner: dict[str, Any], texts: dict[str, str]) -> bool:
    """Independently verify both exact ranges before a containment mapping."""
    a, b = exact_view(outer), exact_view(inner)
    check_span(a, texts)
    check_span(b, texts)
    x, y = a["locator"], b["locator"]
    return bool(
        a["source_id"] == b["source_id"]
        and a["raw_sha256"] == b["raw_sha256"]
        and x["normalization_sha256"] == y["normalization_sha256"]
        and x["start"] <= y["start"] < y["end"] <= x["end"]
        and a["content"][y["start"] - x["start"] : y["end"] - x["start"]]
        == b["content"]
    )


def verify_cards(cards: list[dict[str, Any]], catalog: TaskCatalog) -> dict[str, Any]:
    """Validate all original operand identities, then compute using G113 Decimal."""
    data = catalog.data()
    result = {}
    for card in cards:
        original = {
            k: v
            for k, v in card.items()
            if k not in ("calculation_id", "binding_sha256")
        }
        if (
            blob_hash(json.dumps(original, sort_keys=True).encode())
            != card["binding_sha256"]
        ):
            raise ValueError("R1_CARD_IDENTITY")
        cid = card["calculation_id"]
        if cid in result or card["issuer"] != data["security"]:
            raise ValueError("R1_CARD_SCOPE_OR_DUPLICATE")
        ids = card["observation_ids"]
        if len(ids) != 2 or any(i not in data["operands"] for i in ids):
            raise ValueError("R1_CARD_OPERANDS")
        for n, oid in enumerate(ids):
            op = data["operands"][oid]
            native = op["native_observation"]
            if (
                card["native_operand_refs"][n] != native
                or card["memory_ids"][n] != data["observations"][oid]["memory_id"]
                or card["values_usd"][n] != op["value"]
                or card["periods"][n]
                != {"kind": "QUARTER_DURATION", "start": op["start"], "end": op["end"]}
                or native["concept"].rsplit("}", 1)[-1] != card["concept"]
                or native["dimensions"][0]["member"].rsplit("}", 1)[-1]
                != card["member"]
            ):
                raise ValueError("R1_CARD_NATIVE_PERIOD_UNIT_IDENTITY")
            expected = str(
                arithmetic(
                    op["value"], op["value"], "UNIT_CONVERSION", "USD_MILLION", 0
                )
            )
            if card["values_USDmillion"][n] != expected:
                raise ValueError("R1_CARD_UNIT")
        operations = {}
        for operation, unit, places, field in (
            ("GROWTH_PERCENT", "PERCENT", 2, "growth_pct"),
            ("DIFFERENCE", "USD_MILLION", 0, "delta_USDmillion"),
        ):
            operations[field] = calculate(
                Calculation.model_validate(
                    dict(
                        old_operand_id=ids[0],
                        new_operand_id=ids[1],
                        operation=operation,
                        output_unit=unit,
                        decimal_places=places,
                        reported_value=card[field],
                    )
                ),
                catalog,
            )
        result[cid] = dict(
            original_card=card,
            deterministic_operations=operations,
            rounding="EXACT_DECIMAL_SINGLE_HALF_UP_AT_DECLARED_PRECISION",
            model_responsibility="REFERENCE_CARD_AND_EXPLAIN_ONLY",
            native_scientific_admission=False,
        )
    return result


def compose(root: Path, role: str, arm: str) -> TaskCatalog:
    """Bind original W3 task to original W1 source/Memory identities, losslessly."""
    original = build_catalog(
        root,
        role,
        {"FULL": "FULL_CONTEXT_CONTROL", "DELTA": "MEMORY_DELTA_CONTEXT"}[arm],
    )
    data, texts = original.data(), json.loads(original.source_texts_json)
    payload = w3(root, f"inputs/{role}.{arm}.json")
    common = payload["common"]
    if (
        common["role"] != role
        or common["security"] != data["security"]
        or common["research_as_of"] != data["research_as_of"]
    ):
        raise ValueError("R1_TASK_SCOPE_CLOCK")
    views = {
        v["view_id"]: exact_view(v)
        for v in w3(root, "inputs/SOURCE_VIEW_MANIFEST.json")["views"]
    }
    if set(views) != set(common["allowed_view_ids"]):
        raise ValueError("R1_VISIBLE_VIEW_POPULATION")
    for v in views.values():
        if not any(covers(p, v, texts) for p in payload["context_evidence"]):
            raise ValueError("R1_VIEW_NOT_ACTUALLY_VISIBLE")
    mapping = {
        old_id: [vid for vid, v in views.items() if covers(v, old, texts)]
        for old_id, old in data["views"].items()
    }
    # Support containment retains original source coordinates, never changes the
    # quote to a nearby/identical sentence and never transfers Memory identity.
    supports = pinned(root, "artifacts/g111-r1/delivery/actual/g111-r1-support.json")
    for oid, obs in data["observations"].items():
        original_support = [s for s in supports if s["fact_id"] == oid]
        if not original_support or any(
            s["memory_id"] != obs["memory_id"] for s in original_support
        ):
            raise ValueError("R1_OBSERVATION_SUPPORT_IDENTITY")
        obs["support_view_ids"] = sorted(
            {
                vid
                for s in original_support
                for vid, view in views.items()
                if covers(view, s["evidence"], texts)
            }
        )
        if not obs["support_view_ids"]:
            raise ValueError("R1_OBSERVATION_SUPPORT_NOT_VISIBLE")
    for rel in data["relations"].values():
        rel["support_view_options"] = [
            [vid for vid, view in views.items() if covers(view, e, texts)]
            for e in rel["source_support"]
        ]
        if any(not options for options in rel["support_view_options"]):
            raise ValueError("R1_RELATION_SUPPORT_NOT_VISIBLE")
    for operand in data["operands"].values():
        options = mapping[operand["view_id"]]
        if not options:
            raise ValueError("R1_OPERAND_NOT_VISIBLE")
        operand["view_id"] = options[0]
    if {x["memory_id"] for x in common["T0_memory_context"]} != set(data["t0_ids"]):
        raise ValueError("R1_T0_IDENTITY")
    for row in common["given_system_delta"]:
        obj = data["observations"][row["observation_id"]]
        if (
            row["memory_id"] != obj["memory_id"]
            or row["given_classification"] != obj["given_system_classification"]
        ):
            raise ValueError("R1_OBSERVATION_IDENTITY")
    for rel in common["given_relations"]:
        raw = data["relations"][rel["relation_id"]]
        if any(raw[k] != v for k, v in rel.items()):
            raise ValueError("R1_RELATION_IDENTITY")
    data.update(
        contract_version="G113_R1_TASK_BINDING_V1",
        arm=arm,
        task=common["required_topics"],
        views=views,
        w1_view_mapping=mapping,
        w3_original_payload=payload,
        topics=common["required_topics"],
        mode="HISTORICAL_TRANSITION_DIAGNOSTIC",
        w3_final_binding="PENDING_W3_FINAL_BINDING",
    )
    c = TaskCatalog(json.dumps(data, ensure_ascii=False), original.source_texts_json)
    for vid in views:
        c.resolve_view(vid)
    data["calculation_cards"] = verify_cards(
        w3(root, "inputs/CALCULATION_CARDS.json"), c
    )
    return TaskCatalog(json.dumps(data, ensure_ascii=False), original.source_texts_json)
