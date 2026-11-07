"""Opt-in offline incremental-research interface; no scientific admission or I/O.

Only trusted composition supplies the task catalog. Model output selects IDs,
never hashes/coordinates. A structural receipt is not semantic acceptance.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.agents.numeric_tokens import decimal_value
from src.schemas.research_v2_shared import digest
from src.services.llm_provider import LLMProviderCall
from src.services.research_vnext.native_numeric_binding import scaled_decimal
from tools.g107_matrix import strict_object
from tools.g108_p1_view import reference_diagnostic
from tools.g112_task_freeze import check_span

VERSION = "G113_INCREMENTAL_RESEARCH_INTERFACE_V1"
Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Role = Literal["fundamental_analyst", "news_event_analyst"]


class Record(BaseModel):
    """No coercion, hidden defaults, or model-controlled extra authority fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Application(Record):
    """An explicit historical-to-current chain, subject to semantic review."""

    historical_memory_ids: list[Text] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )
    observation_ids: list[Text] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )
    relation_ids: list[Text] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )
    evidence_view_ids: list[Text] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )
    previous_judgment: Text
    application: Text
    relation_use: Text
    judgment_update: Literal["CHANGED", "MAINTAINED", "INDETERMINATE"]
    limitations: list[Text] = Field(min_length=1)


class Calculation(Record):
    """Select source operands; deterministic output never becomes an Agent Claim."""

    old_operand_id: Text
    new_operand_id: Text
    operation: Literal["DIFFERENCE", "GROWTH_PERCENT", "UNIT_CONVERSION"]
    output_unit: Literal["USD", "USD_MILLION", "PERCENT"]
    decimal_places: int = Field(ge=0, le=8)
    reported_value: Text


class ResearchOutput(Record):
    """Versioned development output; original Agent Role Contracts are unchanged."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "RESULT"}}},
                    "then": {"properties": {"applications": {"minItems": 1}}},
                    "else": {
                        "properties": {
                            "applications": {"maxItems": 0},
                            "calculations": {"maxItems": 0},
                            "unresolved_questions": {"minItems": 1},
                        }
                    },
                }
            ]
        },
    )

    contract_version: Literal["G113_INCREMENTAL_RESEARCH_INTERFACE_V1"]
    task_identity: Text
    agent_name: Role
    status: Literal["RESULT", "NO_RESULT"]
    applications: list[Application]
    calculations: list[Calculation]
    unresolved_questions: list[Text]
    completion_explanation: Text


@dataclass(frozen=True)
class TaskCatalog:
    """Immutable task-local projection of verified sources, not an Evidence registry.

    Constructed by the trusted offline loader, never from model output. Serialized
    copies prevent later mutation of dictionaries from changing the task identity.
    """

    payload_json: str
    source_texts_json: str

    @property
    def identity(self) -> str:
        """Bind complete role, clock, source, Memory and operand population."""
        return digest(json.loads(self.payload_json))

    def data(self) -> dict[str, Any]:
        """Return a detached copy; identity never depends on model fields."""
        return dict(json.loads(self.payload_json))

    def resolve_view(self, view_id: str) -> dict[str, Any]:
        """Recheck original exact source/locator using existing source validators."""
        data = self.data()
        if view_id not in data["views"]:
            raise ValueError("G113_UNKNOWN_VIEW")
        v = dict(data["views"][view_id])
        source = data["sources"][v["source_id"]]
        if (
            v["raw_sha256"] != source["raw_sha256"]
            or source["owner"] != data["security"]
            or datetime.fromisoformat(source["available_at_conservative"])
            > datetime.fromisoformat(data["research_as_of"])
        ):
            raise ValueError("G113_SOURCE_IDENTITY_OR_CLOCK")
        texts = json.loads(self.source_texts_json)
        check_span(v, texts)
        diagnostic = reference_diagnostic(
            {
                "SourceID": v["source_id"],
                "Locator": v["locator"],
                "Quote": v["content"],
            },
            v,
            texts,
        )
        if any(
            diagnostic[k] != "PASS"
            for k in ("SOURCE_AUTHORITY_RESULT", "LOCATOR_RESULT", "QUOTE_RESULT")
        ):
            raise ValueError("G113_VIEW_BINDING")
        return v


def output_schema(catalog: TaskCatalog) -> dict[str, Any]:
    """Pin the existing task's role/identity in its prospective output interface."""
    schema = ResearchOutput.model_json_schema()
    schema["properties"]["agent_name"] = {"const": catalog.data()["role"]}
    schema["properties"]["task_identity"] = {"const": catalog.identity}
    return schema


