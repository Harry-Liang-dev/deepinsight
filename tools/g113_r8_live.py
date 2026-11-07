"""R8 four-slot composition of existing SDK, Meter, Memory and guarded sender."""

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
from tools import g113_r8_binding as tasks
from tools import g113_r8_contract as contract
from tools.g113_r1_binding import ROOT

VERSION = "G113_R8_TRUSTED_FOUR_SLOT_EXECUTION_V1"
RELEASE_CONTRACT = "G113_R8_FOUR_SLOT_V1"
MODULES = tuple(
    sorted(
        set(
            (
                *inherited.MODULES,
                "tools/g113_r8_binding.py",
                "tools/g113_r8_contract.py",
                "tools/g113_r8_live.py",
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
    """Check untouched R8 text before independent evaluation."""
    catalog = tasks.catalog_for(ROOT, row)
    if call.response_schema != contract.output_schema(catalog):
        raise ValueError("R8_RESPONSE_SCHEMA_DRIFT")
    result = contract.diagnose(text, catalog)
    valid = not result["errors"] and not result["not_evaluated"]
    return dict(
        schema_valid=valid,
        checker_version=contract.CHECKER_VERSION,
        contract_diagnostic=result,
        binding=contract.validate_output(text, catalog) if valid else None,
        research_output_accepted=False,
        scientific_admission=False,
        applied="PENDING_W5",
        actually_consumed="PENDING_W5",
    )


def verify(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Require final W3 population, exact files, runtime and model; never repair."""
    signed = tasks.matched(root)
    if (
        freeze["interface"] != VERSION
        or freeze["release_contract"] != RELEASE_CONTRACT
        or freeze["sender_runtime"] != runtime(root)
        or freeze["model_profile"] != profile_record(QWEN38_DEVELOPMENT_PROFILE)
        or freeze["configuration"] != inherited.configuration()
        or freeze["model"] != sdk.MODEL
        or freeze["research_as_of"] != memory.CUTOFF
        or freeze["planned_samples"] != 4
        or not freeze["operation_id"].startswith("G113-R8-LIVE-FREEZE-")
        or tuple(s["sample_id"] for s in freeze["slots"]) != tasks.ORDER
        or freeze["population_identity"] != digest(freeze["slots"])
    ):
        raise ValueError("R8_RUNTIME_POPULATION_DRIFT")
    for row, original in zip(freeze["slots"], signed["candidates"], strict=True):
        if (
            row["semantic_task_identity"] != original["task_identity"]
            or row["role"] != original["role"]
            or row["context"] != original["context"]
            or row["checker"] != contract.CHECKER_VERSION
            or not row["invocation_candidate_id"].startswith(
                freeze["operation_id"] + ":invocation:"
            )
        ):
            raise ValueError("R8_FINAL_TASK_OR_RECEIVER_DRIFT")
        folder = output / row["slot"]
        for name, sha in row["file_identities"].items():
            path = (folder / name).resolve()
            if (
                not path.is_relative_to(folder.resolve())
                or blob_hash(path.read_bytes()) != sha
            ):
                raise ValueError("R8_FROZEN_FILE_DRIFT")
        for key, name in (
            ("input", "MODEL_INPUT.json"),
            ("prompt", "prompt.txt"),
            ("task", "TASK_CATALOG.json"),
            ("schema", "RESPONSE_SCHEMA.json"),
            ("references", "REFERENCE_CATALOG.json"),
            ("temporal", "SYSTEM_TEMPORAL_BINDING.json"),
            ("display_cards", "SYSTEM_DISPLAY_CARDS.json"),
        ):
            if (folder / name).read_bytes() != tasks.member(root, original, key):
                raise ValueError("R8_W3_FROZEN_BYTES_DRIFT")
        raw = (folder / "sdk-request.raw").read_bytes()
        if (
            blob_hash(raw) != row["request_sha256"]
            or digest(read(folder / "MODEL_INPUT.json")) != row["payload_identity"]
            or digest(read(folder / "RESPONSE_SCHEMA.json")) != row["schema_identity"]
        ):
            raise ValueError("R8_REQUEST_OR_SCHEMA_DRIFT")
    if freeze["request_sha256s"] != [
        s["request_sha256"] for s in freeze["slots"]
    ] or freeze["schema_identities"] != [s["schema_identity"] for s in freeze["slots"]]:
        raise ValueError("R8_MANIFEST_POPULATION")


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Freeze only four W3 tasks with new current development receivers and wire."""
    config = inherited.configuration()
    rows = tasks.rows()
    output.mkdir(parents=True, exist_ok=False)
    installation = memory.install_runtime(instance, release_contract=RELEASE_CONTRACT)
    created = datetime.now(UTC)
    operation = "G113-R8-LIVE-FREEZE-" + created.strftime("%Y%m%dT%H%M%S%fZ")
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
        original = tasks.signed_row(ROOT, row["sample_id"])
        folder = output / row["slot"]
        for key, name in (
            ("input", "MODEL_INPUT.json"),
            ("prompt", "prompt.txt"),
            ("task", "TASK_CATALOG.json"),
            ("schema", "RESPONSE_SCHEMA.json"),
            ("references", "REFERENCE_CATALOG.json"),
            ("temporal", "SYSTEM_TEMPORAL_BINDING.json"),
            ("display_cards", "SYSTEM_DISPLAY_CARDS.json"),
        ):
            durable(folder / name, tasks.member(ROOT, original, key))
        catalog = tasks.catalog_for(ROOT, row)
        call = tasks.call_for(catalog, (folder / "prompt.txt").read_text())
        first, second = sdk.sdk_preview(call), sdk.sdk_preview(call)
        if first["raw"] != second["raw"]:
            raise ValueError("R8_SDK_NONDETERMINISTIC")
        raw = first.pop("raw").encode()
        durable(folder / "sdk-request.raw", raw)
        durable(folder / "SDK_SERIALIZATION.json", canonical(first))
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
                task_identity=catalog.identity,
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
        schema="G113_R8_CURRENT_AUTHORITY_EXECUTION_FREEZE_V1",
        status="FROZEN_FOR_INDEPENDENT_REVIEW",
        interface=VERSION,
        created_at=created.isoformat(),
        operation_id=operation,
        source_commit_ref="SOURCE_MANIFEST.json#/source_commit",
        slots=slots,
        population_identity=digest(slots),
        planned_samples=4,
        request_sha256s=[s["request_sha256"] for s in slots],
        schema_identities=[s["schema_identity"] for s in slots],
        sender_runtime=runtime(),
        development_instance=bound["development_instance"],
        model_profile=profile_record(QWEN38_DEVELOPMENT_PROFILE),
        model=sdk.MODEL,
        configuration=config,
        release_contract=RELEASE_CONTRACT,
        W3_source=tasks.SOURCE,
        W3_issuance=tasks.ISSUANCE,
        W3_manifest=tasks.MANIFEST,
        interface_module_sha256=tasks.MODULE,
        research_as_of=memory.CUTOFF,
        mode="HISTORICAL_T0_T1_DIAGNOSTIC_NOT_CURRENT_EVENT",
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        W4_review="NOT_ISSUED",
        W5_preregistration="NOT_ISSUED",
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
    """Use original engine and exact R8 pins; no caller live override."""
    inherited.configuration()
    fixture = fixture_transport is not None
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("R8_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    rt = memory.open_runtime(freeze["development_instance"])
    interface = sender.ResearchInterface(
        VERSION, tasks.catalog_for, verify, tasks.call_for, diagnose
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
