"""H2 fixed12 composition; new technical pins required, original network engine."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    QWEN38_DEVELOPMENT_PROFILE,
    profile_record,
)
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools import g113_r7_live as inherited
from tools import g113_r7_memory as memory
from tools import g113_r7_prepare as sdk
from tools import g113_r8_live as previous_live
from tools import h2_inputs as tasks
from tools import h2_results as results
from tools.g113_r1_binding import ROOT

VERSION = "H2_TRUSTED_FIXED12_EXECUTION_V1"
RELEASE_CONTRACT = "H2_FIXED12_DEVELOPMENT_V1"
MODULES = tuple(
    sorted(
        set(
            (
                *previous_live.MODULES,
                "tools/g113_r9_binding.py",
                "tools/g113_r9_contract.py",
                "tools/g113_r9_live.py",
                "tools/g113_r9_integrity.py",
                "tools/h2_inputs.py",
                "tools/h2_live.py",
                "tools/h2_results.py",
                "h2_pilot/__init__.py",
                "h2_pilot/contract.py",
                "h2_pilot/verifier.py",
            )
        )
    )
)
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()


def read(path: Path) -> Any:
    """Read a local frozen record; fields themselves never grant authority."""
    return json.loads(path.read_bytes())


def runtime(root: Path = ROOT) -> dict[str, str]:
    """Pin the complete inherited chain and actual new composition modules."""
    return {
        **sender.runtime(root),
        **{p: blob_hash((root / p).read_bytes()) for p in MODULES},
    }


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Strict structure only; source-bound predictions follow immutable capture."""
    return results.structure(text, call)


