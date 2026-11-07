"""Offline reusable response-consumption interface; no network or Sender import."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from h2_pilot.contract import VerifierOutput
from src.schemas.research_v2_shared import canonical
from tools.g107_matrix import strict_object


class ClaimSupportVerifier:
    """Consume captured W1 responses without regenerating, repairing or admitting."""

    def consume(
        self,
        request_input: dict[str, Any],
        assistant_bytes: bytes,
        archive: Path,
        *,
        capture: dict[str, Any],
        raw_entity: bytes,
        expected_request_sha256: str,
    ) -> dict[str, Any]:
        """Persist original bytes and return a candidate S/U/D or technical null.

        W1 supplies trusted runtime capture and response/request association. A
        model cannot grant permission by emitting any of these metadata fields.
        """
        archive.mkdir(parents=True, exist_ok=False)
        (archive / "assistant.raw").write_bytes(assistant_bytes)
        (archive / "http-entity.raw").write_bytes(raw_entity)
        allowed_capture_fields = {
            "origin",
            "http_status",
            "provider_status",
            "model",
            "response_id",
            "usage",
            "input_sha256",
            "request_sha256",
            "region",
            "latency_seconds",
            "attempt_identity",
            "execution_identity",
            "actual_started_at",
            "actual_response_at",
            "meter_receipt",
            "provider_request_id",
            "endpoint",
        }
        safe_capture = {k: v for k, v in capture.items() if k in allowed_capture_fields}
        (archive / "capture.json").write_bytes(canonical(safe_capture))
        result: dict[str, Any] = {
            "case_id": request_input["case_id"],
            "verifier_input_sha256": hashlib.sha256(
                canonical(request_input)
            ).hexdigest(),
            "assistant_sha256": hashlib.sha256(assistant_bytes).hexdigest(),
            "http_entity_sha256": hashlib.sha256(raw_entity).hexdigest(),
            "capture_origin": capture.get("origin"),
            "provider_response_id": capture.get("response_id"),
            "actual_model": capture.get("model"),
            "usage": capture.get("usage"),
            "latency_seconds": capture.get("latency_seconds"),
            "account_billing": "UNKNOWN",
            "semantic_prediction": None,
            "prediction_state": "NO_PREDICTION",
            "error": None,
            "raw_model_object": None,
            "bound_evidence_locations": [],
            "independent_gold": None,
            "evaluation_only_gate_off": None,
            "evaluation_only_gate_on": None,
            "scientific_admission": False,
            "real_observation": capture.get("origin") == "W1_REAL_CAPTURE",
        }
        stage = "CAPTURE_IDENTITY"
        try:
            if set(capture) - allowed_capture_fields:
                raise ValueError("UNEXPECTED_CAPTURE_FIELD_NOT_ARCHIVED")
            if capture.get("origin") == "W1_REAL_CAPTURE" and not all(
                capture.get(k)
                for k in (
                    "attempt_identity",
                    "execution_identity",
                    "actual_started_at",
                    "actual_response_at",
                    "meter_receipt",
                )
            ):
                raise ValueError(
                    "REAL_CAPTURE_REQUIRES_NEW_RUNTIME_AND_ATTEMPT_EVIDENCE"
                )
            if (
                capture.get("origin") == "W1_REAL_CAPTURE"
                and capture.get("endpoint")
                != "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
            ):
                raise ValueError("REAL_CAPTURE_ENDPOINT_BINDING")
            if capture.get("origin") not in {"SYNTHETIC_TEST", "W1_REAL_CAPTURE"}:
                raise ValueError("UNTRUSTED_CAPTURE_ORIGIN")
            if (
                capture.get("http_status") != 200
                or capture.get("provider_status") != "completed"
            ):
                raise ValueError("HTTP_OR_PROVIDER_NOT_COMPLETED")
            if capture.get("request_sha256") != expected_request_sha256:
                raise ValueError("FROZEN_SDK_REQUEST_BINDING")
            if capture.get("region") != "cn-beijing":
                raise ValueError("REGION_IDENTITY")
            if capture.get("model") != "qwen3.8-flash":
                raise ValueError("MODEL_IDENTITY")
            if not capture.get("response_id") or not isinstance(
                capture.get("usage"), dict
            ):
                raise ValueError("UNKNOWN_RESPONSE_OR_USAGE")
            usage = capture["usage"]
            if any(
                type(usage.get(k)) is not int or usage[k] < 0
                for k in ("input_tokens", "output_tokens")
            ):
                raise ValueError("UNKNOWN_OR_INVALID_ACTUAL_USAGE")
            if (
                "total_tokens" in usage
                and usage["total_tokens"]
                != usage["input_tokens"] + usage["output_tokens"]
            ):
                raise ValueError("INCONSISTENT_ACTUAL_USAGE")
            if capture.get("input_sha256") != result["verifier_input_sha256"]:
                raise ValueError("RESPONSE_INPUT_BINDING")
            stage = "PROVIDER_ENTITY_BINDING"
            entity = strict_object(raw_entity.decode("utf-8", errors="strict"))
            if (
                entity.get("id") != capture["response_id"]
                or entity.get("model") != capture["model"]
                or entity.get("status") != "completed"
            ):
                raise ValueError("PROVIDER_RESPONSE_IDENTITY")
            pieces = [
                part["text"]
                for item in entity.get("output", [])
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            ]
            if (
                "".join(pieces).encode() != assistant_bytes
                or entity.get("usage") != capture["usage"]
            ):
                raise ValueError("ASSISTANT_ENTITY_OR_USAGE_BINDING")
            stage = "STRICT_ORIGINAL_JSON"
            obj = strict_object(assistant_bytes.decode("utf-8", errors="strict"))
            result["raw_model_object"] = obj
            result["raw_declared_support_status"] = obj.get("support_status")
            stage = "LOCAL_SCHEMA"
            Draft202012Validator(request_input["output_contract"]).validate(obj)
            typed = VerifierOutput.model_validate(obj)
            if typed.model_dump(mode="json") != obj:
                raise ValueError("UNDECLARED_CONVERSION")
            if typed.case_id != request_input["case_id"]:
                raise ValueError("CASE_IDENTITY")
            stage = "EXACT_EVIDENCE_BINDING"
            fragments = {f["fragment_id"]: f for f in request_input["source_fragments"]}
            bound = []
            for citation in typed.evidence:
                fragment = fragments.get(citation.fragment_id)
                if fragment is None:
                    raise ValueError("UNKNOWN_EVIDENCE_FRAGMENT")
                content = fragment["text"]
                at = content.find(citation.quote)
                if at < 0 or content.find(citation.quote, at + 1) >= 0:
                    raise ValueError("QUOTE_NOT_EXACT_AND_UNIQUE")
                location = dict(fragment["binding"])
                location["fragment_unicode_start"] = at
                location["fragment_unicode_end"] = at + len(citation.quote)
                if fragment["kind"] == "SOURCE_SPAN":
                    location["source_unicode_start"] = (
                        fragment["binding"]["locator"]["start"] + at
                    )
                    location["source_unicode_end"] = location[
                        "source_unicode_start"
                    ] + len(citation.quote)
                bound.append(
                    {
                        "citation": citation.model_dump(mode="json"),
                        "system_bound_location": location,
                    }
                )
            result.update(
                semantic_prediction=typed.support_status,
                prediction_state="CANDIDATE_SEMANTIC_PREDICTION_NOT_GOLD",
                model_assessment=typed.model_dump(mode="json"),
                bound_evidence_locations=bound,
            )
        except Exception as exc:
            result["error"] = {
                "stage": stage,
                "type": type(exc).__name__,
                "reason": str(exc)[:2000],
            }
        (archive / "result.json").write_bytes(canonical(result))
        return result
