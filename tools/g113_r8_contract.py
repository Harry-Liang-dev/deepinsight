"""R8 offline candidate: exact references, independent usage/disposition, no admission.

The trusted catalog is an existing TaskCatalog projection, never a new registry.
No old response is migrated. System time is a separate binding, not model prose.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError

from tools import g113_r1_contract as r1
from tools import g113_r6_contract as r6
from tools import g113_r7_contract as r7
from tools.g107_matrix import strict_object
from tools.g113_contract import Calculation, Record, Role, TaskCatalog, Text, calculate
from tools.g113_r1_binding import covers, verify_cards

VERSION = "G113_R8_MINIMAL_RESEARCH_INTERFACE_V1"
CHECKER_VERSION = "G113_R8_EVIDENCE_SAFE_CHECKER_V1"
DOMAINS = {
    "historical_memory_ids": ("M", "memory_versions"),
    "new_observation_ids": ("O", "observations"),
    "relation_ids": ("R", "relations"),
    "view_ids": ("V", "views"),
    "calculation_ids": ("C", "calculation_cards"),
}


class Application(r1.Application):
    """Preserve narrative fields; source context and conditional analysis differ."""

    proposition_scope: Literal[
        "KNOWN_SOURCE_CONTEXT", "CONDITIONAL_ANALYSIS", "ECONOMIC_OR_CAUSAL_INFERENCE"
    ]
    source_evidence_adequacy: Literal[
        "SOURCE_SUPPORTED_CONTEXT", "MISSING_KEY_EVIDENCE"
    ]
    conclusion_scope: Literal["PROVIDED_SOURCE_SNAPSHOT_ONLY"]
    deferred_inferences: list[r6.DeferredInference]
    calculation_contexts: list[r6.CalculationContext]


class Coverage(Record):
    """APPLIED describes declared use, not whether judgment changed."""

    topic_id: Text
    status: Literal["APPLIED", "NOT_APPLIED"]
    reason: Text


class ResearchOutput(Record):
    """New version, required fields, strict types, no default research conclusions."""

    contract_version: Literal["G113_R8_MINIMAL_RESEARCH_INTERFACE_V1"]
    task_identity: Text
    role: Role
    completion_status: Literal["RESULT", "PARTIAL", "NO_RESULT"]
    applications: list[Application]
    topic_coverage: list[Coverage]
    source_revision_status: Literal[
        "NO_REVISION_IN_GIVEN_CASE", "UNKNOWN_REQUIRES_REVIEW"
    ]
    missing_key_information: list[Text]
    completion_explanation: Text


def prospective_catalog(parent: TaskCatalog) -> TaskCatalog:
    """Version a verified R7 projection; W3 must separately bind the new task."""
    r7.topic_choices(parent)
    data = parent.data()
    data.update(
        research_interface_version=VERSION,
        parent_task_identity=parent.identity,
        w3_final_binding="PENDING_W3_R8_MATCH",
    )
    return TaskCatalog(json.dumps(data, ensure_ascii=False), parent.source_texts_json)


def reference_catalog(catalog: TaskCatalog) -> dict[str, dict[str, str]]:
    """One deterministic, task-bound typed handle table; never approximate an ID."""
    data = catalog.data()
    if data.get("research_interface_version") != VERSION:
        raise ValueError("R8_CATALOG_VERSION")
    if (
        data["research_cutoff_authority"]["information_cutoff"]
        != data["research_as_of"]
    ):
        raise ValueError("R8_TRUSTED_CUTOFF_DRIFT")
    if (
        data["provided_memory_inventory"]["t0_memory_ids"] != data["t0_ids"]
        or data["provided_memory_inventory"]["memory_versions"]
        != data["memory_versions"]
    ):
        raise ValueError("R8_MEMORY_INVENTORY_DRIFT")
    # Revalidate every Observation's original support, native source range and clock.
    if r7._selection_index(catalog) != data["topic_selection_index"]:
        raise ValueError("R8_SOURCE_TOPIC_INDEX_DRIFT")
    if (
        verify_cards(
            [x["original_card"] for x in data["calculation_cards"].values()], catalog
        )
        != data["calculation_cards"]
    ):
        raise ValueError("R8_CALCULATION_CARD_DRIFT")
    return {
        field: {
            f"{prefix}{i:02}": identity
            for i, identity in enumerate(sorted(data[key]), 1)
        }
        for field, (prefix, key) in DOMAINS.items()
    }


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Compact typed domains once; topic restrictions stay in trusted validation."""
    refs, d = reference_catalog(catalog), catalog.data()
    schema = ResearchOutput.model_json_schema()
    schema["properties"]["task_identity"] = {"const": catalog.identity}
    schema["properties"]["role"] = {"const": d["role"]}
    for cls in ("Application", "Coverage"):
        schema["$defs"][cls]["properties"]["topic_id"] = {"enum": list(d["topics"])}
    for field, mapping in refs.items():
        allowed = [
            h
            for h, identity in mapping.items()
            if field != "historical_memory_ids" or identity in d["t0_ids"]
        ]
        schema["$defs"]["Application"]["properties"][field]["items"] = (
            {"enum": allowed} if allowed else False
        )
    schema["$defs"]["CalculationContext"]["properties"]["calculation_id"] = {
        "enum": list(refs["calculation_ids"])
    }
    return schema


