"""Bounded two-probe composition over original Sender/Meter; no network bypass."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from src.memory.delivery import MemoryDelivery
from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import evidence_v2_ab_live as inherited
from tools import evidence_v2_runtime as base
from tools import g107_matrix as engine
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools import g113_r7_memory as memory
from tools import minimal2_inputs as inputs
from tools import minimal_semantic_carrier as carrier
from tools.g113_r1_binding import ROOT
from tools.g113_r2_memory import bind_current, recheck

MODULES = tuple(
    sorted(
        set(
            (
                *inherited.MODULES,
                "tools/minimal2_inputs.py",
                "tools/minimal2_live.py",
                "tools/minimal_semantic_carrier.py",
            )
        )
    )
)
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()
PREFIX = "MINIMAL2-LIVE-FREEZE-"


def read(path: Path) -> Any:
    """Read an immutable local record, never caller-generated permission."""
    return json.loads(path.read_bytes())


def runtime() -> dict[str, str]:
    """Pin all inherited runtime and new opt-in wiring."""
    return {
        **sender.runtime(ROOT),
        **{p: blob_hash((ROOT / p).read_bytes()) for p in MODULES},
    }


class CurrentAccessChecker(base.CurrentAccessChecker):
    """New Probe2 receiver; existing source reconstruction and F01/ACL/CAS checks."""

    def __init__(
        self, rt: dev.DevelopmentRuntime, output: Path, row: dict[str, Any]
    ) -> None:
        """Bind new complete claim, unchanged registry and current receiving scope."""
        self.runtime, self.output, self.row = rt, output, dict(row)
        operation, separator, slot = row["operational_task_id"].rpartition(":task:")
        if (
            not separator
            or not operation.startswith(PREFIX)
            or slot != inputs.ORDER[1]
            or row["sample_id"] != slot
            or row["invocation_candidate_id"] != operation + ":invocation:" + slot
            or rt.record["authorization"] != dev.MINIMAL2_AUTHORIZATION
        ):
            raise ValueError("MINIMAL2_CURRENT_RECEIVER")
        self.registry, self.packet, self.claim = inputs.source()
        self.catalog = inputs.catalog()
        if (
            row["semantic_task_identity"] != self.catalog.identity
            or row["claim_fingerprint"] != self.claim.fingerprint
        ):
            raise ValueError("MINIMAL2_TRUSTED_CLAIM_DRIFT")
        self.checked_at = datetime.now(UTC).isoformat()
        self.receipts: list[dict[str, Any]] = []
        self.authority_failure: str | None = None


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Freeze exact two requests; install only Probe2 financial read authority."""
    inputs.verify_design()
    inputs.source()
    output.mkdir(parents=True, exist_ok=False)
    created = datetime.now(UTC)
    operation = PREFIX + created.strftime("%Y%m%dT%H%M%S%fZ")
    record = dev.install(instance, authorization=dev.MINIMAL2_AUTHORIZATION)
    rt = dev.DevelopmentRuntime(
        instance, blob_hash((instance / "INSTANCE.json").read_bytes())
    )
    rt.receiver(
        "fundamental_analyst",
        datetime.fromisoformat(base.CUTOFF),
        "G113-R5-NOCHANGE",
        operation + ":nochange-audit",
        created,
    )
    before = memory.population_receipt(rt)
    durable(output / "NOCHANGE_CONTROL.json", canonical(memory.ordinary_control(rt)))
    technical = dict(
        version="MINIMAL2_NON_RESEARCH_TECHNICAL_AUTHORITY_V1",
        operation_id=operation,
        owner="user-authorized-minimal2-development",
        role="technical_schema_probe",
        scope="NON_FINANCIAL_SCHEMA_PROBE_NO_MEMORY_ACCESS",
        actions=["ONE_FROZEN_PROVIDER_ATTEMPT"],
        effective_at=created.isoformat(),
        expires_at=(created + timedelta(days=7)).isoformat(),
        invocation=operation + ":invocation:" + inputs.ORDER[0],
        episode=operation + ":technical-episode:" + inputs.ORDER[0],
        requires_dual_independent_release=True,
        scientific_admission=False,
    )
    # This is operator-owned runtime metadata, not a financial AgentRun or Memory grant.
    durable(output / "TECHNICAL_AUTHORITY.json", canonical(technical))
    slots = []
    for index, case in enumerate(inputs.cases()):
        name = case["design_slot_id"]
        folder = output / name
        folder.mkdir()
        audit, repeat = inputs.serialize(index), inputs.serialize(index)
        if audit["serialized_http_body"] != repeat["serialized_http_body"]:
            raise ValueError("MINIMAL2_NONDETERMINISTIC_SDK")
        row = dict(
            sample_id=name,
            slot=name,
            ordinal=index + 1,
            role="technical_schema_probe" if index == 0 else "fundamental_analyst",
            operational_task_id=operation + ":task:" + name,
            invocation_candidate_id=operation + ":invocation:" + name,
            execution_operation_id=operation + ":execution",
            request_sha256=audit["http_body_sha256"],
            schema_identity=digest(carrier.proposal_schema()),
            payload_identity=case["model_input_sha256"],
            instructions_sha256=case["instructions_sha256"],
            output_cap=inputs.profile(index).output_cap,
            created_at=created.isoformat(),
        )
        if index == 0:
            row["episode_candidate_id"] = technical["episode"]
            row["authority_kind"] = "TECHNICAL_NO_MEMORY"
        else:
            cat = inputs.catalog()
            current = rt.receiver(
                row["role"],
                datetime.fromisoformat(base.CUTOFF),
                row["operational_task_id"],
                row["invocation_candidate_id"],
                created,
            )
            delivery, binding = bind_current(
                current,
                cat,
                MemoryDelivery.model_validate_json(dev.TEMPLATE.read_bytes()),
            )
            access = digest(current.access)
            receipt = recheck(current, delivery, cat, access)
            row.update(
                episode_candidate_id=current.ep.episode_id,
                access_identity=access,
                semantic_task_identity=cat.identity,
                claim_fingerprint=inputs.source()[2].fingerprint,
                registry_identity=inputs.source()[0].identity,
                authority_kind="CURRENT_MSFT_READ_HISTORY",
                dependency_snapshot=binding["dependency_snapshot"],
            )
            for f, value in {
                "W6_DELIVERY.json": delivery.model_dump(mode="json"),
                "RECEIVING_EPISODE_CANDIDATE.json": current.ep.model_dump(mode="json"),
                "CURRENT_AUTHORITY.json": receipt,
                "DEPENDENCY_BINDING.json": binding,
            }.items():
                durable(folder / f, canonical(value))
        for f, value in {
            "MODEL_INPUT.json": case["model_input"],
            "RESPONSE_SCHEMA.json": carrier.proposal_schema(),
        }.items():
            durable(folder / f, canonical(value))
        durable(folder / "prompt.txt", case["model_instructions"].encode())
        durable(folder / "sdk-request.raw", audit["serialized_http_body"].encode())
        row["file_identities"] = {
            p.name: blob_hash(p.read_bytes()) for p in folder.iterdir()
        }
        slots.append(row)
    if memory.population_receipt(rt) != before:
        raise ValueError("MINIMAL2_BUSINESS_POPULATION_CHANGED")
    authority = dict(
        root=str(instance.resolve()),
        instance_id=record["instance_id"],
        installation_sha256=rt.installation_sha256,
        grant_identities={
            k: blob_hash(raw.encode()) for k, raw in rt.journal.entries(dev.GRANTS)
        },
    )
    freeze = dict(
        interface=inputs.VERSION,
        release_contract=inputs.RELEASE,
        operation_id=operation,
        created_at=created.isoformat(),
        slots=slots,
        planned_samples=2,
        population_identity=digest(slots),
        request_sha256s=[r["request_sha256"] for r in slots],
        schema_identities=[r["schema_identity"] for r in slots],
        W5_design_source=inputs.DESIGN_SOURCE,
        W5_design_manifest=inputs.DESIGN_MANIFEST,
        technical_authority=dict(
            path="TECHNICAL_AUTHORITY.json", sha256=blob_hash(canonical(technical))
        ),
        development_instance=authority,
        authority_counts=before,
        sender_runtime=runtime(),
        installed_sdk=inputs.sdk_identity(),
        model="qwen3.8-flash",
        region="cn-beijing",
        configuration=inputs.read("PROVIDER_PARAMETER_REQUIREMENTS.json")[
            "required_configuration"
        ],
        research_as_of=base.CUTOFF,
        exact_context_fit="UNKNOWN",
        bounded_unknown_context_policy="STOP_ON_PROVIDER_CAPACITY_REJECTION_NO_RETRY",
        budget=dict(
            total_attempts=2,
            per_slot=1,
            retry=0,
            fallback="NONE",
            concurrency=1,
            output_caps=[512, 1024],
        ),
        stop_rules=inputs.read("PROBE_1_TO_PROBE_2_STOP_RULE.json"),
        source_commit_ref="EVIDENCE_MANIFEST.json#/source_commit",
        scientific_admission=False,
        live_execution_ready=False,
        status="FROZEN_FOR_INDEPENDENT_TECHNICAL_REVIEW_AND_EXACT_EXECUTION_BINDING",
    )
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(freeze))
    verify(output, freeze)
    checker = CurrentAccessChecker(memory.open_runtime(authority), output, slots[1])
    checker.check(checker.registry.identity, base.SCOPE, checker.checked_at)
    durable(output / "CURRENT_PRESEND_OFFLINE_CHECK.json", canonical(checker.receipts))
    return freeze


