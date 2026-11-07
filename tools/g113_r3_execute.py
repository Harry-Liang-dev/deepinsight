"""Candidate development composition of the original sample engine; no new gateway.

Live release pins and the authoritative Memory composition are deliberately unset.
A JSON PASS or a copied readset cannot activate this entry point. Installation of
real independently verified release pins is a later, explicit release binding.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.memory.delivery import MemoryDelivery
from src.memory.vnext import MemoryAccessContext
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_v2_shared import canonical, digest
from src.services.development_model_profile import (
    QWEN38_DEVELOPMENT_PROFILE,
    ModelExecutionProfile,
)
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g107_matrix as engine
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT, compose
from tools.g113_r1_contract import validate_output
from tools.g113_r1_prepare import candidate_call
from tools.g113_r2_freeze import freeze_requests, read, verify_frozen_bytes
from tools.g113_r2_memory import ReceivingMemory, bind_current, recheck

ART = ROOT / "artifacts/g113-r3"
RUNTIME = (
    *engine.MODULES,
    "tools/g113_r3_execute.py",
    "tools/g113_r2_freeze.py",
    "tools/g113_r2_memory.py",
    "tools/g113_r1_delivery.py",
)


@dataclass(frozen=True)
class ReviewPin:
    """Composition-root pinned independent issuance; not model/caller approval JSON."""

    issuer: str
    directory: Path
    receipt_path: str
    receipt_sha256: str
    manifest_path: str
    manifest_sha256: str
    engineering_fixture: bool = False
    git_repository: Path | None = None
    issuance_commit: str | None = None


@dataclass(frozen=True)
class MemoryAuthority:
    """Active store and current ACL resolver supplied by trusted composition."""

    root: Path
    access: Callable[[dict[str, Any], ResearchEpisode], MemoryAccessContext]
    engineering_fixture: bool = False
    validate_root: Callable[[Path], None] | None = None


@dataclass(frozen=True)
class ResearchInterface:
    """Trusted versioned task/checker injection, never model-supplied callbacks."""

    version: str
    catalog: Callable[[Path, dict[str, Any]], TaskCatalog]
    verify_freeze: Callable[[Path, Path, dict[str, Any]], None]
    call: Callable[[TaskCatalog, str], LLMProviderCall]
    diagnostic: Callable[[str, dict[str, Any], LLMProviderCall], dict[str, Any]]
    archived_diagnostic: (
        Callable[[Path, dict[str, Any], dict[str, Any]], dict[str, Any]] | None
    ) = None


@dataclass(frozen=True)
class ExecutionComposition:
    """Trusted Python composition, never deserialized from a business request."""

    authority: MemoryAuthority
    pins: tuple[ReviewPin, ...]
    additional_modules: tuple[str, ...] = ()
    interface: ResearchInterface | None = None
    release_contract: str = "LEGACY_FOUR_SLOT"
    model_profile: ModelExecutionProfile | None = None


# No genuine new W4/W5 issuance or authoritative live-store installation exists
# at candidate preparation time. There is no CLI/JSON override for these pins.
APPROVED_RELEASES: tuple[ReviewPin, ...] = ()
LIVE_MEMORY: MemoryAuthority | None = None


def runtime(root: Path) -> dict[str, str]:
    """Bind actual original transport/SDK/meter and the small R3 composition."""
    return {p: blob_hash((root / p).read_bytes()) for p in RUNTIME}


def copy_current_delivery(root: Path, output: Path) -> None:
    """Copy only exact manifest-listed actual storage from repaired W6 source."""
    base = root / "artifacts/g113-r3/intake/w6"
    raw = (base / "SOURCE_MANIFEST.json").read_bytes()
    if (
        blob_hash(raw)
        != "dad9ab2d85ae920222476d281a7cc55043c0969c61ce258e2f21ca799ac62ae8"
    ):
        raise ValueError("R3_W6_MANIFEST")
    prefix = "artifacts/g113-r3/release/actual/storage/"
    members = [e for e in json.loads(raw)["files"] if e["path"].startswith(prefix)]
    for entry in members:
        if blob_hash((base / entry["path"]).read_bytes()) != entry["sha256"]:
            raise ValueError("R3_W6_STORAGE_IDENTITY")
    template = "artifacts/g113-r3/release/actual/DELIVERY.json"
    expected = next(
        e["sha256"] for e in json.loads(raw)["files"] if e["path"] == template
    )
    if blob_hash((base / template).read_bytes()) != expected:
        raise ValueError("R3_W6_TEMPLATE_IDENTITY")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base / prefix, output / "storage")


def prepare(root: Path, output: Path) -> dict[str, Any]:
    """Reuse freeze with new operational identities and dependency version."""
    original = freeze_requests(
        root,
        output,
        operation_prefix="G113-R3-FREEZE",
        copy_store=copy_current_delivery,
        template_path=root
        / "artifacts/g113-r3/intake/w6/artifacts/g113-r3/release/actual/DELIVERY.json",
    )
    prior = read(root / "artifacts/g113-r2/G113_R2_EXECUTION_FREEZE.json")
    if original["request_sha256s"] != prior["request_sha256s"]:
        raise ValueError("R3_TASK_INPUT_CHANGE_REQUIRES_W3")
    result = dict(
        original,
        schema="G113_R3_FINAL_EXECUTION_FREEZE_V1",
        W1_parent_source="3627a204c65c0c101126b3579ff6216e156bd38e",
        W6_repaired_source="0fdbd136f97336008811ee20e24418f3e24b49d2",
        W6_manifest_sha256="dad9ab2d85ae920222476d281a7cc55043c0969c61ce258e2f21ca799ac62ae8",
        sender_runtime=runtime(root),
        source_commit_ref="../SOURCE_MANIFEST.json#/source_commit",
        prior_request_content_preserved=True,
        old_acceptance_transferred=False,
        status="OFFLINE_CANDIDATE_PENDING_W4_W5_AND_LIVE_MEMORY_BINDING",
    )
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(result))
    return result


def require_review(
    pin: ReviewPin,
    freeze: dict[str, Any],
    source_commit: str,
    *,
    fixture: bool,
    release_contract: str = "LEGACY_FOUR_SLOT",
) -> dict[str, Any]:
    """Check pinned issuance bytes, population, scope and chronology."""
    if release_contract not in {
        "LEGACY_FOUR_SLOT",
        "G113_R7_EIGHT_SLOT_V1",
        "G113_R8_FOUR_SLOT_V1",
        "G113_R9_FOUR_SLOT_V1",
        "H2_FIXED12_DEVELOPMENT_V1",
        "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1",
        "MINIMAL2_TWO_PROBE_V1",
        "RESEARCH_EVAL_CAMPAIGN_V1",
    }:
        raise ValueError("R7_UNREGISTERED_RELEASE_CONTRACT")
    if pin.engineering_fixture != fixture:
        raise ValueError("R3_REVIEW_PROVENANCE_MODE")
    if pin.issuer not in {"W4", "W5"}:
        raise ValueError("R3_REVIEW_ISSUER")
    raw = (pin.directory / pin.receipt_path).read_bytes()
    manifest_raw = (pin.directory / pin.manifest_path).read_bytes()
    if (
        blob_hash(raw) != pin.receipt_sha256
        or blob_hash(manifest_raw) != pin.manifest_sha256
    ):
        raise ValueError("R3_REVIEW_PIN_IDENTITY")
    if not fixture:
        if pin.git_repository is None or pin.issuance_commit is None:
            raise ValueError("R3_REVIEW_ISSUANCE_NOT_PINNED")
        # A separately installed, provenance-verified issuer pin is mandatory.
        # Ordinary caller JSON cannot supply the code-owned pin configuration.
        for relative, expected in (
            (pin.receipt_path, raw),
            (pin.manifest_path, manifest_raw),
        ):
            stored = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(pin.git_repository),
                    "show",
                    pin.issuance_commit + ":" + relative,
                ]
            )
            if stored != expected:
                raise ValueError("R3_REVIEW_ISSUANCE_BYTES")
    receipt = json.loads(raw)
    manifest = json.loads(manifest_raw)
    for member in manifest["files"]:
        path = (pin.directory / member["path"]).resolve()
        if not path.is_relative_to(pin.directory.resolve()):
            raise ValueError("R3_REVIEW_MEMBER_PATH")
        if blob_hash(path.read_bytes()) != member["sha256"]:
            raise ValueError("R3_REVIEW_MEMBER_CHANGED")
    if not any(
        x["path"] == pin.receipt_path and x["sha256"] == pin.receipt_sha256
        for x in manifest["files"]
    ):
        raise ValueError("R3_REVIEW_RECEIPT_NOT_IN_MANIFEST")
    if receipt["issuer"] != pin.issuer or receipt["status"] != "PASS":
        raise ValueError("R3_REVIEW_NOT_ACCEPTED")
    if receipt["source_commit"] != source_commit:
        raise ValueError("R3_REVIEW_SOURCE")
    for key in ("population_identity", "request_sha256s", "schema_identities"):
        if receipt.get(key) != freeze[key]:
            raise ValueError("R3_REVIEW_POPULATION_OR_REQUEST")
    if receipt.get("freeze_sha256") != blob_hash(canonical(freeze)):
        raise ValueError("R3_REVIEW_FREEZE_IDENTITY")
    issued = datetime.fromisoformat(receipt["issued_at"])
    if issued.tzinfo is None or not datetime.fromisoformat(
        freeze["created_at"]
    ) <= issued <= datetime.now(UTC):
        raise ValueError("R3_REVIEW_CHRONOLOGY")
    required = (
        "F01_AND_CURRENT_MEMORY_AND_SENDER"
        if pin.issuer == "W4"
        else "FOUR_SLOT_HISTORICAL_FULL_DELTA"
    )
    count = 4
    if release_contract == "G113_R7_EIGHT_SLOT_V1":
        count = 8
        required = (
            "R7_QWEN38_CURRENT_MEMORY_AND_SENDER"
            if pin.issuer == "W4"
            else "R7_EIGHT_SLOT_MODEL_AND_PROMPT_COMPARISON"
        )
        if freeze.get("model") != "qwen3.8-flash" or freeze.get("planned_samples") != 8:
            raise ValueError("R7_RELEASE_MODEL_POPULATION")
    if release_contract in {"G113_R8_FOUR_SLOT_V1", "G113_R9_FOUR_SLOT_V1"}:
        revision = "R9" if release_contract == "G113_R9_FOUR_SLOT_V1" else "R8"
        required = (
            f"{revision}_QWEN38_CURRENT_MEMORY_AND_SENDER"
            if pin.issuer == "W4"
            else f"{revision}_FOUR_SLOT_FINAL_TASK_RESEARCH"
        )
        if (
            freeze.get("model") != "qwen3.8-flash"
            or freeze.get("planned_samples") != 4
            or tuple(r["sample_id"] for r in freeze["slots"])
            != ("B1", "B2", "B3", "B4")
            or receipt.get("release_contract") != release_contract
            or receipt.get("operation_id") != freeze["operation_id"]
            or receipt.get("development_instance") != freeze["development_instance"]
        ):
            raise ValueError("R8_RELEASE_MODEL_POPULATION_AUTHORITY")
    if release_contract == "H2_FIXED12_DEVELOPMENT_V1":
        count = 12
        required = (
            "H2_FIXED12_CURRENT_MEMORY_AND_SENDER"
            if pin.issuer == "W4"
            else "H2_FIXED12_DEVELOPMENT_EXECUTION_BINDING"
        )
        if (
            freeze.get("model") != "qwen3.8-flash"
            or freeze.get("planned_samples") != 12
            or tuple(r["sample_id"] for r in freeze["slots"])
            != tuple(f"H2-C{i:03}" for i in range(1, 13))
            or receipt.get("release_contract") != release_contract
            or receipt.get("operation_id") != freeze["operation_id"]
            or receipt.get("development_instance") != freeze["development_instance"]
        ):
            raise ValueError("H2_RELEASE_MODEL_POPULATION_AUTHORITY")
    if release_contract == "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1":
        from tools.evidence_v2_ab_inputs import DESIGN, W5_MANIFEST, ledger

        count = 24
        required = (
            "EVIDENCE_V2_AB_CURRENT_MEMORY_AND_SENDER"
            if pin.issuer == "W4"
            else "EVIDENCE_V2_AB_EXACT24_EXECUTION_BINDING"
        )
        if (
            freeze.get("model") != "qwen3.8-flash"
            or freeze.get("planned_samples") != 24
            or freeze.get("operation_id") != DESIGN + "-COORDINATOR"
            or freeze.get("arm_operations") != {a: DESIGN + "-" + a for a in ("A", "B")}
            or [r["sample_id"] for r in freeze["slots"]]
            != [r["sample_id"] for r in ledger()]
            or receipt.get("release_contract") != release_contract
            or any(
                receipt.get(k) != freeze[k]
                for k in ("operation_id", "arm_operations", "development_instance")
            )
            or receipt.get("W5_design_manifest") != W5_MANIFEST
            or receipt.get("bounded_unknown_context_policy")
            != "STOP_ON_PROVIDER_CAPACITY_REJECTION_NO_RETRY"
        ):
            raise ValueError("AB_RELEASE_MODEL_POPULATION_AUTHORITY")
    if release_contract == "MINIMAL2_TWO_PROBE_V1":
        from tools.minimal2_inputs import DESIGN_MANIFEST

        count = 2
        required = (
            "MINIMAL2_NATIVE_SCHEMA_AUTHORITY_AND_SENDER"
            if pin.issuer == "W4"
            else "MINIMAL2_EXACT_TWO_PROBE_EXECUTION_BINDING"
        )
        if (
            freeze.get("model") != "qwen3.8-flash"
            or freeze.get("planned_samples") != 2
            or [r["sample_id"] for r in freeze["slots"]]
            != ["MINIMAL2-PROBE-01", "MINIMAL2-PROBE-02"]
            or receipt.get("release_contract") != release_contract
            or any(
                receipt.get(k) != freeze[k]
                for k in ("operation_id", "development_instance", "technical_authority")
            )
            or receipt.get("W5_design_manifest") != DESIGN_MANIFEST
            or receipt.get("bounded_unknown_context_policy")
            != "STOP_ON_PROVIDER_CAPACITY_REJECTION_NO_RETRY"
        ):
            raise ValueError("MINIMAL2_RELEASE_SCOPE_OR_AUTHORITY")
    if release_contract == "RESEARCH_EVAL_CAMPAIGN_V1":
        from research_eval.models import TrustedExperimentCampaign, identity
        from research_eval.security import release_projection

        policy = TrustedExperimentCampaign.model_validate(freeze["campaign_policy"])
        count = policy.budget.max_samples
        required = (
            "EVAL_CAMPAIGN_RUNNER_SOURCE_AND_AUTHORITY"
            if pin.issuer == "W4"
            else "EVAL_CAMPAIGN_DATASET_AND_EVALUATOR_PROTOCOL"
        )
        if (
            freeze != release_projection(policy)
            or policy.source_commit != source_commit
            or receipt.get("release_contract") != release_contract
            or receipt.get("campaign_identity") != identity(policy)
            or receipt.get("campaign_policy") != policy.model_dump(mode="json")
            or receipt.get("operation_id") != policy.campaign_id
            or not policy.created_at <= datetime.now(UTC) < policy.expires_at
        ):
            raise ValueError("EVAL_CAMPAIGN_RELEASE_BOUNDARY")
    if receipt.get("scope") != required or receipt.get("planned_samples") != count:
        raise ValueError("R3_REVIEW_SCOPE")
    if not receipt.get("context_fit_unknown_acknowledged"):
        raise ValueError("R3_CONTEXT_UNCERTAINTY_NOT_REGISTERED")
    return dict(
        issuer=pin.issuer,
        receipt_sha256=pin.receipt_sha256,
        manifest_sha256=pin.manifest_sha256,
        issued_at=receipt["issued_at"],
        engineering_fixture=fixture,
    )


def reviews(
    pins: tuple[ReviewPin, ...],
    freeze: dict[str, Any],
    commit: str,
    *,
    fixture: bool,
    release_contract: str = "LEGACY_FOUR_SLOT",
) -> list[dict[str, Any]]:
    """Require both independent authorities; one cannot stand in for the other."""
    if len(pins) != 2 or {p.issuer for p in pins} != {"W4", "W5"}:
        raise ValueError("R3_W4_W5_RELEASE_PINS_NOT_INSTALLED")
    return [
        require_review(
            p, freeze, commit, fixture=fixture, release_contract=release_contract
        )
        for p in pins
    ]


def current_memory(
    root: Path,
    output: Path,
    row: dict[str, Any],
    authority: MemoryAuthority,
    *,
    catalog: TaskCatalog | None = None,
) -> tuple[ReceivingMemory, MemoryDelivery, dict[str, Any]]:
    """Read active authority in place; a copied DB is not current access."""
    if authority.validate_root is not None:
        authority.validate_root(authority.root)
    if not (authority.root / "storage/memory.duckdb").is_file():
        raise ValueError("R3_AUTHORITATIVE_MEMORY_STORE_MISSING")
    if not authority.engineering_fixture and authority.root.resolve().is_relative_to(
        root / "artifacts"
    ):
        raise ValueError("R3_ARCHIVE_IS_NOT_LIVE_MEMORY_AUTHORITY")
    folder = output / row["slot"]
    ep = ResearchEpisode.model_validate(
        read(folder / "RECEIVING_EPISODE_CANDIDATE.json")
    )
    # Source directories must already be present. Do not silently rehydrate a
    # missing current source from the historical archive at the send boundary.
    for sid in ("G105-GET-05", "G105-GET-09", "G105-GET-12"):
        if not (authority.root / "native" / sid / "session.json").is_file():
            raise ValueError("R3_CURRENT_NATIVE_SOURCE_MISSING")
    memory = ReceivingMemory(root, authority.root)
    memory.bind_receiver(ep, authority.access(row, ep), row["invocation_candidate_id"])
    if digest(memory.access) != row["access_identity"]:
        raise ValueError("R3_CURRENT_ACCESS_CHANGED_REFREEZE_REQUIRED")
    catalog = catalog or compose(root, row["role"], row["arm"])
    expected = MemoryDelivery.model_validate(read(folder / "W6_DELIVERY.json"))
    # The old envelope is not a credential in this active store. Build a new
    # checked delivery, then demand the exact frozen business dependency snapshot.
    candidate, binding = bind_current(memory, catalog, expected)
    if (
        candidate.checkpoint.memory_snapshot != expected.checkpoint.memory_snapshot
        or candidate.checkpoint.dependencies != expected.checkpoint.dependencies
    ):
        raise ValueError("R3_CURRENT_DEPENDENCIES_DRIFT")
    receipt = recheck(memory, candidate, catalog, row["access_identity"])
    receipt["current_binding"] = binding
    receipt["authority_database"] = str(memory.journal.database_path)
    return memory, candidate, receipt


def diagnose(text: str, row: dict[str, Any], call: LLMProviderCall) -> dict[str, Any]:
    """Keep malformed output unchanged; mechanical validity never proves research."""
    del call
    try:
        result = validate_output(text, compose(ROOT, row["role"], row["arm"]))
        return dict(
            schema_valid=True,
            binding=result,
            actually_consumed="PENDING_W5",
            applied="PENDING_W5",
            scientific_admission=False,
        )
    except Exception as exc:
        return dict(
            schema_valid=False,
            error_type=type(exc).__name__,
            diagnostic=str(exc),
            scientific_admission=False,
        )


def binding_error(exc: Exception) -> str:
    """Archive only known-shaped local gate codes, never arbitrary SDK messages."""
    code = str(exc).split(":", 1)[0]
    return (
        code
        if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code)
        else "UNCLASSIFIED_BINDING_FAILURE"
    )


def execute(
    *,
    environment: str,
    source_commit: str,
    output: Path,
    result_root: Path,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[ReviewPin, ...] = (),
    fixture_memory: MemoryAuthority | None = None,
    composition: ExecutionComposition | None = None,
) -> dict[str, Any]:
    """Original serial engine with independent-release and current ACL gates."""
    fixture = fixture_transport is not None
    if environment != "DEVELOPMENT":
        raise ValueError("R3_DEVELOPMENT_ONLY")
    if fixture and type(fixture_transport) is not httpx.MockTransport:
        raise ValueError("R3_FIXTURE_TRANSPORT_TYPE")
    if not fixture and (fixture_pins or fixture_memory is not None):
        raise ValueError("R3_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    # One durable archive per frozen operation: a different CLI path is not
    # permission to repeat the same reviewed population or reuse Attempt IDs.
    expected_root = ROOT / "data/runtime/g113-r3" / freeze["operation_id"]
    if not fixture and result_root.resolve() != expected_root.resolve():
        raise ValueError("R3_LIVE_ARCHIVE_NOT_OPERATION_BOUND")
    if composition is not None and (fixture_pins or fixture_memory is not None):
        raise ValueError("R5_MIXED_COMPOSITION")
    pins = (
        composition.pins
        if composition
        else (fixture_pins if fixture else APPROVED_RELEASES)
    )
    release_contract = (
        composition.release_contract if composition else "LEGACY_FOUR_SLOT"
    )
    model_profile = composition.model_profile if composition else None
    if (
        release_contract
        in {
            "G113_R7_EIGHT_SLOT_V1",
            "G113_R8_FOUR_SLOT_V1",
            "G113_R9_FOUR_SLOT_V1",
            "H2_FIXED12_DEVELOPMENT_V1",
            "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1",
        }
        and model_profile is not QWEN38_DEVELOPMENT_PROFILE
    ):
        raise ValueError("R7_RELEASE_MODEL_PROFILE")
    if model_profile is not None and release_contract not in {
        "G113_R7_EIGHT_SLOT_V1",
        "G113_R8_FOUR_SLOT_V1",
        "G113_R9_FOUR_SLOT_V1",
        "H2_FIXED12_DEVELOPMENT_V1",
        "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1",
    }:
        raise ValueError("R7_PROFILE_REQUIRES_NEW_RELEASE")
    proof = reviews(
        pins, freeze, source_commit, fixture=fixture, release_contract=release_contract
    )
    authority = (
        composition.authority
        if composition
        else (fixture_memory if fixture else LIVE_MEMORY)
    )
    if authority is None or authority.engineering_fixture != fixture:
        raise ValueError("R3_CURRENT_MEMORY_AUTHORITY_NOT_INSTALLED")

    def actual_runtime() -> dict[str, str]:
        modules = composition.additional_modules if composition else ()
        return {
            **runtime(ROOT),
            **{p: blob_hash((ROOT / p).read_bytes()) for p in modules},
        }

    interface = composition.interface if composition else None
    if interface is not None and freeze.get("interface") != interface.version:
        raise ValueError("R6_EXECUTION_INTERFACE_IDENTITY")
    verify = interface.verify_freeze if interface else verify_frozen_bytes
    verify(ROOT, output, freeze)
    if freeze["sender_runtime"] != actual_runtime():
        raise ValueError("R3_RUNTIME_DRIFT")
    if not fixture:
        for path, sha in freeze["sender_runtime"].items():
            raw = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", source_commit + ":" + path]
            )
            if blob_hash(raw) != sha:
                raise ValueError("R3_EXECUTION_SOURCE_IDENTITY")
    result_root.mkdir(parents=True, exist_ok=False)
    paired = release_contract == "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1"
    arm_roots: dict[str, Path] = {}
    if paired:
        for arm, op in freeze["arm_operations"].items():
            path = (
                result_root / ("arm-" + arm) if fixture else expected_root.parent / op
            )
            path.mkdir(parents=True, exist_ok=False)
            arm_roots[arm] = path
            durable(
                path / "ARM_RESERVATION.json",
                canonical(
                    dict(
                        operation_id=op,
                        coordinator=str(result_root),
                        population_identity=freeze["population_identity"],
                        source_commit=source_commit,
                        engineering_fixture=fixture,
                    )
                ),
            )
    operation = freeze["operation_id"] + ":execution"
    durable(
        result_root / "PREDISPATCH.json",
        canonical(
            dict(
                operation=operation,
                source_commit=source_commit,
                reviews=proof,
                population_identity=freeze["population_identity"],
                engineering_fixture=fixture,
                created_at=datetime.now(UTC).isoformat(),
                w4_live_review="FIXTURE_ONLY" if fixture else "SCOPED_RELEASE_BOUND",
            )
        ),
    )
    outcomes, stop = [], None
    for ordinal, row in enumerate(freeze["slots"], 1):
        slot = dict(
            row,
            ordinal=ordinal,
            sample_id=(
                row["sample_id"]
                if release_contract
                in {
                    "G113_R7_EIGHT_SLOT_V1",
                    "G113_R8_FOUR_SLOT_V1",
                    "G113_R9_FOUR_SLOT_V1",
                    "H2_FIXED12_DEVELOPMENT_V1",
                    "EVIDENCE_V2_AB_PAIRED_DEVELOPMENT_V1",
                }
                else row["slot"]
            ),
            AttemptID=f"{operation}:{ordinal:02}:attempt1",
        )
        slot_operation = operation
        if paired:
            slot["ordinal"] = row["arm_ordinal"]
            slot_operation = freeze["arm_operations"][row["arm"]] + ":execution"
            slot["AttemptID"] = f"{slot_operation}:{row['arm_ordinal']:02}:attempt1"
            slot["execution_operation_id"] = slot_operation
        if stop:
            outcomes.append(
                dict(slot, status="NOT_ATTEMPTED", not_attempted_reason=stop)
            )
            continue
        target = (
            arm_roots[row["arm"]] / f"{row['arm_ordinal']:02}"
            if paired
            else result_root / f"{ordinal:02}"
        )
        try:
            catalog = (
                interface.catalog(ROOT, row)
                if interface
                else compose(ROOT, row["role"], row["arm"])
            )
            memory, candidate, initial = current_memory(
                ROOT, output, row, authority, catalog=catalog
            )
            durable(
                result_root / f"{ordinal:02}-current-memory.json", canonical(initial)
            )

            def loader(_: dict[str, Any]) -> tuple[bytes, LLMProviderCall]:
                folder = output / row["slot"]
                return (folder / "sdk-request.raw").read_bytes(), (
                    interface.call if interface else candidate_call
                )(catalog, (folder / "prompt.txt").read_text())

            def presend(request: httpx.Request) -> None:
                # Executed by the original SDK hook, before meter reservation/send.
                del request
                try:
                    reviews(
                        pins,
                        freeze,
                        source_commit,
                        fixture=fixture,
                        release_contract=release_contract,
                    )
                    verify(ROOT, output, freeze)
                    if freeze["sender_runtime"] != actual_runtime():
                        raise ValueError("R3_RUNTIME_DRIFT")
                    if authority.validate_root is not None:
                        authority.validate_root(memory.output)
                    current_access = authority.access(row, memory.ep)
                    memory.access = current_access
                    current = recheck(
                        memory, candidate, catalog, row["access_identity"]
                    )
                    durable(
                        target / "IMMEDIATE_PRESEND_MEMORY.json", canonical(current)
                    )
                except Exception as exc:
                    durable(
                        target / "PRESEND_DENIAL.json",
                        canonical(
                            dict(
                                error_type=type(exc).__name__,
                                error_code=binding_error(exc),
                            )
                        ),
                    )
                    raise

            result = engine.sample(
                slot,
                target,
                fixture_transport=fixture_transport,
                operation_id=slot_operation,
                episode_id=row["episode_candidate_id"],
                call_loader=loader,
                diagnostic=interface.diagnostic if interface else diagnose,
                before_send=presend,
                model_profile=model_profile,
            )
            if interface is not None and interface.archived_diagnostic is not None:
                result["archived_diagnostic"] = interface.archived_diagnostic(
                    target, slot, result
                )
        except Exception as exc:
            result = dict(
                slot,
                status="SYSTEM_FAILURE",
                stop_remaining=True,
                stop_reason="R3_BINDING_OR_ARCHIVE_FAILURE",
                error_type=type(exc).__name__,
                error_code=binding_error(exc),
                provider_attempts=int((target / "invocation.json").exists()),
                response_received=(target / "response.raw").exists(),
            )
            durable(result_root / f"{ordinal:02}-failure.json", canonical(result))
        outcomes.append(result)
        if result["stop_remaining"]:
            stop = result["stop_reason"]
        durable(result_root / f"PROGRESS-{ordinal:02}.json", canonical(outcomes))
        if paired:
            durable(
                arm_roots[row["arm"]] / f"PROGRESS-{row['arm_ordinal']:02}.json",
                canonical([o for o in outcomes if o["arm"] == row["arm"]]),
            )
    census = dict(
        samples=outcomes,
        planned_samples=freeze.get("planned_samples", 4),
        stop_reason=stop,
        engineering_fixture=fixture,
        actual_provider_attempts=(
            0 if fixture else sum(x.get("provider_attempts", 0) for x in outcomes)
        ),
        mock_http_attempts=(
            sum(x.get("provider_attempts", 0) for x in outcomes) if fixture else 0
        ),
        scientific_memory_writes=0,
        researchstate_writes=0,
        quant_writes=0,
        W5_evaluation="PENDING",
        actually_consumed="NOT_DEMONSTRATED",
        applied="NOT_DEMONSTRATED",
    )
    durable(result_root / "COHORT_CENSUS.json", canonical(census))
    if paired:
        for arm, path in arm_roots.items():
            durable(
                path / "COHORT_CENSUS.json",
                canonical(
                    dict(
                        operation_id=freeze["arm_operations"][arm],
                        planned_samples=12,
                        samples=[o for o in outcomes if o["arm"] == arm],
                        global_stop_reason=stop,
                        engineering_fixture=fixture,
                    )
                ),
            )
    return census


def main() -> int:
    """Explicit operator trigger; currently fails closed without real release pins."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=["DEVELOPMENT"])
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    result = execute(
        environment=args.environment,
        source_commit=args.source_commit,
        output=args.freeze,
        result_root=args.result_root,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
