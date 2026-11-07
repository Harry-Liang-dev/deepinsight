"""User-authorized G113 development replay; original Memory, ACL and sender only.

Installation is a local operational action, never a model-supplied permission.
It creates a new store from pinned W6 bytes and issues read-only, instance-bound
receivers under the current G113-R5 user instruction. Review pins remain absent.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from src.memory.temporal_delta import ObservedContent
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import Action, Scope
from src.models.enums import AgentName, ResearchScopeType
from src.repositories import DuckDBDatabase
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_v2_shared import canonical, digest
from src.services.native_preservation import blob_hash
from src.services.research_vnext.real_memory_meter import durable
from tools import g113_r3_execute as sender
from tools.g111_r1_msft import SOURCE_IDS
from tools.g113_r1_binding import ROOT
from tools.g113_r2_freeze import freeze_requests, read, verify_frozen_bytes
from tools.g113_r2_memory import ReceivingMemory, prospective_episode

ART = ROOT / "artifacts/g113-r5"
RUNTIME_PARENT = ROOT / "data/runtime/g113-r5"
MODULE = "tools/g113_r5_replay.py"
AUTHORIZATION = "G113-R5_CURRENT_USER_AUTHORIZED_DEVELOPMENT_REPLAY"
H2_AUTHORIZATION = "H2_CURRENT_USER_FIXED12_DEVELOPMENT_REPLAY"
V2_AUTHORIZATION = "EVIDENCE_V2_CURRENT_USER_OFFLINE_RUNTIME_INTEGRATION"
AB_AUTHORIZATION = "EVIDENCE_V2_CURRENT_USER_PAIRED_DEVELOPMENT_REPLAY"
MINIMAL2_AUTHORIZATION = "MINIMAL2_CURRENT_USER_TWO_PROBE_DEVELOPMENT"
CAMPAIGN_AUTHORIZATION = "CURRENT_USER_EXACT12_CAMPAIGN_RECEIVER_DEVELOPMENT_V1"
ROLES = ("fundamental_analyst", "news_event_analyst")
GRANTS = "g113-r5-receiver-grants"
INSTALLATION = "g113-r5-instance"
REVOKED = "g113-r5-revocations"
W6_BASE = ROOT / "artifacts/g113-r3/intake/w6"
TEMPLATE = W6_BASE / "artifacts/g113-r3/release/actual/DELIVERY.json"
# Genuine user-directed independent issuance must later be installed by trusted
# release composition. No CLI path or ordinary PASS JSON overrides these pins.
APPROVED_RELEASES: tuple[sender.ReviewPin, ...] = ()


class ReplayReadAccess(MemoryAccessContext):
    """Narrow the original G84 role capabilities to historical reads only."""

    def require(self, action: Action, scope: Scope) -> None:
        """Retain original ACL and reject write/proposal/scientific actions."""
        if action != "READ_HISTORY":
            raise ValueError("R5_READ_ONLY_PERMISSION")
        super().require(action, scope)


class NoChangeAuditAccess(MemoryAccessContext):
    """Internal reentry controller; no Specialist receives this audit capability."""

    def require(self, action: Action, scope: Scope) -> None:
        """Only original read/audit gate, with all original Scope checks."""
        if action not in {"READ_HISTORY", "APPEND_EVENT"}:
            raise ValueError("R5_NOCHANGE_AUDIT_ONLY")
        super().require(action, scope)


class NoChangeMemory(ReceivingMemory):
    """Reuse the original Delta algorithm but never admit a new fact."""

    def admit(self, c: ObservedContent) -> str:
        """A material change requires another task; cannot reseed this replay."""
        raise ValueError("R5_NOCHANGE_CANNOT_ADMIT_FACT")


def append(journal: MemoryJournalRepository, stream: str, body: Any) -> None:
    """Append audit using the existing ordered-snapshot CAS repository."""
    with journal.serialized():
        rows = journal.entries_with_sequence(stream)
        journal.append(
            stream,
            digest(body),
            canonical(body).decode(),
            len(rows),
            expected_snapshot=rows,
        )


def install(
    path: Path,
    *,
    authorization: str = AUTHORIZATION,
    campaign_registration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one explicit new development instance; never open W6 for writes."""
    if authorization not in {
        AUTHORIZATION,
        H2_AUTHORIZATION,
        V2_AUTHORIZATION,
        AB_AUTHORIZATION,
        MINIMAL2_AUTHORIZATION,
        CAMPAIGN_AUTHORIZATION,
    }:
        raise ValueError("UNREGISTERED_DEVELOPMENT_AUTHORITY")
    if authorization == CAMPAIGN_AUTHORIZATION:
        from research_eval.receivers import validate_registration

        validate_registration(campaign_registration)
    elif campaign_registration is not None:
        raise ValueError("CAMPAIGN_REGISTRATION_PURPOSE_MISMATCH")
    if path.exists() or path.is_symlink():
        raise ValueError("R5_INSTANCE_ALREADY_EXISTS")
    sender.copy_current_delivery(ROOT, path)
    copied = {
        str(p.relative_to(path)): blob_hash(p.read_bytes())
        for p in (path / "storage").rglob("*")
        if p.is_file()
    }
    # Original NativePreserver hydration copies pinned retained source bytes;
    # only this new instance can receive bootstrap and subsequent audit writes.
    memory = ReceivingMemory(ROOT, path)
    if len(memory.population()) != 27 or len(memory.id_map()) != 11:
        raise ValueError("R5_RETAINED_POPULATION")
    instance = "g113-dev-" + uuid4().hex
    db = path / "storage/memory.duckdb"
    stat = db.stat()
    body: dict[str, Any] = dict(
        schema="G113_AUTHORIZED_DEVELOPMENT_REPLAY_V1",
        instance_id=instance,
        authorization=authorization,
        created_at=datetime.now(UTC).isoformat(),
        environment="DEVELOPMENT",
        owner=(
            "campaign-development-reader:"
            if authorization == CAMPAIGN_AUTHORIZATION
            else (
                "h2-development-reader:"
                if authorization
                in {
                    H2_AUTHORIZATION,
                    V2_AUTHORIZATION,
                    AB_AUTHORIZATION,
                    MINIMAL2_AUTHORIZATION,
                    CAMPAIGN_AUTHORIZATION,
                }
                else "g113-r5-reader:"
            )
        )
        + instance,
        asset="US:MSFT",
        purpose=(
            "EXACT12_CLAIM_CAMPAIGN_READ_ONLY"
            if authorization == CAMPAIGN_AUTHORIZATION
            else (
                "MINIMAL2_TWO_PROBE_DEVELOPMENT"
                if authorization == MINIMAL2_AUTHORIZATION
                else (
                    "EVIDENCE_V2_PAIRED_DEVELOPMENT"
                    if authorization == AB_AUTHORIZATION
                    else (
                        "EVIDENCE_V2_OFFLINE_RUNTIME_INTEGRATION"
                        if authorization == V2_AUTHORIZATION
                        else (
                            "H2_FIXED_CLAIM_DEVELOPMENT_PILOT"
                            if authorization == H2_AUTHORIZATION
                            else "HISTORICAL_T0_T1_DIAGNOSTIC"
                        )
                    )
                )
            )
        ),
        root=str(path.resolve()),
        database=str(db.resolve()),
        device=stat.st_dev,
        inode=stat.st_ino,
        original_business_population_sha256=digest(memory.population()),
        original_msft_ids=memory.id_map(),
        history_scopes=[s.model_dump(mode="json") for s in memory.history_scopes],
        retained_copy_sha256=copied,
        source_commit="0fdbd136f97336008811ee20e24418f3e24b49d2",
        source_manifest_sha256="dad9ab2d85ae920222476d281a7cc55043c0969c61ce258e2f21ca799ac62ae8",
        allowed_roles=(
            ["fundamental_analyst"]
            if authorization
            in {
                H2_AUTHORIZATION,
                V2_AUTHORIZATION,
                AB_AUTHORIZATION,
                MINIMAL2_AUTHORIZATION,
                CAMPAIGN_AUTHORIZATION,
            }
            else list(ROLES)
        ),
        allowed_operations=["READ_HISTORY", "LOCAL_CONTROLLED_AUDIT"],
        scientific_memory=False,
        production_access=False,
        model_execution_authorized=False,
    )
    if authorization == CAMPAIGN_AUTHORIZATION:
        body["campaign_registration"] = campaign_registration
        body["authorization_origin"] = (
            "USER_CURRENT_CAMPAIGN_RECEIVER_FACTORY_INTEGRATION"
        )
    append(memory.journal, INSTALLATION, body)
    durable(path / "INSTANCE.json", canonical(body))
    return body


