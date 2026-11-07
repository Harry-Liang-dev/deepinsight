"""Isolated G106 composition with explicit, development-only standing execution.

Historical per-batch approval remains available. Standing mode reuses the same
Provider, requests and archive loop; it never writes scientific state.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
from openai import OpenAI
from pydantic import SecretStr

from src.agents.prompts import PromptLoader
from src.core.settings import QwenSettings
from src.memory.vnext_contracts import ArtifactRef
from src.models.enums import AgentName
from src.schemas.agents import FundamentalDraftResponse, NewsDraftResponse
from src.schemas.research_v2_shared import Clock, Frozen, canonical
from src.services.llm_provider import LLMProviderCall, QwenProvider
from src.services.native_preservation import blob_hash
from src.services.pilot_capacity_budget import (
    MAX_INPUT,
    CapacityMeter,
    capacity_envelope,
    capacity_limits,
)
from src.services.pilot_model_readiness import (
    BEIJING,
    SNAPSHOT,
    request_audit,
)
from src.services.research_vnext.real_memory_meter import durable
from tools.development_model_policy import (
    DevelopmentAccountingMeter,
    DevelopmentExecution,
    DevelopmentOperation,
    RecoveryOperation,
    bind_development,
)
from tools.g105_r1_googl_preflight import read, verify
from tools.g106_transport import recovery_client

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "artifacts/g105-r1/g106-input"
FREEZE = INPUT / "artifacts/g106/freeze-v2"
ROLES = ("fundamental_analyst", "news_event_analyst")
CAP = 8192
PARENT_MANIFEST = "1e3f6a0fc52da7c8d38e1ae09d1e75becc5d71151e36565a3753de58a379e7ec"


class ExperimentApproval(Frozen):
    """Trusted resolver's normalized user permission, never request JSON authority.

    The resolver must independently verify actual user approval and W4/W5 scope,
    bytes and chronology before returning ACTUAL_USER_APPROVAL. No issuer string
    or this schema alone supplies that trust. No resolver is shipped/configured.
    """

    origin: Literal["ACTUAL_USER_APPROVAL", "SYNTHETIC_ENGINEERING_FIXTURE"]
    user_event: ArtifactRef
    w4_review: ArtifactRef
    w5_addendum: ArtifactRef
    approved_at: Clock
    expires_at: Clock
    experiment_sha256: str
    model: str
    roles: tuple[str, ...]
    source_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    request_sha256: tuple[str, ...]
    max_calls: int
    ceiling_cny: str
    results_root: str
    permission: Literal["EXPLORATORY_MODEL_RESEARCH_EVALUATION"]
    fixed_rate_capacity_assumptions_accepted: bool


def inputs_verified() -> None:
    """Check immutable source/view/schema/Prompt bytes against the pinned parent."""
    raw = (ROOT / "artifacts/g106-d1/inputs/PARENT_MANIFEST.json").read_bytes()
    if blob_hash(raw) != PARENT_MANIFEST:
        raise ValueError("D1_PARENT_MANIFEST_IDENTITY")
    for item in json.loads(raw)["files"]:
        name = item["path"]
        if name.startswith(
            ("src/", "config/prompts/", "artifacts/g105-r1/g106-input/")
        ):
            if blob_hash((ROOT / name).read_bytes()) != item["sha256"]:
                raise ValueError("D1_FROZEN_INPUT_DRIFT:" + name)
    verify(INPUT)


def call_for(role: str) -> LLMProviderCall:
    """Reuse original role Prompt and complete frozen model context/schema."""
    if role not in ROLES:
        raise ValueError("D1_ROLE")
    context = read(FREEZE / (role + ".MODEL_CONTEXT.json"))
    schema = read(FREEZE / "ORIGINAL_ROLE_SCHEMAS.json")[role]
    prompt = PromptLoader(ROOT / "config/prompts").load(AgentName(role))
    return LLMProviderCall(SNAPSHOT, prompt.system_prompt, context, schema)


def prepare(output: Path, results_root: Path) -> dict[str, Any]:
    """Freeze two exact SDK requests; adding only the declared output limit."""
    inputs_verified()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for role in ROLES:
        audit = request_audit(call_for(role), output_cap=CAP)
        body = audit["serialized_http_body"].encode()
        old = read(
            ROOT
            / "artifacts/g106-predispatch/execution-final"
            / (role + ".sdk-body.json")
        )
        current = json.loads(body)
        if current != {**old, "max_output_tokens": CAP}:
            raise ValueError("D1_UNAPPROVED_REQUEST_CHANGE")
        durable(output / (role + ".request.json"), body)
        durable(output / (role + ".audit.json"), canonical(audit))
        task = read(FREEZE / (role + ".RESEARCH_TASK.json"))
        rows.append(
            dict(
                role=role,
                task_id=task["task_id"],
                task_sha256=blob_hash(
                    (FREEZE / (role + ".RESEARCH_TASK.json")).read_bytes()
                ),
                request_sha256=blob_hash(body),
                request_file=role + ".request.json",
                input_context_sha256=blob_hash(
                    (FREEZE / (role + ".MODEL_CONTEXT.json")).read_bytes()
                ),
            )
        )
    plan = dict(
        schema="G106_D1_ISOLATED_EXPERIMENT_V1",
        experiment_id="G106-D1-GOOGL-CLOUD-v1",
        purpose="EXPLORATORY_MODEL_RESEARCH_EVALUATION",
        model=SNAPSHOT,
        region="cn-beijing",
        endpoint=BEIJING + "/responses",
        roles=list(ROLES),
        sources=["G105-GET-02", "G105-GET-07"],
        security="US:GOOGL",
        cik="0001652044",
        max_calls=2,
        concurrency=1,
        retries=0,
        fallback="NONE",
        output_cap=CAP,
        temperature="OMITTED_ORIGINAL_PROVIDER_DEFAULT_UNKNOWN",
        baseline_sha256=blob_hash(
            (FREEZE / "DETERMINISTIC_BASELINE_FREEZE.json").read_bytes()
        ),
        source_readset_sha256=blob_hash((FREEZE / "SOURCE_READSET.json").read_bytes()),
        ResearchInformationCutoff="2026-10-29T18:35:03.531050Z",
        OriginalTaskCreatedAt="2026-10-29T18:46:34.877770Z",
        ExperimentCreatedAt=datetime.now(UTC).isoformat(),
        ActualInvocationAt=None,
        ActualResponseAt=None,
        requests=rows,
        results_root=str(results_root.resolve()),
        implementation_sha256=blob_hash(Path(__file__).read_bytes()),
        model_execution_authorized=False,
        paid_execution_authorized=False,
        canonical_evidence_count=0,
        financial_allowlist=[],
        memory=[],
        run_bound_memory_readset=None,
        scientific_admission="BLOCKED",
        source_attribution_only=True,
        proposed_capacity_ceiling_cny="2.50",
        conditional_two_call_bound_cny=str(
            2
            * (Decimal(MAX_INPUT) * Decimal("1.2") + Decimal(CAP) * Decimal("4.8"))
            / Decimal(1000000)
        ),
        cost_ceiling_qualification="UNKNOWN",
        context_fit="UNKNOWN",
        envelope={
            **{
                k: v
                for k, v in capacity_envelope().items()
                if k
                in {
                    "model",
                    "region",
                    "endpoint",
                    "context",
                    "maximum_input",
                    "maximum_output",
                    "currency",
                    "per_attempt_reservation",
                    "assumptions",
                    "documentation_identity",
                    "exact_token_count",
                    "context_enforcement",
                    "account_access",
                    "actual_bill",
                }
            },
            "version": "g106_d1_two_call_capacity/1.0.0",
            "maximum_calls": 2,
            "aggregate_capacity_reservation": 2 * (MAX_INPUT + CAP),
            "maximum_standard_cost": "2.4589824",
            "proposed_ceiling": "2.50",
            "elapsed_seconds": 600,
            "concurrency": 1,
            "retries": 0,
            "execution_authorized": False,
        },
        stop_policy=(
            "Stop both-call sequence on failure, truncation, unknown usage "
            "or schema rejection; never retry/resume"
        ),
        w4_review_required=True,
        w5_addendum_required=True,
    )
    durable(output / "EXPERIMENT.json", canonical(plan))
    return plan


def _authorize(
    plan: dict[str, Any],
    raw: bytes,
    approval_ref: ArtifactRef | None,
    resolver: Callable[[ArtifactRef], ExperimentApproval] | None,
    *,
    fixture_transport: bool,
) -> ExperimentApproval:
    if approval_ref is None or resolver is None:
        raise ValueError("D1_USER_AUTHORIZATION_MISSING")
    approval = resolver(approval_ref)
    approval = ExperimentApproval.model_validate_json(approval.model_dump_json())
    now = datetime.now(UTC)
    if (
        blob_hash(canonical(approval)) != approval_ref.sha256_digest
        or approval.approved_at > now
        or approval.expires_at <= now
        or approval.experiment_sha256 != blob_hash(raw)
        or approval.model != SNAPSHOT
        or approval.roles != ROLES
        or approval.source_ids != tuple(plan["sources"])
        or approval.task_ids != tuple(x["task_id"] for x in plan["requests"])
        or approval.request_sha256
        != tuple(x["request_sha256"] for x in plan["requests"])
        or type(approval.max_calls) is not int
        or approval.max_calls != 2
        or approval.ceiling_cny != "2.50"
        or not approval.fixed_rate_capacity_assumptions_accepted
        or approval.results_root != plan["results_root"]
    ):
        raise ValueError("D1_APPROVAL_SCOPE_MISMATCH")
    approval_ref.require_recorded_by(now)
    for ref in (approval.user_event, approval.w4_review, approval.w5_addendum):
        ref.require_recorded_by(approval.approved_at)
    if fixture_transport != (approval.origin == "SYNTHETIC_ENGINEERING_FIXTURE"):
        raise ValueError("D1_AUTHORITY_TRANSPORT_ORIGIN")
    return approval


def execute_approved(
    plan_dir: Path,
    *,
    approval_ref: ArtifactRef | None = None,
    trusted_resolver: Callable[[ArtifactRef], ExperimentApproval] | None = None,
    fixture_transport: httpx.MockTransport | None = None,
    development: DevelopmentOperation | None = None,
) -> dict[str, Any]:
    """One approved two-call attempt sequence; no scientific services are present.

    The development CLI requires the installed standing policy and independent
    W5 pre-output record. Historical fixture authorization cannot use the network.
    An exclusive approval-bound result directory consumes the experiment once, including
    crashes; no resume/retry or archive-root substitution is permitted.
    """
    if (
        fixture_transport is not None
        and type(fixture_transport) is not httpx.MockTransport
    ):
        raise ValueError("D1_FIXTURE_TRANSPORT_REQUIRED")
    raw = (plan_dir / "EXPERIMENT.json").read_bytes()
    plan = json.loads(raw)
    approval: ExperimentApproval | DevelopmentExecution
    if development is not None:
        if approval_ref is not None or trusted_resolver is not None:
            raise ValueError("DEV_MIXED_AUTHORITY_MODES")
        approval = bind_development(
            development, raw, fixture=fixture_transport is not None
        )
    else:
        approval = _authorize(
            plan,
            raw,
            approval_ref,
            trusted_resolver,
            fixture_transport=fixture_transport is not None,
        )
    inputs_verified()
    if (
        (
            development is None
            and plan["implementation_sha256"] != blob_hash(Path(__file__).read_bytes())
        )
        or plan["roles"] != list(ROLES)
        or plan["model"] != SNAPSHOT
        or plan["max_calls"] != 2
        or plan["output_cap"] != CAP
        or plan["sources"] != ["G105-GET-02", "G105-GET-07"]
    ):
        raise ValueError("D1_PLAN_IDENTITY")
    calls = [call_for(role) for role in ROLES]
    audits = [request_audit(c, output_cap=CAP) for c in calls]
    for row, audit in zip(plan["requests"], audits, strict=True):
        body = (plan_dir / row["request_file"]).read_bytes()
        if (
            blob_hash(body) != row["request_sha256"]
            or body != audit["serialized_http_body"].encode()
        ):
            raise ValueError("D1_REQUEST_IDENTITY")
    destination = Path(approval.results_root)
    if str(destination.resolve()) != approval.results_root:
        raise ValueError("D1_RESULT_PATH_IDENTITY")
    destination.mkdir(parents=True, exist_ok=False)
    durable(destination / "experiment.json", raw)
    if isinstance(approval, DevelopmentExecution):
        durable(
            destination / "development-operation.json",
            canonical(
                {**approval.record, "ActualStartedAt": datetime.now(UTC).isoformat()}
            ),
        )
    else:
        durable(destination / "approval.json", canonical(approval))
    durable(
        destination / "execution-code.json",
        canonical(
            dict(
                executor_sha256=blob_hash(Path(__file__).read_bytes()),
                development_policy_sha256=blob_hash(
                    (ROOT / "tools/development_model_policy.py").read_bytes()
                ),
            )
        ),
    )
    events = 0

    def persist(event: dict[str, Any]) -> None:
        nonlocal events
        durable(destination / "budget" / f"{events:04}.json", canonical(event))
        events += 1

    meter_type = (
        DevelopmentAccountingMeter if development is not None else CapacityMeter
    )
    meter = meter_type(persist, scope=plan, initial_call_limit=2)
    meter.limits = replace(
        capacity_limits(),
        calls=2,
        retries=0,
        total_tokens=2 * (MAX_INPUT + CAP),
        cost_ceiling=(
            Decimal(approval.ceiling_cny)
            if isinstance(approval, ExperimentApproval)
            else Decimal("2.50")
        ),
        seconds=600,
    )
    settings = QwenSettings(
        max_output_tokens=CAP,
        max_retries=0,
        base_url=BEIJING,
        enable_thinking=False,
        store_remote=False,
    )
    if fixture_transport is not None:
        settings = settings.model_copy(
            update={"api_key": SecretStr("OFFLINE_SENTINEL_NOT_A_CREDENTIAL")}
        )
    if settings.api_key is None:
        durable(
            destination / "STOPPED.json",
            canonical(dict(error="CREDENTIAL_NOT_CONFIGURED")),
        )
        raise ValueError("D1_CREDENTIAL_NOT_CONFIGURED")
    outcomes = []
    for index, (role, call) in enumerate(zip(ROLES, calls, strict=True), 1):
        attempt = destination / f"{index:02}-{role}"
        audit = meter.prepare_request(call, scope=plan, output_cap=CAP)
        sent = False
        response_seen = False

        def before(request: httpx.Request) -> None:
            nonlocal sent
            if (
                sent
                or request.method != "POST"
                or str(request.url) != plan["endpoint"]
                or blob_hash(request.content) != audit["http_body_sha256"]
            ):
                raise ValueError("D1_ACTUAL_WIRE_IDENTITY")
            meter.reserve(MAX_INPUT)
            durable(attempt / "request.raw", request.content)
            durable(
                attempt / "invocation.json",
                canonical(
                    dict(
                        ActualInvocationAt=datetime.now(UTC),
                        role=role,
                        origin=approval.origin,
                        scientific_agent_run=False,
                        status="STARTED_RESULT_UNKNOWN",
                        request_sha256=blob_hash(request.content),
                    )
                ),
            )
            sent = True

        def after(response: httpx.Response) -> None:
            nonlocal response_seen
            response.read()
            durable(attempt / "response.raw", response.content)
            durable(
                attempt / "http.json",
                canonical(
                    dict(
                        ActualResponseAt=datetime.now(UTC),
                        http_status=response.status_code,
                        response_sha256=blob_hash(response.content),
                    )
                ),
            )
            response_seen = True
            body = json.loads(response.content)
            if response.status_code != 200 or body.get("status") != "completed":
                raise ValueError("D1_HTTP_OR_TRUNCATION")
            meter.reconcile(
                body,
                request_id=body.get("id", ""),
                persist=lambda row: durable(attempt / "usage.json", canonical(row)),
            )

        try:
            hooks: dict[str, list[Callable[..., Any]]] = {
                "request": [before],
                "response": [after],
            }
            client = (
                recovery_client(hooks, fixture_transport=fixture_transport)
                if development is not None and development.recovery is not None
                else httpx.Client(
                    transport=fixture_transport,
                    follow_redirects=False,
                    event_hooks=hooks,
                )
            )
            with client as http:
                with OpenAI(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=BEIJING,
                    max_retries=0,
                    http_client=http,
                ) as sdk:
                    result = QwenProvider(settings, client=sdk).invoke_json(
                        call.model,
                        call.system_prompt,
                        call.input_payload,
                        response_schema=call.response_schema,
                        schema_name=role,
                    )
            model_type = (
                FundamentalDraftResponse if role == ROLES[0] else NewsDraftResponse
            )
            parsed = model_type.model_validate(result.content)
            if parsed.status.value != "ok":
                raise ValueError("D1_ROLE_REPORTED_FAILURE")
            durable(attempt / "parsed-research.json", canonical(result.content))
            outcome = dict(
                role=role,
                status="SCHEMA_VALID_NOT_SCIENTIFIC",
                schema_valid=True,
                actual_model=result.model,
                source_attribution="MODEL_ASSERTIONS_NOT_INDEPENDENTLY_VALIDATED",
                scientific_claims=0,
                state_events=0,
                scientific_memory_writes=0,
                actual_provider_bill="UNKNOWN",
                request_sha256=audit["http_body_sha256"],
            )
            durable(attempt / "outcome.json", canonical(outcome))
            outcomes.append(outcome)
        except Exception as exc:
            # Preserve raw wire data separately; never serialize exception messages
            # which may contain credentials, host state or untrusted response text.
            failure = dict(
                role=role,
                error_type=type(exc).__name__,
                sent=sent,
                response_seen=response_seen,
                status="STOPPED_NO_RETRY",
                scientific_acceptance=False,
                stop_reason=(
                    str(exc)
                    if isinstance(exc, ValueError) and str(exc).startswith("D1_")
                    else meter.stopped
                    or "PROVIDER_OR_SCHEMA_ERROR_RAW_ARCHIVE_PRESERVED"
                ),
            )
            durable(attempt / "failure.json", canonical(failure))
            durable(destination / "STOPPED.json", canonical(failure))
            outcomes.append(failure)
            break
    receipt = dict(
        experiment_sha256=blob_hash(raw),
        outcomes=outcomes,
        origin=approval.origin,
        scientific_agent_runs=0,
        scientific_claims=0,
        state_events=0,
        scientific_memory_writes=0,
        quant_handoffs=0,
        provider_attempts=meter.calls,
        fixed_rate_reserved_or_settled_cny=str(meter.cost),
        actual_provider_bill="UNKNOWN",
    )
    if development is not None:
        settled = [row for row in meter.receipts if row["event"] == "SETTLED"]
        complete_usage = len(settled) == meter.calls
        receipt.update(
            policy="DEVELOPMENT_MODEL_EXECUTION_POLICY_V1",
            w4_live_boundary_review="NOT_COMPLETED",
            token_cost_gate="DISABLED",
            cost_reporting="REFERENCE_ONLY",
            usage_complete=complete_usage,
            actual_input_tokens=(
                sum(row["input_tokens"] for row in settled) if complete_usage else None
            ),
            actual_output_tokens=(
                sum(row["output_tokens"] for row in settled) if complete_usage else None
            ),
            estimated_cost_cny=str(meter.cost) if complete_usage else "UNKNOWN",
        )
    if development is not None and development.recovery is not None:
        receipt.update(
            OperationID=development.recovery.operation_id,
            EvaluationEpisodeID=development.recovery.evaluation_episode_id,
            old_stopped_archive_preserved=True,
        )
    durable(destination / "W5_EXPERIMENT_INPUT.json", canonical(receipt))
    return receipt


def main() -> None:
    """Prepare inputs or explicitly trigger the isolated development experiment."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--results-root", type=Path)
    parser.add_argument("--development-execute", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--experiment-id")
    parser.add_argument("--w5-commit", default="")
    parser.add_argument("--w5-path", default="")
    parser.add_argument("--w5-sha256", default="")
    parser.add_argument("--operation-id")
    parser.add_argument("--evaluation-episode-id")
    parser.add_argument("--episode-repository", type=Path)
    parser.add_argument("--episode-commit")
    parser.add_argument("--episode-path")
    parser.add_argument("--episode-sha256")
    args = parser.parse_args()
    if args.development_execute:
        recovery = None
        episode_args = [
            args.operation_id,
            args.evaluation_episode_id,
            args.episode_repository,
            args.episode_commit,
            args.episode_path,
            args.episode_sha256,
        ]
        if any(episode_args):
            if not all(episode_args):
                parser.error("all recovery operation/episode fields are required")
            recovery = RecoveryOperation(*episode_args)
        receipt = execute_approved(
            ROOT / "artifacts/g106-d1/freeze",
            development=DevelopmentOperation(
                args.environment,
                args.experiment_id,
                args.w5_commit,
                args.w5_path,
                args.w5_sha256,
                recovery=recovery,
            ),
        )
        print(json.dumps(receipt))
        return
    if args.output is None or args.results_root is None:
        parser.error("preparation requires --output and --results-root")
    plan = prepare(args.output, args.results_root)
    print(json.dumps(dict(model_execution_authorized=False, requests=plan["requests"])))


if __name__ == "__main__":
    main()
