"""Offline R7 preparation with original Qwen SDK; no dispatch capability."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from pydantic import SecretStr

from src.core.settings import QwenSettings
from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall, QwenProvider
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import BEIJING
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r6_final as r6
from tools import g113_r7_contract as contract
from tools.g113_r1_binding import ROOT

MODEL = "qwen3.8-flash"
VERSION = "G113_R7_OFFLINE_MODEL_MIGRATION_V1"


def active_model(settings: QwenSettings | None = None) -> str:
    """Require explicit active model identity before any SDK preparation."""
    return (settings or QwenSettings()).resolve_model(
        expected_model=MODEL, allowed_models=frozenset({MODEL})
    )


def sdk_preview(call: LLMProviderCall) -> dict[str, Any]:
    """Capture real SDK serialization using only an in-memory mock transport."""
    if call.model != active_model():
        raise ValueError("R7_REQUEST_MODEL_MISMATCH")
    bodies: list[bytes] = []
    urls: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        urls.append(str(request.url))
        return httpx.Response(
            200,
            json=dict(
                id="R7_OFFLINE_SERIALIZATION_FIXTURE",
                object="response",
                created_at=0,
                model=MODEL,
                status="completed",
                output=[],
            ),
        )

    settings = QwenSettings(
        api_key=SecretStr("OFFLINE_SENTINEL_NOT_A_CREDENTIAL"),
        base_url=BEIJING,
        max_retries=0,
        max_output_tokens=8192,
        enable_thinking=False,
        store_remote=False,
    )
    with httpx.Client(transport=httpx.MockTransport(capture)) as http:
        with OpenAI(
            api_key="OFFLINE_SENTINEL_NOT_A_CREDENTIAL",
            base_url=BEIJING,
            max_retries=0,
            http_client=http,
        ) as sdk:
            provider = QwenProvider(settings, client=sdk)
            provider._create_response(
                model=call.model,
                system_prompt=call.system_prompt,
                encoded_input=provider.encode_input_payload(call.input_payload),
                response_schema=call.response_schema,
                schema_name="r7_candidate",
            )
    if len(bodies) != 1 or urls != [BEIJING + "/responses"]:
        raise ValueError("R7_SDK_CAPTURE_IDENTITY")
    body = json.loads(bodies[0])
    if (
        body["model"] != MODEL
        or body["enable_thinking"] is not False
        or body["store"] is not False
        or body["max_output_tokens"] != 8192
        or any(k in body for k in ("text", "temperature", "top_p", "seed"))
    ):
        raise ValueError("R7_SDK_PARAMETER_IDENTITY")
    return dict(
        status="OFFLINE_PREVIEW_NOT_EXECUTION_FREEZE",
        raw=bodies[0].decode(),
        request_sha256=blob_hash(bodies[0]),
        endpoint=urls[0],
        model=MODEL,
        region="cn-beijing",
        max_output_tokens=8192,
        enable_thinking=False,
        store=False,
        actual_vendor_retention="UNVERIFIED",
        concurrency=1,
        retry=0,
        fallback="NONE",
        native_response_format_sent=False,
        response_schema_identity=digest(call.response_schema),
        schema_enforcement="MODEL_VISIBLE_AND_LOCAL_CHECKER_NOT_SERVER_ENFORCED",
        input_tokens=None,
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        bytes_are_not_tokens=True,
        real_model_calls=0,
        mock_serializations=1,
    )


def model_only_call(row: dict[str, Any]) -> tuple[LLMProviderCall, dict[str, Any]]:
    """Retain original R6 task/prompt/schema; version the external binding only."""
    parent = r6.catalog_for(ROOT, row)
    prompt = r6.checked(ROOT, "candidates/" + row["slot"] + "/prompt.txt").decode()
    old = r6.call_for(parent, prompt)
    call = replace(old, model=active_model())
    binding = dict(
        version=VERSION,
        arm="A_MODEL_ONLY",
        model=call.model,
        parent_semantic_task_identity=parent.identity,
        original_response_schema_identity=digest(old.response_schema),
        prompt_sha256=blob_hash(prompt.encode()),
        payload_sha256=blob_hash(canonical(old.input_payload)),
        model_visible_task_schema_unchanged=True,
    )
    return call, dict(
        binding,
        operational_task_identity=digest(binding),
        schema_binding_identity=digest(
            dict(
                arm="A",
                model=MODEL,
                schema=binding["original_response_schema_identity"],
            )
        ),
    )


def prepare(output: Path) -> dict[str, Any]:
    """Create new previews and W3 inputs; never create a sendable freeze."""
    active_model()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for row in r6.matched(ROOT)["task_slots"]:
        call, binding = model_only_call(row)
        audit = sdk_preview(call)
        repeat = sdk_preview(call)
        if audit["raw"] != repeat["raw"]:
            raise ValueError("R7_SDK_SERIALIZATION_NONDETERMINISTIC")
        old_path = ROOT / "artifacts/g113-r6-final/freeze-final" / row["slot"]
        old_raw = (old_path / "sdk-request.raw").read_bytes()
        old_body = json.loads(old_raw)
        new_body = json.loads(audit["raw"])
        if old_body.pop("model") != "qwen3.7-flash-2026-07-15":
            raise ValueError("R7_PARENT_MODEL")
        new_body.pop("model")
        if old_body != new_body:
            raise ValueError("R7_ARM_A_INPUT_DRIFT")
        folder = output / "A" / row["slot"]
        durable(folder / "sdk-preview.raw", audit.pop("raw").encode())
        durable(folder / "SDK_PREVIEW.json", canonical(audit))
        durable(folder / "TASK_BINDING.json", canonical(binding))
        durable(folder / "RESPONSE_SCHEMA.json", canonical(call.response_schema))
        parent = r6.catalog_for(ROOT, row)
        b = contract.prospective_catalog(parent)
        bfolder = output / "B-W3-ADAPTATION" / row["slot"]
        durable(bfolder / "TASK_CATALOG_CANDIDATE.json", canonical(b.data()))
        durable(
            bfolder / "RESPONSE_SCHEMA_CANDIDATE.json",
            canonical(contract.output_schema(b)),
        )
        rows.append(
            dict(
                slot=row["slot"],
                role=row["role"],
                context=row["arm"],
                A=binding,
                A_preview_sha256=audit["request_sha256"],
                R6_request_sha256=blob_hash(old_raw),
                A_wire_changes=["/model"],
                B_task_candidate_identity=b.identity,
                B_schema_identity=digest(contract.output_schema(b)),
                B_prompt="PENDING_W3_FORMAL_BINDING",
                B_sdk_request=None,
            )
        )
    result = dict(
        version=VERSION,
        created_at=datetime.now(UTC).isoformat(),
        phase="INTERFACE_HANDOFF_NOT_EXECUTION_FREEZE",
        planned_population=8,
        ordered_slots_per_arm=[r["slot"] for r in rows],
        cross_arm_execution_order="PENDING_W3_W5_PROSPECTIVE_FREEZE",
        slots=rows,
        W3_final_binding="PENDING",
        W4_review="REQUIRED_NEW_SCOPE",
        W5_preregistration="REQUIRED_NEW_POPULATION",
        R6_release_pins_applicable=False,
        future_current_memory_revalidation_required=True,
        existing_R6_episodes_are_not_R7_authority=True,
        actual_model_calls=0,
        new_scientific_writes=0,
    )
    durable(output / "PREPARATION.json", canonical(result))
    return result


def main() -> int:
    """Only an offline preparation command is exposed; no live flag exists."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["DEVELOPMENT"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
