"""Bounded concurrent orchestration over original Qwen Sender/Meter/HTTP capture."""

from __future__ import annotations

import fcntl
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx

from research_eval.compiler import RequestCompiler, profile
from research_eval.evaluation import ProposalShape
from research_eval.models import (
    Budget,
    FrozenExperiment,
    FrozenRequest,
    identity,
)
from research_eval.recovery import reconcile_previous, seal_completed
from research_eval.security import Authority, CampaignReleaseGate
from research_eval.storage import TraceRecorder
from src.models.types import JsonObject
from src.services.development_model_profile import reference_cost
from src.services.llm_provider import LLMProviderCall
from tools import g107_matrix as sender
from tools.g113_r3_execute import binding_error


def shape_diagnostic(
    text: str, row: dict[str, Any], call: LLMProviderCall
) -> dict[str, Any]:
    """Strict shape after capture, without implying local or scientific PASS."""
    del row, call
    try:
        ProposalShape.model_validate(sender.strict_object(text))
        return dict(schema_valid=True, local_guard="NOT_EVALUATED")
    except ValueError as exc:
        return dict(schema_valid=False, error_type=type(exc).__name__)


class BudgetController:
    """Atomic reservations under a campaign process lock; no retries or refunds."""

    def __init__(self, budget: Budget, cap: int, recorder: TraceRecorder) -> None:
        self.budget, self.profile, self.recorder = budget, profile(cap), recorder
        self.lock = threading.RLock()
        self.attempts = self.tokens = self.active = self.peak = 0
        self.cost = Decimal(0)
        self.stopped: str | None = None
        self.stop_persistence_error: Exception | None = None
        self.next_dispatch = 0.0

    def reserve(self, request: FrozenRequest) -> None:
        """Reserve an envelope before network; bytes are not token counts."""
        with self.lock:
            if self.stopped:
                raise ValueError("GLOBAL_SYSTEM_STOP")
            tokens = self.profile.input_reservation + self.profile.output_cap
            cost = reference_cost(
                self.profile, self.profile.input_reservation, self.profile.output_cap
            )
            if (
                self.attempts + 1 > self.budget.max_attempts
                or self.tokens + tokens > self.budget.max_tokens
                or self.cost + cost > self.budget.max_reference_cost_cny
            ):
                self.stop("BUDGET_EXCEEDED")
                raise ValueError(self.stopped)
            delay = self.next_dispatch - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.next_dispatch = time.monotonic() + 1 / self.budget.requests_per_second
            # A body key survives crashes, workers and experiment renames.
            self.recorder.record(
                "attempts/" + request.request_sha256 + ".json",
                dict(
                    run_id=request.run_id,
                    request_sha256=request.request_sha256,
                    status="RESERVED_CONSUMED_OR_QUARANTINED",
                    reserved_at=datetime.now(UTC).isoformat(),
                ),
            )
            self.attempts += 1
            self.tokens += tokens
            self.cost += cost
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.recorder.record(
                f"budget/{self.attempts:06}.json",
                dict(
                    attempts=self.attempts,
                    reserved_tokens=self.tokens,
                    reserved_reference_cny=str(self.cost),
                ),
            )

    def stop(self, reason: str) -> None:
        """Persist a campaign-wide stop, including unknown-send quarantine."""
        with self.lock:
            if not self.stopped:
                self.stopped = reason
                try:
                    self.recorder.record("STOP.json", dict(reason=reason))
                except Exception as exc:
                    self.stop_persistence_error = exc
                    raise

    def finish(self, *, system_failure: str | None) -> None:
        """Stop pending sends, leaving already in-flight requests preserved."""
        with self.lock:
            self.active = max(0, self.active - 1)
            if system_failure:
                self.stop(system_failure)


class OfflineScenario:
    """Explicit synthetic response plan, never a Provider capability certificate."""

    def __init__(
        self, outcomes: dict[str, dict[str, Any]], delay: float = 0.08
    ) -> None:
        self.outcomes, self.delay = outcomes, delay

    def transport(self, request: FrozenRequest) -> httpx.MockTransport:
        """Return isolated transport; original SDK and capture hooks remain in use."""
        record = self.outcomes[request.variant_id + "/" + request.case_id]

        def respond(wire: httpx.Request) -> httpx.Response:
            time.sleep(self.delay)
            if record.get("system_error") == "UNKNOWN_SEND":
                raise httpx.ReadTimeout("OFFLINE_UNKNOWN_SEND", request=wire)
            text = str(record["assistant"])
            body = dict(
                id="offline-" + request.run_id[:16],
                object="response",
                created_at=0,
                model=record.get("model", "qwen3.8-flash"),
                status="completed",
                output=[
                    dict(
                        type="message",
                        role="assistant",
                        content=[dict(type="output_text", text=text)],
                    )
                ],
                usage=dict(
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    input_tokens_details=dict(cached_tokens=0),
                ),
            )
            if record.get("system_error") == "MISSING_USAGE":
                body.pop("usage")
            return httpx.Response(int(record.get("http_status", 200)), json=body)

        return httpx.MockTransport(respond)