def verify(output: Path, freeze: dict[str, Any]) -> None:
    """Reject all runtime/request/design/permission drift before releasing a send."""
    inputs.verify_design()
    if (
        freeze["interface"] != inputs.VERSION
        or freeze["release_contract"] != inputs.RELEASE
        or freeze["sender_runtime"] != runtime()
        or freeze["installed_sdk"] != inputs.sdk_identity()
        or freeze["configuration"]
        != inputs.read("PROVIDER_PARAMETER_REQUIREMENTS.json")["required_configuration"]
        or freeze["planned_samples"] != 2
        or freeze["population_identity"] != digest(freeze["slots"])
        or freeze["W5_design_manifest"] != inputs.DESIGN_MANIFEST
        or not freeze["operation_id"].startswith(PREFIX)
        or tuple(r["sample_id"] for r in freeze["slots"]) != inputs.ORDER
        or freeze["stop_rules"] != inputs.read("PROBE_1_TO_PROBE_2_STOP_RULE.json")
        or freeze["budget"]
        != dict(
            total_attempts=2,
            per_slot=1,
            retry=0,
            fallback="NONE",
            concurrency=1,
            output_caps=[512, 1024],
        )
    ):
        raise ValueError("MINIMAL2_FREEZE_DRIFT")
    for i, row in enumerate(freeze["slots"]):
        folder = output / row["slot"]
        for path, sha in row["file_identities"].items():
            p = (folder / path).resolve()
            if (
                not p.is_relative_to(folder.resolve())
                or blob_hash(p.read_bytes()) != sha
            ):
                raise ValueError("MINIMAL2_FROZEN_MEMBER")
        if (
            (folder / "sdk-request.raw").read_bytes()
            != inputs.serialize(i)["serialized_http_body"].encode()
            or blob_hash((folder / "sdk-request.raw").read_bytes())
            != row["request_sha256"]
            or row["schema_identity"] != digest(carrier.proposal_schema())
            or row["invocation_candidate_id"]
            != freeze["operation_id"] + ":invocation:" + row["sample_id"]
        ):
            raise ValueError("MINIMAL2_REQUEST_IDENTITY")
    if freeze["request_sha256s"] != [
        r["request_sha256"] for r in freeze["slots"]
    ] or freeze["schema_identities"] != [r["schema_identity"] for r in freeze["slots"]]:
        raise ValueError("MINIMAL2_REQUEST_MANIFEST")
    technical_check(output, freeze)


