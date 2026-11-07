"""Versioned offline R9 integrity extension of the unchanged R8 evidence contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tools import g113_r8_contract as r8
from tools.g107_matrix import strict_object
from tools.g113_contract import TaskCatalog
from tools.g113_r9_integrity import amount_display, prose_errors, strict_json_diagnostic

VERSION = "G113_R9_MINIMAL_RESEARCH_INTERFACE_V1"
CHECKER_VERSION = "G113_R9_EVIDENCE_SAFE_CHECKER_V1"
JSON_OUTPUT_RULE = (
    "Return exactly one raw JSON object. No Markdown fences or surrounding text."
)


def prospective_catalog(parent: TaskCatalog) -> TaskCatalog:
    """Version the interface envelope without rewriting task or source semantics."""
    r8.reference_catalog(parent)
    data = parent.data()
    data.update(
        research_interface_version=VERSION,
        r9_parent_catalog_identity=parent.identity,
        r9_parent_w3_binding=data["w3_final_binding"],
        w3_final_binding="PENDING_W3_R9_MATCH",
    )
    return TaskCatalog(json.dumps(data, ensure_ascii=False), parent.source_texts_json)


def parent_catalog(catalog: TaskCatalog) -> TaskCatalog:
    """Reverse only the declared version envelope and verify its parent identity."""
    data = catalog.data()
    if data.get("research_interface_version") != VERSION:
        raise ValueError("R9_CATALOG_VERSION")
    if data.get("w3_final_binding") != "PENDING_W3_R9_MATCH":
        raise ValueError("R9_CANDIDATE_BINDING_IDENTITY")
    identity = data.pop("r9_parent_catalog_identity", None)
    data["w3_final_binding"] = data.pop("r9_parent_w3_binding", None)
    data["research_interface_version"] = r8.VERSION
    parent = TaskCatalog(
        json.dumps(data, ensure_ascii=False), catalog.source_texts_json
    )
    if parent.identity != identity:
        raise ValueError("R9_PARENT_CATALOG_DRIFT")
    r8.reference_catalog(parent)
    return parent


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Preserve R8 semantics and exact handles under the new version identity."""
    schema = r8.output_schema(parent_catalog(catalog))
    schema["properties"]["contract_version"]["const"] = VERSION
    schema["properties"]["task_identity"] = {"const": catalog.identity}
    return schema


def display_cards(catalog: TaskCatalog) -> dict[str, Any]:
    """Present verified existing operands/deltas with a single canonical unit string."""
    parent = parent_catalog(catalog)
    refs = r8.reference_catalog(parent)
    result = {}
    for handle, card in r8.display_cards(parent).items():
        result[handle] = dict(card, canonical_text=f"USD {card['value']} billion")
    for handle, identity in refs["calculation_ids"].items():
        card = parent.data()["calculation_cards"][identity]
        delta = card["deterministic_operations"]["delta_USDmillion"][
            "deterministic_value"
        ]
        result[handle] = dict(
            amount_display(
                delta, currency="USD", native_scale=6, display_scale=9, decimal_places=1
            ),
            operation="DIFFERENCE",
            periods=card["original_card"]["periods"],
            observation_ids=card["original_card"]["observation_ids"],
            original_value_USDmillion=delta,
            calculation_id=identity,
            authority="SYSTEM_DERIVED_SOURCE_DISPLAY_NOT_MODEL_DISCOVERY",
            native_scientific_admission=False,
        )
    return result


def topic_reference_navigation(catalog: TaskCatalog) -> dict[str, Any]:
    """Expose exact topic-to-view handles; keep existing source text unchanged."""
    parent = parent_catalog(catalog)
    refs, data = r8.reference_catalog(parent), parent.data()
    reverse = {identity: handle for handle, identity in refs["view_ids"].items()}
    return {
        topic: dict(
            required_context_views=[
                reverse[v] for v in index["required_context_view_ids"]
            ],
            evidence_location="EXISTING_CONTEXT_EVIDENCE_UNCHANGED",
            provided_is_not_used=True,
            source_entailment="PENDING_INDEPENDENT_RESEARCH_EVALUATION",
        )
        for topic, index in data["topic_selection_index"].items()
    }


def diagnose(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Apply raw integrity and inherited checks; reject old-version output."""
    parent = parent_catalog(catalog)
    raw_sha = hashlib.sha256(text.encode()).hexdigest()
    report: dict[str, Any] = dict(
        checker_version=CHECKER_VERSION,
        raw_utf8_sha256=raw_sha,
        errors=[],
        not_evaluated=[],
        research_output_accepted=False,
        scientific_admission=False,
        semantic_validation="PENDING_INDEPENDENT_REVIEW",
    )
    syntax = strict_json_diagnostic(text)
    if not syntax["valid"]:
        return dict(
            report,
            errors=syntax["errors"],
            diagnostic_status="DIAGNOSTIC_PARTIAL",
            not_evaluated=["JSON_OBJECT_UNAVAILABLE_NO_REPAIR"],
        )
    obj = strict_object(text)
    errors = prose_errors(obj)
    if (
        obj.get("contract_version") != VERSION
        or obj.get("task_identity") != catalog.identity
    ):
        errors.append(dict(code="R9_VERSION_OR_TASK_IDENTITY", json_pointer=""))
        return dict(
            report,
            errors=errors,
            diagnostic_status="DIAGNOSTIC_PARTIAL",
            not_evaluated=["CONTRACT_VERSION_MISMATCH_NO_MIGRATION"],
        )
    # Explicit protocol-only compatibility view. No research field is added, removed,
    # defaulted, corrected or reordered. Original model bytes remain authoritative.
    projection = dict(obj, contract_version=r8.VERSION, task_identity=parent.identity)
    inherited = r8.diagnose(json.dumps(projection, ensure_ascii=False), parent)
    report.update(
        errors=inherited["errors"] + errors,
        not_evaluated=inherited["not_evaluated"],
        diagnostic_status=inherited["diagnostic_status"],
        system_temporal_binding=inherited.get("system_temporal_binding"),
        semantic_review_required=inherited.get("semantic_review_required"),
        compatibility_projection_fields=["contract_version", "task_identity"],
        numerical_prose_scope="EXPLICIT_LOCAL_UNIT_CONFLICTS_ONLY_NOT_FULL_FACT_GROUNDING",
    )
    return report


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Fail closed on integrity/binding errors; never award scientific acceptance."""
    diagnostic = diagnose(text, catalog)
    if diagnostic["errors"] or diagnostic["not_evaluated"]:
        raise ValueError("R9_CONTRACT_REJECTED:" + json.dumps(diagnostic))
    return dict(
        contract_version=VERSION,
        mechanical_binding="PASS",
        original_output=strict_object(text),
        raw_utf8_sha256=diagnostic["raw_utf8_sha256"],
        diagnostic=diagnostic,
        research_output_accepted=False,
        scientific_admission=False,
    )