class TrustedExperimentRunner:
    """One operator-owned root per campaign; prompt workers cannot install grants."""

    def __init__(
        self, root: Path, authority: Authority, release_gate: CampaignReleaseGate
    ) -> None:
        self.root, self.authority, self.release_gate = root, authority, release_gate

    def run(
        self, frozen: FrozenExperiment, *, scenario: OfflineScenario | None = None
    ) -> dict[str, Any]:
        """Execute a freeze; live requires genuine release and current receiver."""
        RequestCompiler().verify(frozen)
        offline = frozen.spec.mode == "OFFLINE"
        if (
            offline != (scenario is not None)
            or offline != self.authority.engineering_fixture
        ):
            raise ValueError("FIXTURE_LIVE_MODE_MISMATCH")
        if not offline:
            if self.root.resolve() != Path(frozen.campaign.ledger_root).resolve():
                raise ValueError("CANONICAL_CAMPAIGN_LEDGER_ROOT")
            self.release_gate.check(frozen.campaign)
        if (
            not frozen.campaign.created_at
            <= datetime.now(UTC)
            < frozen.campaign.expires_at
        ):
            raise ValueError("CAMPAIGN_EXPIRED")
        campaign_root = self.root / identity(frozen.campaign)
        campaign_root.mkdir(parents=True, exist_ok=True)
        with (campaign_root / "campaign.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._locked(frozen, campaign_root, scenario)

    def _locked(
        self,
        frozen: FrozenExperiment,
        campaign_root: Path,
        scenario: OfflineScenario | None,
    ) -> dict[str, Any]:
        recorder = TraceRecorder(campaign_root)

        # Reconstruct reservations across every prior experiment, including crashes.
        prior = list((campaign_root / "attempts").glob("*.json"))
        reconcile_previous(campaign_root, frozen.campaign, prior)
        reserved_bodies = {p.stem for p in prior}
        if any(r.request_sha256 in reserved_bodies for r in frozen.requests):
            raise ValueError("REQUEST_ALREADY_CONSUMED_NO_RESEND")
        if (campaign_root / "STOP.json").exists():
            raise ValueError("CAMPAIGN_STOPPED_NO_RESEND")
        previous_plans = sum(
            len(json.loads(p.read_bytes())["requests"])
            for p in (campaign_root / "experiments").glob("*/freeze.json")
        )
        if previous_plans + len(frozen.requests) > frozen.campaign.budget.max_samples:
            raise ValueError("CAMPAIGN_SAMPLE_BUDGET")
        target = campaign_root / "experiments" / frozen.spec.experiment_id
        target.mkdir(parents=True, exist_ok=False)
        TraceRecorder(target).record("freeze.json", frozen)
        budget = BudgetController(
            frozen.campaign.budget, frozen.campaign.output_cap, recorder
        )
        budget.attempts = len(prior)
        budget.tokens = len(prior) * (
            budget.profile.input_reservation + budget.profile.output_cap
        )
        budget.cost = len(prior) * reference_cost(
            budget.profile, budget.profile.input_reservation, budget.profile.output_cap
        )
        cases = {c.case_id: c for c in frozen.dataset.cases}
        started = time.monotonic()

        def work(request: FrozenRequest) -> dict[str, Any]:
            case = cases[request.case_id]
            with budget.lock:
                if budget.stopped:
                    return dict(
                        run_id=request.run_id,
                        case_id=request.case_id,
                        variant_id=request.variant_id,
                        status="NOT_ATTEMPTED",
                        provider_attempts=0,
                        reason=budget.stopped,
                    )
            folder = target / request.run_id
            reserved = False

            def before_send(wire: httpx.Request) -> None:
                nonlocal reserved
                if (
                    wire.content != request.raw_body.encode()
                    or hashlib.sha256(wire.content).hexdigest()
                    != request.request_sha256
                ):
                    raise ValueError("REQUEST_DRIFT")
                # Rate waiting precedes the final current-authority check.
                # A reserved-but-denied slot is quarantined, not a Provider attempt.
                budget.reserve(request)
                reserved = True
                if (
                    not frozen.campaign.created_at
                    <= datetime.now(UTC)
                    < frozen.campaign.expires_at
                ):
                    raise ValueError("CAMPAIGN_EXPIRED")
                if scenario is None:
                    self.release_gate.check(frozen.campaign)
                try:
                    receipt = self.authority.check(case, request)
                except Exception as exc:
                    TraceRecorder(folder).record(
                        "authority_failure.json",
                        dict(
                            failure_kind="SOURCE_AUTHORITY_FAILURE",
                            rule=binding_error(exc),
                            pointer="/current_authority",
                        ),
                    )
                    raise
                TraceRecorder(folder).record("authority.json", receipt)
                # A sibling may have failed while current authority was checked.
                with budget.lock:
                    if budget.stopped:
                        raise ValueError("GLOBAL_SYSTEM_STOP")

            def dispatch(wire: httpx.Request) -> None:
                # Linearization point: admitted requests become in-flight here.
                # The original transport is entered only after this locked check.
                with budget.lock:
                    if budget.stopped:
                        raise ValueError("GLOBAL_SYSTEM_STOP")
                    if not reserved or wire.content != request.raw_body.encode():
                        raise ValueError("DISPATCH_WITHOUT_EXACT_RESERVATION")
                    TraceRecorder(folder).record(
                        "dispatch.json",
                        dict(
                            request_sha256=request.request_sha256,
                            run_id=request.run_id,
                            status="IN_FLIGHT",
                            admitted_at=datetime.now(UTC).isoformat(),
                        ),
                    )

            try:
                call = LLMProviderCall(
                    frozen.campaign.model,
                    request.system_prompt,
                    cast(JsonObject, request.input_payload),
                    cast(JsonObject, request.response_schema),
                )
                row = dict(
                    sample_id=request.run_id,
                    ordinal=1,
                    role=case.specialist_role,
                    request_sha256=request.request_sha256,
                )
                result = sender.sample(
                    row,
                    folder,
                    fixture_transport=scenario.transport(request) if scenario else None,
                    operation_id=frozen.spec.experiment_id,
                    episode_id=request.run_id,
                    call_loader=lambda _: (request.raw_body.encode(), call),
                    diagnostic=shape_diagnostic,
                    before_send=before_send,
                    before_transport=dispatch,
                    model_profile=profile(frozen.campaign.output_cap),
                )
                system_failure = (
                    result.get("stop_reason") if result.get("stop_remaining") else None
                )
                with budget.lock:
                    if system_failure:
                        budget.stop(str(system_failure))
                if reserved:
                    budget.finish(system_failure=system_failure)
                result.update(
                    run_id=request.run_id,
                    case_id=request.case_id,
                    variant_id=request.variant_id,
                    raw_contract_status="NOT_EVALUATED_BY_SENDER",
                    fixture=scenario is not None,
                )
                # Sender COMPLETED is transport/capture only; evaluator decides content.
                result["sender_status"] = result["status"]
                result["status"] = (
                    "SYSTEM_FAILURE" if system_failure else "RESPONSE_CAPTURED"
                )
            except Exception as exc:
                with budget.lock:
                    budget.stop("SYSTEM_SAFETY_OR_ARCHIVE_FAILURE")
                if reserved:
                    budget.finish(system_failure=budget.stopped)
                result = dict(
                    run_id=request.run_id,
                    case_id=request.case_id,
                    variant_id=request.variant_id,
                    status="SYSTEM_FAILURE",
                    error_type=type(exc).__name__,
                    provider_attempts=int((folder / "dispatch.json").exists()),
                    reason=budget.stopped,
                )
            try:
                TraceRecorder(folder).record("worker-result.json", result)
                if result["status"] == "RESPONSE_CAPTURED":
                    seal_completed(folder, frozen, request)
            except Exception:
                budget.stop("TERMINAL_ARCHIVE_FAILURE")
                raise
            return result

        with ThreadPoolExecutor(max_workers=frozen.campaign.budget.concurrency) as pool:
            rows = list(pool.map(work, frozen.requests))
        result = dict(
            version="eval-run-v1",
            freeze_identity=identity(frozen),
            campaign_identity=identity(frozen.campaign),
            experiment_id=frozen.spec.experiment_id,
            origin="ENGINEERING_MOCK_SDK" if scenario else "REAL_QWEN",
            planned=len(frozen.requests),
            rows=rows,
            elapsed_seconds=time.monotonic() - started,
            peak_inflight=budget.peak,
            stop_reason=budget.stopped,
            stop_persistence_error=(
                type(budget.stop_persistence_error).__name__
                if budget.stop_persistence_error
                else None
            ),
            campaign_reserved_attempts=budget.attempts,
            campaign_reserved_tokens=budget.tokens,
            real_provider_attempts=(
                0 if scenario else sum(r.get("provider_attempts", 0) for r in rows)
            ),
            mock_attempts=(
                sum(r.get("provider_attempts", 0) for r in rows) if scenario else 0
            ),
            scientific_admission=False,
            business_writes=0,
        )
        TraceRecorder(target).record("census.json", result)
        if budget.stop_persistence_error is not None:
            raise OSError(
                "CAMPAIGN_STOP_PERSISTENCE_FAILED"
            ) from budget.stop_persistence_error
        return dict(result, archive=str(target))
