"""G113-R2 offline prospective freeze. There is deliberately no send operation."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.delivery import MemoryDelivery
from src.memory.vnext_contracts import Scope
from src.models.enums import AgentName, ResearchScopeType
from src.schemas.research_v2_shared import digest
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import request_audit
from tools.g111_r1_msft import MSFTMemory, save
from tools.g113_r1_binding import INPUT, ROOT, compose
from tools.g113_r1_contract import VERSION, output_schema
from tools.g113_r1_delivery import resolve_delivery_view
from tools.g113_r1_prepare import candidate_call, no_change
from tools.g113_r2_memory import (
    ReceivingMemory,
    bind_current,
    prospective_episode,
    recheck,
)

W3 = "artifacts/g113-r2/inputs/w3/artifacts/g113-w3-r2"
W6 = "artifacts/g113-r2/inputs/w6/artifacts/g113-r1"
MANIFEST_SHA = "0482c304e0bcf1bb07babf9cdfe4b2c1109c5868b62fe0fb29603867bd34d7d1"
MATCH_SHA = "838d0434c881adf4030d620ecea02991833f3cd17faffbfc69b7c0fd5788c739"
W6_SHA = "926c335a3013cdbd2600210237f59fcf0a91ad298037602a2e991fe3925084f3"
ORDER = (
    ("fundamental_analyst", "FULL"),
    ("fundamental_analyst", "DELTA"),
    ("news_event_analyst", "FULL"),
    ("news_event_analyst", "DELTA"),
)
RUNTIME = (
    "tools/g113_r2_freeze.py",
    "tools/g113_r2_memory.py",
    "tools/g113_r1_binding.py",
    "tools/g113_r1_contract.py",
    "tools/g113_r1_prepare.py",
    "tools/g113_contract.py",
    "src/services/pilot_model_readiness.py",
    "src/services/llm_provider.py",
)


def read(path: Path) -> Any:
    """Read retained JSON without mutation."""
    return json.loads(path.read_bytes())


def runtime_identity(root: Path) -> dict[str, str]:
    """Include the R2 glue omitted from W6's older implementation closure."""
    return {p: blob_hash((root / p).read_bytes()) for p in RUNTIME}


def final_match(root: Path) -> dict[str, Any]:
    """Verify exact independently delivered W3 receipt and each consumed byte."""
    base = root / W3
    if blob_hash((base / "SOURCE_MANIFEST.json").read_bytes()) != MANIFEST_SHA:
        raise ValueError("R2_W3_MANIFEST")
    if (
        blob_hash((base / "G113_R2_W3_FINAL_SEMANTIC_MATCH.json").read_bytes())
        != MATCH_SHA
    ):
        raise ValueError("R2_W3_MATCH")
    manifest = read(base / "SOURCE_MANIFEST.json")
    name = "artifacts/g113-w3-r2/FINAL_RESEARCH_TASK_FREEZE.json"
    member = next(x for x in manifest["files"] if x["path"] == name)
    raw = (base / "FINAL_RESEARCH_TASK_FREEZE.json").read_bytes()
    if blob_hash(raw) != member["sha256"]:
        raise ValueError("R2_W3_TASK_BYTES")
    result: dict[str, Any] = json.loads(raw)
    if (
        result["interface_version"] != VERSION
        or result["W3_final_task_binding"] != "PASS"
    ):
        raise ValueError("R2_W3_INTERFACE")
    if [(x["role"], x["arm"]) for x in result["slots"]] != list(ORDER):
        raise ValueError("R2_POPULATION_ORDER")
    return result


def checked_storage(root: Path, output: Path) -> None:
    """Copy only byte-verified actual W6 storage; never use controlled identities."""
    base = root / W6
    if blob_hash((base / "MANIFEST.json").read_bytes()) != W6_SHA:
        raise ValueError("R2_W6_MANIFEST")
    prefix = "artifacts/g113-r1/release/actual/storage/"
    manifest = read(base / "MANIFEST.json")
    for row in manifest["files"]:
        if row["path"].startswith(prefix):
            p = base / row["path"].removeprefix("artifacts/g113-r1/")
            if blob_hash(p.read_bytes()) != row["sha256"]:
                raise ValueError("R2_STORAGE_IDENTITY")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base / "release/actual/storage", output / "storage")


def receiver(
    root: Path,
    output: Path,
    role: str,
    cutoff: datetime,
    task: str,
    invocation: str,
    created: datetime,
    copy_store: Callable[[Path, Path], None] = checked_storage,
) -> ReceivingMemory:
    """Development-only composition assigns explicit receiver; grants no send rights."""
    copy_store(root, output)
    memory = ReceivingMemory(root, output)
    ep = prospective_episode(cutoff, created, task)
    scope = Scope(
        scope_type=ResearchScopeType.RESEARCH_EPISODE,
        scope_id="EPISODE:" + ep.episode_id,
    )
    access = memory.access.model_copy(
        update={"role": AgentName(role), "scopes": (*memory.history_scopes, scope)}
    )
    memory.bind_receiver(ep, access, invocation)
    return memory


