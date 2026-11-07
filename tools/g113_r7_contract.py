"""Prospective R7 ID-selection presentation over original R6 validation clauses.

No response migration, semantic repair, new source authority, or Memory access.
TaskCatalog remains a trusted projection; current send-time ACL/F01/CAS validation
is still mandatory and cannot be replaced by this offline interface candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError

from tools import g113_r1_contract as legacy
from tools import g113_r6_contract as previous
from tools.g107_matrix import strict_object
from tools.g113_contract import TaskCatalog
from tools.g113_prepare import pinned
from tools.g113_r1_binding import ROOT, covers

VERSION = "G113_R7_RESEARCH_INTERFACE_V1"
CHECKER_VERSION = "G113_R7_EVIDENCE_SAFE_CHECKER_V1"


class ResearchOutput(previous.ResearchOutput):
    """Keep existing natural-language fields; never fill a model's missing content."""

    # Pydantic rebuilds this field for the new contract; old responses stay invalid.
    contract_version: Literal["G113_R7_RESEARCH_INTERFACE_V1"]  # type: ignore[assignment]


def _selection_index(catalog: TaskCatalog) -> dict[str, Any]:
    data, texts = catalog.data(), json.loads(catalog.source_texts_json)
    views = {vid: catalog.resolve_view(vid) for vid in data["views"]}
    supports = pinned(ROOT, "artifacts/g111-r1/delivery/actual/g111-r1-support.json")
    choices: dict[str, Any] = {}
    for oid, observation in data["observations"].items():
        source_rows = [s for s in supports if s["fact_id"] == oid]
        if not source_rows or any(
            s["memory_id"] != observation["memory_id"] for s in source_rows
        ):
            raise ValueError("R7_OBSERVATION_SUPPORT_IDENTITY")
        exact = sorted(
            {
                vid
                for s in source_rows
                for vid, view in views.items()
                if covers(view, s["evidence"], texts)
            }
        )
        if not exact or exact != sorted(observation["support_view_ids"]):
            raise ValueError("R7_OBSERVATION_SUPPORT_BINDING")
        choices[oid] = dict(
            observation_id=oid,
            memory_id=observation["memory_id"],
            temporal_role=(
                "T0" if observation["memory_id"] in data["t0_ids"] else "T1"
            ),
            system_delta_classification=observation["given_system_classification"],
            supporting_view_ids=exact,
            selection_means="ACTUALLY_USED_DEPENDENCY_NOT_ALL_PROVIDED_BACKGROUND",
        )
    edges = {}
    for rid, relation in data["relations"].items():
        exact = [
            [vid for vid, view in views.items() if covers(view, support, texts)]
            for support in relation["source_support"]
        ]
        if any(not ids for ids in exact) or exact != relation["support_view_options"]:
            raise ValueError("R7_RELATION_SUPPORT_BINDING")
        if (
            relation["to_memory_id"] not in data["t0_ids"]
            or relation["from_memory_id"] not in data["memory_versions"]
        ):
            raise ValueError("R7_RELATION_ENDPOINT")
        edges[rid] = dict(
            relation_id=rid,
            from_memory_id=relation["from_memory_id"],
            to_memory_id=relation["to_memory_id"],
            supporting_view_options=exact,
            implication="REGISTERED_REPORTING_CONTEXT_NOT_CAUSAL_PROOF",
        )
    mapping = data["topic_observation_ids"]
    if set(mapping) != set(data["topics"]):
        raise ValueError("R7_TOPIC_SELECTION_POPULATION")
    result = {}
    for topic, ids in mapping.items():
        if (
            not isinstance(ids, list)
            or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(set(ids))
            or not set(ids) <= choices.keys()
        ):
            raise ValueError("R7_TOPIC_OBSERVATION_DOMAIN")
        current = {choices[i]["memory_id"] for i in ids}
        linked = {
            rid: edge
            for rid, edge in edges.items()
            if edge["from_memory_id"] in current
        }
        historical = sorted(
            current.intersection(data["t0_ids"])
            | {e["to_memory_id"] for e in linked.values()}
        )
        result[topic] = dict(
            selection_authority=data["topic_selection_status"],
            research_relevance="W3_SEMANTIC_BINDING_REQUIRED",
            provided_background_is_not_selected_dependency=True,
            observation_support_choices={i: choices[i] for i in ids},
            eligible_historical_memory_ids=historical,
            registered_relation_choices=linked,
            direct_history_observation_ids=[
                i for i in ids if choices[i]["memory_id"] in data["t0_ids"]
            ],
            available_view_ids=list(views),
            eligible_calculation_ids=[
                cid
                for cid, card in data["calculation_cards"].items()
                if set(card["original_card"]["observation_ids"]) <= set(ids)
            ],
            required_context_view_ids=data.get("w3_task_requirements", {})
            .get("required_views", {})
            .get(topic, []),
        )
    return result


