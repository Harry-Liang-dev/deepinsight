"""Exact W3-R6 task composition over the existing development sender and Memory.

Offline preparation is not independent release. No historical response or
synthetic answer is ever an input to call_for().
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.memory.delivery import MemoryDelivery
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_v2_shared import canonical, digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.pilot_model_readiness import SNAPSHOT, request_audit
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools import g113_r6_contract as contract
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT, compose, covers
from tools.g113_r1_prepare import no_change
from tools.g113_r2_freeze import ORDER, read
from tools.g113_r2_memory import bind_current, recheck

ART = ROOT / "artifacts/g113-r6-final"
W3 = "artifacts/g113-r6-final/intake/w3"
W3_SOURCE = "fc587fcffd09b3c495c032b0119b19ae23d80f22"
W3_MANIFEST = "51b98056e336cfea0ed038b233e63aae27ac5bf75bb985e384b56192b0a6b96f"
CHECKER_SHA = "454440399870b8631779ff6ca805876916b2fbb5d13cc24155cf4f98b61459d6"
MODULES = ("tools/g113_r6_final.py", "tools/g113_r6_contract.py", dev.MODULE)
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()
TASKS = (
    "8c2e27191fcd1f870bd3a7d4a2e3ab657c9d1242d5cdee989dea385321e1c389",
    "ce005d6a2aafae884cd577b96e5d2bddc9b18f86fe3d37aea849ff964363c2d1",
    "de62f15e8aec535840577ebab9edd15cae7613bae0c6a01eb6367aa7465c4ee5",
    "bd0ba8b2ce1134cb27fbc6706cab2cb64f591db6c4e7d1272228f7c5564f2e28",
)


def checked(root: Path, name: str) -> bytes:
    """Read a W3 member only by its exact independently pinned manifest entry."""
    base = root / W3
    raw = (base / "SOURCE_MANIFEST.json").read_bytes()
    if blob_hash(raw) != W3_MANIFEST:
        raise ValueError("R6_W3_MANIFEST")
    m = json.loads(raw)
    if m["source_commit"] != W3_SOURCE:
        raise ValueError("R6_W3_SOURCE")
    full = "artifacts/g113-w3-r6/" + name
    rows = [r for r in m["files"] if r["path"] == full]
    if len(rows) != 1 or not (base / name).resolve().is_relative_to(base.resolve()):
        raise ValueError("R6_W3_MEMBER")
    value = (base / name).read_bytes()
    if blob_hash(value) != rows[0]["sha256"]:
        raise ValueError("R6_W3_MEMBER_DRIFT")
    return value


def matched(root: Path) -> dict[str, Any]:
    """Resolve historical PENDING using the actual later W3 final matching receipt."""
    m: dict[str, Any] = json.loads(checked(root, "W3_R6_SEMANTIC_BINDING.json"))
    handoff = json.loads(checked(root, "W1_FINAL_FREEZE_HANDOFF.json"))
    if (
        m["W3_R6_SEMANTIC_BINDING"] != "PASS"
        or m["interface_version"] != contract.VERSION
        or m["observed_module_sha256"] != CHECKER_SHA
        or blob_hash((root / "tools/g113_r6_contract.py").read_bytes()) != CHECKER_SHA
        or handoff["interface_snapshot"]["checker_version"] != contract.CHECKER_VERSION
        or handoff["slots"] != m["task_slots"]
        or tuple(s["task_identity"] for s in m["task_slots"]) != TASKS
        or [(s["role"], s["arm"]) for s in m["task_slots"]] != list(ORDER)
    ):
        raise ValueError("R6_W3_FINAL_MATCH")
    return m


def catalog_for(root: Path, row: dict[str, Any]) -> TaskCatalog:
    """Use exact W3 tasks but require unchanged trusted source/Memory populations."""
    slots = matched(root)["task_slots"]
    original = next((s for s in slots if s["slot"] == row["slot"]), None)
    if original is None or any(row[k] != original[k] for k in ("role", "arm")):
        raise ValueError("R6_SLOT_IDENTITY")
    name = "candidates/" + row["slot"] + "/TASK_CATALOG.json"
    data = json.loads(checked(root, name))
    parent = compose(root, row["role"], row["arm"])
    allowed = {
        "task",
        "topics",
        "w3_original_payload",
        "w3_final_binding",
        "parent_task_identity",
        "research_interface_version",
        "w3_task_version",
        "w3_task_requirements",
    }
    old = parent.data()
    if any(
        data.get(k) != old.get(k) for k in data.keys() | old.keys() if k not in allowed
    ):
        raise ValueError("R6_TRUSTED_POPULATION_CHANGED")
    catalog = TaskCatalog(
        json.dumps(data, ensure_ascii=False), parent.source_texts_json
    )
    if (
        catalog.identity != original["task_identity"]
        or row.get("semantic_task_identity", original["task_identity"])
        != catalog.identity
    ):
        raise ValueError("R6_TASK_IDENTITY")
    schema = json.loads(
        checked(root, "candidates/" + row["slot"] + "/RESPONSE_SCHEMA_CANDIDATE.json")
    )
    if schema != contract.output_schema(catalog):
        raise ValueError("R6_SCHEMA_MATCH")
    for vid in data["views"]:
        catalog.resolve_view(vid)
    return catalog


def call_for(catalog: TaskCatalog, prompt: str) -> LLMProviderCall:
    """Feed only exact W3 model-visible files to the existing Provider serializer."""
    slot = next(
        s for s in matched(ROOT)["task_slots"] if s["task_identity"] == catalog.identity
    )
    base = "candidates/" + slot["slot"] + "/"
    if prompt.encode() != checked(ROOT, base + "prompt.txt"):
        raise ValueError("R6_PROMPT_IDENTITY")
    payload = json.loads(checked(ROOT, base + "MODEL_INPUT_CANDIDATE.json"))
    schema = contract.output_schema(catalog)
    if (
        payload["output_schema"] != schema
        or payload["task_identity"] != catalog.identity
    ):
        raise ValueError("R6_PAYLOAD_SCHEMA_IDENTITY")
    data = catalog.data()
    for key, source in (
        ("given_observations", "observations"),
        ("given_relations", "relations"),
        ("original_sources", "sources"),
        ("calculation_cards", "calculation_cards"),
        ("required_topics", "task"),
        ("research_as_of", "research_as_of"),
    ):
        if payload[key] != data[source]:
            raise ValueError("R6_MODEL_VISIBLE_SOURCE_BINDING")
    metadata = {
        vid: {k: v[k] for k in ("source_id", "raw_sha256", "locator")}
        for vid, v in data["views"].items()
    }
    if payload["view_catalog"] != metadata:
        raise ValueError("R6_MODEL_VIEW_PROJECTION")
    texts = json.loads(catalog.source_texts_json)
    for packet in payload["context_evidence"]:
        if not covers(packet, packet, texts):
            raise ValueError("R6_CONTEXT_SOURCE_SPAN")
    for view in data["views"].values():
        if not any(
            covers(packet, view, texts) for packet in payload["context_evidence"]
        ):
            raise ValueError("R6_REQUIRED_EVIDENCE_COVERAGE")
    return LLMProviderCall(SNAPSHOT, prompt, payload, schema)


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Run R6 on actual archived output, plus W3's declared material requirements."""
    catalog = catalog_for(ROOT, row)
    if call.response_schema != contract.output_schema(catalog):
        raise ValueError("R6_OUTPUT_SCHEMA_BINDING")
    report = contract.diagnose(text, catalog)
    findings: list[dict[str, Any]] = []
    binding = None
    if not report["errors"] and not report["not_evaluated"]:
        binding = contract.validate_output(text, catalog)
        obj = binding["original_output"]
        apps = {a["topic_id"]: a for a in obj["applications"]}
        for topic, views in catalog.data()["w3_task_requirements"][
            "required_views"
        ].items():
            app = apps.get(topic)
            if app is None:
                findings.append(dict(code="MISSING_TOPIC_APPLICATION", topic=topic))
                continue
            if not set(views) <= set(app["view_ids"]):
                findings.append(
                    dict(
                        code="MISSING_NECESSARY_SOURCE_OR_COUNTEREVIDENCE", topic=topic
                    )
                )
            if (
                topic in {"F_PERIOD_CHANGE", "N_CONTENT_RELATIONS"}
                and app["relation_status"] != "LINKED"
            ):
                findings.append(
                    dict(code="REPORTING_RELATION_NOT_APPLIED", topic=topic)
                )
            if topic == "F_PERIOD_CHANGE" and set(app["calculation_ids"]) != set(
                catalog.data()["calculation_cards"]
            ):
                findings.append(
                    dict(code="MISSING_SYSTEM_CARD_COMPARISON", topic=topic)
                )
            if (
                topic in {"F_MAINTAIN_LIMITS", "N_CONTENT_RELATIONS"}
                and not app["unknown_conditions"]
            ):
                findings.append(dict(code="UNKNOWN_CONDITIONS_DROPPED", topic=topic))
            if topic == "F_MAINTAIN_LIMITS" and not app["deferred_inferences"]:
                findings.append(
                    dict(
                        code="MAINTAIN_AND_UNKNOWN_INFERENCE_NOT_SEPARATED", topic=topic
                    )
                )
        if not obj["missing_key_information"]:
            findings.append(dict(code="MISSING_KEY_UNKNOWN_INFORMATION"))
    return dict(
        schema_valid=not report["errors"]
        and not report["not_evaluated"]
        and not findings,
        checker_version=contract.CHECKER_VERSION,
        contract_diagnostic=report,
        task_findings=findings,
        binding=binding,
        actually_consumed="PENDING_W5",
        applied="PENDING_W5",
        research_output_accepted=False,
        scientific_admission=False,
        prose_entailment_fiscal_scope_counterevidence="PENDING_INDEPENDENT_REVIEW",
    )