def validate_prereg_binding(
    freeze: dict[str, Any], registration: dict[str, Any]
) -> None:
    """Mechanical matching only; this does not authenticate or sign a W5 receipt."""
    for key in ("population_identity", "request_sha256s", "schema_identities"):
        if registration.get(key) != freeze[key]:
            raise ValueError("R2_PREREG_IDENTITY:" + key)
    if registration.get("planned_samples") != 4:
        raise ValueError("R2_PREREG_DENOMINATOR")


def verify_frozen_bytes(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Reject drift before future review/consumer use; never send or repair."""
    if freeze["runtime_identity"] != runtime_identity(root):
        raise ValueError("R2_RUNTIME_DRIFT")
    final_match(root)
    for slot in freeze["slots"]:
        folder = output / slot["slot"]
        for name, expected in slot["file_identities"].items():
            if blob_hash((folder / name).read_bytes()) != expected:
                raise ValueError("R2_REQUEST_OR_DEPENDENCY_DRIFT:" + name)


def freeze_requests(
    root: Path,
    output: Path,
    *,
    operation_prefix: str = "G113-R2-FREEZE",
    copy_store: Callable[[Path, Path], None] = checked_storage,
    template_path: Path | None = None,
    ordinary_memory: MSFTMemory | None = None,
    memory_for_slot: (
        Callable[[str, datetime, str, str, datetime], ReceivingMemory] | None
    ) = None,
) -> dict[str, Any]:
    """Requery and serialize four review candidates twice without inference."""
    matched = final_match(root)
    output.mkdir(parents=True, exist_ok=False)
    created = datetime.now(UTC)
    operation = operation_prefix + "-" + created.strftime("%Y%m%dT%H%M%S%fZ")
    if ordinary_memory is None:
        copy_store(root, output / "ordinary")
        ordinary = MSFTMemory(root, output / "ordinary")
    else:
        ordinary = ordinary_memory
    daily = no_change(ordinary)
    save(output / "NOCHANGE_CONTROL.json", daily)
    prompt = (
        root / INPUT / "w3/artifacts/g113-w3/inputs/COMMON_PROMPT_CANDIDATE.txt"
    ).read_bytes()
    slots, bindings = [], []
    template = MemoryDelivery.model_validate(
        read(template_path or root / W6 / "release/actual/DELIVERY.json")
    )
    for original in matched["slots"]:
        role, arm, name = original["role"], original["arm"], original["slot"]
        catalog = compose(root, role, arm)
        schema = output_schema(catalog)
        if (
            catalog.identity != original["task_identity"]
            or digest(schema) != original["schema_canonical_identity"]
            or blob_hash(prompt) != original["prompt_sha256"]
        ):
            raise ValueError("R2_TASK_SCHEMA_PROMPT_DRIFT")
        folder = output / name
        folder.mkdir()
        task = operation + ":task:" + name
        invocation = operation + ":invocation:" + name
        cutoff = datetime.fromisoformat(matched["research_as_of"])
        memory = (
            memory_for_slot(role, cutoff, task, invocation, created)
            if memory_for_slot is not None
            else receiver(
                root,
                folder / "memory",
                role,
                cutoff,
                task,
                invocation,
                created,
                copy_store,
            )
        )
        before = memory.population()
        candidate, binding = bind_current(memory, catalog, template)
        access_identity = digest(memory.access)
        receipt = recheck(memory, candidate, catalog, access_identity)
        legacy_view = resolve_delivery_view(
            memory, candidate, role=role, w1_view_id="G110:Q1_RECAST_POLICY"
        )
        call = candidate_call(catalog, prompt.decode())
        first, second = request_audit(call, output_cap=8192), request_audit(
            call, output_cap=8192
        )
        raw = first["serialized_http_body"].encode()
        if raw != second["serialized_http_body"].encode():
            raise ValueError("R2_SERIALIZATION_NONDETERMINISTIC")
        # Equality with W3 preview is checked, never used as the final hash source.
        if blob_hash(raw) != original["request_preview_sha256"]:
            raise ValueError("R2_MODEL_VISIBLE_SEMANTIC_DRIFT_REQUIRES_W3")
        (folder / "sdk-request.raw").write_bytes(raw)
        (folder / "prompt.txt").write_bytes(prompt)
        records = {
            "RESPONSE_SCHEMA.json": schema,
            "TASK_CATALOG.json": catalog.data(),
            "CURRENT_BINDING.json": binding,
            "W6_DELIVERY.json": candidate.model_dump(mode="json"),
            "PRESEND_OFFLINE_CHECK.json": receipt,
            "SDK_AUDIT.json": first,
            "RECEIVING_EPISODE_CANDIDATE.json": memory.ep.model_dump(mode="json"),
            "ACCESS_CONTEXT.json": memory.access.model_dump(mode="json"),
            "LEGACY_VIEW_RESOLUTION.json": legacy_view,
        }
        for filename, value in records.items():
            save(folder / filename, value)
        if memory.population() != before:
            raise ValueError("R2_MEMORY_CONTENT_CHANGED")
        file_ids = {
            p.name: blob_hash(p.read_bytes()) for p in folder.iterdir() if p.is_file()
        }
        row = dict(
            slot=name,
            role=role,
            arm=arm,
            operational_task_id=task,
            semantic_task_identity=catalog.identity,
            episode_candidate_id=memory.ep.episode_id,
            invocation_candidate_id=invocation,
            request_sha256=blob_hash(raw),
            schema_identity=digest(schema),
            file_identities=file_ids,
            access_identity=access_identity,
            dependency_snapshot=binding["dependency_snapshot"],
            delivery_identity=digest(candidate),
            created_at=created.isoformat(),
            request_recomputed_not_copied=True,
            preview_equality=True,
            actual_invocation_at=None,
            actually_consumed=False,
            applied=False,
        )
        slots.append(row)
        bindings.append(
            dict(
                slot=name,
                memory_readset=binding["memory_readset"],
                versions=binding["original_memory_versions"],
                relations=binding["relation_ids"],
                sources=binding["source_readset"],
                access_identity=access_identity,
                ordinary_mode=candidate.mode,
                dispatch_authorized=False,
            )
        )
    result = dict(
        schema="G113_R2_EXECUTION_FREEZE_V1",
        status="FROZEN_FOR_INDEPENDENT_REVIEW",
        operation_id=operation,
        created_at=created.isoformat(),
        interface=VERSION,
        mode="HISTORICAL_T0_T1_DIAGNOSTIC_NOT_CURRENT_EVENT",
        research_as_of=matched["research_as_of"],
        slots=slots,
        request_sha256s=[s["request_sha256"] for s in slots],
        schema_identities=[s["schema_identity"] for s in slots],
        population_identity=digest(slots),
        planned_samples=4,
        runtime_identity=runtime_identity(root),
        input_identities=read(root / "artifacts/g113-r2/INPUT_IDENTITIES.json"),
        model="qwen3.7-flash-2026-07-15",
        region="cn-beijing",
        max_output_tokens=8192,
        enable_thinking=False,
        store=False,
        concurrency=1,
        retry=0,
        fallback="NONE",
        token_cost_gate=False,
        exact_context_fit="UNKNOWN",
        tokenizer_template_qualification="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        W4_review="REQUIRED",
        W5_preregistration="PENDING",
        execution_authorized=False,
        actual_attempts=0,
        source_memory_recheck="REQUIRED_IMMEDIATELY_BEFORE_EACH_SEND",
        authority="SOURCE_ATTRIBUTED_ONLY_NOT_WORLD_FACT",
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
        new_model_calls=0,
        new_provider_calls=0,
        native_scientific_admission="BLOCKED",
        formal_pit=False,
        failures=dict(
            identity_or_permission_drift="STOP_AND_REFREEZE_BEFORE_SEND",
            uncertain_send_or_usage="STOP_REMAINING_NO_RETRY",
            provider_error_or_context_rejection="PRESERVE_STOP_NO_RETRY",
            content_schema_failure="PRESERVE_NO_REPAIR_NO_RETRY_SUBJECT_TO_W5_PROTOCOL",
        ),
    )
    save(output / "G113_R2_EXECUTION_FREEZE.json", result)
    save(
        output / "FINAL_SDK_REQUEST_MANIFEST.json",
        dict(slots=slots, population_identity=result["population_identity"]),
    )
    save(
        output / "SOURCE_MEMORY_PERMISSION_BINDING.json",
        dict(
            slots=bindings,
            live_recheck_required=True,
            retrieval_backend="ORIGINAL_MEMORY_SERVICE_DUCKDB_FAISS_WITH_RETAINED_DETERMINISTIC_EMBEDDING",
            semantic_retrieval_quality="NOT_MEASURED",
            scientific_admission=False,
        ),
    )
    verify_frozen_bytes(root, output, result)
    return result


def main() -> int:
    """Offline serialization and permission checks only; no Provider invocation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze_requests(ROOT, args.output)
    print(
        json.dumps(
            {k: result[k] for k in ("status", "population_identity", "request_sha256s")}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
