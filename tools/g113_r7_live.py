"""R7 composition of the original sender, Meter, Memory and exact offline requests.

This module is not a second Gateway. Independent release pins are deliberately
empty; only code-owned installation after review can enable real dispatch.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.core.settings import QwenSettings
from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    QWEN38_DEVELOPMENT_PROFILE,
    profile_record,
)
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import BEIJING
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools import g113_r6_final as r6
from tools import g113_r7_contract as contract
from tools import g113_r7_freeze as frozen
from tools import g113_r7_memory as memory
from tools import g113_r7_prepare as prep
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT

VERSION = "G113_R7_TRUSTED_EIGHT_SLOT_EXECUTION_V1"
ORIGINAL = "artifacts/g113-r7/final-freeze-v1"
ORIGINAL_SHA = "cfc21f5ebbab7c275fbcd3a66a9645358e7784ca7bc149d7b04789d8c5ab0936"
RELEASE_CONTRACT = "G113_R7_EIGHT_SLOT_V1"
MODULES = tuple(
    sorted(
        set(
            (
                *r6.MODULES,
                "tools/g113_r7_live.py",
                "tools/g113_r7_memory.py",
                "tools/g113_r7_freeze.py",
                "tools/g113_r7_prepare.py",
                "tools/g113_r7_contract.py",
                "src/core/settings.py",
                "src/services/development_model_profile.py",
            )
        )
    )
)
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()


def read(path: Path) -> Any:
    """Read local versioned JSON without granting authority from its fields."""
    return json.loads(path.read_bytes())


def original(root: Path = ROOT) -> dict[str, Any]:
    """Verify immutable eight-slot request population and real W3 Git binding."""
    frozen.matched(root)
    raw = (root / ORIGINAL / "FINAL_R7_EXECUTION_FREEZE.json").read_bytes()
    if blob_hash(raw) != ORIGINAL_SHA:
        raise ValueError("R7_ORIGINAL_FREEZE_IDENTITY")
    result: dict[str, Any] = json.loads(raw)
    if tuple(s["sample_id"] for s in result["slots"]) != frozen.ORDER:
        raise ValueError("R7_ORIGINAL_ORDER")
    for row in result["slots"]:
        if (
            blob_hash((root / ORIGINAL / row["slot"] / "sdk-request.raw").read_bytes())
            != row["request_sha256"]
        ):
            raise ValueError("R7_ORIGINAL_REQUEST_HASH")
    return result


def original_row(row: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Require the exact original A/B slot and task, not a caller-selected checker."""
    matches: list[dict[str, Any]] = [
        s for s in original(root)["slots"] if s["sample_id"] == row["sample_id"]
    ]
    if len(matches) != 1 or any(
        row[k] != matches[0][k]
        for k in (
            "slot",
            "arm",
            "context",
            "role",
            "semantic_task_identity",
            "checker",
            "request_sha256",
            "response_schema_identity",
        )
    ):
        raise ValueError("R7_ARM_TASK_CHECKER_IDENTITY")
    return matches[0]