class DevelopmentRuntime:
    """Exact installed instance and current grants; archived access JSON is inert."""

    def __init__(
        self,
        path: Path,
        installation_sha256: str,
        expected_grants: dict[str, str] | None = None,
    ) -> None:
        """Open a specifically pinned instance without initialization fallback."""
        self.path = path.resolve()
        raw = (self.path / "INSTANCE.json").read_bytes()
        if blob_hash(raw) != installation_sha256:
            raise ValueError("R5_INSTALLATION_IDENTITY")
        self.installation_sha256 = installation_sha256
        self.expected_grants = expected_grants
        self.record = json.loads(raw)
        self.journal = MemoryJournalRepository(
            DuckDBDatabase(self.path / "storage/memory.duckdb")
        )
        self.check_root(path)

    def check_root(self, path: Path) -> None:
        """Deny path substitution, another DB, modified contract or revocation."""
        b = self.record
        db = self.path / "storage/memory.duckdb"
        if (
            path.resolve() != self.path
            or str(self.path) != b["root"]
            or str(db.resolve()) != b["database"]
            or db.is_symlink()
            or (db.stat().st_dev, db.stat().st_ino) != (b["device"], b["inode"])
            or blob_hash((self.path / "INSTANCE.json").read_bytes())
            != self.installation_sha256
            or b["authorization"]
            not in {
                AUTHORIZATION,
                H2_AUTHORIZATION,
                V2_AUTHORIZATION,
                AB_AUTHORIZATION,
                MINIMAL2_AUTHORIZATION,
                CAMPAIGN_AUTHORIZATION,
            }
            or b["asset"] != "US:MSFT"
            or b["allowed_roles"]
            != (
                ["fundamental_analyst"]
                if b["authorization"]
                in {
                    H2_AUTHORIZATION,
                    V2_AUTHORIZATION,
                    AB_AUTHORIZATION,
                    MINIMAL2_AUTHORIZATION,
                    CAMPAIGN_AUTHORIZATION,
                }
                else list(ROLES)
            )
        ):
            raise ValueError("R5_INSTANCE_SCOPE_IDENTITY")
        if self.journal.entries(INSTALLATION) != ((digest(b), canonical(b).decode()),):
            raise ValueError("R5_INSTALLATION_JOURNAL")
        if (
            self.expected_grants is not None
            and {k: blob_hash(raw.encode()) for k, raw in self.journal.entries(GRANTS)}
            != self.expected_grants
        ):
            raise ValueError("R5_GRANT_DEPENDENCY_DRIFT")
        if b["authorization"] == CAMPAIGN_AUTHORIZATION:
            from research_eval.receivers import validate_registration

            validate_registration(b.get("campaign_registration"))
        for sid in SOURCE_IDS:
            if not (self.path / "native" / sid / "session.json").is_file():
                raise ValueError("R5_NATIVE_SOURCE_MISSING")
        if any(
            json.loads(raw).get("instance_id") == b["instance_id"]
            for _, raw in self.journal.entries(REVOKED)
        ):
            raise ValueError("R5_INSTANCE_REVOKED")

    def receiver(
        self, role: str, cutoff: datetime, task: str, invocation: str, created: datetime
    ) -> ReceivingMemory:
        """Install the current user-authorized receiver, without changing facts."""
        self.check_root(self.path)
        if role not in self.record["allowed_roles"] or not task.startswith(
            (
                "G113-R5-",
                "G113-R6-",
                "G113-R7-",
                "G113-R8-",
                "G113-R9-",
                "H2-LIVE-FREEZE-",
                "EVIDENCE-V2-OFFLINE-",
                "EVIDENCE-V2-AB-DEV-",
                "MINIMAL2-LIVE-FREEZE-",
                "CLAIM-CAMPAIGN-V1-",
            )
        ):
            raise ValueError("R5_TASK_ROLE_NOT_AUTHORIZED")
        campaign = self.record["authorization"] == CAMPAIGN_AUTHORIZATION
        if campaign != task.startswith("CLAIM-CAMPAIGN-V1-"):
            raise ValueError("CAMPAIGN_RECEIVER_PURPOSE_BOUNDARY")
        if campaign:
            from research_eval.receivers import validate_receiver

            validate_receiver(
                self.record["campaign_registration"],
                task,
                invocation,
                role,
                cutoff,
                created,
            )
        minimal2 = self.record["authorization"] == MINIMAL2_AUTHORIZATION
        if task != "G113-R5-NOCHANGE" and minimal2 != task.startswith(
            "MINIMAL2-LIVE-FREEZE-"
        ):
            raise ValueError("MINIMAL2_PURPOSE_BOUNDARY")
        if minimal2 and task != "G113-R5-NOCHANGE":
            operation, separator, sample = task.rpartition(":task:")
            if (
                not separator
                or sample != "MINIMAL2-PROBE-02"
                or role != "fundamental_analyst"
                or invocation != operation + ":invocation:" + sample
                or cutoff.isoformat() != "2026-10-30T18:40:22.704289+00:00"
                or created.tzinfo is None
                or created < cutoff
            ):
                raise ValueError("MINIMAL2_RECEIVER_SCOPE")
        ab = self.record["authorization"] == AB_AUTHORIZATION
        if task != "G113-R5-NOCHANGE" and ab != task.startswith("EVIDENCE-V2-AB-DEV-"):
            raise ValueError("AB_AUTHORIZATION_PURPOSE_BOUNDARY")
        if ab and task != "G113-R5-NOCHANGE":
            operation, separator, sample = task.rpartition(":task:")
            if (
                not separator
                or operation
                not in {
                    "EVIDENCE-V2-AB-DEV-20261105T141136258881Z-A",
                    "EVIDENCE-V2-AB-DEV-20261105T141136258881Z-B",
                }
                or sample not in {f"EV2-AB-DEV-C{i:03}" for i in range(1, 13)}
                or role != "fundamental_analyst"
                or invocation != operation + ":invocation:" + sample
                or cutoff.isoformat() != "2026-10-30T18:40:22.704289+00:00"
                or created.tzinfo is None
                or created < cutoff
            ):
                raise ValueError("AB_TASK_ROLE_INVOCATION_NOT_AUTHORIZED")
        v2 = self.record["authorization"] == V2_AUTHORIZATION
        if task != "G113-R5-NOCHANGE" and v2 != task.startswith("EVIDENCE-V2-OFFLINE-"):
            raise ValueError("V2_OFFLINE_AUTHORIZATION_PURPOSE_BOUNDARY")
        if v2 and task != "G113-R5-NOCHANGE":
            operation, separator, sample = task.rpartition(":task:")
            if (
                not separator
                or sample not in {f"H2-C{i:03}" for i in range(1, 13)}
                or role != "fundamental_analyst"
                or invocation != operation + ":invocation:" + sample
                or cutoff.isoformat() != "2026-10-30T18:40:22.704289+00:00"
                or created.tzinfo is None
                or created < cutoff
            ):
                raise ValueError("V2_OFFLINE_RECEIVER_IDENTITY")
        h2 = self.record["authorization"] == H2_AUTHORIZATION
        if task != "G113-R5-NOCHANGE" and h2 != task.startswith("H2-LIVE-FREEZE-"):
            raise ValueError("H2_AUTHORIZATION_PURPOSE_BOUNDARY")
        if h2 and task != "G113-R5-NOCHANGE":
            operation, separator, sample = task.rpartition(":task:")
            if (
                not separator
                or not operation.startswith("H2-LIVE-FREEZE-")
                or sample not in {f"H2-C{i:03}" for i in range(1, 13)}
                or role != "fundamental_analyst"
                or invocation != operation + ":invocation:" + sample
                or cutoff.isoformat() != "2026-10-30T18:40:22.704289+00:00"
                or created.tzinfo is None
                or created < cutoff
            ):
                raise ValueError("H2_TASK_ROLE_INVOCATION_NOT_AUTHORIZED")
        if task.startswith(("G113-R8-", "G113-R9-")):
            revision = "R9" if task.startswith("G113-R9-") else "R8"
            operation, separator, sample = task.rpartition(":task:")
            expected_role = {
                "B1": "fundamental_analyst",
                "B2": "fundamental_analyst",
                "B3": "news_event_analyst",
                "B4": "news_event_analyst",
            }.get(sample)
            if (
                not separator
                or not operation.startswith(f"G113-{revision}-LIVE-FREEZE-")
                or expected_role != role
                or invocation != operation + ":invocation:" + sample
                or cutoff.isoformat() != "2026-10-30T18:40:22.704289+00:00"
                or created.tzinfo is None
                or created < cutoff
            ):
                raise ValueError("R8_TASK_ROLE_INVOCATION_NOT_AUTHORIZED")
        nochange = task == "G113-R5-NOCHANGE"
        memory = (NoChangeMemory if nochange else ReceivingMemory)(ROOT, self.path)
        ep = prospective_episode(cutoff, created, task)
        scope = Scope(
            scope_type=ResearchScopeType.RESEARCH_EPISODE,
            scope_id="EPISODE:" + ep.episode_id,
        )
        history = tuple(Scope.model_validate(s) for s in self.record["history_scopes"])
        if memory.history_scopes != history:
            raise ValueError("R5_HISTORY_SCOPE_DRIFT")
        access = (NoChangeAuditAccess if nochange else ReplayReadAccess)(
            owner=self.record["owner"],
            role=AgentName(role),
            scopes=(*history, scope),
            enabled=True,
        )
        grant = dict(
            instance_id=self.record["instance_id"],
            task=task,
            invocation=invocation,
            role=role,
            episode=ep.model_dump(mode="json"),
            access=access.model_dump(mode="json"),
            effective_at=datetime.now(UTC).isoformat(),
            authorization=self.record["authorization"],
            allowed_actions=(
                ["READ_HISTORY", "NOCHANGE_AUDIT_ONLY"]
                if nochange
                else ["READ_HISTORY"]
            ),
        )
        if campaign:
            grant["campaign_registration_identity"] = digest(
                self.record["campaign_registration"]
            )
            grant["expires_at"] = self.record["campaign_registration"]["expires_at"]
        # Existing grants cannot be replaced or used for a second receiver identity.
        if any(
            json.loads(raw)["invocation"] == invocation
            for _, raw in self.journal.entries(GRANTS)
        ):
            raise ValueError("R5_RECEIVER_ALREADY_INSTALLED")
        append(self.journal, GRANTS, grant)
        memory.bind_receiver(ep, access, invocation)
        return memory

    def access(self, row: dict[str, Any], ep: ResearchEpisode) -> ReplayReadAccess:
        """Requery the current exact journal grant, rather than a frozen ReadSet."""
        self.check_root(self.path)
        matches = [
            (k, raw)
            for k, raw in self.journal.entries(GRANTS)
            if json.loads(raw)["invocation"] == row["invocation_candidate_id"]
        ]
        if len(matches) != 1:
            raise ValueError("R5_RECEIVER_NOT_INSTALLED")
        key, raw = matches[0]
        b = json.loads(raw)
        if (
            key != digest(b)
            or b["role"] not in ROLES
            or b["role"] != row["role"]
            or b["task"] != row["operational_task_id"]
            or b["episode"] != ep.model_dump(mode="json")
            or row.get("episode_candidate_id", ep.episode_id) != ep.episode_id
            or b["instance_id"] != self.record["instance_id"]
            or b["authorization"] != self.record["authorization"]
            or b["allowed_actions"] != ["READ_HISTORY"]
            or str(ep.asset_id) != "US:MSFT"
        ):
            raise ValueError("R5_RECEIVER_IDENTITY")
        if self.record["authorization"] == CAMPAIGN_AUTHORIZATION:
            from research_eval.receivers import validate_receiver

            registration = self.record["campaign_registration"]
            validate_receiver(
                registration,
                b["task"],
                b["invocation"],
                b["role"],
                ep.research_as_of,
                ep.created_at,
            )
            if (
                b.get("campaign_registration_identity") != digest(registration)
                or b.get("expires_at") != registration["expires_at"]
                or datetime.now(UTC) >= datetime.fromisoformat(b["expires_at"])
            ):
                raise ValueError("CAMPAIGN_GRANT_EXPIRED_OR_CHANGED")
        access = ReplayReadAccess.model_validate(b["access"])
        expected_scopes = (
            *[Scope.model_validate(s) for s in self.record["history_scopes"]],
            Scope(
                scope_type=ResearchScopeType.RESEARCH_EPISODE,
                scope_id="EPISODE:" + ep.episode_id,
            ),
        )
        if (
            access.owner != self.record["owner"]
            or str(access.role) != row["role"]
            or access.scopes != expected_scopes
            or digest(access) != row["access_identity"]
        ):
            raise ValueError("R5_ACL_IDENTITY")
        for scope in expected_scopes:
            access.require("READ_HISTORY", scope)
        if datetime.fromisoformat(b["effective_at"]) > datetime.now(UTC):
            raise ValueError("R5_FUTURE_GRANT")
        return access

    def authority(self, *, fixture: bool = False) -> sender.MemoryAuthority:
        """Provide narrow authority to the original sender composition only."""
        return sender.MemoryAuthority(self.path, self.access, fixture, self.check_root)