def verify(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Recheck exact published bytes and new technical runtime before every send."""
    if (
        freeze["interface"] != VERSION
        or freeze["release_contract"] != RELEASE_CONTRACT
        or freeze["sender_runtime"] != runtime(root)
        or freeze["model_profile"] != profile_record(QWEN38_DEVELOPMENT_PROFILE)
        or freeze["configuration"] != inherited.configuration()
        or freeze["model"] != sdk.MODEL
        or freeze["research_as_of"] != memory.CUTOFF
        or freeze["planned_samples"] != 12
        or not freeze["operation_id"].startswith("H2-LIVE-FREEZE-")
        or tuple(s["sample_id"] for s in freeze["slots"]) != tasks.ORDER
        or freeze["population_identity"] != digest(freeze["slots"])
    ):
        raise ValueError("H2_RUNTIME_POPULATION_DRIFT")
    for row in freeze["slots"]:
        folder = output / row["slot"]
        for name, sha in row["file_identities"].items():
            path = (folder / name).resolve()
            if (
                not path.is_relative_to(folder.resolve())
                or blob_hash(path.read_bytes()) != sha
            ):
                raise ValueError("H2_FROZEN_FILE_DRIFT")
        for name in tasks.FILES:
            if (folder / name).read_bytes() != tasks.checked(
                root, row["sample_id"], name
            ):
                raise ValueError("H2_W3_BYTES_DRIFT")
        if (
            blob_hash((folder / "sdk-request.raw").read_bytes())
            != row["request_sha256"]
            or digest(read(folder / "RESPONSE_SCHEMA.json")) != row["schema_identity"]
        ):
            raise ValueError("H2_REQUEST_OR_SCHEMA_DRIFT")
        if row["role"] != "fundamental_analyst" or not row[
            "invocation_candidate_id"
        ].startswith(freeze["operation_id"] + ":invocation:"):
            raise ValueError("H2_RECEIVER_DRIFT")
    if freeze["request_sha256s"] != [
        s["request_sha256"] for s in freeze["slots"]
    ] or freeze["schema_identities"] != [s["schema_identity"] for s in freeze["slots"]]:
        raise ValueError("H2_MANIFEST_POPULATION")


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Bind published fixed12 to current receivers without regenerating prompts."""
    tasks.published()
    config = inherited.configuration()
    rows = tasks.rows()
    output.mkdir(parents=True, exist_ok=False)
    installation = memory.install_runtime(instance, release_contract=RELEASE_CONTRACT)
    created = datetime.now(UTC)
    operation = "H2-LIVE-FREEZE-" + created.strftime("%Y%m%dT%H%M%S%fZ")
    bound = memory.bind_receivers(
        instance,
        installation["installation_sha256"],
        rows,
        lambda row: tasks.catalog_for(ROOT, row),
        output,
        operation_id=operation,
        created=created,
        release_contract=RELEASE_CONTRACT,
    )
    slots = []
    requests = []
    for item in bound["slots"]:
        row = dict(item)
        folder = output / row["slot"]
        for name in tasks.FILES:
            durable(folder / name, tasks.checked(ROOT, row["sample_id"], name))
        call = tasks.call_for_case(ROOT, row["sample_id"])
        first, second = sdk.sdk_preview(call), sdk.sdk_preview(call)
        raw = (folder / "sdk-request.raw").read_bytes()
        if first["raw"].encode() != raw or second["raw"].encode() != raw:
            raise ValueError("H2_W1_W3_SDK_BYTES_DIFFER")
        row.update(
            request_sha256=blob_hash(raw),
            schema_identity=digest(call.response_schema),
            response_schema_identity=digest(call.response_schema),
            payload_identity=digest(call.input_payload),
        )
        row["file_identities"] = {
            p.name: blob_hash(p.read_bytes()) for p in folder.iterdir() if p.is_file()
        }
        slots.append(row)
        requests.append(
            dict(
                sample_id=row["sample_id"],
                role=row["role"],
                context=row["context"],
                task_identity=row["semantic_task_identity"],
                schema_identity=row["schema_identity"],
                payload_identity=row["payload_identity"],
                request_sha256=row["request_sha256"],
                raw_path=row["slot"] + "/sdk-request.raw",
                bytes=len(raw),
                repeated_sdk_bytes_equal=True,
                w3_prompt_bytes_preserved=True,
                operational_authority_in_model_payload=False,
            )
        )
    freeze = dict(
        schema="H2_FIXED12_CURRENT_AUTHORITY_EXECUTION_FREEZE_V1",
        status="FROZEN_FOR_INDEPENDENT_REVIEW",
        interface=VERSION,
        created_at=created.isoformat(),
        operation_id=operation,
        source_commit_ref="SOURCE_MANIFEST.json#/source_commit",
        slots=slots,
        population_identity=digest(slots),
        planned_samples=12,
        request_sha256s=[s["request_sha256"] for s in slots],
        schema_identities=[s["schema_identity"] for s in slots],
        sender_runtime=runtime(),
        development_instance=bound["development_instance"],
        model_profile=profile_record(QWEN38_DEVELOPMENT_PROFILE),
        model=sdk.MODEL,
        configuration=config,
        release_contract=RELEASE_CONTRACT,
        W3_source=tasks.SOURCE,
        W3_source_tree=tasks.TREE,
        W3_manifest=tasks.MANIFEST,
        research_as_of=memory.CUTOFF,
        mode="H2_FIXED_CLAIM_DEVELOPMENT_PILOT",
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        W4_review="NOT_ISSUED",
        W5_execution_binding="NOT_ISSUED_METHODS_V2_ALREADY_ACCEPTED",
        execution_authorized=False,
        new_model_calls=0,
        new_provider_calls=0,
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
        failures=dict(
            system="STOP_REMAINING_NO_RETRY",
            content="PRESERVE_CONTINUE_SUBJECT_TO_EXACT_W5_REGISTRATION",
        ),
    )
    verify(ROOT, output, freeze)
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(freeze))
    durable(
        output / "EXACT_SDK_REQUEST_MANIFEST.json",
        canonical(
            dict(
                operation_id=operation,
                population_identity=freeze["population_identity"],
                requests=requests,
            )
        ),
    )
    durable(
        output / "PRE_SEND_ACL_CAS_REVALIDATION.json", canonical(revalidate(output))
    )
    return freeze


def revalidate(output: Path) -> list[dict[str, Any]]:
    """Reopen current authority and independently requery every final recipient."""
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    verify(ROOT, output, freeze)
    return memory.revalidate(
        output,
        freeze["development_instance"],
        freeze["slots"],
        lambda row: tasks.catalog_for(ROOT, row),
    )


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Use original engine and exact H2 pins; no caller live override."""
    inherited.configuration()
    fixture = fixture_transport is not None
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("R9_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    rt = memory.open_runtime(freeze["development_instance"])
    interface = sender.ResearchInterface(
        VERSION,
        tasks.catalog_for,
        verify,
        tasks.call_for,
        diagnose,
        results.consume_archived,
    )
    composition = sender.ExecutionComposition(
        rt.authority(fixture=fixture),
        fixture_pins if fixture else APPROVED_RELEASES,
        MODULES,
        interface,
        RELEASE_CONTRACT,
        QWEN38_DEVELOPMENT_PROFILE,
    )
    return sender.execute(
        environment="DEVELOPMENT",
        source_commit=source_commit,
        output=output,
        result_root=fixture_result
        or ROOT / "data/runtime/g113-r3" / freeze["operation_id"],
        fixture_transport=fixture_transport,
        composition=composition,
    )


def main() -> int:
    """Explicit development trigger, with no live-release pins installed by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["DEVELOPMENT"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        if not args.source_commit:
            parser.error("--source-commit required")
        execute(args.output, args.source_commit)
    else:
        if args.instance is None:
            parser.error("--instance required")
        prepare(args.instance, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