def prospective_catalog(
    parent: TaskCatalog,
    *,
    topic_observation_ids: Mapping[str, Sequence[str]] | None = None,
) -> TaskCatalog:
    """Create an offline new version; optional topic domains are authored by W3.

    Without W3's prospective semantic choice, every visible observation remains
    mechanically selectable. This is explicitly pending, not a relevance guess.
    """
    data = parent.data()
    if data.get("research_interface_version") != previous.VERSION:
        raise ValueError("R7_REQUIRES_EXACT_R6_PARENT")
    data.update(
        research_interface_version=VERSION,
        parent_task_identity=parent.identity,
        w3_final_binding="PENDING_W3_R7_SEMANTIC_MATCH",
        topic_selection_status=(
            "W3_PROPOSED_REQUIRES_FINAL_BINDING"
            if topic_observation_ids is not None
            else "MECHANICAL_VISIBILITY_ONLY_PENDING_W3_TOPIC_SELECTION"
        ),
        topic_observation_ids=(
            {k: list(v) for k, v in topic_observation_ids.items()}
            if topic_observation_ids is not None
            else {k: list(data["observations"]) for k in data["topics"]}
        ),
        provided_memory_inventory=dict(
            t0_memory_ids=list(data["t0_ids"]),
            memory_versions=data["memory_versions"],
            provided_does_not_imply_cited_or_consumed=True,
        ),
        research_cutoff_authority=dict(
            information_cutoff=data["research_as_of"],
            authority="TRUSTED_RUN_METADATA_NOT_SOURCE_PUBLICATION_TIME",
            response_rule="EXACT_CONST_NO_POSTPROCESS_REPAIR",
        ),
    )
    candidate = TaskCatalog(
        json.dumps(data, ensure_ascii=False), parent.source_texts_json
    )
    data["topic_selection_index"] = _selection_index(candidate)
    return TaskCatalog(json.dumps(data, ensure_ascii=False), parent.source_texts_json)


