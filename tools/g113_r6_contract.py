"""Prospective R6 contract: exact bindings, separate dispositions, no admission.

R5 responses are diagnosed under their ORIGINAL contract only. No migration,
semantic repair, registry, sender, or scientific validator is installed here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import Field, ValidationError

from tools import g113_r1_contract as legacy
from tools.g107_matrix import strict_object
from tools.g113_contract import Record, Role, TaskCatalog, Text, classify_memory
from tools.g113_r1_binding import covers

VERSION = "G113_R6_RESEARCH_INTERFACE_V1"
CHECKER_VERSION = "G113_R6_EVIDENCE_SAFE_CHECKER_V1"


class DeferredInference(Record):
    """Explicitly separate unknown economics from maintained source context."""

    proposition: Text
    missing_evidence: list[Text] = Field(min_length=1)
    disposition: Literal["DEFER_MISSING_EVIDENCE"]


class Period(Record):
    """Exact source-card duration; not a model-generated fiscal-year authority."""

    kind: Literal["QUARTER_DURATION"]
    start: Text
    end: Text


class CalculationContext(Record):
    """Select the system result and declare its scope without recomputing it."""

    calculation_id: Text
    periods: list[Period] = Field(min_length=2, max_length=2)
    unit: Literal["USD_MILLION"]


class Application(legacy.Application):
    """Three orthogonal axes; evidence adequacy is declared, never self-certified."""

    proposition_scope: Literal["KNOWN_SOURCE_CONTEXT", "ECONOMIC_OR_CAUSAL_INFERENCE"]
    source_evidence_adequacy: Literal[
        "SOURCE_SUPPORTED_CONTEXT", "MISSING_KEY_EVIDENCE"
    ]
    information_cutoff: Text
    conclusion_scope: Literal["PROVIDED_SOURCE_SNAPSHOT_ONLY"]
    deferred_inferences: list[DeferredInference]
    calculation_contexts: list[CalculationContext]


class ResearchOutput(Record):
    """Versioned prospective output; every field required, no inferred defaults."""

    contract_version: Literal["G113_R6_RESEARCH_INTERFACE_V1"]
    task_identity: Text
    role: Role
    completion_status: Literal["RESULT", "PARTIAL", "NO_RESULT"]
    applications: list[Application]
    topic_coverage: list[legacy.Coverage]
    source_revision_status: Literal[
        "NO_REVISION_IN_GIVEN_CASE", "UNKNOWN_REQUIRES_REVIEW"
    ]
    missing_key_information: list[Text]
    completion_explanation: Text


def prospective_catalog(parent: TaskCatalog) -> TaskCatalog:
    """Version only the controlled projection; no new source/Memory authority."""
    data = parent.data()
    if data.get("research_interface_version"):
        raise ValueError("R6_ALREADY_VERSIONED_CATALOG")
    data.update(
        research_interface_version=VERSION,
        parent_task_identity=parent.identity,
        w3_final_binding="PENDING_W3_R6_SEMANTIC_MATCH",
    )
    return TaskCatalog(json.dumps(data, ensure_ascii=False), parent.source_texts_json)


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Retain original ID domains, with explicit new fields and version identity."""
    data = catalog.data()
    if data.get("research_interface_version") != VERSION:
        raise ValueError("R6_CATALOG_VERSION")
    schema = ResearchOutput.model_json_schema()
    original = legacy.output_schema(catalog)
    for key in ("task_identity", "role"):
        schema["properties"][key] = original["properties"][key]
    for cls in ("Application", "Coverage"):
        for field, value in original["$defs"][cls]["properties"].items():
            schema["$defs"][cls]["properties"][field] = value
    schema["$defs"]["CalculationContext"]["properties"]["calculation_id"] = {
        "enum": list(data["calculation_cards"])
    }
    return schema


def pointer(parts: Iterable[Any]) -> str:
    """Encode an unambiguous RFC6901 path, including array positions."""
    return "".join("/" + str(x).replace("~", "~0").replace("/", "~1") for x in parts)


class Diagnostics:
    """Read-only accumulated findings; unresolved prerequisites remain explicit."""

    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []

    def add(self, code: str, path: str, **details: Any) -> None:
        """Keep separate clause occurrences rather than erasing sibling errors."""
        self.errors.append(dict(code=code, json_pointer=path, details=details))

    def ids(self, app: dict[str, Any], key: str, path: str) -> list[str] | None:
        """Never coerce, drop or deduplicate malformed reference populations."""
        value = app.get(key)
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            self.skipped.append(dict(path=path + "/" + key, reason="INVALID_ID_ARRAY"))
            return None
        if len(value) != len(set(value)):
            self.add("G113_DUPLICATE_" + key, path + "/" + key)
        return value