def runtime(root: Path) -> dict[str, str]:
    """Pin every executable existing sender dependency and the new combination."""
    return {
        **sender.runtime(root),
        **{p: blob_hash((root / p).read_bytes()) for p in MODULES},
    }


def verify(root: Path, output: Path, freeze: dict[str, Any]) -> None:
    """Reject changed requests, catalogs, authority envelopes or task version."""
    matched(root)
    if freeze["interface"] != contract.VERSION or freeze["sender_runtime"] != runtime(
        root
    ):
        raise ValueError("R6_RUNTIME_OR_INTERFACE_DRIFT")
    if freeze["operation_id"].startswith("G113-R5-") or not freeze[
        "operation_id"
    ].startswith("G113-R6-"):
        raise ValueError("R6_OPERATION_IDENTITY")
    if len(freeze["slots"]) != 4 or [
        (r["role"], r["arm"]) for r in freeze["slots"]
    ] != list(ORDER):
        raise ValueError("R6_POPULATION_ORDER")
    if freeze["population_identity"] != digest(freeze["slots"]):
        raise ValueError("R6_POPULATION_IDENTITY")
    for row in freeze["slots"]:
        catalog = catalog_for(root, row)
        folder = output / row["slot"]
        for name, sha in row["file_identities"].items():
            if (
                not (folder / name).resolve().is_relative_to(folder.resolve())
                or blob_hash((folder / name).read_bytes()) != sha
            ):
                raise ValueError("R6_FROZEN_FILE_DRIFT")
        if (
            blob_hash((folder / "sdk-request.raw").read_bytes())
            != row["request_sha256"]
            or digest(contract.output_schema(catalog)) != row["schema_identity"]
        ):
            raise ValueError("R6_REQUEST_SCHEMA_IDENTITY")
    if freeze["request_sha256s"] != [
        r["request_sha256"] for r in freeze["slots"]
    ] or freeze["schema_identities"] != [r["schema_identity"] for r in freeze["slots"]]:
        raise ValueError("R6_MANIFEST_POPULATION")