def prepare(instance: Path, output: Path) -> dict[str, Any]:
    """Install and freeze the four existing SDK requests against one real replay."""
    install(instance)
    runtime = DevelopmentRuntime(
        instance, blob_hash((instance / "INSTANCE.json").read_bytes())
    )
    ordinary = runtime.receiver(
        ROLES[0],
        datetime.fromisoformat("2026-10-30T18:40:22.704289+00:00"),
        "G113-R5-NOCHANGE",
        "G113-R5-NOCHANGE:read",
        datetime.now(UTC),
    )
    frozen = freeze_requests(
        ROOT,
        output,
        operation_prefix="G113-R5-FREEZE",
        template_path=TEMPLATE,
        ordinary_memory=ordinary,
        memory_for_slot=runtime.receiver,
    )
    if (
        frozen["request_sha256s"]
        != read(ROOT / "artifacts/g113-r3/freeze/FINAL_EXECUTION_FREEZE.json")[
            "request_sha256s"
        ]
    ):
        raise ValueError("R5_SEMANTIC_CHANGE_REQUIRES_W3")
    grants = {k: blob_hash(raw.encode()) for k, raw in runtime.journal.entries(GRANTS)}
    result = dict(
        frozen,
        schema="G113_R5_AUTHORIZED_REPLAY_EXECUTION_FREEZE_V1",
        status="ACTIVE_DEV_REPLAY_BOUND_PENDING_INDEPENDENT_W4_W5",
        sender_runtime={
            **sender.runtime(ROOT),
            MODULE: blob_hash((ROOT / MODULE).read_bytes()),
        },
        development_instance=dict(
            root=str(instance.resolve()),
            installation_sha256=runtime.installation_sha256,
            instance_id=runtime.record["instance_id"],
            grant_identities=grants,
        ),
        source_commit_ref="../SOURCE_MANIFEST.json#/source_commit",
        development_authorization=AUTHORIZATION,
    )
    durable(output / "FINAL_EXECUTION_FREEZE.json", canonical(result))
    # Reopen repositories and requery from current receiver authority for each slot.
    reopened = DevelopmentRuntime(instance, runtime.installation_sha256, grants)
    checks = []
    for row in result["slots"]:
        _, _, receipt = sender.current_memory(ROOT, output, row, reopened.authority())
        checks.append(dict(slot=row["slot"], receipt=receipt))
    if (
        digest(ReceivingMemory(ROOT, instance).population())
        != runtime.record["original_business_population_sha256"]
    ):
        raise ValueError("R5_POPULATION_CHANGED")
    durable(output / "DEV_REOPEN_REVALIDATION.json", canonical(checks))
    return result