def topic_choices(catalog: TaskCatalog) -> dict[str, Any]:
    """Resolve exact source-supported choices; no similarity or opaque-ID repair."""
    data = catalog.data()
    if data.get("research_interface_version") != VERSION:
        raise ValueError("R7_CATALOG_VERSION")
    expected = _selection_index(catalog)
    if data.get("topic_selection_index") != expected:
        raise ValueError("R7_TOPIC_INDEX_DRIFT")
    if data.get("provided_memory_inventory") != dict(
        t0_memory_ids=list(data["t0_ids"]),
        memory_versions=data["memory_versions"],
        provided_does_not_imply_cited_or_consumed=True,
    ):
        raise ValueError("R7_PROVIDED_MEMORY_DRIFT")
    if data.get("research_cutoff_authority") != dict(
        information_cutoff=data["research_as_of"],
        authority="TRUSTED_RUN_METADATA_NOT_SOURCE_PUBLICATION_TIME",
        response_rule="EXACT_CONST_NO_POSTPROCESS_REPAIR",
    ):
        raise ValueError("R7_CUTOFF_AUTHORITY_DRIFT")
    return expected


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Expose exact cutoff and allowed per-topic selections, retaining R6 fields."""
    data, index = catalog.data(), topic_choices(catalog)
    schema = ResearchOutput.model_json_schema()
    original = legacy.output_schema(catalog)
    for key in ("task_identity", "role"):
        schema["properties"][key] = original["properties"][key]
    for cls in ("Application", "Coverage"):
        for field, value in original["$defs"][cls]["properties"].items():
            schema["$defs"][cls]["properties"][field] = value
    app = schema["$defs"]["Application"]
    app["properties"]["information_cutoff"] = {"const": data["research_as_of"]}
    schema["$defs"]["CalculationContext"]["properties"]["calculation_id"] = {
        "enum": list(data["calculation_cards"])
    }
    app["allOf"] = []
    for topic, row in index.items():
        domains = {
            "historical_memory_ids": row["eligible_historical_memory_ids"],
            "new_observation_ids": list(row["observation_support_choices"]),
            "relation_ids": list(row["registered_relation_choices"]),
            "calculation_ids": row["eligible_calculation_ids"],
        }
        app["allOf"].append(
            dict(
                **{"if": {"properties": {"topic_id": {"const": topic}}}},
                then={
                    "properties": {
                        key: {"items": {"enum": ids} if ids else False}
                        for key, ids in domains.items()
                    }
                },
            )
        )
    return schema


def diagnose(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Accumulate new shape checks and unchanged original scientific clauses."""
    schema = output_schema(catalog)
    result: dict[str, Any] = dict(
        checker_version=CHECKER_VERSION,
        evaluated_contract_version=VERSION,
        raw_utf8_sha256=hashlib.sha256(text.encode()).hexdigest(),
        research_output_accepted=False,
        scientific_admission=False,
        semantic_validation="PENDING_INDEPENDENT_REVIEW",
        errors=[],
        schema_errors=[],
        shape_errors=[],
        clause_errors=[],
        not_evaluated=[],
        diagnostic_status="DIAGNOSTIC_PARTIAL",
    )
    try:
        obj = strict_object(text)
    except (ValueError, TypeError) as exc:
        result["errors"] = [
            dict(
                code="JSON_SYNTAX_OR_DUPLICATE_KEY",
                json_pointer="",
                details=dict(error_type=type(exc).__name__),
            )
        ]
        result["not_evaluated"] = [dict(path="", reason="JSON_OBJECT_UNAVAILABLE")]
        return result
    result["schema_errors"] = [
        dict(
            code="DYNAMIC_JSON_SCHEMA",
            json_pointer=previous.pointer(e.absolute_path),
            keyword=e.validator,
            schema_pointer=previous.pointer(e.absolute_schema_path),
        )
        for e in Draft202012Validator(schema).iter_errors(obj)
    ]
    try:
        ResearchOutput.model_validate(obj)
    except ValidationError as exc:
        result["shape_errors"] = [
            dict(
                code="STRICT_RESPONSE_SHAPE",
                json_pointer=previous.pointer(e["loc"]),
                type=e["type"],
            )
            for e in exc.errors(include_input=False, include_url=False)
        ]
    # Reuse, do not fork or weaken, all R6 Memory/Observation/Relation/Source,
    # clock, disposition, card, fiscal period and coverage predicates.
    clauses = previous._clauses(obj, catalog, r6=True)
    result["clause_errors"] = clauses.errors
    result["not_evaluated"] = clauses.skipped
    result["errors"] = result["schema_errors"] + result["shape_errors"] + clauses.errors
    result["diagnostic_status"] = (
        "DIAGNOSTIC_PARTIAL" if clauses.skipped else "DIAGNOSTIC_COMPLETE"
    )
    result["semantic_review_required"] = [
        "SOURCE_ENTAILMENT",
        "FISCAL_PERIOD_IN_PROSE",
        "INFERENCE_SCOPE",
        "COUNTEREVIDENCE",
        "UNKNOWN_ECONOMICS",
        "TOPIC_RELEVANCE_AND_W3_TASK_COMPLETENESS",
    ]
    return result


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Reject every deterministic failure; never certify long-tail prose by shape."""
    diagnostic = diagnose(text, catalog)
    if diagnostic["errors"] or diagnostic["not_evaluated"]:
        raise ValueError("R7_CONTRACT_REJECTED:" + json.dumps(diagnostic))
    obj = ResearchOutput.model_validate(strict_object(text))
    return dict(
        contract_version=VERSION,
        checker_version=CHECKER_VERSION,
        mechanical_binding="PASS",
        original_output=obj.model_dump(),
        expanded_views=[
            catalog.resolve_view(v) for a in obj.applications for v in a.view_ids
        ],
        expanded_calculations=[
            catalog.data()["calculation_cards"][cid]
            for a in obj.applications
            for cid in a.calculation_ids
        ],
        diagnostic=diagnostic,
        research_output_accepted=False,
        world_fact_authority=False,
        scientific_memory_admitted=False,
        semantic_review="PENDING_INDEPENDENT_REVIEW",
    )
