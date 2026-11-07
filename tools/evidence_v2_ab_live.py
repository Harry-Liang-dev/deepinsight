"""New paired release composition over the original serial SDK/Memory engine."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.memory.delivery import MemoryDelivery
from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    QWEN38_DEVELOPMENT_PROFILE,
    profile_record,
)
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import evidence_v2_ab_inputs as inputs
from tools import evidence_v2_ab_results as results
from tools import evidence_v2_runtime as base
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools import g113_r7_live as inherited
from tools import g113_r7_memory as memory
from tools import g113_r7_prepare as sdk
from tools import h2_live, h2_results
from tools.g113_r1_binding import ROOT
from tools.g113_r2_memory import bind_current, recheck

MODULES = tuple(
    sorted(
        set(
            (
                *h2_live.MODULES,
                "tools/evidence_v2_ab_inputs.py",
                "tools/evidence_v2_ab_results.py",
                "tools/evidence_v2_ab_live.py",
                "tools/evidence_v2_runtime.py",
                *[
                    f"evidence_v2/{p}.py"
                    for p in ("__init__", "models", "registry", "mechanism", "prepare")
                ],
            )
        )
    )
)
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()


def runtime() -> dict[str, str]:
    """Hash the entire inherited executable path and new matched adapter."""
    return {
        **sender.runtime(ROOT),
        **{p: blob_hash((ROOT / p).read_bytes()) for p in MODULES},
    }


class CurrentAccessChecker(base.CurrentAccessChecker):
    """New exact receivers; reuse original live F01/ACL/CAS registry rebuilding."""

    def __init__(
        self, rt: dev.DevelopmentRuntime, output: Path, row: dict[str, Any]
    ) -> None:
        """Bind only this published design, installed instance and original parent."""
        self.runtime, self.output, self.row = rt, output, dict(row)
        arm, case = row["arm"], row["case_id"]
        op = inputs.DESIGN + "-" + arm
        if (
            arm not in {"A", "B"}
            or case not in inputs.CASES
            or row["sample_id"] != arm + ":" + case
            or row["operational_task_id"] != op + ":task:" + case
            or row["invocation_candidate_id"] != op + ":invocation:" + case
            or row["execution_operation_id"] != op + ":execution"
            or rt.record["authorization"] != dev.AB_AUTHORIZATION
        ):
            raise ValueError("AB_CURRENT_RECEIVER_IDENTITY")
        self.registry, self.packet, _ = base.fixed(inputs.SOURCE_CASE)
        self.claim = inputs.fixed(case, arm)
        self.catalog = inputs.catalog_for(ROOT, row)
        if (
            self.registry.identity != inputs.REGISTRY
            or row["registry_identity"] != self.registry.identity
            or row["claim_fingerprint"] != self.claim.fingerprint
            or row["semantic_task_identity"] != self.catalog.identity
        ):
            raise ValueError("AB_CURRENT_TASK_REGISTRY_DRIFT")
        self.checked_at = datetime.now(UTC).isoformat()
        self.receipts: list[dict[str, Any]] = []
        self.authority_failure: str | None = None


def verify(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Verify all input/runtime bytes; no old release identity can dispatch here."""
    del root
    inputs.verify_intake()
    if (
        freeze["interface"] != inputs.VERSION
        or freeze["release_contract"] != inputs.RELEASE
        or freeze["sender_runtime"] != runtime()
        or freeze["configuration"] != inherited.configuration()
        or freeze["model_profile"] != profile_record(QWEN38_DEVELOPMENT_PROFILE)
        or freeze["model"] != "qwen3.8-flash"
        or freeze["operation_id"] != inputs.DESIGN + "-COORDINATOR"
        or freeze["arm_operations"] != {a: inputs.DESIGN + "-" + a for a in ("A", "B")}
        or freeze["planned_samples"] != 24
        or freeze["research_as_of"] != base.CUTOFF
        or freeze["population_identity"] != digest(freeze["slots"])
    ):
        raise ValueError("AB_RUNTIME_FREEZE_DRIFT")
    for original, row in zip(inputs.ledger(), freeze["slots"], strict=True):
        for key in (
            "sample_id",
            "case_id",
            "arm",
            "arm_ordinal",
            "global_order",
            "operation_id",
        ):
            if row[key] != original[key]:
                raise ValueError("AB_ORDER_IDENTITY_DRIFT")
        folder = output / row["slot"]
        for name, sha in row["file_identities"].items():
            p = (folder / name).resolve()
            if (
                not p.is_relative_to(folder.resolve())
                or blob_hash(p.read_bytes()) != sha
            ):
                raise ValueError("AB_FROZEN_MEMBER_DRIFT")
        call = inputs.call(row["case_id"], row["arm"])
        if (
            json.loads((folder / "MODEL_INPUT.json").read_bytes()) != call.input_payload
            or json.loads((folder / "RESPONSE_SCHEMA.json").read_bytes())
            != call.response_schema
            or (folder / "prompt.txt").read_text() != call.system_prompt
            or blob_hash((folder / "sdk-request.raw").read_bytes())
            != row["request_sha256"]
            or digest(call.response_schema) != row["schema_identity"]
            or inputs.catalog_for(ROOT, row).identity != row["semantic_task_identity"]
        ):
            raise ValueError("AB_REQUEST_TASK_DRIFT")
    for key, field in (
        ("request_sha256s", "request_sha256"),
        ("schema_identities", "schema_identity"),
    ):
        if freeze[key] != [s[field] for s in freeze["slots"]]:
            raise ValueError("AB_REQUEST_MANIFEST_DRIFT")


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Freeze real SDK serialization and new current receivers without sending."""
    inputs.verify_intake()
    base.verify_intake()
    inherited.configuration()
    if output.exists() or instance.exists():
        raise ValueError("AB_EXISTING_FREEZE_OR_INSTANCE")
    registry, packet, _ = base.fixed(inputs.SOURCE_CASE)
    common_catalog = [
        dict(
            handle=e.handle,
            fragment_id=e.fragment_id,
            source_id=e.source_id,
            authority_kind=e.authority_kind,
            text=e.text,
        )
        for e in registry.entries.values()
    ]
    if registry.identity != inputs.REGISTRY or common_catalog != inputs.read(
        "COMMON_MODEL_EVIDENCE_CATALOG.json"
    ):
        raise ValueError("AB_PUBLISHED_CATALOG_NOT_TRUSTED_SOURCE_PROJECTION")
    output.mkdir(parents=True, exist_ok=False)
    dev.install(instance, authorization=dev.AB_AUTHORIZATION)
    rt = dev.DevelopmentRuntime(
        instance, blob_hash((instance / "INSTANCE.json").read_bytes())
    )
    before = memory.population_receipt(rt)
    created = datetime.now(UTC)
    rt.receiver(
        "fundamental_analyst",
        datetime.fromisoformat(base.CUTOFF),
        "G113-R5-NOCHANGE",
        inputs.DESIGN + ":nochange",
        created,
    )
    control = memory.ordinary_control(rt)
    durable(output / "NOCHANGE_CONTROL.json", canonical(control))
    slots = []
    for original in inputs.ledger():
        row = dict(
            original,
            slot=f"{original['global_order']:02}-{original['arm']}-{original['case_id']}",
            role="fundamental_analyst",
            context="IDENTICAL_CLOSED_DELTA_SOURCE_UNIVERSE",
            checker="EVIDENCE_V2_AB_MATCHED_SEMANTIC_ENVELOPE_V1",
        )
        case, arm, op = row["case_id"], row["arm"], row["operation_id"]
        folder = output / row["slot"]
        folder.mkdir()
        catalog = inputs.catalog_for(ROOT, row)
        task, invocation = op + ":task:" + case, op + ":invocation:" + case
        current = rt.receiver(
            row["role"], datetime.fromisoformat(base.CUTOFF), task, invocation, created
        )
        delivery, binding = bind_current(
            current,
            catalog,
            MemoryDelivery.model_validate_json(dev.TEMPLATE.read_bytes()),
        )
        access = digest(current.access)
        check = recheck(current, delivery, catalog, access)
        call = inputs.call(case, arm)
        first, second = sdk.sdk_preview(call), sdk.sdk_preview(call)
        if first["raw"] != second["raw"]:
            raise ValueError("AB_NONDETERMINISTIC_SDK_BYTES")
        row.update(
            operational_task_id=task,
            invocation_candidate_id=invocation,
            episode_candidate_id=current.ep.episode_id,
            access_identity=access,
            execution_operation_id=op + ":execution",
            semantic_task_identity=catalog.identity,
            registry_identity=registry.identity,
            claim_fingerprint=inputs.fixed(case, arm).fingerprint,
            schema_identity=digest(call.response_schema),
            response_schema_identity=digest(call.response_schema),
            payload_identity=digest(call.input_payload),
            request_sha256=blob_hash(first["raw"].encode()),
            dependency_snapshot=binding["dependency_snapshot"],
            current_created_at=created.isoformat(),
            actual_invocation_at=None,
        )
        for name, value in {
            "W6_DELIVERY.json": delivery.model_dump(mode="json"),
            "RECEIVING_EPISODE_CANDIDATE.json": current.ep.model_dump(mode="json"),
            "CURRENT_AUTHORITY.json": check,
            "DEPENDENCY_BINDING.json": binding,
            "MODEL_INPUT.json": call.input_payload,
            "RESPONSE_SCHEMA.json": call.response_schema,
            "SDK_SERIALIZATION_RECEIPT.json": {
                k: v for k, v in first.items() if k != "raw"
            },
        }.items():
            durable(folder / name, canonical(value))
        durable(folder / "prompt.txt", call.system_prompt.encode())
        durable(folder / "sdk-request.raw", first["raw"].encode())
        row["file_identities"] = {
            p.name: blob_hash(p.read_bytes()) for p in folder.iterdir() if p.is_file()
        }
        slots.append(row)
        durable(output / f"PREPARATION-{row['global_order']:02}.json", canonical(row))
        print("FROZEN", row["sample_id"], row["request_sha256"], flush=True)
    if memory.population_receipt(rt) != before:
        raise ValueError("AB_BUSINESS_POPULATION_CHANGED")
    authority = dict(
        root=str(instance.resolve()),
        installation_sha256=rt.installation_sha256,
        instance_id=rt.record["instance_id"],
        grant_identities={
            k: blob_hash(raw.encode()) for k, raw in rt.journal.entries(dev.GRANTS)
        },
    )
    freeze = dict(
        interface=inputs.VERSION,
        release_contract=inputs.RELEASE,
        status="FROZEN_FOR_INDEPENDENT_TECHNICAL_REVIEW_AND_EXECUTION_BINDING",
        operation_id=inputs.DESIGN + "-COORDINATOR",
        arm_operations={a: inputs.DESIGN + "-" + a for a in ("A", "B")},
        W5_design_source=inputs.W5_SOURCE,
        W5_design_manifest=inputs.W5_MANIFEST,
        design_population_identity=inputs.read("FROZEN_NEW_CLAIM_POPULATION.json")[
            "population_sha256"
        ],
        created_at=created.isoformat(),
        research_as_of=base.CUTOFF,
        slots=slots,
        planned_samples=24,
        population_identity=digest(slots),
        request_sha256s=[r["request_sha256"] for r in slots],
        schema_identities=[r["schema_identity"] for r in slots],
        sender_runtime=runtime(),
        development_instance=authority,
        model="qwen3.8-flash",
        model_profile=profile_record(QWEN38_DEVELOPMENT_PROFILE),
        configuration=inherited.configuration(),
        exact_context_fit="UNKNOWN",
        bounded_unknown_context_policy="STOP_ON_PROVIDER_CAPACITY_REJECTION_NO_RETRY",
        actual_provider_retention="UNVERIFIED",
        actual_bill="UNKNOWN",
        budget=dict(
            total_attempts=24, per_slot=1, retry=0, fallback="NONE", concurrency=1
        ),
        stop_rules=dict(
            system="STOP_BOTH_ARMS_NO_RETRY", content="PRESERVE_CONTINUE_FROZEN_ORDER"
        ),
        authority_counts=before,
        new_model_calls=0,
        scientific_admission=False,
    )
    verify(ROOT, output, freeze)
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(freeze))
    durable(output / "AB_EXACT_SDK_REQUEST_FREEZE.json", canonical(freeze))
    durable(
        output / "AB_CURRENT_AUTHORITY_CHECK.json",
        canonical(
            dict(
                development_instance=authority,
                business_population=before,
                current_per_slot_checks="*/CURRENT_AUTHORITY.json",
                not_continuing_send_authority=True,
            )
        ),
    )
    return freeze


def archived_handler(rt: dev.DevelopmentRuntime, output: Path, fixture: bool) -> Any:
    """Consume authenticated original captures; post-capture faults stop both arms."""

    def consume(
        target: Path, row: dict[str, Any], outcome: dict[str, Any]
    ) -> dict[str, Any]:
        if outcome.get("stop_remaining") or not outcome.get("response_received"):
            return dict(
                prediction_state="NO_PREDICTION",
                candidate_semantic_prediction=None,
                system_stop_required=bool(outcome.get("stop_remaining")),
                scientific_admission=False,
            )
        checker = CurrentAccessChecker(rt, output, row)
        binding = base.CaptureBinding(
            row["request_sha256"],
            row["execution_operation_id"],
            row["AttemptID"],
            checker.registry.identity,
            checker.claim.fingerprint,
            fixture,
        )
        raw = base.verify_capture(target, checker, binding)
        # Always current authority, even if no selection or invalid model JSON.
        checker.check(checker.registry.identity, base.SCOPE, checker.checked_at)
        complete = (
            json.loads((target / "response.raw").read_bytes()).get("status")
            == "completed"
        )
        result = results.diagnose(
            raw,
            row["case_id"],
            row["arm"],
            checker.registry,
            checker.packet,
            checker,
            checker.checked_at,
            preflight_valid=True,
            capture_valid=complete,
        )
        response = json.loads((target / "response.raw").read_bytes())
        usage = response["usage"]
        details = usage.get("input_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if cached is not None and (
            type(cached) is not int or not 0 <= cached <= usage["input_tokens"]
        ):
            raise ValueError("AB_CACHED_USAGE_INTEGRITY")
        result["provider_usage"] = usage
        result["cached_tokens"] = cached
        result["cached_tokens_status"] = (
            "UNKNOWN" if cached is None else "PROVIDER_REPORTED"
        )
        result["account_bill"] = "UNKNOWN"
        result["meter_reference_cost_scope"] = (
            "CONDITIONAL_REFERENCE_ONLY_CACHE_ABSENCE_NOT_ZERO"
        )
        outcome["native_evidence_candidate_valid"] = result["E_link"]
        if not result["E_link"]:
            outcome["status"] = "CONTENT_OR_SCHEMA_FAILURE"
        result["authority_failure"] = checker.authority_failure
        durable(target / "AB_AUTHORITY_RECHECKS.json", canonical(checker.receipts))
        durable(target / "AB_MATCHED_FRONTIER.json", canonical(result))
        if checker.authority_failure:
            outcome.update(
                stop_remaining=True, stop_reason="AB_POST_CAPTURE_AUTHORITY_FAILURE"
            )
        return result

    return consume


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Only original sender; separate genuine pins required for this exact runtime."""
    if fixture_transport is None and (fixture_pins or fixture_result is not None):
        raise ValueError("AB_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    freeze = json.loads((output / "FINAL_EXECUTION_FREEZE.json").read_bytes())
    rt = memory.open_runtime(freeze["development_instance"])
    interface = sender.ResearchInterface(
        inputs.VERSION,
        inputs.catalog_for,
        verify,
        inputs.call_for,
        lambda text, row, call: h2_results.structure(text, call),
        archived_handler(rt, output, fixture_transport is not None),
    )
    return sender.execute(
        environment="DEVELOPMENT",
        source_commit=source_commit,
        output=output,
        result_root=fixture_result
        or ROOT / "data/runtime/g113-r3" / freeze["operation_id"],
        fixture_transport=fixture_transport,
        composition=sender.ExecutionComposition(
            rt.authority(fixture=fixture_transport is not None),
            fixture_pins if fixture_transport is not None else APPROVED_RELEASES,
            MODULES,
            interface,
            inputs.RELEASE,
            QWEN38_DEVELOPMENT_PROFILE,
        ),
    )


def main() -> None:
    """Explicit offline preparation; live execution remains separately released."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.instance, args.output)


if __name__ == "__main__":
    main()