def execute(
    output: Path,
    source_commit: str,
    *,
    fixture_transport: httpx.MockTransport | None = None,
    fixture_pins: tuple[sender.ReviewPin, ...] = (),
    fixture_result: Path | None = None,
) -> dict[str, Any]:
    """Use the reviewed original sender; preparation never calls this live."""
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    bound = freeze["development_instance"]
    path = Path(bound["root"])
    fixture = fixture_transport is not None
    if not fixture and (fixture_pins or fixture_result is not None):
        raise ValueError("R5_FIXTURE_CANNOT_AUTHORIZE_LIVE")
    if not fixture and not path.resolve().is_relative_to(RUNTIME_PARENT.resolve()):
        raise ValueError("R5_DEVELOPMENT_ROOT_ONLY")
    runtime = DevelopmentRuntime(
        path, bound["installation_sha256"], bound["grant_identities"]
    )
    grants = {k: blob_hash(raw.encode()) for k, raw in runtime.journal.entries(GRANTS)}
    if grants != bound["grant_identities"]:
        raise ValueError("R5_GRANT_DEPENDENCY_DRIFT")
    composition = sender.ExecutionComposition(
        runtime.authority(fixture=fixture),
        fixture_pins if fixture else APPROVED_RELEASES,
        (MODULE,),
    )
    dest = ROOT / "data/runtime/g113-r3" / freeze["operation_id"]
    if fixture_result is not None:
        dest = fixture_result
    return sender.execute(
        environment="DEVELOPMENT",
        source_commit=source_commit,
        output=output,
        result_root=dest,
        fixture_transport=fixture_transport,
        composition=composition,
    )


