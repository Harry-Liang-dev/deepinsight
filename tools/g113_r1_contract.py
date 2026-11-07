"""Versioned W1 mechanical / W3 semantic-task contract, never scientific State."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from tools.g107_matrix import strict_object
from tools.g113_contract import Record, Role, TaskCatalog, Text, classify_memory, unique

VERSION = "G113_R1_RESEARCH_MEMORY_INTERFACE_V1"
IDs = list[Text]


class Application(Record):
    """No fabricated past Agent judgment, relation, default text or model hashes."""

    topic_id: Text
    historical_memory_ids: IDs = Field(json_schema_extra={"uniqueItems": True})
    new_observation_ids: IDs = Field(json_schema_extra={"uniqueItems": True})
    relation_ids: IDs = Field(json_schema_extra={"uniqueItems": True})
    view_ids: IDs = Field(json_schema_extra={"uniqueItems": True})
    calculation_ids: IDs = Field(json_schema_extra={"uniqueItems": True})
    relation_status: Literal["LINKED", "UNAVAILABLE"]
    historical_context: Text
    relation_explanation: Text
    effect: Literal[
        "UPDATE_CONTEXT",
        "MAINTAIN_CONTEXT",
        "DEFER_MISSING_EVIDENCE",
        "NO_SUPPORTED_CHANGE",
    ]
    application: Text
    unknown_conditions: list[Text]


class Coverage(Record):
    """Require every requested topic; missing evidence is a valid explicit result."""

    topic_id: Text
    status: Literal[
        "APPLIED",
        "MAINTAINED",
        "DEFERRED_MISSING_INFORMATION",
        "BLOCKED_MISSING_EVIDENCE",
    ]
    reason: Text


class ResearchOutput(Record):
    """New opt-in interface; neither old W1 nor old W3 responses are transformed."""

    contract_version: Literal["G113_R1_RESEARCH_MEMORY_INTERFACE_V1"]
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


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Expose actual role/topic/ID domains; runtime still checks endpoint semantics."""
    d = catalog.data()
    s = ResearchOutput.model_json_schema()
    s["properties"]["task_identity"] = {"const": catalog.identity}
    s["properties"]["role"] = {"const": d["role"]}
    for key in ("Application", "Coverage"):
        s["$defs"][key]["properties"]["topic_id"] = {"enum": list(d["topics"])}
    app = s["$defs"]["Application"]["properties"]
    for field, values in (
        ("historical_memory_ids", d["t0_ids"]),
        ("new_observation_ids", list(d["observations"])),
        ("relation_ids", list(d["relations"])),
        ("view_ids", list(d["views"])),
        ("calculation_ids", list(d["calculation_cards"])),
    ):
        app[field]["items"] = {"enum": values}
    return s


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Bind exact references without filling prose or asserting semantic support."""
    obj = ResearchOutput.model_validate(strict_object(text))
    d = catalog.data()
    if obj.task_identity != catalog.identity or obj.role != d["role"]:
        raise ValueError("R1_TASK_ROLE")
    topics = set(d["topics"])
    unique([a.topic_id for a in obj.applications], "APPLICATION_TOPIC")
    unique([c.topic_id for c in obj.topic_coverage], "COVERAGE_TOPIC")
    if {c.topic_id for c in obj.topic_coverage} != topics:
        raise ValueError("R1_INCOMPLETE_TOPIC_COVERAGE")
    coverage = {c.topic_id: c for c in obj.topic_coverage}
    apps = {a.topic_id: a for a in obj.applications}
    if not set(apps) <= topics:
        raise ValueError("R1_WRONG_ROLE_TOPIC")
    rows = []
    for app in obj.applications:
        for key in (
            "historical_memory_ids",
            "new_observation_ids",
            "relation_ids",
            "view_ids",
            "calculation_ids",
        ):
            unique(getattr(app, key), key)
        classes = classify_memory(app.historical_memory_ids, catalog)
        if classes["T1"] or classes["UNKNOWN"]:
            raise ValueError("R1_NOT_T0_MEMORY")
        if not set(app.new_observation_ids) <= d["observations"].keys():
            raise ValueError("R1_UNKNOWN_OBSERVATION")
        if not set(app.calculation_ids) <= d["calculation_cards"].keys():
            raise ValueError("R1_UNAUTHORIZED_CALCULATION")
        resolved = [catalog.resolve_view(vid) for vid in app.view_ids]
        current = {
            d["observations"][oid]["memory_id"] for oid in app.new_observation_ids
        }
        linked_old, linked_new = set(), set()
        for rid in app.relation_ids:
            rel = d["relations"].get(rid)
            if rel is None:
                raise ValueError("R1_UNKNOWN_RELATION")
            if (
                rel["from_memory_id"] not in current
                or rel["to_memory_id"] not in app.historical_memory_ids
            ):
                raise ValueError("R1_RELATION_ENDPOINT")
            if any(
                not set(options).intersection(app.view_ids)
                for options in rel["support_view_options"]
            ):
                raise ValueError("R1_RELATION_SOURCE_SUPPORT")
            linked_old.add(rel["to_memory_id"])
            linked_new.add(rel["from_memory_id"])
        if app.relation_status == "LINKED":
            if (
                not app.relation_ids
                or not app.historical_memory_ids
                or linked_old != set(app.historical_memory_ids)
            ):
                raise ValueError("R1_INCOMPLETE_HISTORY_CHAIN")
        elif (
            app.relation_ids
            or app.effect != "DEFER_MISSING_EVIDENCE"
            or not app.unknown_conditions
        ):
            raise ValueError("R1_UNAVAILABLE_RELATION_MUST_DEFER")
        for oid in app.new_observation_ids:
            if not set(d["observations"][oid]["support_view_ids"]).intersection(
                app.view_ids
            ):
                raise ValueError("R1_OBSERVATION_SUPPORT")
        for cid in app.calculation_ids:
            if not set(
                d["calculation_cards"][cid]["original_card"]["observation_ids"]
            ) <= set(app.new_observation_ids):
                raise ValueError("R1_CALCULATION_OPERAND_CHAIN")
        expected = {
            "UPDATE_CONTEXT": "APPLIED",
            "MAINTAIN_CONTEXT": "MAINTAINED",
            "NO_SUPPORTED_CHANGE": "MAINTAINED",
            "DEFER_MISSING_EVIDENCE": "DEFERRED_MISSING_INFORMATION",
        }[app.effect]
        if coverage[app.topic_id].status != expected:
            raise ValueError("R1_EFFECT_COVERAGE_CONFLICT")
        rows.append(
            dict(
                original_application=app.model_dump(),
                resolved_views=resolved,
                resolved_calculations=[
                    d["calculation_cards"][cid] for cid in app.calculation_ids
                ],
                memory_classification=classes,
                linked_current_memory_ids=sorted(linked_new),
                contextual_observations_without_claimed_relation=sorted(
                    current - linked_new
                ),
                semantic_support="PENDING_INDEPENDENT_REVIEW_NOT_INFERRED_FROM_IDS",
            )
        )
    active = {
        c.topic_id for c in obj.topic_coverage if c.status in ("APPLIED", "MAINTAINED")
    }
    if not active <= apps.keys():
        raise ValueError("R1_MISSING_APPLICATION")
    required_status = (
        "RESULT" if active == topics else "PARTIAL" if active else "NO_RESULT"
    )
    if obj.completion_status != required_status:
        raise ValueError("R1_COMPLETION_COVERAGE")
    if not active and not obj.missing_key_information:
        raise ValueError("R1_NO_RESULT_REASON_REQUIRED")
    return dict(
        contract=VERSION,
        mechanical_binding="PASS",
        completion_status=obj.completion_status,
        original_output=obj.model_dump(),
        expanded_applications=rows,
        task_coverage="DECLARED_ONLY_SEMANTIC_REVIEW_REQUIRED",
        research_result_accepted=False,
        source_statement_support="PENDING_SEMANTIC_REVIEW",
        world_fact_authority=False,
        scientific_memory_admitted=False,
        actually_consumed="NOT_DEMONSTRATED_BY_ENGINEERING_FIXTURES",
    )