def system_temporal_binding(catalog: TaskCatalog) -> dict[str, Any]:
    """Preserve source clocks separately; invocation time comes only from executor."""
    return dict(
        authority="SYSTEM_BOUND_TEMPORAL_METADATA",
        research_as_of=catalog.data()["research_as_of"],
        source_clocks=catalog.data()["sources"],
        actual_invocation_at=None,
        actual_invocation_rule="RECORDED_BY_FUTURE_EXECUTOR_NO_BACKFILL",
        model_temporal_reasoning="NOT_PROVEN_BY_SYSTEM_METADATA",
    )


def display_cards(catalog: TaskCatalog) -> dict[str, Any]:
    """Ground operands first, then exact USD to billion with one HALF_UP rounding."""
    refs, d = reference_catalog(catalog), catalog.data()
    reverse = {v: k for k, v in refs["new_observation_ids"].items()}
    result = {}
    for oid, op in d["operands"].items():
        checked = calculate(
            Calculation(
                old_operand_id=oid,
                new_operand_id=oid,
                operation="UNIT_CONVERSION",
                output_unit="USD",
                decimal_places=0,
                reported_value=op["value"],
            ),
            catalog,
        )
        with localcontext() as ctx:
            ctx.prec = 100
            value = (
                Decimal(checked["deterministic_value"]) / Decimal("1000000000")
            ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        result[reverse[oid]] = dict(
            value=str(value),
            currency="USD",
            unit="BILLION",
            scale=9,
            fiscal_period=dict(start=op["start"], end=op["end"]),
            original_usd=op["value"],
            original_native=op["native_observation"],
            source_view=op["view_id"],
            rounding="ROUND_HALF_UP",
            decimal_places=1,
            authority="SYSTEM_DERIVED_SOURCE_DISPLAY_NOT_MODEL_DISCOVERY",
            native_scientific_admission=False,
        )
    return result


def validate_display_value(
    catalog: TaskCatalog,
    observation_handle: str,
    value: str,
    *,
    currency: str,
    unit: str,
    scale: int,
    fiscal_period: dict[str, str],
) -> dict[str, Any]:
    """Compare a declared common amount exactly; never rewrite arbitrary prose."""
    card = display_cards(catalog).get(observation_handle)
    if card is None or any(
        card[k] != v
        for k, v in dict(
            value=value,
            currency=currency,
            unit=unit,
            scale=scale,
            fiscal_period=fiscal_period,
        ).items()
    ):
        raise ValueError("R8_FINANCIAL_DISPLAY_MISMATCH")
    return dict(binding="EXACT_SOURCE_DISPLAY", card=card, scientific_admission=False)


def _references(
    app: dict[str, Any],
    catalog: TaskCatalog,
    table: dict[str, dict[str, str]],
    out: r6.Diagnostics,
    path: str,
) -> dict[str, list[str]] | None:
    d, expanded = catalog.data(), {}
    for field, mapping in table.items():
        handles = out.ids(app, field, path)
        if handles is None:
            return None
        unknown = [h for h in handles if h not in mapping]
        if unknown:
            out.add("R8_UNKNOWN_TYPED_REFERENCE", path + "/" + field, unknown=unknown)
        expanded[field] = [mapping[h] for h in handles if h in mapping]
    old, current = set(expanded["historical_memory_ids"]), {
        d["observations"][o]["memory_id"] for o in expanded["new_observation_ids"]
    }
    if not old <= set(d["t0_ids"]):
        out.add("R8_NOT_T0_MEMORY", path + "/historical_memory_ids")
    topic = app.get("topic_id")
    index = d["topic_selection_index"].get(topic) if isinstance(topic, str) else None
    if index is not None:
        for field, key in [
            ("historical_memory_ids", "eligible_historical_memory_ids"),
            ("new_observation_ids", "observation_support_choices"),
            ("relation_ids", "registered_relation_choices"),
            ("calculation_ids", "eligible_calculation_ids"),
        ]:
            if not set(expanded[field]) <= set(index[key]):
                out.add("R8_TOPIC_REFERENCE_DOMAIN", path + "/" + field)
        if not set(index["required_context_view_ids"]) <= set(expanded["view_ids"]):
            out.add("R8_REQUIRED_CONTEXT_VIEW", path + "/view_ids")
    views, linked = set(expanded["view_ids"]), set()
    for rid in expanded["relation_ids"]:
        rel = d["relations"][rid]
        if rel["from_memory_id"] not in current or rel["to_memory_id"] not in old:
            out.add("R8_RELATION_ENDPOINT", path + "/relation_ids")
        if any(not set(options) & views for options in rel["support_view_options"]):
            out.add("R8_RELATION_SOURCE_SUPPORT", path + "/view_ids")
        linked.add(rel["to_memory_id"])
    if app.get("relation_status") == "LINKED" and (not linked or linked != old):
        out.add("R8_INCOMPLETE_HISTORY_CHAIN", path)
    if app.get("relation_status") == "UNAVAILABLE" and expanded["relation_ids"]:
        out.add("R8_UNAVAILABLE_WITH_RELATION", path + "/relation_ids")
    for oid in expanded["new_observation_ids"]:
        if not set(d["observations"][oid]["support_view_ids"]) & views:
            out.add("R8_OBSERVATION_SUPPORT", path + "/view_ids", observation_id=oid)
    for cid in expanded["calculation_ids"]:
        if not set(
            d["calculation_cards"][cid]["original_card"]["observation_ids"]
        ) <= set(expanded["new_observation_ids"]):
            out.add("R8_CALCULATION_OPERAND_CHAIN", path + "/calculation_ids")
    return expanded


def _disposition(
    app: dict[str, Any],
    refs: dict[str, list[str]],
    catalog: TaskCatalog,
    table: dict[str, dict[str, str]],
    found: r6.Diagnostics,
    path: str,
) -> None:
    d, effect = catalog.data(), app.get("effect")
    scope, adequacy = app.get("proposition_scope"), app.get("source_evidence_adequacy")
    if (
        adequacy == "MISSING_KEY_EVIDENCE" or scope == "ECONOMIC_OR_CAUSAL_INFERENCE"
    ) and effect != "DEFER_MISSING_EVIDENCE":
        found.add("R8_UNSUPPORTED_MECHANISM_MUST_DEFER", path + "/effect")
    if scope == "CONDITIONAL_ANALYSIS" and (
        not app.get("deferred_inferences") or not app.get("unknown_conditions")
    ):
        found.add("R8_CONDITIONAL_LIMITS_REQUIRED", path + "/deferred_inferences")
    observations = [d["observations"][o] for o in refs["new_observation_ids"]]
    if effect == "DEFER_MISSING_EVIDENCE":
        if not app.get("unknown_conditions"):
            found.add("R8_MISSING_EVIDENCE_REQUIRED", path + "/unknown_conditions")
    if not refs["historical_memory_ids"] or not observations or not refs["view_ids"]:
        found.add("R8_SUPPORTED_CHAIN_REQUIRED", path)
    if app.get("relation_status") == "UNAVAILABLE" and not set(
        refs["historical_memory_ids"]
    ) <= {o["memory_id"] for o in observations}:
        found.add("R8_DIRECT_HISTORY_OBSERVATION_REQUIRED", path)
    if effect == "UPDATE_CONTEXT":
        texts = json.loads(catalog.source_texts_json)
        if not any(
            o["given_system_classification"]
            in {"NEW_FACT", "NEW_EVIDENCE_FOR_EXISTING_FACT"}
            and any(
                covers(d["views"][v], e, texts)
                for v in refs["view_ids"]
                for e in o["added_source_support"]
            )
            for o in observations
        ):
            found.add("R8_UPDATE_REQUIRES_NEW_SUPPORT", path + "/effect")
    contexts = app.get("calculation_contexts")
    if isinstance(contexts, list) and all(isinstance(x, dict) for x in contexts):
        ids = [x.get("calculation_id") for x in contexts]
        expected = {
            h
            for h, cid in table["calculation_ids"].items()
            if cid in refs["calculation_ids"]
        }
        if (
            len(set(str(x) for x in ids)) != len(ids)
            or set(str(x) for x in ids) != expected
        ):
            found.add(
                "R8_CALCULATION_CONTEXT_POPULATION", path + "/calculation_contexts"
            )
        for i, ctx in enumerate(contexts):
            cid = table["calculation_ids"].get(str(ctx.get("calculation_id")))
            if cid is not None and (
                ctx.get("periods")
                != d["calculation_cards"][cid]["original_card"]["periods"]
                or ctx.get("unit") != "USD_MILLION"
            ):
                found.add(
                    "R8_CALCULATION_PERIOD_UNIT", path + f"/calculation_contexts/{i}"
                )


def diagnose(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Return all decidable errors, retaining original bytes and independent review."""
    table, schema, found = (
        reference_catalog(catalog),
        output_schema(catalog),
        r6.Diagnostics(),
    )
    result: dict[str, Any] = dict(
        checker_version=CHECKER_VERSION,
        raw_utf8_sha256=hashlib.sha256(text.encode()).hexdigest(),
        research_output_accepted=False,
        scientific_admission=False,
        semantic_validation="PENDING_INDEPENDENT_REVIEW",
        errors=[],
        not_evaluated=[],
    )
    try:
        obj = strict_object(text)
    except (ValueError, TypeError):
        result.update(
            errors=[dict(code="JSON_SYNTAX_OR_DUPLICATE_KEY", json_pointer="")],
            diagnostic_status="DIAGNOSTIC_PARTIAL",
            not_evaluated=["JSON_OBJECT_UNAVAILABLE"],
        )
        return result
    errors = [
        dict(
            code="DYNAMIC_JSON_SCHEMA",
            json_pointer=r6.pointer(e.absolute_path),
            keyword=e.validator,
        )
        for e in Draft202012Validator(schema).iter_errors(obj)
    ]
    try:
        ResearchOutput.model_validate(obj)
    except ValidationError as exc:
        errors.extend(
            dict(
                code="STRICT_RESPONSE_SHAPE",
                json_pointer=r6.pointer(e["loc"]),
                type=e["type"],
            )
            for e in exc.errors(include_input=False, include_url=False)
        )
    # Old outputs are never silently translated, including references and cutoff.
    if obj.get("contract_version") != VERSION:
        result.update(
            errors=errors,
            diagnostic_status="DIAGNOSTIC_PARTIAL",
            not_evaluated=["CONTRACT_VERSION_MISMATCH_NO_MIGRATION"],
        )
        return result
    applications, coverage = obj.get("applications"), obj.get("topic_coverage")
    if not isinstance(applications, list) or not isinstance(coverage, list):
        result.update(
            errors=errors,
            diagnostic_status="DIAGNOSTIC_PARTIAL",
            not_evaluated=["APPLICATION_OR_COVERAGE_SHAPE"],
        )
        return result
    apps = [a for a in applications if isinstance(a, dict)]
    cov = [c for c in coverage if isinstance(c, dict)]
    app_topics = [a.get("topic_id") for a in apps if isinstance(a.get("topic_id"), str)]
    cov_topics = [c.get("topic_id") for c in cov if isinstance(c.get("topic_id"), str)]
    topics = set(catalog.data()["topics"])
    if len(set(app_topics)) != len(app_topics) or len(set(cov_topics)) != len(
        cov_topics
    ):
        found.add("R8_DUPLICATE_TOPIC", "/applications")
    if set(cov_topics) != topics:
        found.add("R8_TOPIC_COVERAGE", "/topic_coverage")
    for i, app in enumerate(applications):
        if not isinstance(app, dict):
            found.skipped.append(
                dict(path=f"/applications/{i}", reason="INVALID_APPLICATION_OBJECT")
            )
            continue
        path = f"/applications/{i}"
        refs = _references(app, catalog, table, found, path)
        if refs is not None:
            _disposition(app, refs, catalog, table, found, path)
        matching = [c for c in cov if c.get("topic_id") == app.get("topic_id")]
        if len(matching) != 1 or matching[0].get("status") != "APPLIED":
            found.add("R8_APPLICATION_COVERAGE_CONFLICT", path + "/topic_id")
    active = {
        c["topic_id"]
        for c in cov
        if isinstance(c.get("topic_id"), str) and c.get("status") == "APPLIED"
    }
    if not active <= set(app_topics):
        found.add("R8_MISSING_APPLICATION", "/applications")
    required = "RESULT" if active == topics else "PARTIAL" if active else "NO_RESULT"
    if obj.get("completion_status") != required:
        found.add("R8_COMPLETION_COVERAGE", "/completion_status")
    if not active and not obj.get("missing_key_information"):
        found.add("R8_NO_RESULT_REASON", "/missing_key_information")
    result.update(
        errors=errors + found.errors,
        not_evaluated=found.skipped,
        diagnostic_status=(
            "DIAGNOSTIC_PARTIAL" if found.skipped else "DIAGNOSTIC_COMPLETE"
        ),
        system_temporal_binding=system_temporal_binding(catalog),
        semantic_review_required=[
            "SOURCE_ENTAILMENT",
            "BODY_DISPOSITION_CONFLICT",
            "CAUSAL_OVERREACH",
            "COUNTEREVIDENCE_APPLICATION",
            "FISCAL_PERIOD_AND_UNDECLARED_PROSE_AMOUNTS",
            "MODEL_TEMPORAL_REASONING",
        ],
    )
    return result


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Bind mechanical results only; a correct shape never proves research quality."""
    diagnostic = diagnose(text, catalog)
    if diagnostic["errors"] or diagnostic["not_evaluated"]:
        raise ValueError("R8_CONTRACT_REJECTED:" + json.dumps(diagnostic))
    return dict(
        contract_version=VERSION,
        mechanical_binding="PASS",
        original_output=strict_object(text),
        reference_catalog=reference_catalog(catalog),
        system_temporal_binding=system_temporal_binding(catalog),
        diagnostic=diagnostic,
        research_output_accepted=False,
        scientific_admission=False,
        semantic_review="PENDING_INDEPENDENT_REVIEW",
    )