def _r6_disposition(
    app: dict[str, Any],
    refs: dict[str, list[str]],
    catalog: TaskCatalog,
    findings: Diagnostics,
    path: str,
) -> None:
    data = catalog.data()
    effect = app.get("effect")
    supported = app.get("source_evidence_adequacy") == "SOURCE_SUPPORTED_CONTEXT"
    known = app.get("proposition_scope") == "KNOWN_SOURCE_CONTEXT"
    if app.get("information_cutoff") != data["research_as_of"]:
        findings.add("R6_INFORMATION_CUTOFF", path + "/information_cutoff")
    # No economic/cause authority follows from a relation or true source ID.
    if (not known or not supported) and effect != "DEFER_MISSING_EVIDENCE":
        findings.add("R6_UNSUPPORTED_INFERENCE_MUST_DEFER", path + "/effect")
    if effect == "DEFER_MISSING_EVIDENCE" and not app.get("unknown_conditions"):
        findings.add("R6_DEFER_REQUIRES_MISSING_EVIDENCE", path + "/unknown_conditions")
    observations = [
        data["observations"][o]
        for o in refs["new_observation_ids"]
        if o in data["observations"]
    ]
    current = {o["memory_id"] for o in observations}
    if effect != "DEFER_MISSING_EVIDENCE":
        if (
            not refs["historical_memory_ids"]
            or not observations
            or not refs["view_ids"]
        ):
            findings.add("R6_SOURCE_SUPPORTED_CHAIN_REQUIRED", path)
        if (
            app.get("relation_status") == "UNAVAILABLE"
            and not set(refs["historical_memory_ids"]) <= current
        ):
            findings.add("R6_UNLINKED_HISTORY_REQUIRES_DIRECT_OBSERVATION", path)
    if effect == "UPDATE_CONTEXT":
        texts = json.loads(catalog.source_texts_json)

        def exact_added_support(vid: str, evidence: dict[str, Any]) -> bool:
            try:
                return covers(data["views"][vid], evidence, texts)
            except (ValueError, KeyError) as exc:
                findings.add(
                    "R6_DISPOSITION_SOURCE_PREREQUISITE",
                    path + "/view_ids",
                    view_id=vid,
                    cause=str(exc),
                )
                return False

        has_new_support = any(
            observation["given_system_classification"]
            in {"NEW_FACT", "NEW_EVIDENCE_FOR_EXISTING_FACT"}
            and any(
                exact_added_support(vid, evidence)
                for evidence in observation["added_source_support"]
                for vid in refs["view_ids"]
                if vid in data["views"]
            )
            for observation in observations
        )
        if not has_new_support:
            findings.add("R6_UPDATE_REQUIRES_NEW_INFORMATION", path + "/effect")
    contexts = app.get("calculation_contexts")
    if isinstance(contexts, list) and all(isinstance(x, dict) for x in contexts):
        ids = [x.get("calculation_id") for x in contexts]
        if len(ids) != len(set(str(x) for x in ids)) or set(str(x) for x in ids) != set(
            refs["calculation_ids"]
        ):
            findings.add(
                "R6_CALCULATION_CONTEXT_POPULATION", path + "/calculation_contexts"
            )
        for i, ctx in enumerate(contexts):
            card = data["calculation_cards"].get(str(ctx.get("calculation_id")))
            if card is not None and (
                ctx.get("periods") != card["original_card"]["periods"]
                or ctx.get("unit") != "USD_MILLION"
            ):
                findings.add(
                    "R6_CALCULATION_PERIOD_UNIT", path + f"/calculation_contexts/{i}"
                )