def engine_diagnostic(
    catalog: TaskCatalog,
) -> Callable[[str, dict[str, Any], LLMProviderCall], dict[str, Any]]:
    """Adapt only the original sample engine's diagnostic hook; never dispatch.

    Catalog comes from trusted composition. Pre-dispatch authorization and exact
    request hashing remain the original executor's responsibility. A future task
    must bind these before send; this callback grants no execution authority.
    """

    def diagnose(
        text: str, row: dict[str, Any], call: LLMProviderCall
    ) -> dict[str, Any]:
        if (
            row["role"] != catalog.data()["role"]
            or call.input_payload
            != {"task_identity": catalog.identity, "catalog": catalog.data()}
            or call.response_schema != output_schema(catalog)
        ):
            raise ValueError("G113_EXECUTOR_TASK_BINDING")
        shape_valid = False
        try:
            ResearchOutput.model_validate(strict_object(text))
            shape_valid = True
            result = validate_output(text, catalog)
        except ValueError as exc:
            result = {
                "schema_valid": False,
                "json_shape_valid": shape_valid,
                "contract_valid": False,
                "error_type": type(exc).__name__,
                "reason": str(exc),
                "scientific_admission": False,
            }
        else:
            result.update(
                schema_valid=True,
                json_shape_valid=True,
                contract_valid=True,
                scientific_admission=False,
            )
        result["legacy_engine_flag_semantics"] = "G113_COMPONENT_CONTRACT_ONLY"
        result["original_response_text_identity"] = digest(text)
        return result

    return diagnose


def unique(values: list[str], label: str) -> None:
    """Reject duplicates without silently deduplicating model content."""
    if len(values) != len(set(values)):
        raise ValueError("G113_DUPLICATE_" + label)


def classify_memory(values: list[str], catalog: TaskCatalog) -> dict[str, Any]:
    """Separate T0, T1, repeated and genuinely unknown IDs."""
    data = catalog.data()
    t0, all_ids = set(data["t0_ids"]), set(data["memory_versions"])
    return {
        "T0": [x for x in values if x in t0],
        "T1": [x for x in values if x in all_ids - t0],
        "UNKNOWN": [x for x in values if x not in all_ids],
        "DUPLICATE": sorted({x for x in values if values.count(x) > 1}),
    }


def arithmetic(old: str, new: str, operation: str, unit: str, places: int) -> Decimal:
    """Exact bounded Decimal arithmetic, one HALF_UP at declared precision.

    Inputs are canonical USD source observations. This adds no global Grounder
    tolerance. Existing parsing/scaling is reused; there was no shared growth
    calculator in the original research code.
    """
    numbers = [decimal_value(v) if not v.endswith("%") else None for v in (old, new)]
    if any(v is None or abs(v) >= Decimal("1e30") for v in numbers):
        raise ValueError("G113_FINITE_BOUNDED_OPERAND")
    if not 0 <= places <= 8:
        raise ValueError("G113_PRECISION")
    a, b = numbers
    assert a is not None and b is not None
    with localcontext() as ctx:
        ctx.prec = 100
        if operation == "GROWTH_PERCENT":
            if a <= 0 or unit != "PERCENT":
                raise ValueError("G113_GROWTH_BASIS")
            result = (b - a) / a * 100
        elif operation in ("DIFFERENCE", "UNIT_CONVERSION"):
            if unit not in ("USD", "USD_MILLION"):
                raise ValueError("G113_UNIT")
            result = b - a if operation == "DIFFERENCE" else b
            if unit == "USD_MILLION":
                result = scaled_decimal(
                    format(abs(result), "f"), -6, "-" if result < 0 else ""
                )
        else:
            raise ValueError("G113_OPERATION")
        return result.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def calculate(calc: Calculation, catalog: TaskCatalog) -> dict[str, Any]:
    """Bind economic identity/period/unit before computing a displayed result."""
    operands = catalog.data()["operands"]
    if calc.old_operand_id not in operands or calc.new_operand_id not in operands:
        raise ValueError("G113_UNREGISTERED_TASK_OPERAND")
    old, new = operands[calc.old_operand_id], operands[calc.new_operand_id]
    for obj in (old, new):
        catalog.resolve_view(obj["view_id"])
        native = obj["native_observation"]
        if (
            obj["issuer"] != catalog.data()["security"]
            or obj["start"] != native["period"]["startdate"]
            or obj["end"] != native["period"]["enddate"]
            or Decimal(obj["value"])
            != scaled_decimal(native["literal"], int(native["scale"]), "")
        ):
            raise ValueError("G113_ORIGINAL_OPERAND_IDENTITY")
    for field in ("issuer", "series", "unit", "basis"):
        if old[field] != new[field]:
            raise ValueError("G113_OPERAND_SCOPE_OR_BASIS")
    if old["unit"] != "USD":
        raise ValueError("G113_OPERAND_UNIT")
    if calc.operation == "UNIT_CONVERSION":
        if calc.old_operand_id != calc.new_operand_id:
            raise ValueError("G113_CONVERSION_IDENTITY")
    elif (
        old["start"][5:] != new["start"][5:]
        or old["end"][5:] != new["end"][5:]
        or int(new["start"][:4]) - int(old["start"][:4]) != 1
        or int(new["end"][:4]) - int(old["end"][:4]) != 1
    ):
        raise ValueError("G113_COMPARABLE_PERIOD_REQUIRED")
    value = arithmetic(
        old["value"],
        new["value"],
        calc.operation,
        calc.output_unit,
        calc.decimal_places,
    )
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", calc.reported_value):
        raise ValueError("G113_REPORTED_NUMBER_FORMAT")
    reported = decimal_value(calc.reported_value)
    if (
        reported is None
        or reported != value
        or reported.as_tuple().exponent != -calc.decimal_places
    ):
        raise ValueError("G113_DECLARED_PRECISION_MISMATCH")
    return {
        "original": calc.model_dump(),
        "deterministic_value": str(value),
        "operands": [old, new],
        "authority": "SOURCE_OBSERVATION_CALCULATION_ONLY",
        "native_scientific_admission": False,
    }


