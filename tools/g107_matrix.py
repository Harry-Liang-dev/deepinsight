"""Frozen G107 primary16 composition of the existing isolated Qwen path.

No AgentRun, State, Memory or scientific admission. No retry/resume. Monetary
accounting is reference-only; identity, call count, capacity and Usage remain hard.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from openai import OpenAI
from pydantic import SecretStr

from src.core.settings import QwenSettings
from src.schemas.agents import FundamentalDraftResponse, NewsDraftResponse
from src.schemas.research_v2_shared import canonical
from src.services.development_model_profile import (
    ModelExecutionProfile,
    profile_record,
    require_profile,
)
from src.services.llm_provider import LLMProviderCall, QwenProvider
from src.services.native_preservation import blob_hash
from src.services.pilot_capacity_budget import capacity_limits
from src.services.pilot_model_readiness import BEIJING, SNAPSHOT, request_audit
from src.services.research_vnext.real_memory_meter import durable as durable
from tools.development_model_policy import POLICY, DevelopmentAccountingMeter
from tools.g106_d1_experiment import inputs_verified
from tools.g106_transport import configured_https_proxy, recovery_client
from tools.g107_design import check_body, context, schedule
from tools.g108_p1_view import diagnose_p1

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/g107-execution"
DESIGN = ART / "inputs/w3"
W5 = ART / "inputs/w5"
OPERATION = "G107-PRIMARY16-001"
EPISODE = "G107-FACTORIAL-EVALUATION-001"
RESULT = ROOT / "data/runtime/g107-matrix" / OPERATION
W5_COMMIT = "7c003ea486995cff4b47b5a14a5abdd5af933076"
W5_REPO = Path("/home/harry/deepinsight-w5/g107-causal-prereg")
MODULES = (
    "tools/g107_matrix.py",
    "tools/g107_design.py",
    "tools/g108_p1_view.py",
    "tools/g106_transport.py",
    "tools/development_model_policy.py",
    "src/services/llm_provider.py",
    "src/services/pilot_model_readiness.py",
    "src/services/pilot_capacity_budget.py",
    "src/services/retained_pilot_budget.py",
    "src/schemas/agents.py",
    "src/services/research_vnext/real_memory_meter.py",
)


def now() -> str:
    """Capture actual UTC execution time, never the historical source cutoff."""
    return datetime.now(UTC).isoformat()


def read(path: Path) -> Any:
    """Read a frozen local JSON object."""
    return json.loads(path.read_bytes())


def git(*args: str, repo: Path = ROOT) -> bytes:
    """Read exact Git identity without altering a worktree."""
    return subprocess.check_output(["git", "-C", str(repo), *args])


def call_for(row: dict[str, Any]) -> tuple[bytes, LLMProviderCall]:
    """Reconstruct the existing Provider call, requiring exact SDK serialization."""
    raw = (DESIGN / "freeze" / row["request_file"]).read_bytes()
    if blob_hash(raw) != row["request_sha256"]:
        raise ValueError("G107_REQUEST_HASH")
    body = json.loads(raw)
    ctx = context(body)
    call = LLMProviderCall(
        SNAPSHOT, body["instructions"], ctx, ctx["original_role_schema"]
    )
    audit = request_audit(call, output_cap=8192)
    if audit["serialized_http_body"].encode() != raw:
        raise ValueError("G107_SDK_BODY_DRIFT")
    return raw, call


def verify() -> list[dict[str, Any]]:
    """Verify signed-off bytes, exact cohort and original E0 scientific boundaries."""
    pins = {
        "w3": "87711bb530eb6d1a6e3ddb2d38e5d32735e47f395cf030f97607c18aa1ca5806",
        "w5": "3934b71eb3f49ef44805074095acb4762134fb7524fe74944a25fd3a32207967",
    }
    for label, pin in pins.items():
        base = ART / "inputs" / label
        manifest = base / "SOURCE_MANIFEST.json"
        if blob_hash(manifest.read_bytes()) != pin:
            raise ValueError("G107_MANIFEST_IDENTITY")
        prefix = "artifacts/g107/" if label == "w3" else "g107/"
        for item in read(manifest)["files"]:
            name = item["path"]
            if name.startswith(prefix):
                local = base / name.removeprefix(prefix)
                # W5 evaluator-only archive is not needed by the execution consumer.
                if label == "w5" and not (
                    name.startswith("g107/protocol/")
                    or name
                    in {"g107/PREREGISTRATION_ZH.md", "g107/REGISTRATION_RECORD.json"}
                ):
                    continue
                if blob_hash(local.read_bytes()) != item["sha256"]:
                    raise ValueError("G107_FROZEN_INPUT_DRIFT")
    issued = git("show", f"{W5_COMMIT}:g107/PREREG_RECEIPT.json", repo=W5_REPO)
    if issued != (W5 / "PREREG_RECEIPT.json").read_bytes():
        raise ValueError("G107_W5_ISSUANCE")
    receipt = json.loads(issued)
    if receipt["primary16_registration"] != (
        "FROZEN_ACCEPTED_SUBJECT_TO_W1_PREDISPATCH_RUNTIME_BINDING"
    ):
        raise ValueError("G107_PRIMARY16_NOT_REGISTERED")
    if datetime.fromisoformat(receipt["issued_at"]) >= datetime.now(UTC):
        raise ValueError("G107_PREREG_CLOCK")
    matrix = read(DESIGN / "freeze/REQUEST_MATRIX.json")
    cohort = read(W5 / "protocol/SAMPLE_COHORT.json")
    rows: list[dict[str, Any]] = matrix["samples"]
    if len(rows) != 16 or rows != cohort["samples"]:
        raise ValueError("G107_COHORT_IDENTITY")
    for row, planned in zip(rows, schedule(), strict=True):
        if any(row[k] != v for k, v in planned.items()):
            raise ValueError("G107_ORDER_IDENTITY")
        raw, _ = call_for(row)
        check_body(DESIGN, row["role"], row["arm"], raw)
    inputs_verified()  # Original Source, Prompt, native science and role bytes.
    return rows


def strict_object(text: str) -> dict[str, Any]:
    """Reject malformed JSON, duplicate keys and non-object roots without repair."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def bad_constant(value: str) -> None:
        raise ValueError("NONFINITE_JSON_NUMBER")

    obj = json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)
    if not isinstance(obj, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT")
    return obj


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Check frozen interface only, never repair content or confer research value."""
    try:
        obj = strict_object(text)
        if row["arm"] in {"A0", "A1"}:
            model = (
                FundamentalDraftResponse
                if row["role"] == "fundamental_analyst"
                else NewsDraftResponse
            )
            model.model_validate(obj)
        else:
            ctx = cast(dict[str, Any], call.input_payload)
            return diagnose_p1(obj, ctx["original_role_schema"], ctx["evidence_view"])
        return {"schema_valid": True, "scientific_admission": False}
    except Exception as exc:
        return {
            "schema_valid": False,
            "error_type": type(exc).__name__,
            "diagnostic": str(exc),
            "scientific_admission": False,
        }


def sample(
    row: dict[str, Any],
    target: Path,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    operation_id: str = OPERATION,
    episode_id: str = EPISODE,
    call_loader: (
        Callable[[dict[str, Any]], tuple[bytes, LLMProviderCall]] | None
    ) = None,
    diagnostic: (
        Callable[[str, dict[str, Any], LLMProviderCall], dict[str, Any]] | None
    ) = None,
    before_send: Callable[[httpx.Request], None] | None = None,
    before_transport: Callable[[httpx.Request], None] | None = None,
    model_profile: ModelExecutionProfile | None = None,
) -> dict[str, Any]:
    """Invoke exactly once through the original Provider; archive before parsing."""
    require_profile(model_profile)
    output_cap = model_profile.output_cap if model_profile else 8192
    raw, call = (call_loader or call_for)(row)
    target.mkdir(parents=True, exist_ok=False)
    identity = dict(
        row,
        AttemptID=f"{operation_id}:{row['ordinal']:02}:attempt1",
        OperationID=operation_id,
        EvaluationEpisodeID=episode_id,
        ResultRoot=str(target),
        ActualStartedAt=now(),
        engineering_fixture=fixture_transport is not None,
    )
    if model_profile is not None:
        identity["model_profile"] = profile_record(model_profile)
    durable(target / "identity.json", canonical(identity))
    event_number = 0

    def persist(event: dict[str, Any]) -> None:
        nonlocal event_number
        durable(target / "meter" / f"{event_number:04}.json", canonical(event))
        event_number += 1

    meter = DevelopmentAccountingMeter(
        persist, scope=identity, initial_call_limit=1, model_profile=model_profile
    )
    meter.limits = replace(
        capacity_limits(model_profile),
        calls=1,
        retries=0,
        output_per_call=output_cap,
        total_tokens=meter.input_reservation + output_cap,
        seconds=600,
    )
    audit = meter.prepare_request(call, scope=identity, output_cap=output_cap)
    attempted = False
    transport_entered = False
    response: dict[str, Any] | None = None
    reconciled = False
    system_error: str | None = None
    assistant = ""

    def before(request: httpx.Request) -> None:
        nonlocal attempted, system_error
        if (
            attempted
            or request.method != "POST"
            or str(request.url) != BEIJING + "/responses"
            or request.content != raw
        ):
            system_error = "G107_ACTUAL_WIRE_IDENTITY"
            raise ValueError(system_error)
        if before_send is not None:
            before_send(request)
        meter.reserve(meter.input_reservation)
        durable(target / "request.raw", request.content)
        durable(
            target / "invocation.json",
            canonical(
                {
                    "ActualInvocationAt": now(),
                    "request_sha256": blob_hash(request.content),
                    "status": "ATTEMPTED_SEND_UNCONFIRMED",
                }
            ),
        )
        attempted = True

    def enter_transport(request: httpx.Request) -> None:
        nonlocal transport_entered
        if before_transport is not None:
            before_transport(request)
        transport_entered = True

    def after(http: httpx.Response) -> None:
        nonlocal response, reconciled, system_error, assistant
        http.read()
        durable(target / "response.raw", http.content)
        durable(
            target / "http.json",
            canonical(
                {
                    "ActualResponseAt": now(),
                    "http_status": http.status_code,
                    "response_sha256": blob_hash(http.content),
                    "provider_request_ids": {
                        k: http.headers[k]
                        for k in ("x-request-id", "x-dashscope-request-id")
                        if k in http.headers
                    },
                }
            ),
        )
        try:
            response = json.loads(http.content)
            if (
                http.status_code != 200
                or not isinstance(response, dict)
                or response.get("status") not in {"completed", "incomplete"}
            ):
                raise ValueError("HTTP_OR_RESPONSE_ENVELOPE")
            assistant = "".join(
                part["text"]
                for output in response.get("output", [])
                if output.get("type") == "message"
                for part in output.get("content", [])
                if part.get("type") == "output_text"
            )
            durable(target / "assistant.txt", assistant.encode())
            meter.reconcile(
                response,
                request_id=(
                    http.headers.get("x-request-id")
                    or http.headers.get("x-dashscope-request-id")
                    or response.get("id", "")
                ),
                persist=lambda x: durable(target / "usage.json", canonical(x)),
            )
            reconciled = True
        except Exception:
            system_error = "G107_HTTP_MODEL_OR_USAGE_INTEGRITY"
            raise

    settings = QwenSettings(
        max_output_tokens=output_cap,
        max_retries=0,
        base_url=BEIJING,
        enable_thinking=False,
        store_remote=False,
    )
    if fixture_transport is not None:
        settings = settings.model_copy(
            update={"api_key": SecretStr("OFFLINE_SENTINEL")}
        )
    error_type = None
    try:
        if model_profile is not None:
            settings.resolve_model(
                expected_model=model_profile.model,
                allowed_models=frozenset({model_profile.model}),
            )
            if settings.timeout_seconds != 90:
                raise ValueError("DEVELOPMENT_PROFILE_TIMEOUT_IDENTITY")
        if settings.api_key is None:
            raise ValueError("CREDENTIAL_NOT_CONFIGURED")
        hooks: dict[str, list[Callable[..., Any]]] = {
            "request": [before],
            "response": [after],
        }
        with recovery_client(
            hooks,
            fixture_transport=fixture_transport,
            before_transport=enter_transport if before_transport else None,
        ) as http:
            with OpenAI(
                api_key=settings.api_key.get_secret_value(),
                base_url=BEIJING,
                max_retries=0,
                http_client=http,
            ) as sdk:
                QwenProvider(
                    settings,
                    client=sdk,
                    native_schema_probe=bool(
                        model_profile and model_profile.native_schema_probe
                    ),
                ).invoke_json(
                    call.model,
                    call.system_prompt,
                    call.input_payload,
                    response_schema=call.response_schema,
                    schema_name=row["role"],
                )
    except Exception as exc:
        error_type = type(exc).__name__  # Exception strings may contain secrets.
    diagnostic_result = (
        (diagnostic or diagnose)(assistant, row, call)
        if reconciled
        else {"schema_valid": False, "not_evaluated": "NO_RELIABLE_USAGE_RESPONSE"}
    )
    system_stop = system_error is not None or not reconciled
    complete = response is not None and response.get("status") == "completed"
    outcome = dict(
        identity,
        provider_attempts=(int(transport_entered) if before_transport else meter.calls),
        response_received=(target / "response.raw").exists(),
        actual_model=response.get("model") if response else None,
        response_id=response.get("id") if response else None,
        response_completed=complete,
        usage_known=reconciled,
        diagnostic=diagnostic_result,
        provider_error_type=error_type,
        stop_remaining=system_stop,
        stop_reason=system_error
        or ("LOCAL_OR_UNCERTAIN_SEND_FAILURE" if system_stop else None),
        status=(
            "SYSTEM_FAILURE"
            if system_stop
            else (
                "COMPLETED"
                if complete and diagnostic_result["schema_valid"]
                else "CONTENT_OR_SCHEMA_FAILURE"
            )
        ),
        input_tokens=(
            response["usage"]["input_tokens"] if reconciled and response else None
        ),
        output_tokens=(
            response["usage"]["output_tokens"] if reconciled and response else None
        ),
        fixed_rate_cost_reference=str(meter.cost) if reconciled else "UNKNOWN",
        actual_provider_bill="UNKNOWN",
        cost_reference_scope=(
            "CONDITIONAL_PUBLIC_MODEL_PRICE_NOT_ACCOUNT_BILL"
            if model_profile
            else "LEGACY_CONSERVATIVE_REFERENCE"
        ),
        scientific_writes=0,
        audit_request_sha256=audit["http_body_sha256"],
    )
    if before_transport is not None:
        outcome["meter_reserved_calls"] = meter.calls
        outcome["transport_admitted"] = transport_entered
    durable(target / "outcome.json", canonical(outcome))
    return outcome


def execute(
    *,
    environment: str,
    source_commit: str,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_root: Path | None = None,
) -> dict[str, Any]:
    """Bind one exclusive primary16 operation, then execute only frozen slots."""
    if environment != "DEVELOPMENT":
        raise ValueError("G107_DEVELOPMENT_ONLY")
    rows = verify()
    head = git("rev-parse", "HEAD").decode().strip()
    if head != source_commit:
        raise ValueError("G107_EXECUTION_SOURCE_IDENTITY")
    modules = {p: blob_hash((ROOT / p).read_bytes()) for p in MODULES}
    if fixture_transport is None:
        for p in MODULES:
            if git("show", f"{head}:{p}") != (ROOT / p).read_bytes():
                raise ValueError("G107_UNCOMMITTED_RUNTIME")
    elif type(fixture_transport) is not httpx.MockTransport or fixture_root is None:
        raise ValueError("G107_FIXTURE_ORIGIN")
    destination = RESULT if fixture_transport is None else fixture_root
    assert destination is not None
    # Construct transport offline before reserving an exclusive operation/archive.
    client = recovery_client({}, fixture_transport=fixture_transport)
    client.close()
    destination.mkdir(parents=True, exist_ok=False)
    planned = [
        dict(
            row,
            AttemptID=f"{OPERATION}:{row['ordinal']:02}:attempt1",
            OperationID=OPERATION,
            EvaluationEpisodeID=EPISODE,
            status="NOT_ATTEMPTED",
        )
        for row in rows
    ]
    binding = dict(
        created_at=now(),
        OperationID=OPERATION,
        EvaluationEpisodeID=EPISODE,
        execution_source_commit=head,
        modules=modules,
        w5_issuance_commit=W5_COMMIT,
        w5_receipt_sha256=blob_hash((W5 / "PREREG_RECEIPT.json").read_bytes()),
        w3_source_commit="accf461bbad476b812f146b288ce7989d0aafac4",
        policy=POLICY,
        monetary_cost_gate="DISABLED",
        usage_integrity_gate="REQUIRED",
        science_admission="BLOCKED",
        w4_live_review="NOT_COMPLETED",
        slots=planned,
        proxy=configured_https_proxy()[1],
        engine="EXISTING_QWEN_PROVIDER_AND_OPENAI_SDK",
        engineering_fixture=fixture_transport is not None,
    )
    durable(destination / "PREDISPATCH.json", canonical(binding))
    outcomes = []
    stop = None
    for row, slot in zip(rows, planned, strict=True):
        if stop:
            outcomes.append(dict(slot, not_attempted_reason=stop))
            continue
        try:
            result = sample(
                row,
                destination / f"{row['ordinal']:02}",
                fixture_transport=fixture_transport,
            )
        except Exception as exc:
            # Archive assembly/source failures must not erase unexecuted slots.
            # Any existing invocation marker is conservatively counted as attempted.
            target = destination / f"{row['ordinal']:02}"
            attempted = (target / "invocation.json").exists()
            result = dict(
                slot,
                status="SYSTEM_FAILURE",
                provider_attempts=int(attempted),
                response_received=(target / "response.raw").exists(),
                stop_remaining=True,
                stop_reason="LOCAL_ARCHIVE_OR_INPUT_ERROR",
                error_type=type(exc).__name__,
                usage_known=False,
            )
            durable(
                destination / f"{row['ordinal']:02}-orchestration-failure.json",
                canonical(result),
            )
        outcomes.append(result)
        print(
            json.dumps(
                {
                    "sample_id": row["sample_id"],
                    "status": result["status"],
                    "attempts": result["provider_attempts"],
                }
            ),
            flush=True,
        )
        if result["stop_remaining"]:
            stop = result["stop_reason"]
    census = dict(
        binding=binding,
        finished_at=now(),
        planned_samples=16,
        actual_provider_attempts=sum(x.get("provider_attempts", 0) for x in outcomes),
        actual_model_responses=sum(bool(x.get("response_received")) for x in outcomes),
        samples=outcomes,
        stop_reason=stop,
        w5_evaluation="PENDING",
        scientific_writes=0,
    )
    durable(destination / "COHORT_CENSUS.json", canonical(census))
    return census


def main() -> None:
    """Explicit CLI trigger; standing authorization is not a JSON approval flag."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if not args.execute:
        raise ValueError("G107_EXPLICIT_EXECUTION_TRIGGER_REQUIRED")
    execute(environment=args.environment, source_commit=args.source_commit)


if __name__ == "__main__":
    main()