def _clauses(obj: dict[str, Any], catalog: TaskCatalog, *, r6: bool) -> Diagnostics:
    d, found = catalog.data(), Diagnostics()
    if obj.get("task_identity") != catalog.identity or obj.get("role") != d["role"]:
        found.add("R1_TASK_ROLE", "")
    applications, cover = obj.get("applications"), obj.get("topic_coverage")
    if not isinstance(applications, list) or not isinstance(cover, list):
        found.skipped.append(dict(path="", reason="APPLICATIONS_OR_COVERAGE_NOT_ARRAY"))
        return found
    apps = [(i, a) for i, a in enumerate(applications) if isinstance(a, dict)]
    covers = [(i, c) for i, c in enumerate(cover) if isinstance(c, dict)]
    if len(apps) != len(applications) or len(covers) != len(cover):
        found.skipped.append(dict(path="", reason="NON_OBJECT_APPLICATION_OR_COVERAGE"))
    topics = set(d["topics"])
    app_topics = [a.get("topic_id") for _, a in apps]
    cover_topics = [c.get("topic_id") for _, c in covers]
    # Malformed topic types are schema errors; do not hash arbitrary JSON values.
    app_names = [t for t in app_topics if isinstance(t, str)]
    cover_names = [t for t in cover_topics if isinstance(t, str)]
    if len(app_names) != len(set(app_names)):
        found.add("G113_DUPLICATE_APPLICATION_TOPIC", "/applications")
    if len(cover_names) != len(set(cover_names)):
        found.add("G113_DUPLICATE_COVERAGE_TOPIC", "/topic_coverage")
    if set(cover_names) != topics:
        found.add("R1_INCOMPLETE_TOPIC_COVERAGE", "/topic_coverage")
    for i, app in apps:
        path = f"/applications/{i}"
        topic = app.get("topic_id")
        if not isinstance(topic, str) or topic not in topics:
            found.add("R1_WRONG_ROLE_TOPIC", path + "/topic_id")
        refs = {
            k: found.ids(app, k, path)
            for k in (
                "historical_memory_ids",
                "new_observation_ids",
                "relation_ids",
                "view_ids",
                "calculation_ids",
            )
        }
        # Each independent domain is checked even when another field is malformed.
        for field, domain, code in (
            ("new_observation_ids", d["observations"], "R1_UNKNOWN_OBSERVATION"),
            ("relation_ids", d["relations"], "R1_UNKNOWN_RELATION"),
            ("calculation_ids", d["calculation_cards"], "R1_UNAUTHORIZED_CALCULATION"),
        ):
            if refs[field] is not None:
                unknown = [v for v in refs[field] or [] if v not in domain]
                if unknown:
                    found.add(code, path + "/" + field, unknown=unknown)
        if refs["historical_memory_ids"] is not None:
            classes = classify_memory(refs["historical_memory_ids"] or [], catalog)
            if classes["T1"] or classes["UNKNOWN"]:
                found.add(
                    "R1_NOT_T0_MEMORY", path + "/historical_memory_ids", **classes
                )
        for j, vid in enumerate(refs["view_ids"] or []):
            try:
                catalog.resolve_view(vid)
            except (ValueError, KeyError) as exc:
                found.add(
                    "R6_SOURCE_VIEW_BINDING",
                    path + f"/view_ids/{j}",
                    cause=str(exc),
                    view_id=vid,
                )
        if any(x is None for x in refs.values()):
            found.skipped.append(dict(path=path, reason="CHAIN_REQUIRES_VALID_ARRAYS"))
            continue
        ids = {k: list(v or []) for k, v in refs.items()}
        current = {
            d["observations"][o]["memory_id"]
            for o in ids["new_observation_ids"]
            if o in d["observations"]
        }
        old = set(ids["historical_memory_ids"])
        linked: set[str] = set()
        for rid in ids["relation_ids"]:
            rel = d["relations"].get(rid)
            if rel is None:
                continue
            if rel["from_memory_id"] not in current or rel["to_memory_id"] not in old:
                found.add(
                    "R1_RELATION_ENDPOINT", path + "/relation_ids", relation_id=rid
                )
            if any(
                not set(vs).intersection(ids["view_ids"])
                for vs in rel["support_view_options"]
            ):
                found.add(
                    "R1_RELATION_SOURCE_SUPPORT", path + "/view_ids", relation_id=rid
                )
            linked.add(rel["to_memory_id"])
        if app.get("relation_status") == "LINKED":
            if not ids["relation_ids"] or not old or linked != old:
                found.add("R1_INCOMPLETE_HISTORY_CHAIN", path)
        elif app.get("relation_status") == "UNAVAILABLE":
            if r6:
                if ids["relation_ids"]:
                    found.add("R6_UNAVAILABLE_RELATION_IDS", path + "/relation_ids")
            elif (
                ids["relation_ids"]
                or app.get("effect") != "DEFER_MISSING_EVIDENCE"
                or not app.get("unknown_conditions")
            ):
                found.add("R1_UNAVAILABLE_RELATION_MUST_DEFER", path)
        for oid in ids["new_observation_ids"]:
            if oid in d["observations"] and not set(
                d["observations"][oid]["support_view_ids"]
            ).intersection(ids["view_ids"]):
                found.add(
                    "R1_OBSERVATION_SUPPORT", path + "/view_ids", observation_id=oid
                )
        for cid in ids["calculation_ids"]:
            if cid in d["calculation_cards"] and not set(
                d["calculation_cards"][cid]["original_card"]["observation_ids"]
            ) <= set(ids["new_observation_ids"]):
                found.add(
                    "R1_CALCULATION_OPERAND_CHAIN",
                    path + "/calculation_ids",
                    calculation_id=cid,
                )
        expected = {
            "UPDATE_CONTEXT": "APPLIED",
            "MAINTAIN_CONTEXT": "MAINTAINED",
            "NO_SUPPORTED_CHANGE": "MAINTAINED",
            "DEFER_MISSING_EVIDENCE": "DEFERRED_MISSING_INFORMATION",
        }.get(str(app.get("effect")))
        matching = [c for _, c in covers if c.get("topic_id") == topic]
        if expected and len(matching) == 1 and matching[0].get("status") != expected:
            found.add("R1_EFFECT_COVERAGE_CONFLICT", path + "/effect")
        if r6:
            try:
                _r6_disposition(app, ids, catalog, found, path)
            except (ValueError, KeyError) as exc:
                found.add("R6_DISPOSITION_SOURCE_PREREQUISITE", path, cause=str(exc))
    active = {
        str(c.get("topic_id"))
        for _, c in covers
        if c.get("status") in ("APPLIED", "MAINTAINED")
    }
    if not active <= set(app_names):
        found.add("R1_MISSING_APPLICATION", "/topic_coverage")
    expected_completion = (
        "RESULT" if active == topics else "PARTIAL" if active else "NO_RESULT"
    )
    if obj.get("completion_status") != expected_completion:
        found.add("R1_COMPLETION_COVERAGE", "/completion_status")
    if not active and not obj.get("missing_key_information"):
        found.add("R1_NO_RESULT_REASON_REQUIRED", "/missing_key_information")
    return found


