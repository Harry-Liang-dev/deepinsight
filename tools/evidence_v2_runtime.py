"""Offline V2 projection on original current Memory and immutable SDK capture.

No live contract is registered here. A registry is a request-local projection,
not a Source registry, a scientific validator, or an authorization credential.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_v2.mechanism import FixedClaim, consume
from evidence_v2.prepare import leaf_locator, load
from evidence_v2.registry import Access, Registry, build_registry
from src.memory.delivery import MemoryDelivery
from src.schemas.research_v2_shared import canonical, digest
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools import h2_inputs as legacy
from tools.g107_matrix import strict_object
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT
from tools.g113_r2_memory import bind_current, recheck

VERSION = "EVIDENCE_V2_CURRENT_AUTHORITY_ADAPTER_V1"
INTAKE = ROOT / "artifacts/evidence-v2/intake/w3"
W3_SOURCE = "501aec9f909adb1f0c0021358faeba8cd82587c7"
W3_MANIFEST = "ce90d4fbe7051f5a064d2b6f68a0d4756f2fd36c27a95c8c960d4551fc1daf09"
CUTOFF = "2026-10-30T18:40:22.704289+00:00"
SCOPE = "ASSET:US:MSFT"
RELEASE_CONTRACT = "EVIDENCE_V2_PROSPECTIVE_EXPERIMENT_NOT_REGISTERED"


def verify_intake() -> None:
    """Check imported Git-sealed bytes and exact unmodified W3 runtime modules."""
    raw = (INTAKE / "EVIDENCE_MANIFEST.json").read_bytes()
    manifest = json.loads(raw)
    if blob_hash(raw) != W3_MANIFEST or manifest["source_commit"] != W3_SOURCE:
        raise ValueError("V2_W3_MANIFEST_DRIFT")
    for entry in manifest["files"]:
        path = INTAKE / entry["path"]
        required = entry["path"].startswith(
            ("evidence_v2/", "v2-evidence/", "v2-registry-freeze/")
        ) or entry["path"] in {
            "V2_INPUT_IDENTITY_VERIFICATION.json",
            "V2_RETAINED_TOOL_PIN.json",
            "W1_EVIDENCE_V2_RUNTIME_HANDOFF.json",
            "SEMANTIC_CLAIM_PROPOSAL_CONTRACT.json",
        }
        if required and (
            not path.is_file() or blob_hash(path.read_bytes()) != entry["sha256"]
        ):
            raise ValueError("V2_INTAKE_MEMBER_DRIFT")
    for name in (
        "__init__.py",
        "models.py",
        "registry.py",
        "mechanism.py",
        "prepare.py",
    ):
        if (ROOT / "evidence_v2" / name).read_bytes() != (
            INTAKE / "evidence_v2" / name
        ).read_bytes():
            raise ValueError("V2_W3_MODULE_DRIFT")


def catalog_for(case: str) -> TaskCatalog:
    """Reuse the original exact source projection; version only internal purpose."""
    parent = legacy.catalog_for(
        ROOT, {"sample_id": case, "role": "fundamental_analyst"}
    )
    data = parent.data()
    data["evidence_v2_runtime"] = {"version": VERSION, "case": case, "live": False}
    return TaskCatalog(canonical(data).decode(), parent.source_texts_json)


def fixed(case: str) -> tuple[Registry, dict[str, Any], FixedClaim]:
    """Bind the complete original claim, never a model-authored interpretation."""
    verify_intake()
    registry, packet = load(INTAKE, case)
    original = legacy.checked(ROOT, case, "MODEL_INPUT.json")
    if (
        INTAKE / "v2-evidence/cases" / case / "MODEL_INPUT.json"
    ).read_bytes() != original:
        raise ValueError("V2_ORIGINAL_COMPLETE_INPUT_DRIFT")
    legacy.claim_span(case, packet)
    claim = FixedClaim(
        case,
        packet["target"]["statement"],
        canonical(packet["target"]).decode(),
        blob_hash(original),
    )
    return registry, packet, claim


def prepare_offline_receiver(
    runtime: dev.DevelopmentRuntime, output: Path, case: str, operation: str
) -> dict[str, Any]:
    """Install a new offline-only read receiver through the original ACL journal."""
    if not operation.startswith("EVIDENCE-V2-OFFLINE-"):
        raise ValueError("V2_OFFLINE_OPERATION_ONLY")
    registry, _, claim = fixed(case)
    catalog = catalog_for(case)
    created = datetime.now(UTC)
    task, invocation = operation + ":task:" + case, operation + ":invocation:" + case
    memory = runtime.receiver(
        "fundamental_analyst", datetime.fromisoformat(CUTOFF), task, invocation, created
    )
    candidate, binding = bind_current(
        memory, catalog, MemoryDelivery.model_validate_json(dev.TEMPLATE.read_bytes())
    )
    access = digest(memory.access)
    receipt = recheck(memory, candidate, catalog, access)
    folder = output / case
    folder.mkdir(parents=True, exist_ok=False)
    for name, value in {
        "W6_DELIVERY.json": candidate.model_dump(mode="json"),
        "RECEIVING_EPISODE_CANDIDATE.json": memory.ep.model_dump(mode="json"),
        "CURRENT_AUTHORITY.json": receipt,
        "DEPENDENCY_BINDING.json": binding,
    }.items():
        durable(folder / name, canonical(value))
    row = dict(
        sample_id=case,
        slot=case,
        role="fundamental_analyst",
        operational_task_id=task,
        invocation_candidate_id=invocation,
        episode_candidate_id=memory.ep.episode_id,
        access_identity=access,
        registry_identity=registry.identity,
        claim_fingerprint=claim.fingerprint,
        semantic_task_identity=catalog.identity,
        purpose="OFFLINE_INTEGRATION_NOT_SEND_AUTHORIZATION",
    )
    durable(folder / "RECEIVER.json", canonical(row))
    return row


class CurrentAccessChecker:
    """Trusted composition only; no API accepts caller-authored permission JSON."""

    def __init__(
        self, runtime: dev.DevelopmentRuntime, output: Path, row: dict[str, Any]
    ) -> None:
        """Bind an installed receiver and exact original catalog/claim/registry."""
        self.runtime, self.output = runtime, output
        self.row = json.loads(canonical(row))
        operation, separator, case = row["operational_task_id"].rpartition(":task:")
        if (
            not separator
            or not operation.startswith("EVIDENCE-V2-OFFLINE-")
            or case != row["sample_id"]
            or row["invocation_candidate_id"] != operation + ":invocation:" + case
        ):
            raise ValueError("V2_OPERATION_CLAIM_RECEIVER_MISMATCH")
        self.registry, self.packet, self.claim = fixed(row["sample_id"])
        self.catalog = catalog_for(row["sample_id"])
        if (
            row["registry_identity"] != self.registry.identity
            or row["claim_fingerprint"] != self.claim.fingerprint
            or row["semantic_task_identity"] != self.catalog.identity
        ):
            raise ValueError("V2_RECEIVER_CONTENT_DRIFT")
        if runtime.record["authorization"] != dev.V2_AUTHORIZATION:
            raise ValueError("V2_OLD_AUTHORITY_NOT_APPLICABLE")
        self.checked_at = datetime.now(UTC).isoformat()
        self.receipts: list[dict[str, Any]] = []
        self.authority_failure: str | None = None

    def check(self, registry_id: str, scope: str, at: str) -> Access:
        """Preserve current-authority failure separately from content rejection."""
        if self.authority_failure is not None:
            raise ValueError("V2_AUTHORITY_FAILURE_LATCHED")
        try:
            return self._check(registry_id, scope, at)
        except Exception as exc:
            self.authority_failure = sender.binding_error(exc)
            raise

    def _check(self, registry_id: str, scope: str, at: str) -> Access:
        """Reopen actual store, requery ACL/CAS/F01, and rebuild trusted registry."""
        if (
            registry_id != self.registry.identity
            or scope != SCOPE
            or at != self.checked_at
        ):
            raise ValueError("V2_CHECK_CONTEXT_MISMATCH")
        verify_intake()
        memory, _, receipt = sender.current_memory(
            ROOT, self.output, self.row, self.runtime.authority(), catalog=self.catalog
        )
        # Original current_memory verifies every Observation support, current
        # grants, versions, relations, clocks, raw source bytes and checkpoints.
        # Reconstruct the W3 registry using current resolved raw source bytes.
        texts = json.loads(self.catalog.source_texts_json)
        documents = {sid: (raw, texts[sid]) for sid, raw in memory.raws.items()}
        pin = json.loads((INTAKE / "V2_RETAINED_TOOL_PIN.json").read_bytes())["sha256"]
        rebuilt = build_registry(
            self.packet,
            documents,
            leaf_locator(INTAKE / "v2-evidence/methods/w5_text_diagnostics.py", pin),
            self.catalog.data()["views"],
        )
        if rebuilt.identity != registry_id:
            raise ValueError("V2_CURRENT_REGISTRY_DRIFT")
        self.receipts.append(receipt)
        # This is a synchronous resolution receipt, not a reusable future grant.
        return Access(
            registry_id,
            scope,
            at,
            at,
            tuple(
                (k, "PASS")
                for k in ("F01", "ACL", "TTL", "CAS", "REVOCATION", "SOURCE_VERSION")
            ),
            digest(receipt),
            VERSION + ":NOT_DISPATCH_AUTHORIZATION",
        )


@dataclass(frozen=True)
class CaptureBinding:
    """Code-owned closure over a future frozen request, never model authority."""

    request_sha256: str
    operation_id: str
    attempt_id: str
    registry_identity: str
    claim_fingerprint: str
    engineering_fixture: bool


def verify_capture(
    target: Path, checker: CurrentAccessChecker, binding: CaptureBinding
) -> bytes:
    """Authenticate original HTTP, Assistant, identity and Meter before parsing."""
    # Fail before reading model content when trusted context was substituted.
    if (
        binding.registry_identity != checker.registry.identity
        or binding.claim_fingerprint != checker.claim.fingerprint
    ):
        raise ValueError("V2_CAPTURE_CONTEXT_DRIFT")
    return verify_capture_identity(target, checker.row, binding)


def verify_capture_identity(
    target: Path, row: dict[str, Any], binding: CaptureBinding
) -> bytes:
    """Original raw/Meter integrity check, also usable for a non-Memory probe."""
    identity = strict_object((target / "identity.json").read_text())
    http = strict_object((target / "http.json").read_text())
    entity = (target / "response.raw").read_bytes()
    response = strict_object(entity.decode("utf-8", errors="strict"))
    assistant = (target / "assistant.txt").read_bytes()
    text = "".join(
        p["text"]
        for o in response.get("output", [])
        if o.get("type") == "message"
        for p in o.get("content", [])
        if p.get("type") == "output_text"
    )
    usage = response.get("usage", {})
    settlement = strict_object((target / "usage.json").read_text())
    if (
        binding.operation_id
        != row.get(
            "execution_operation_id",
            row["operational_task_id"].rpartition(":task:")[0],
        )
        or identity["EvaluationEpisodeID"] != row["episode_candidate_id"]
        or identity.get("invocation_candidate_id") != row["invocation_candidate_id"]
        or identity.get("sample_id") != row["sample_id"]
        or identity["OperationID"] != binding.operation_id
        or identity["AttemptID"] != binding.attempt_id
        or identity["engineering_fixture"] != binding.engineering_fixture
        or blob_hash((target / "request.raw").read_bytes()) != binding.request_sha256
        or http["response_sha256"] != blob_hash(entity)
        or http["http_status"] != 200
        or response.get("model") != "qwen3.8-flash"
        or response.get("status") not in {"completed", "incomplete"}
        or text.encode() != assistant
        or not all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("input_tokens", "output_tokens", "total_tokens")
        )
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
        or any(
            settlement.get(k) != usage[k]
            for k in ("input_tokens", "output_tokens", "total_tokens")
        )
        or settlement.get("actual_resolved_model") != response["model"]
        or settlement.get("response_id") != response.get("id")
    ):
        raise ValueError("V2_POST_CAPTURE_INTEGRITY_STOP_REMAINING")
    return assistant


def consume_archived(
    target: Path, checker: CurrentAccessChecker, binding: CaptureBinding
) -> dict[str, Any]:
    """Consume only already-captured HTTP/text; never repair or infer support."""
    assistant = verify_capture(target, checker, binding)
    result = consume(
        assistant,
        target / "evidence-v2-diagnostic",
        (checker.claim,),
        checker.registry,
        checker,
        submission_context_registry_id=binding.registry_identity,
        checked_at=checker.checked_at,
        research_as_of=CUTOFF,
        scope=SCOPE,
    )
    durable(target / "V2_CURRENT_AUTHORITY_RECHECKS.json", canonical(checker.receipts))
    result["authority_failure"] = checker.authority_failure
    result["system_stop_required"] = checker.authority_failure is not None
    result["semantic_acceptance"] = "NOT_PERFORMED_REQUIRES_FULL_CLAIM_REVIEW"
    result["scientific_admission"] = False
    result["formal_numeric_admission"] = False
    result["new_live_release_authorized"] = False
    durable(target / "V2_ADAPTER_RESULT.json", canonical(result))
    return result


def archived_handler(
    checker: CurrentAccessChecker, binding: CaptureBinding
) -> Callable[[Path, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Adapt to the original ResearchInterface.archived_diagnostic callback.

    The existing sender owns network, pins, exclusive operation and Meter.
    This hook only consumes its archived result; it cannot dispatch a request.
    """

    def handler(
        target: Path, row: dict[str, Any], outcome: dict[str, Any]
    ) -> dict[str, Any]:
        del row
        try:
            if not outcome.get("response_received") or not outcome.get("usage_known"):
                raise ValueError("V2_NO_RELIABLE_CAPTURE")
            result = consume_archived(target, checker, binding)
            if result["system_stop_required"]:
                raise ValueError("V2_CURRENT_AUTHORITY_FAILED_AFTER_CAPTURE")
            result["candidate_predictions"] = [
                {
                    "claim_id": item["application"]["original_claim"]["claim_id"],
                    "model_declared": item["application"]["semantic_prediction"],
                    "technical_candidate": (
                        item["application"]["semantic_prediction"]
                        if not item["application"]["technical_or_consistency_blockers"]
                        else None
                    ),
                    "semantic_acceptance": None,
                }
                for item in result["items"]
                if "application" in item
            ]
            if not result["task_complete"]:
                outcome["status"] = "CONTENT_OR_SCHEMA_FAILURE"
        except Exception as exc:
            result = dict(
                error=sender.binding_error(exc),
                semantic_prediction=None,
                scientific_admission=False,
                system_stop_required=True,
            )
            outcome.update(
                status="SYSTEM_FAILURE",
                stop_remaining=True,
                stop_reason="V2_POST_CAPTURE_OR_CURRENT_AUTHORITY_FAILURE",
            )
        durable(target / "V2_SENDER_HOOK_RESULT.json", canonical(result))
        return result

    return handler