def technical_check(output: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    """Code-owned non-research receiver; no financial scope or fake AgentRun."""
    raw = (output / "TECHNICAL_AUTHORITY.json").read_bytes()
    b = json.loads(raw)
    now = datetime.now(UTC)
    if (
        blob_hash(raw) != freeze["technical_authority"]["sha256"]
        or b["operation_id"] != freeze["operation_id"]
        or b["role"] != "technical_schema_probe"
        or b["scope"] != "NON_FINANCIAL_SCHEMA_PROBE_NO_MEMORY_ACCESS"
        or b["actions"] != ["ONE_FROZEN_PROVIDER_ATTEMPT"]
        or b["invocation"] != freeze["slots"][0]["invocation_candidate_id"]
        or b["episode"] != freeze["slots"][0]["episode_candidate_id"]
        or not datetime.fromisoformat(b["effective_at"])
        <= now
        < datetime.fromisoformat(b["expires_at"])
        or (output / "TECHNICAL_AUTHORITY_REVOKED.json").exists()
    ):
        raise ValueError("MINIMAL2_TECHNICAL_AUTHORITY_INVALID")
    return dict(
        checked_at=now.isoformat(),
        authority_sha256=blob_hash(raw),
        memory_read=False,
        technical_authority="VALID_SUBJECT_TO_DUAL_RELEASE",
        scientific_admission=False,
    )


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Strict local six-field result; never fix syntax or infer economic truth."""
    del call
    try:
        obj = engine.strict_object(text)
        proposal = carrier.MinimalSemanticProposal.model_validate(obj)
        handles = proposal.evidence_handles + proposal.counterevidence_handles
        offered = set() if row["sample_id"] == inputs.ORDER[0] else {"H0005", "H0006"}
        if set(handles) - offered:
            raise ValueError("MINIMAL2_UNOFFERED_HANDLE")
        return dict(schema_valid=True, proposal=obj, scientific_admission=False)
    except Exception as exc:
        return dict(
            schema_valid=False,
            error_type=type(exc).__name__,
            candidate_prediction=None,
            prediction_state="NO_PREDICTION",
            scientific_admission=False,
        )


def first_success(result: dict[str, Any], raw: dict[str, Any]) -> dict[str, bool]:
    """Eleven independently explicit facts; UNKNOWN/missing never releases Probe2."""
    diagnostic = result.get("diagnostic", {})
    proposal = diagnostic.get("proposal", {})
    no_refusal = not any(
        p.get("type") == "refusal"
        for o in raw.get("output", [])
        for p in o.get("content", [])
    )
    facts = [
        isinstance(result.get("request_sha256"), str)
        and result.get("audit_request_sha256") == result["request_sha256"],
        result.get("response_received") is True,
        result.get("response_completed") is True,
        result.get("actual_model") == "qwen3.8-flash",
        result.get("usage_known") is True,
        diagnostic.get("schema_valid") is True,
        diagnostic.get("schema_valid") is True,
        diagnostic.get("schema_valid") is True,
        proposal.get("evidence_handles") == []
        and proposal.get("counterevidence_handles") == [],
        no_refusal and not result.get("stop_remaining") and raw.get("error") is None,
        diagnostic.get("scientific_admission") is False,
    ]
    return dict(
        zip(
            inputs.read("PROBE_1_TO_PROBE_2_STOP_RULE.json")[
                "Probe1_success_requires_all"
            ],
            facts,
            strict=True,
        )
    )


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Original serial sample engine, one canonical operation and dependent Probe2."""
    fixture = fixture_transport is not None
    if fixture and type(fixture_transport) is not httpx.MockTransport:
        raise ValueError("MINIMAL2_FIXTURE_TRANSPORT")
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("MINIMAL2_FIXTURE_CANNOT_RELEASE")
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    pins = fixture_pins if fixture else APPROVED_RELEASES
    proof = sender.reviews(
        pins, freeze, source_commit, fixture=fixture, release_contract=inputs.RELEASE
    )
    if (
        not fixture
        and len({p.git_repository.resolve() for p in pins if p.git_repository}) != 2
    ):
        raise ValueError("MINIMAL2_INDEPENDENT_ISSUERS")
    verify(output, freeze)
    if not fixture:
        for p, sha in runtime().items():
            if (
                blob_hash(
                    subprocess.check_output(
                        ["git", "-C", str(ROOT), "show", source_commit + ":" + p]
                    )
                )
                != sha
            ):
                raise ValueError("MINIMAL2_SOURCE_DRIFT")
    destination = (
        fixture_result
        if fixture
        else ROOT / "data/runtime/minimal2" / freeze["operation_id"]
    )
    if destination is None:
        raise ValueError("MINIMAL2_FIXTURE_ARCHIVE_REQUIRED")
    if destination.exists():
        raise FileExistsError("MINIMAL2_OPERATION_ALREADY_RESERVED_NO_RESEND")
    rt = memory.open_runtime(freeze["development_instance"])
    # Both sources/current authority must be eligible before consuming the first slot.
    pre = CurrentAccessChecker(rt, output, freeze["slots"][1])
    pre.check(pre.registry.identity, base.SCOPE, pre.checked_at)
    destination.mkdir(parents=True, exist_ok=False)
    durable(
        destination / "PREDISPATCH.json",
        canonical(
            dict(
                source_commit=source_commit,
                reviews=proof,
                freeze_sha256=blob_hash(canonical(freeze)),
                engineering_fixture=fixture,
            )
        ),
    )
    outcomes = []
    stop = None
    for index, row in enumerate(freeze["slots"]):
        if stop:
            outcomes.append(
                dict(
                    sample_id=row["sample_id"],
                    status="NOT_ATTEMPTED",
                    reason=stop,
                    provider_attempts=0,
                )
            )
            continue
        target = destination / f"{index+1:02}"

        def presend(request: httpx.Request) -> None:
            del request
            sender.reviews(
                pins,
                freeze,
                source_commit,
                fixture=fixture,
                release_contract=inputs.RELEASE,
            )
            verify(output, freeze)
            if index == 0:
                receipt = technical_check(output, freeze)
            else:
                current = CurrentAccessChecker(rt, output, row)
                current.check(current.registry.identity, base.SCOPE, current.checked_at)
                receipt = dict(checks=current.receipts)
            durable(target / "IMMEDIATE_PRESEND_AUTHORITY.json", canonical(receipt))

        try:
            result = engine.sample(
                row,
                target,
                fixture_transport=fixture_transport,
                operation_id=freeze["operation_id"] + ":execution",
                episode_id=row["episode_candidate_id"],
                call_loader=lambda _: (
                    (output / row["slot"] / "sdk-request.raw").read_bytes(),
                    inputs.call(index),
                ),
                diagnostic=diagnose,
                before_send=presend,
                model_profile=inputs.profile(index),
            )
            if result["stop_remaining"]:
                stop = result["stop_reason"]
            else:
                binding = base.CaptureBinding(
                    row["request_sha256"],
                    result["OperationID"],
                    result["AttemptID"],
                    row.get("registry_identity", "NOT_APPLICABLE"),
                    row.get("claim_fingerprint", "NOT_APPLICABLE"),
                    fixture,
                )
                raw = base.verify_capture_identity(target, row, binding)
                response = read(target / "response.raw")
                if index == 0:
                    result["success_facts"] = first_success(result, response)
                    if not all(result["success_facts"].values()):
                        stop = "PROBE1_NOT_SUCCESSFUL_PROBE2_DEPENDENCY_STOP"
                elif (
                    result["diagnostic"]["schema_valid"]
                    and result["response_completed"]
                ):
                    checker = CurrentAccessChecker(rt, output, row)
                    task = carrier.TrustedTask(
                        checker.claim,
                        base.CUTOFF,
                        base.SCOPE,
                        checker.registry.identity,
                    )
                    result["assessment"] = carrier.assemble(
                        raw,
                        task,
                        checker.registry,
                        checker,
                        checked_at=checker.checked_at,
                    )
                    result["full_claim_semantic_consistency"] = (
                        "PENDING_INDEPENDENT_W5_NO_AUTOMATIC_ENTAILMENT"
                    )
                else:
                    result["assessment"] = dict(
                        prediction_state="NO_PREDICTION",
                        candidate_prediction=None,
                        scientific_admission=False,
                    )
        except Exception as exc:
            stop = "MINIMAL2_BINDING_OR_ARCHIVE_SYSTEM_FAILURE"
            result = dict(
                sample_id=row["sample_id"],
                status="SYSTEM_FAILURE",
                error_type=type(exc).__name__,
                error_code=sender.binding_error(exc),
                provider_attempts=int((target / "invocation.json").exists()),
                response_received=(target / "response.raw").exists(),
            )
        outcomes.append(result)
        durable(destination / f"PROGRESS-{index+1:02}.json", canonical(outcomes))
    census = dict(
        planned_samples=2,
        samples=outcomes,
        stop_reason=stop,
        engineering_fixture=fixture,
        real_attempts=(
            0 if fixture else sum(x.get("provider_attempts", 0) for x in outcomes)
        ),
        mock_attempts=(
            sum(x.get("provider_attempts", 0) for x in outcomes) if fixture else 0
        ),
        scientific_admission=False,
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
    )
    durable(destination / "COHORT_CENSUS.json", canonical(census))
    return census