def diagnose(
    text: str, catalog: TaskCatalog, *, version: str = VERSION
) -> dict[str, Any]:
    """Collect all decidable original/new clauses without translating any response.

    DIAGNOSTIC_COMPLETE means all applicable deterministic clauses were visited;
    free-text entailment, fiscal prose and causality ALWAYS need independent review.
    """
    if version not in (VERSION, legacy.VERSION):
        raise ValueError("R6_UNKNOWN_DIAGNOSTIC_VERSION")
    r6 = version == VERSION
    schema = output_schema(catalog) if r6 else legacy.output_schema(catalog)
    model = ResearchOutput if r6 else legacy.ResearchOutput
    result: dict[str, Any] = dict(
        checker_version=CHECKER_VERSION,
        evaluated_contract_version=version,
        raw_utf8_sha256=hashlib.sha256(text.encode()).hexdigest(),
        research_output_accepted=False,
        scientific_admission=False,
        semantic_validation="PENDING_INDEPENDENT_REVIEW",
        errors=[],
        clause_errors=[],
        schema_errors=[],
        shape_errors=[],
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
    for error in Draft202012Validator(schema).iter_errors(obj):
        result["schema_errors"].append(
            dict(
                code="DYNAMIC_JSON_SCHEMA",
                json_pointer=pointer(error.absolute_path),
                keyword=error.validator,
                schema_pointer=pointer(error.absolute_schema_path),
            )
        )
    try:
        model.model_validate(obj)
    except ValidationError as exc:
        result["shape_errors"] = [
            dict(
                code="STRICT_RESPONSE_SHAPE",
                json_pointer=pointer(e["loc"]),
                type=e["type"],
            )
            for e in exc.errors(include_input=False, include_url=False)
        ]
    findings = _clauses(obj, catalog, r6=r6)
    result["clause_errors"] = findings.errors
    result["not_evaluated"] = findings.skipped
    result["errors"] = (
        result["schema_errors"] + result["shape_errors"] + findings.errors
    )
    result["diagnostic_status"] = (
        "DIAGNOSTIC_PARTIAL" if findings.skipped else "DIAGNOSTIC_COMPLETE"
    )
    result["semantic_review_required"] = (
        [
            dict(
                json_pointer=f"/applications/{i}",
                checks=[
                    "SOURCE_ENTAILMENT",
                    "FISCAL_PERIOD_IN_PROSE",
                    "INFERENCE_SCOPE",
                    "KNOWN_T0_CONTENT",
                    "COUNTEREVIDENCE",
                    "UNKNOWN_ECONOMICS",
                ],
            )
            for i, _ in enumerate(obj.get("applications", []))
        ]
        if isinstance(obj.get("applications"), list)
        else []
    )
    return result


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Fail closed on any contract error; structural success is NOT research success."""
    diagnostic = diagnose(text, catalog)
    if diagnostic["errors"] or diagnostic["not_evaluated"]:
        raise ValueError(
            "R6_CONTRACT_REJECTED:" + json.dumps(diagnostic, ensure_ascii=False)
        )
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
            catalog.data()["calculation_cards"][c]
            for a in obj.applications
            for c in a.calculation_ids
        ],
        diagnostic=diagnostic,
        research_output_accepted=False,
        world_fact_authority=False,
        scientific_memory_admitted=False,
        semantic_review="PENDING_INDEPENDENT_REVIEW",
    )