def interface() -> sender.ResearchInterface:
    """Trusted Python composition; cannot be selected by model JSON."""
    return sender.ResearchInterface(
        contract.VERSION, catalog_for, verify, call_for, diagnose
    )


def open_runtime(freeze: dict[str, Any]) -> dev.DevelopmentRuntime:
    """Current active instance and exact append-only grant set, never old ReadSet."""
    b = freeze["development_instance"]
    return dev.DevelopmentRuntime(
        Path(b["root"]), b["installation_sha256"], b["grant_identities"]
    )


def prepare(instance: Path, installation: str, output: Path) -> dict[str, Any]:
    """Install new read-only R6 receivers and freeze four real SDK serializations."""
    matched(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    rt = dev.DevelopmentRuntime(instance, installation)
    grants_before = rt.journal.entries(dev.GRANTS)
    controls = [json.loads(b) for _, b in grants_before]
    control = next(g for g in controls if g["task"] == "G113-R5-NOCHANGE")
    ordinary = dev.NoChangeMemory(ROOT, instance)
    ordinary.bind_receiver(
        ResearchEpisode.model_validate(control["episode"]),
        dev.NoChangeAuditAccess.model_validate(control["access"]),
        control["invocation"],
    )
    daily = no_change(ordinary)
    durable(output / "NOCHANGE_CONTROL.json", canonical(daily))
    before = ordinary.population()
    created = datetime.now(UTC)
    operation = "G113-R6-FREEZE-" + created.strftime("%Y%m%dT%H%M%S%fZ")
    slots = []
    template = MemoryDelivery.model_validate(read(dev.TEMPLATE))
    for original in matched(ROOT)["task_slots"]:
        name = original["slot"]
        catalog = catalog_for(ROOT, original)
        folder = output / name
        folder.mkdir()
        task, invocation = (
            operation + ":task:" + name,
            operation + ":invocation:" + name,
        )
        memory = rt.receiver(
            original["role"],
            datetime.fromisoformat(catalog.data()["research_as_of"]),
            task,
            invocation,
            created,
        )
        candidate, binding = bind_current(memory, catalog, template)
        access = digest(memory.access)
        checked_now = recheck(memory, candidate, catalog, access)
        prompt = checked(ROOT, "candidates/" + name + "/prompt.txt")
        call = call_for(catalog, prompt.decode())
        audit = request_audit(call, output_cap=8192)
        second = request_audit(call, output_cap=8192)
        raw = audit["serialized_http_body"].encode()
        if raw != second["serialized_http_body"].encode():
            raise ValueError("R6_SDK_NONDETERMINISTIC")
        durable(folder / "sdk-request.raw", raw)
        durable(folder / "prompt.txt", prompt)
        records = {
            "MODEL_INPUT_CANDIDATE.json": call.input_payload,
            "RESPONSE_SCHEMA.json": call.response_schema,
            "TASK_CATALOG.json": catalog.data(),
            "CURRENT_BINDING.json": binding,
            "W6_DELIVERY.json": candidate.model_dump(mode="json"),
            "PRESEND_OFFLINE_CHECK.json": checked_now,
            "SDK_AUDIT.json": audit,
            "RECEIVING_EPISODE_CANDIDATE.json": memory.ep.model_dump(mode="json"),
            "ACCESS_CONTEXT.json": memory.access.model_dump(mode="json"),
            "INVOCATION_CANDIDATE.json": dict(
                task=task,
                invocation=invocation,
                episode=memory.ep.episode_id,
                semantic_task_identity=catalog.identity,
                authorized_to_send=False,
                native_scientific_admission=False,
            ),
        }
        for file, value in records.items():
            durable(folder / file, canonical(value))
        slots.append(
            dict(
                slot=name,
                role=original["role"],
                arm=original["arm"],
                operational_task_id=task,
                invocation_candidate_id=invocation,
                semantic_task_identity=catalog.identity,
                episode_candidate_id=memory.ep.episode_id,
                request_sha256=blob_hash(raw),
                schema_identity=digest(call.response_schema),
                file_identities={
                    p.name: blob_hash(p.read_bytes())
                    for p in folder.iterdir()
                    if p.is_file()
                },
                access_identity=access,
                dependency_snapshot=binding["dependency_snapshot"],
                created_at=created.isoformat(),
                actual_invocation_at=None,
            )
        )
    if ordinary.population() != before or not set(grants_before) <= set(
        rt.journal.entries(dev.GRANTS)
    ):
        raise ValueError("R6_POPULATION_OR_OLD_GRANTS_CHANGED")
    freeze = dict(
        schema="G113_R6_FINAL_EXECUTION_FREEZE_V1",
        status="FROZEN_FOR_INDEPENDENT_REVIEW",
        interface=contract.VERSION,
        checker_version=contract.CHECKER_VERSION,
        created_at=created.isoformat(),
        operation_id=operation,
        slots=slots,
        population_identity=digest(slots),
        planned_samples=4,
        request_sha256s=[s["request_sha256"] for s in slots],
        schema_identities=[s["schema_identity"] for s in slots],
        sender_runtime=runtime(ROOT),
        development_instance=dict(
            root=str(instance.resolve()),
            installation_sha256=installation,
            instance_id=rt.record["instance_id"],
            grant_identities={
                k: blob_hash(b.encode()) for k, b in rt.journal.entries(dev.GRANTS)
            },
        ),
        W3_source=W3_SOURCE,
        W3_manifest=W3_MANIFEST,
        W3_final_binding="RESOLVED",
        model=SNAPSHOT,
        region="cn-beijing",
        enable_thinking=False,
        store=False,
        max_output_tokens=8192,
        concurrency=1,
        retry=0,
        fallback="NONE",
        research_as_of=catalog.data()["research_as_of"],
        mode="HISTORICAL_T0_T1_DIAGNOSTIC_NOT_CURRENT_MARKET_EVENT",
        exact_context_fit="UNKNOWN",
        historical_tokenizer_failure="EXACT_MODEL_TOKENIZER_AND_TEMPLATE_AUTHORITY_UNAVAILABLE",
        token_cost_gate=False,
        W4_review="REQUIRED_NEW_SCOPE_NOT_ISSUED",
        W5_preregistration="REQUIRED_NEW_POPULATION_NOT_ISSUED",
        execution_authorized=False,
        new_model_calls=0,
        new_provider_calls=0,
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
        failures=dict(
            system="STOP_REMAINING_NO_RETRY",
            content="PRESERVE_CONTINUE_SUBJECT_TO_NEW_W5_PROTOCOL",
        ),
    )
    verify(ROOT, output, freeze)
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(freeze))
    revalidate(output)
    return freeze


def revalidate(output: Path) -> list[dict[str, Any]]:
    """Requery every receiver and exact F01/source/version dependency from store."""
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    verify(ROOT, output, freeze)
    rt = open_runtime(freeze)
    checks = []
    for row in freeze["slots"]:
        _, _, receipt = sender.current_memory(
            ROOT, output, row, rt.authority(), catalog=catalog_for(ROOT, row)
        )
        checks.append(dict(slot=row["slot"], receipt=receipt))
    return checks


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Reuse reviewed sender; genuine new pins remain absent in this candidate."""
    fixture = fixture_transport is not None
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("R6_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    rt = open_runtime(freeze)
    result = fixture_result or ROOT / "data/runtime/g113-r3" / freeze["operation_id"]
    composition = sender.ExecutionComposition(
        rt.authority(fixture=fixture),
        fixture_pins if fixture else APPROVED_RELEASES,
        MODULES,
        interface(),
    )
    return sender.execute(
        environment="DEVELOPMENT",
        source_commit=source_commit,
        output=output,
        result_root=result,
        fixture_transport=fixture_transport,
        composition=composition,
    )