def catalog_for(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Resolve A through original R6 and B through signed R7 W3 catalogs."""
    old = original_row(row, root)
    index = int(old["sample_id"][1:]) - 1
    if old["arm"] == "A":
        catalog = r6.catalog_for(root, r6.matched(root)["task_slots"][index])
    else:
        catalog = frozen.b_catalog(root, frozen.matched(root)["slots"][index])
    if catalog.identity != old["semantic_task_identity"]:
        raise ValueError("R7_SEMANTIC_TASK_CHANGED")
    return catalog


def call_for(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Use exact previously serialized input; no runtime metadata enters the model."""
    old = next(
        s
        for s in original()["slots"]
        if s["semantic_task_identity"] == catalog.identity
    )
    trusted = catalog_for(ROOT, old)
    folder = ROOT / ORIGINAL / old["slot"]
    if (
        catalog.data() != trusted.data()
        or prompt != (folder / "prompt.txt").read_text()
    ):
        raise ValueError("R7_CALL_CATALOG_PROMPT_DRIFT")
    if old["arm"] == "A":
        parent = r6.matched(ROOT)["task_slots"][int(old["sample_id"][1:]) - 1]
        call, _ = prep.model_only_call(parent)
    else:
        call, _ = frozen.b_call(
            ROOT, frozen.matched(ROOT)["slots"][int(old["sample_id"][1:]) - 1]
        )
    if call.input_payload != read(
        folder / "MODEL_INPUT.json"
    ) or call.response_schema != read(folder / "RESPONSE_SCHEMA.json"):
        raise ValueError("R7_CALL_PAYLOAD_DRIFT")
    return call


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Preserve arm-specific checker; never rewrite model content or grant facts."""
    old = original_row(row)
    if old["arm"] == "A":
        return r6.diagnose(
            text, r6.matched(ROOT)["task_slots"][int(old["sample_id"][1:]) - 1], call
        )
    catalog = catalog_for(ROOT, row)
    if call.response_schema != contract.output_schema(catalog):
        raise ValueError("R7_RESPONSE_SCHEMA_DRIFT")
    report = contract.diagnose(text, catalog)
    valid = not report["errors"] and not report["not_evaluated"]
    return dict(
        schema_valid=valid,
        checker_version=contract.CHECKER_VERSION,
        contract_diagnostic=report,
        binding=contract.validate_output(text, catalog) if valid else None,
        research_output_accepted=False,
        scientific_admission=False,
        applied="PENDING_W5",
        actually_consumed="PENDING_W5",
    )


def configuration() -> dict[str, Any]:
    """Validate the inherited active route/model without network or secret output."""
    settings = QwenSettings()
    prep.active_model(settings)
    if (
        settings.base_url.rstrip("/") != BEIJING
        or os.environ.get("DEEPINSIGHT_LLM_PROVIDER", "qwen") != "qwen"
    ):
        raise ValueError("R7_ACTIVE_PROVIDER_ROUTE_MISMATCH")
    return dict(
        model=prep.MODEL,
        provider="qwen",
        base_url=BEIJING,
        region="cn-beijing",
        credential_source="QWEN_API_KEY_ENVIRONMENT",
        credential_present=settings.api_key is not None,
        timeout_seconds=90,
        meter_elapsed_seconds=600,
        enable_thinking=False,
        store=False,
        max_output_tokens=8192,
        concurrency=1,
        retry=0,
        fallback="NONE",
        actual_response_model="UNKNOWN_UNTIL_RESPONSE",
        account_access="UNKNOWN",
        provider_retention="NOT_PROVEN",
    )


def runtime(root: Path = ROOT) -> dict[str, str]:
    """Freeze original chain plus exact opt-in composition and closed profile."""
    return {
        **sender.runtime(root),
        **{p: blob_hash((root / p).read_bytes()) for p in MODULES},
    }


def verify(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Fail closed on any input, permission envelope, runtime or population drift."""
    original(root)
    if (
        freeze["interface"] != VERSION
        or freeze["sender_runtime"] != runtime(root)
        or freeze["model_profile"] != profile_record(QWEN38_DEVELOPMENT_PROFILE)
    ):
        raise ValueError("R7_RUNTIME_INTERFACE_PROFILE_DRIFT")
    if (
        not freeze["operation_id"].startswith("G113-R7-LIVE-FREEZE-")
        or len(freeze["slots"]) != 8
        or tuple(s["sample_id"] for s in freeze["slots"]) != frozen.ORDER
    ):
        raise ValueError("R7_OPERATION_POPULATION")
    if freeze["population_identity"] != digest(freeze["slots"]):
        raise ValueError("R7_POPULATION_IDENTITY")
    for row in freeze["slots"]:
        catalog = catalog_for(root, row)
        folder = output / row["slot"]
        for name, expected in row["file_identities"].items():
            path = (folder / name).resolve()
            if (
                not path.is_relative_to(folder.resolve())
                or blob_hash(path.read_bytes()) != expected
            ):
                raise ValueError("R7_FROZEN_FILE_DRIFT")
        if (
            (folder / "sdk-request.raw").read_bytes()
            != (root / ORIGINAL / row["slot"] / "sdk-request.raw").read_bytes()
            or catalog.identity != row["semantic_task_identity"]
            or digest(read(folder / "RESPONSE_SCHEMA.json")) != row["schema_identity"]
        ):
            raise ValueError("R7_REQUEST_SCHEMA_DRIFT")
    if freeze["request_sha256s"] != [
        s["request_sha256"] for s in freeze["slots"]
    ] or freeze["schema_identities"] != [s["schema_identity"] for s in freeze["slots"]]:
        raise ValueError("R7_MANIFEST_POPULATION")


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Create actual current receivers and a new execution envelope, keeping bytes."""
    config = configuration()
    old = original()
    output.mkdir(parents=True, exist_ok=False)
    installation = memory.install_runtime(instance)
    created = datetime.now(UTC)
    operation = "G113-R7-LIVE-FREEZE-" + created.strftime("%Y%m%dT%H%M%S%fZ")
    bound = memory.bind_receivers(
        instance,
        installation["installation_sha256"],
        old["slots"],
        lambda row: catalog_for(ROOT, row),
        output,
        operation_id=operation,
        created=created,
    )
    slots = []
    comparisons = []
    for item in bound["slots"]:
        row = dict(item)
        folder = output / row["slot"]
        prior = ROOT / ORIGINAL / row["slot"]
        for name in (
            "sdk-request.raw",
            "prompt.txt",
            "MODEL_INPUT.json",
            "RESPONSE_SCHEMA.json",
            "TASK_CATALOG.json",
        ):
            durable(folder / name, (prior / name).read_bytes())
        catalog = catalog_for(ROOT, row)
        call = call_for(catalog, (folder / "prompt.txt").read_text())
        captured = prep.sdk_preview(call)
        if captured["raw"].encode() != (folder / "sdk-request.raw").read_bytes():
            raise ValueError("R7_CURRENT_SDK_WIRE_DRIFT")
        row["schema_identity"] = digest(call.response_schema)
        row["file_identities"] = {
            p.name: blob_hash(p.read_bytes()) for p in folder.iterdir() if p.is_file()
        }
        slots.append(row)
        comparisons.append(
            dict(
                sample_id=row["sample_id"],
                old_sha256=row["request_sha256"],
                new_sha256=blob_hash((folder / "sdk-request.raw").read_bytes()),
                byte_equal=True,
            )
        )
    freeze = dict(
        schema="G113_R7_CURRENT_AUTHORITY_EXECUTION_FREEZE_V1",
        status="FROZEN_FOR_INDEPENDENT_REVIEW",
        interface=VERSION,
        created_at=created.isoformat(),
        operation_id=operation,
        slots=slots,
        population_identity=digest(slots),
        planned_samples=8,
        request_sha256s=[s["request_sha256"] for s in slots],
        schema_identities=[s["schema_identity"] for s in slots],
        sender_runtime=runtime(),
        development_instance=bound["development_instance"],
        model_profile=profile_record(QWEN38_DEVELOPMENT_PROFILE),
        model=prep.MODEL,
        configuration=config,
        release_contract=RELEASE_CONTRACT,
        prior_freeze_sha256=ORIGINAL_SHA,
        prior_operation=old["operation_id"],
        prior_population=old["population_identity"],
        W3_issuance=frozen.W3_ISSUANCE,
        W3_manifest=frozen.W3_MANIFEST,
        research_as_of=old["research_as_of"],
        mode="HISTORICAL_T0_T1_DIAGNOSTIC_NOT_CURRENT_EVENT",
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure=old["historical_tokenizer_failure"],
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
        output / "EIGHT_SLOT_REQUEST_BYTE_COMPARISON.json",
        canonical(
            dict(
                original_freeze=ORIGINAL_SHA, requests=comparisons, all_byte_equal=True
            )
        ),
    )
    durable(
        output / "PRE_SEND_ACL_CAS_REVALIDATION.json", canonical(revalidate(output))
    )
    return freeze


def revalidate(output: Path) -> list[dict[str, Any]]:
    """Requery actual store, not an old authority JSON, for all eight recipients."""
    f = read(output / "FINAL_EXECUTION_FREEZE.json")
    verify(ROOT, output, f)
    return memory.revalidate(
        output,
        f["development_instance"],
        f["slots"],
        lambda row: catalog_for(ROOT, row),
    )


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Use original guarded sender; no caller-supplied live approval override."""
    configuration()
    fixture = fixture_transport is not None
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("R7_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    f = read(output / "FINAL_EXECUTION_FREEZE.json")
    rt = memory.open_runtime(f["development_instance"])
    interface = sender.ResearchInterface(
        VERSION, catalog_for, verify, call_for, diagnose
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
        result_root=fixture_result or ROOT / "data/runtime/g113-r3" / f["operation_id"],
        fixture_transport=fixture_transport,
        composition=composition,
    )


def main() -> int:
    """Explicit trusted development trigger; live sends still require installed pins."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["DEVELOPMENT"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        if not args.source_commit:
            parser.error("--source-commit required for reviewed execution")
        execute(args.output, args.source_commit)
    else:
        if args.instance is None:
            parser.error("--instance required for isolated installation")
        prepare(args.instance, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
