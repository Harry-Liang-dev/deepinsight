"""Read-only consumption of original captures and a tri-state shared frontier."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from h2_pilot.verifier import ClaimSupportVerifier
from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall
from src.services.research_vnext.real_memory_meter import durable
from tools import h2_inputs as inputs
from tools.g107_matrix import strict_object
from tools.g113_r1_binding import ROOT


def structure(text: str, call: LLMProviderCall) -> dict[str, Any]:
    """No repair, default label, or inferred semantic correctness."""
    try:
        obj = strict_object(text)
        if call.response_schema is None:
            raise ValueError("H2_RESPONSE_SCHEMA_REQUIRED")
        Draft202012Validator(call.response_schema).validate(obj)
        return {"schema_valid": True, "scientific_admission": False}
    except (ValueError, TypeError, KeyError) as exc:
        return {
            "schema_valid": False,
            "error_type": type(exc).__name__,
            "scientific_admission": False,
        }
    except Exception as exc:
        # The external schema library has its own exception hierarchy.
        return {
            "schema_valid": False,
            "error_type": type(exc).__name__,
            "scientific_admission": False,
        }


def frontier(
    prediction: str | None,
    *,
    root_valid: bool | None = None,
    component: bool | None = None,
    mechanical: bool | None = None,
) -> dict[str, Any]:
    """Keep uninstrumented original eligibility unknown, never derive Gold."""
    if prediction not in {None, "SUPPORTED", "UNSUPPORTED", "UNDETERMINED"}:
        raise ValueError("H2_UNKNOWN_PREDICTION")
    values = (root_valid, component, mechanical)
    if any(v is not None and type(v) is not bool for v in values):
        raise ValueError("H2_FRONTIER_STATE_TYPE")
    eligible = (
        False if False in values else True if all(v is True for v in values) else None
    )
    off = "BLOCK" if eligible is False else "WOULD_PASS" if eligible else "UNRESOLVED"
    on = (
        off
        if eligible is not True
        else (
            "WITHHOLD_NO_PREDICTION"
            if prediction is None
            else "WOULD_PASS" if prediction == "SUPPORTED" else "WITHHOLD"
        )
    )
    return dict(
        root_valid=root_valid,
        original_component_pass=component,
        common_claim_mechanical_pass=mechanical,
        mechanical_eligibility=eligible,
        semantic_prediction=prediction,
        evaluation_only_gate_off=off,
        evaluation_only_gate_on=on,
        actual_scientific_admission=False,
        independent_gold=None,
        limitation=(
            "Original component/common mechanical boundary not instrumented by W3; "
            "input integrity and current ACL alone do not fill it."
        ),
    )


def consume_archived(
    target: Path, row: dict[str, Any], outcome: dict[str, Any]
) -> dict[str, Any]:
    """Use original sender files only, after HTTP/text/Usage preservation."""
    if not outcome.get("response_received") or not (target / "assistant.txt").exists():
        result = dict(
            case_id=row["sample_id"],
            prediction_state="NO_PREDICTION",
            semantic_prediction=None,
            error="NO_COMPLETE_CAPTURE",
            scientific_admission=False,
        )
    else:
        identity = json.loads((target / "identity.json").read_bytes())
        http = json.loads((target / "http.json").read_bytes())
        entity = (target / "response.raw").read_bytes()
        try:
            response = strict_object(entity.decode("utf-8", errors="strict"))
        except (ValueError, UnicodeError):
            result = dict(
                case_id=row["sample_id"],
                prediction_state="NO_PREDICTION",
                semantic_prediction=None,
                error={
                    "stage": "PROVIDER_ENTITY_BINDING",
                    "reason": "STRICT_RAW_PROVIDER_JSON",
                },
                scientific_admission=False,
                shared_frontier=frontier(None),
            )
            outcome["stop_remaining"] = True
            outcome["stop_reason"] = "H2_POST_CAPTURE_ENTITY_INTEGRITY"
            outcome["status"] = "SYSTEM_FAILURE"
            durable(target / "H2_PREDICTION.json", canonical(result))
            durable(target / "H2_POST_CAPTURE_SYSTEM_STOP.json", canonical(result))
            return result
        payload = inputs.call_for_case(ROOT, row["sample_id"]).input_payload
        start = identity["ActualStartedAt"]
        end = http["ActualResponseAt"]
        capture = dict(
            origin=(
                "SYNTHETIC_TEST"
                if identity["engineering_fixture"]
                else "W1_REAL_CAPTURE"
            ),
            http_status=http["http_status"],
            provider_status=response.get("status"),
            model=response.get("model"),
            response_id=response.get("id"),
            usage=response.get("usage"),
            input_sha256=digest(payload),
            request_sha256=row["request_sha256"],
            region="cn-beijing",
            latency_seconds=(
                datetime.fromisoformat(end) - datetime.fromisoformat(start)
            ).total_seconds(),
            attempt_identity=identity["AttemptID"],
            execution_identity=identity["OperationID"],
            actual_started_at=start,
            actual_response_at=end,
            meter_receipt=(
                json.loads((target / "usage.json").read_bytes())
                if (target / "usage.json").exists()
                else None
            ),
            provider_request_id=http["provider_request_ids"],
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/responses",
        )
        result = ClaimSupportVerifier().consume(
            payload,
            (target / "assistant.txt").read_bytes(),
            target / "h2-verifier",
            capture=capture,
            raw_entity=entity,
            expected_request_sha256=row["request_sha256"],
        )
    error = result.get("error")
    if (
        outcome.get("response_completed")
        and not outcome.get("stop_remaining")
        and isinstance(error, dict)
        and error.get("stage") in {"CAPTURE_IDENTITY", "PROVIDER_ENTITY_BINDING"}
    ):
        # A malformed Provider envelope is a system failure, not model content.
        # Known incomplete text with valid Usage remains a content observation.
        outcome["stop_remaining"] = True
        outcome["stop_reason"] = "H2_POST_CAPTURE_ENTITY_INTEGRITY"
        outcome["status"] = "SYSTEM_FAILURE"
        durable(
            target / "H2_POST_CAPTURE_SYSTEM_STOP.json",
            canonical(dict(reason=outcome["stop_reason"], error=error)),
        )
    result["shared_frontier"] = frontier(result["semantic_prediction"])
    durable(target / "H2_PREDICTION.json", canonical(result))
    if result["semantic_prediction"] is None and not outcome["stop_remaining"]:
        outcome["status"] = "CONTENT_OR_SCHEMA_FAILURE"
    return result
