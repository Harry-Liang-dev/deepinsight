"""Fail-closed restart reconciliation under the exclusive campaign process lock.

A terminal seal is an integrity record, not authority. Its complete original
archive and frozen identity chain are independently checked on every restart.
No recovery path retries, refunds, repairs or authorizes a request.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from research_eval.compiler import RequestCompiler, profile
from research_eval.models import (
    FrozenExperiment,
    FrozenRequest,
    TrustedExperimentCampaign,
    identity,
)
from research_eval.storage import TraceRecorder
from src.schemas.research_v2_shared import canonical
from src.services.development_model_profile import profile_record, reference_cost
from src.services.pilot_capacity_budget import _usage_details

REQUIRED = frozenset(
    {
        "identity.json",
        "authority.json",
        "dispatch.json",
        "request.raw",
        "invocation.json",
        "response.raw",
        "http.json",
        "assistant.txt",
        "usage.json",
        "meter/0000.json",
        "meter/0001.json",
        "outcome.json",
        "worker-result.json",
    }
)


def digest(raw: bytes) -> str:
    """Hash exact bytes."""
    return hashlib.sha256(raw).hexdigest()


def read(path: Path) -> Any:
    """Read archived JSON without repairing it."""
    return json.loads(path.read_bytes())


def require(condition: bool) -> None:
    """Reject incomplete or conflicting terminal evidence."""
    if not condition:
        raise ValueError("UNTRUSTED_ATTEMPT_TERMINAL")


def evidence(
    folder: Path, frozen: FrozenExperiment, request: FrozenRequest
) -> dict[str, str]:
    """Cross-check original HTTP, usage, accounting and identities, not PASS flags."""
    paths = {
        p.relative_to(folder).as_posix(): p
        for p in folder.rglob("*")
        if p.is_file() and p.name != "terminal.json"
    }
    require(REQUIRED <= paths.keys())
    require(
        all(
            not p.is_symlink() and p.resolve().is_relative_to(folder.resolve())
            for p in paths.values()
        )
    )
    hashes = {name: digest(p.read_bytes()) for name, p in paths.items()}
    require((folder / "request.raw").read_bytes() == request.raw_body.encode())
    require(hashes["request.raw"] == request.request_sha256)
    ident = read(folder / "identity.json")
    invocation = read(folder / "invocation.json")
    dispatch = read(folder / "dispatch.json")
    http = read(folder / "http.json")
    response = read(folder / "response.raw")
    usage = read(folder / "usage.json")
    outcome = read(folder / "outcome.json")
    worker = read(folder / "worker-result.json")
    reserved = read(folder / "meter/0000.json")
    settled = read(folder / "meter/0001.json")
    authority = read(folder / "authority.json")
    require(isinstance(authority, dict) and bool(authority))
    require(
        ident["OperationID"] == frozen.spec.experiment_id
        and ident["sample_id"] == request.run_id
        and ident["EvaluationEpisodeID"] == request.run_id
        and ident["ResultRoot"] == str(folder)
        and ident["request_sha256"] == request.request_sha256
        and ident["engineering_fixture"] == (frozen.spec.mode == "OFFLINE")
    )
    require(
        invocation["request_sha256"] == request.request_sha256
        and invocation["status"] == "ATTEMPTED_SEND_UNCONFIRMED"
        and bool(invocation["ActualInvocationAt"])
    )
    require(
        dispatch["request_sha256"] == request.request_sha256
        and dispatch["run_id"] == request.run_id
        and dispatch["status"] == "IN_FLIGHT"
    )
    require(
        http["http_status"] == 200
        and http["response_sha256"] == hashes["response.raw"]
        and response["status"] in {"completed", "incomplete"}
        and response["model"] == frozen.campaign.model
        and isinstance(response["id"], str)
        and bool(response["id"])
    )
    assistant = "".join(
        part["text"]
        for item in response["output"]
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    require(assistant.encode() == (folder / "assistant.txt").read_bytes())
    require(
        ident["model_profile"] == profile_record(profile(frozen.campaign.output_cap))
    )
    raw_usage = response["usage"]
    _usage_details(response, raw_usage)
    inputs, outputs = raw_usage["input_tokens"], raw_usage["output_tokens"]
    cached = raw_usage.get("input_tokens_details", {}).get("cached_tokens", 0)
    require(
        all(type(n) is int and n >= 0 for n in (inputs, outputs, cached))
        and cached <= inputs
        and raw_usage["total_tokens"] == inputs + outputs
    )
    require(
        usage["validated_usage"] == raw_usage
        and usage["input_tokens"] == inputs
        and usage["output_tokens"] == outputs
        and usage["cached_tokens"] == cached
        and usage["actual_resolved_model"] == response["model"]
        and usage["response_id"] == response["id"]
    )
    require(
        reserved["event"] == "RESERVED"
        and settled["event"] == "SETTLED"
        and reserved["attempt"] == settled["attempt"] == 1
    )
    for event in (reserved, settled):
        require(
            event["request_identity"] == request.request_sha256
            and event["scope_identity"] == digest(canonical(ident))
            and event["envelope_identity"] == usage["price_version"]
        )
    require(
        settled["input_tokens"] == inputs
        and settled["output_tokens"] == outputs
        and settled["cost"] == usage["estimated_cost"]
        and outcome["fixed_rate_cost_reference"] == usage["estimated_cost"]
    )
    require(
        Decimal(usage["estimated_cost"])
        == reference_cost(profile(frozen.campaign.output_cap), inputs, outputs, cached)
    )
    # Cost is reference-only; validate the existing meter's applicable profile.
    require(
        inputs <= profile(frozen.campaign.output_cap).input_reservation
        and outputs <= frozen.campaign.output_cap
    )
    require(all(outcome[k] == v for k, v in ident.items()))
    require(
        outcome["provider_attempts"] == 1
        and outcome["usage_known"] is True
        and outcome["response_received"] is True
        and outcome["stop_remaining"] is False
        and outcome["stop_reason"] is None
        and outcome["actual_model"] == response["model"]
        and outcome["response_id"] == response["id"]
        and outcome["audit_request_sha256"] == request.request_sha256
        and outcome["input_tokens"] == inputs
        and outcome["output_tokens"] == outputs
        and outcome["status"] in {"COMPLETED", "CONTENT_OR_SCHEMA_FAILURE"}
    )
    require(
        worker["status"] == "RESPONSE_CAPTURED"
        and worker["sender_status"] == outcome["status"]
        and worker["run_id"] == request.run_id
        and worker["case_id"] == request.case_id
        and worker["variant_id"] == request.variant_id
        and all(worker[k] == v for k, v in outcome.items() if k != "status")
    )
    return hashes


def seal_completed(
    folder: Path, frozen: FrozenExperiment, request: FrozenRequest
) -> None:
    """Seal only after complete capture and terminal cross-checks succeed."""
    files = evidence(folder, frozen, request)
    TraceRecorder(folder).record(
        "terminal.json",
        dict(
            version="CAMPAIGN_TERMINAL_V1",
            freeze_identity=identity(frozen),
            campaign_identity=identity(frozen.campaign),
            run_id=request.run_id,
            request_sha256=request.request_sha256,
            files=files,
            status="TRANSPORT_CAPTURE_ACCOUNTING_COMPLETE_NOT_SCIENTIFIC_ADMISSION",
        ),
    )


def reconcile_previous(
    root: Path, campaign: TrustedExperimentCampaign, reservations: list[Path]
) -> None:
    """Quarantine unresolved prior reservations before any new batch or worker."""
    if (root / "QUARANTINE.json").exists():
        raise ValueError(
            "CAMPAIGN_STOPPED_NO_RESEND:UNRESOLVED_PREVIOUS_SEND:RESERVATION_ALREADY_CONSUMED"
        )
    freezes: list[FrozenExperiment] = []
    try:
        for path in (root / "experiments").glob("*/freeze.json"):
            f = FrozenExperiment.model_validate_json(path.read_bytes())
            require(identity(f.campaign) == identity(campaign))
            RequestCompiler().verify(f)
            freezes.append(f)
        for path in reservations:
            reservation = read(path)
            require(
                reservation["status"] == "RESERVED_CONSUMED_OR_QUARANTINED"
                and bool(reservation["reserved_at"])
            )
            matches = [
                (f, q)
                for f in freezes
                for q in f.requests
                if q.run_id == reservation["run_id"]
                and q.request_sha256 == path.stem == reservation["request_sha256"]
            ]
            require(len(matches) == 1)
            f, q = matches[0]
            folder = root / "experiments" / f.spec.experiment_id / q.run_id
            terminal = read(folder / "terminal.json")
            require(
                terminal["version"] == "CAMPAIGN_TERMINAL_V1"
                and terminal["freeze_identity"] == identity(f)
                and terminal["campaign_identity"] == identity(campaign)
                and terminal["run_id"] == q.run_id
                and terminal["request_sha256"] == q.request_sha256
            )
            require(terminal["files"] == evidence(folder, f, q))
    except Exception as exc:
        # If quarantine persistence fails, propagate it. The consumed reservation
        # remains; the next process repeats reconciliation and cannot dispatch.
        TraceRecorder(root).record(
            "QUARANTINE.json",
            dict(
                status="UNKNOWN",
                reason="UNRESOLVED_PREVIOUS_SEND",
                error_type=type(exc).__name__,
                consumed_reservations=len(reservations),
                new_dispatches=0,
                refunds=0,
                retries=0,
            ),
        )
        raise ValueError(
            "CAMPAIGN_STOPPED_NO_RESEND:UNRESOLVED_PREVIOUS_SEND:RESERVATION_ALREADY_CONSUMED"
        ) from exc