def validate_output(text: str, catalog: TaskCatalog) -> dict[str, Any]:
    """Fail the whole component; never salvage or complete rejected siblings."""
    obj = ResearchOutput.model_validate(strict_object(text))
    data = catalog.data()
    if obj.task_identity != catalog.identity or obj.agent_name != data["role"]:
        raise ValueError("G113_TASK_ROLE_IDENTITY")
    if obj.status == "NO_RESULT":
        if obj.applications or obj.calculations or not obj.unresolved_questions:
            raise ValueError("G113_NO_RESULT_CONTENT")
    elif not obj.applications:
        raise ValueError("G113_MISSING_APPLICATION")
    bound = []
    for app in obj.applications:
        for field in (
            "historical_memory_ids",
            "observation_ids",
            "relation_ids",
            "evidence_view_ids",
        ):
            unique(getattr(app, field), field)
        classes = classify_memory(app.historical_memory_ids, catalog)
        if classes["T1"] or classes["UNKNOWN"]:
            raise ValueError("G113_NOT_T0_HISTORY")
        if any(x not in data["observations"] for x in app.observation_ids):
            raise ValueError("G113_UNKNOWN_OBSERVATION")
        new_ids = {data["observations"][x]["memory_id"] for x in app.observation_ids}
        resolved = [catalog.resolve_view(v) for v in app.evidence_view_ids]
        for rid in app.relation_ids:
            relation = data["relations"].get(rid)
            if relation is None:
                raise ValueError("G113_UNKNOWN_RELATION")
            if (
                relation["from_memory_id"] not in new_ids
                or relation["to_memory_id"] not in app.historical_memory_ids
            ):
                raise ValueError("G113_RELATION_ENDPOINTS")
            if not set(relation["support_view_ids"]) <= set(app.evidence_view_ids):
                raise ValueError("G113_RELATION_SUPPORT_MISSING")
        used = [data["relations"][rid] for rid in app.relation_ids]
        if {e["to_memory_id"] for e in used} != set(app.historical_memory_ids) or {
            e["from_memory_id"] for e in used
        } != new_ids:
            raise ValueError("G113_UNLINKED_CHAIN_ID")
        if any(
            not set(data["observations"][x]["support_view_ids"]).intersection(
                app.evidence_view_ids
            )
            for x in app.observation_ids
        ):
            raise ValueError("G113_OBSERVATION_SUPPORT_MISSING")
        bound.append(
            {
                "original_application": app.model_dump(),
                "resolved_views": resolved,
                "memory_classification": classes,
                "semantic_fidelity": "PENDING_INDEPENDENT_REVIEW",
            }
        )
    calculated = [calculate(c, catalog) for c in obj.calculations]
    return {
        "contract": VERSION,
        "task_identity": catalog.identity,
        "structural_binding": "PASS",
        "status": obj.status,
        "applications": bound,
        "calculations": calculated,
        "research_result_accepted": False,
        "world_fact_authority": False,
        "scientific_memory_admitted": False,
        "model_application": "NOT_EVALUATED",
        "task_coverage": "PENDING_ROLE_SPECIFIC_EVALUATION",
    }