def revalidate(output: Path) -> list[dict[str, Any]]:
    """Reopen current instance and requery all four qualified receiver ReadSets."""
    freeze = read(output / "FINAL_EXECUTION_FREEZE.json")
    verify_frozen_bytes(ROOT, output, freeze)
    expected_runtime = {
        **sender.runtime(ROOT),
        MODULE: blob_hash((ROOT / MODULE).read_bytes()),
    }
    if freeze["sender_runtime"] != expected_runtime:
        raise ValueError("R5_RUNTIME_DRIFT_REFREEZE")
    bound = freeze["development_instance"]
    runtime = DevelopmentRuntime(
        Path(bound["root"]), bound["installation_sha256"], bound["grant_identities"]
    )
    rows = []
    for row in freeze["slots"]:
        _, _, receipt = sender.current_memory(ROOT, output, row, runtime.authority())
        rows.append(dict(slot=row["slot"], receipt=receipt))
    return rows


def main() -> None:
    """Explicit offline installation/check; never a model-sending CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--check", action="store_true")
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = (
        args.instance
        if args.prepare
        else Path(
            read(args.output / "FINAL_EXECUTION_FREEZE.json")["development_instance"][
                "root"
            ]
        )
    )
    if path is None or not path.resolve().is_relative_to(RUNTIME_PARENT.resolve()):
        raise ValueError("R5_DEVELOPMENT_ROOT_ONLY")
    if args.prepare:
        prepare(path, args.output)
    else:
        print(json.dumps(revalidate(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
