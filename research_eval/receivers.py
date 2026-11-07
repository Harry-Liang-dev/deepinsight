"""Owner-installed exact12 receiving contexts over the existing Memory runtime.

This is operational composition, not a prompt-supplied authorization API. It
creates no fact, model attempt or independent release. All reads use the original
current_memory -> W6 delivery -> G84/TTL/F01/Journal-CAS verification path.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_v2.mechanism import FixedClaim
from research_eval.compiler import RequestCompiler
from research_eval.models import (
    FrozenExperiment,
    FrozenRequest,
    TrustedExperimentCampaign,
    identity,
)
from research_eval.security import CurrentAuthorityAdapter
from research_eval.source_text import verify_source_text
from research_eval.storage import TraceRecorder
from src.memory.delivery import MemoryDelivery
from src.schemas.research_v2_shared import canonical, digest
from src.services.native_preservation import blob_hash
from tools import evidence_v2_runtime as base
from tools import g113_r5_replay as dev
from tools.g113_contract import TaskCatalog
from tools.g113_r1_binding import ROOT
from tools.g113_r2_memory import bind_current, recheck

VERSION = "CURRENT_CAMPAIGN_RECEIVER_FACTORY_V1"
PARENT_FREEZE = ROOT / "artifacts/stop-hardening/execution-freeze-final/freeze.json"
PARENT_HASH = "5ea5775b227a4d5b4e9db79026799d731a118a55ef81e655a0fa1eee51547cd7"
SOURCE_CASE = "H2-C004"


def parent() -> FrozenExperiment:
    """Read exact published parent, not a replacement dataset or grant."""
    raw = PARENT_FREEZE.read_bytes()
    if blob_hash(raw) != PARENT_HASH:
        raise ValueError("CAMPAIGN_PARENT_FREEZE_DRIFT")
    return FrozenExperiment.model_validate_json(raw)


def registration(frozen: FrozenExperiment) -> dict[str, Any]:
    """Bind a new runtime to the same12 original SDK bodies and source population."""
    RequestCompiler().verify(frozen)
    original = parent()
    if (
        frozen.spec.mode != "LIVE"
        or len(frozen.requests) != 12
        or frozen.dataset != original.dataset
        or frozen.campaign.budget != original.campaign.budget
        or frozen.campaign.output_cap != 1024
        or frozen.campaign.model != original.campaign.model
        or frozen.campaign.evaluator_protocol_sha256
        != original.campaign.evaluator_protocol_sha256
        or [q.raw_body for q in frozen.requests]
        != [q.raw_body for q in original.requests]
    ):
        raise ValueError("CAMPAIGN_EXACT12_SOURCE_CLAIM_OR_REQUEST_DRIFT")
    cases = {c.case_id: c for c in frozen.dataset.cases}
    for case in cases.values():
        if case.specialist_role != "fundamental_analyst":
            raise ValueError("CAMPAIGN_ROLE")
        for source in case.sources:
            verify_source_text(
                source, case.visible_input["source_read_bindings"][source.source_id]
            )
    result = dict(
        version=VERSION,
        parent_freeze_sha256=PARENT_HASH,
        campaign_policy=frozen.campaign.model_dump(mode="json"),
        experiment_id=frozen.spec.experiment_id,
        freeze_identity=identity(frozen),
        campaign_identity=identity(frozen.campaign),
        operation=frozen.campaign.campaign_id,
        created_at=frozen.campaign.created_at.isoformat(),
        expires_at=frozen.campaign.expires_at.isoformat(),
        allowed_action="READ_HISTORY",
        asset_scope=base.SCOPE,
        receivers=[
            dict(
                run_id=q.run_id,
                task=frozen.campaign.campaign_id + ":task:" + q.run_id,
                case_id=q.case_id,
                claim=cases[q.case_id].full_claim,
                role="fundamental_analyst",
                research_as_of=cases[q.case_id].research_as_of.isoformat(),
                request_sha256=q.request_sha256,
                task_identity=q.task_identity,
                rights_fingerprint=cases[q.case_id].visible_input[
                    "w5_rights_fingerprint"
                ],
            )
            for q in frozen.requests
        ],
    )
    validate_registration(result)
    return result


def validate_registration(value: dict[str, Any] | None) -> FrozenExperiment:
    """Reject modified membership, rights, model, scope, expiry or original evidence."""
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise ValueError("CAMPAIGN_REGISTRATION_REQUIRED")
    original = parent()
    campaign = TrustedExperimentCampaign.model_validate(value["campaign_policy"])
    mutable_installation = {
        "campaign_id",
        "ledger_root",
        "source_commit",
        "runtime_hashes",
        "created_at",
        "expires_at",
    }
    current_policy = campaign.model_dump(mode="json")
    parent_policy = original.campaign.model_dump(mode="json")
    if any(
        current_policy[k] != v
        for k, v in parent_policy.items()
        if k not in mutable_installation
    ) or (
        campaign.expires_at - campaign.created_at
        > original.campaign.expires_at - original.campaign.created_at
    ):
        raise ValueError("CAMPAIGN_POLICY_SCOPE_OR_DURATION_DRIFT")
    variants = tuple(
        v.model_copy(update={"immutable_boundary_identity": identity(campaign)})
        for v in original.variants
    )
    spec = original.spec.model_copy(
        update={
            "experiment_id": value["experiment_id"],
            "campaign_identity": identity(campaign),
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    variant_map = {v.variant_id: v for v in variants}
    case_map = {c.case_id: c for c in original.dataset.cases}
    requests = tuple(
        q.model_copy(
            update={
                "run_id": identity(
                    [
                        spec.experiment_id,
                        identity(campaign),
                        identity(case_map[q.case_id]),
                        identity(variant_map[q.variant_id]),
                    ]
                ),
                "prompt_identity": identity(variant_map[q.variant_id]),
            }
        )
        for q in original.requests
    )
    f = FrozenExperiment(
        spec=spec,
        campaign=campaign,
        dataset=original.dataset,
        variants=variants,
        requests=requests,
    )
    if (
        value.get("parent_freeze_sha256") != PARENT_HASH
        or value.get("freeze_identity") != identity(f)
        or value.get("campaign_identity") != identity(f.campaign)
        or value.get("operation") != f.campaign.campaign_id
        or value.get("created_at") != f.campaign.created_at.isoformat()
        or value.get("expires_at") != f.campaign.expires_at.isoformat()
        or value.get("allowed_action") != "READ_HISTORY"
        or value.get("asset_scope") != base.SCOPE
        or f.spec.mode != "LIVE"
        or len(f.requests) != 12
        or f.dataset != original.dataset
        or [q.raw_body for q in f.requests] != [q.raw_body for q in original.requests]
        or f.campaign.budget != original.campaign.budget
        or f.campaign.evaluator_protocol_sha256
        != original.campaign.evaluator_protocol_sha256
        or not f.campaign.created_at <= datetime.now(UTC) < f.campaign.expires_at
    ):
        raise ValueError("CAMPAIGN_REGISTRATION_IDENTITY_OR_EXPIRED")
    cases = {c.case_id: c for c in f.dataset.cases}
    expected = [
        dict(
            run_id=q.run_id,
            task=f.campaign.campaign_id + ":task:" + q.run_id,
            case_id=q.case_id,
            claim=cases[q.case_id].full_claim,
            role="fundamental_analyst",
            research_as_of=cases[q.case_id].research_as_of.isoformat(),
            request_sha256=q.request_sha256,
            task_identity=q.task_identity,
            rights_fingerprint=cases[q.case_id].visible_input["w5_rights_fingerprint"],
        )
        for q in f.requests
    ]
    if value.get("receivers") != expected or len({q.run_id for q in f.requests}) != 12:
        raise ValueError("CAMPAIGN_RECEIVER_MEMBERSHIP")
    return f


def validate_receiver(
    value: dict[str, Any],
    task: str,
    invocation: str,
    role: str,
    cutoff: datetime,
    created: datetime,
) -> None:
    """Authorize only one installed prospective receiving identity, never a 13th."""
    validate_registration(value)
    matches = [row for row in value["receivers"] if row["run_id"] == invocation]
    if (
        len(matches) != 1
        or matches[0]["task"] != task
        or matches[0]["role"] != role
        or matches[0]["research_as_of"] != cutoff.isoformat()
        or created.tzinfo is None
        or created < cutoff
        or created > datetime.now(UTC)
    ):
        raise ValueError("CAMPAIGN_RECEIVER_IDENTITY")


def catalog_for(frozen: FrozenExperiment, request: FrozenRequest) -> TaskCatalog:
    """Keep original source/support views; bind the exact new consumer identity."""
    old = base.catalog_for(SOURCE_CASE)
    data = old.data()
    data["campaign_receiver"] = dict(
        version=VERSION,
        freeze_identity=identity(frozen),
        run_id=request.run_id,
        task_identity=request.task_identity,
        request_sha256=request.request_sha256,
    )
    return TaskCatalog(canonical(data).decode(), old.source_texts_json)


class CampaignAccessChecker(base.CurrentAccessChecker):
    """Use the original live _check implementation after exact prospective binding."""

    def __init__(
        self, factory: CurrentCampaignReceiverFactory, request: FrozenRequest
    ) -> None:
        self.runtime = factory.runtime()
        self.output = factory.output
        self.row = factory.row(request)
        self.registry, self.packet, _ = base.fixed(SOURCE_CASE)
        case = next(
            c for c in factory.frozen.dataset.cases if c.case_id == request.case_id
        )
        self.claim = FixedClaim(
            case.case_id,
            case.full_claim,
            canonical(dict(case_id=case.case_id, statement=case.full_claim)).decode(),
            identity(case),
        )
        self.catalog = catalog_for(factory.frozen, request)
        if (
            self.row["registry_identity"] != self.registry.identity
            or self.row["semantic_task_identity"] != self.catalog.identity
            or self.row["claim_fingerprint"] != self.claim.fingerprint
        ):
            raise ValueError("CAMPAIGN_CURRENT_CONTENT_DRIFT")
        self.checked_at = datetime.now(UTC).isoformat()
        self.receipts: list[dict[str, Any]] = []
        self.authority_failure: str | None = None


class CurrentCampaignReceiverFactory:
    """Trusted operator composition over pinned installation and immutable files."""

    def __init__(
        self,
        frozen: FrozenExperiment,
        instance: Path,
        output: Path,
        installation_binding_sha256: str,
    ) -> None:
        self.frozen, self.instance, self.output = (
            frozen,
            instance.resolve(),
            output.resolve(),
        )
        raw = (self.output / "RECEIVER_INSTALLATION.json").read_bytes()
        if blob_hash(raw) != installation_binding_sha256:
            raise ValueError("CAMPAIGN_INSTALLATION_BINDING_DRIFT")
        self.binding = json.loads(raw)
        if (
            self.binding["freeze_identity"] != identity(frozen)
            or self.binding["instance_root"] != str(self.instance)
            or self.binding["output_root"] != str(self.output)
            or len(self.binding["rows"]) != 12
        ):
            raise ValueError("CAMPAIGN_FACTORY_FREEZE_BINDING")
        self.runtime()

    def runtime(self) -> dev.DevelopmentRuntime:
        """Reopen actual Owner instance and current journal grants on every call."""
        rt = dev.DevelopmentRuntime(
            self.instance,
            self.binding["installation_sha256"],
            self.binding["grant_identities"],
        )
        if rt.record["authorization"] != dev.CAMPAIGN_AUTHORIZATION or rt.record[
            "campaign_registration"
        ]["freeze_identity"] != identity(self.frozen):
            raise ValueError("CAMPAIGN_FACTORY_INSTANCE_PURPOSE")
        return rt

    def row(self, request: FrozenRequest) -> dict[str, Any]:
        """Reject request/claim substitution and verify exact receiving artifacts."""
        expected = [q for q in self.frozen.requests if q.run_id == request.run_id]
        if len(expected) != 1 or expected[0] != request:
            raise ValueError("CAMPAIGN_FROZEN_REQUEST_MEMBERSHIP")
        matches = [
            x
            for x in self.binding["rows"]
            if x["invocation_candidate_id"] == request.run_id
        ]
        if len(matches) != 1:
            raise ValueError("CAMPAIGN_RECEIVER_NOT_INSTALLED")
        row = matches[0]
        for name, h in row["file_identities"].items():
            if blob_hash((self.output / row["slot"] / name).read_bytes()) != h:
                raise ValueError("CAMPAIGN_RECEIVER_ARCHIVE_DRIFT")
        return dict(row)

    def checker(self, request: FrozenRequest) -> CampaignAccessChecker:
        """Construct a current checker; no historical ReadSet grants access."""
        return CampaignAccessChecker(self, request)

    def authority(self) -> CurrentAuthorityAdapter:
        """Connect to the unchanged Runner's original authority protocol."""
        return CurrentAuthorityAdapter(
            {
                c.case_id: (c.authority_binding, base.SCOPE, self.checker)
                for c in self.frozen.dataset.cases
            }
        )

    @classmethod
    def install(
        cls, frozen: FrozenExperiment, instance: Path, output: Path
    ) -> CurrentCampaignReceiverFactory:
        """Explicit Owner action: new isolated replay and 12 append-only grants."""
        plan = registration(frozen)
        if output.exists() or instance.exists():
            raise ValueError("CAMPAIGN_INSTALLATION_ALREADY_EXISTS")
        record = dev.install(
            instance,
            authorization=dev.CAMPAIGN_AUTHORIZATION,
            campaign_registration=plan,
        )
        installation = blob_hash((instance / "INSTANCE.json").read_bytes())
        rt = dev.DevelopmentRuntime(instance, installation)
        output.mkdir(parents=True, exist_ok=False)
        cases = {c.case_id: c for c in frozen.dataset.cases}
        registry, _, _ = base.fixed(SOURCE_CASE)
        rows = []
        for q in frozen.requests:
            case = cases[q.case_id]
            task = frozen.campaign.campaign_id + ":task:" + q.run_id
            memory = rt.receiver(
                "fundamental_analyst",
                case.research_as_of,
                task,
                q.run_id,
                datetime.now(UTC),
            )
            catalog = catalog_for(frozen, q)
            candidate, dependency = bind_current(
                memory,
                catalog,
                MemoryDelivery.model_validate_json(dev.TEMPLATE.read_bytes()),
            )
            receipt = recheck(memory, candidate, catalog, digest(memory.access))
            folder = output / q.run_id
            recorder = TraceRecorder(folder)
            objects = {
                "W6_DELIVERY.json": candidate.model_dump(mode="json"),
                "RECEIVING_EPISODE_CANDIDATE.json": memory.ep.model_dump(mode="json"),
                "CURRENT_AUTHORITY.json": receipt,
                "DEPENDENCY_BINDING.json": dependency,
            }
            for name, value in objects.items():
                recorder.record(name, value)
            claim = FixedClaim(
                case.case_id,
                case.full_claim,
                canonical(
                    dict(case_id=case.case_id, statement=case.full_claim)
                ).decode(),
                identity(case),
            )
            rows.append(
                dict(
                    slot=q.run_id,
                    sample_id=case.case_id,
                    role="fundamental_analyst",
                    operational_task_id=task,
                    invocation_candidate_id=q.run_id,
                    episode_candidate_id=memory.ep.episode_id,
                    access_identity=digest(memory.access),
                    registry_identity=registry.identity,
                    claim_fingerprint=claim.fingerprint,
                    semantic_task_identity=catalog.identity,
                    request_sha256=q.request_sha256,
                    file_identities={
                        name: blob_hash((folder / name).read_bytes())
                        for name in objects
                    },
                )
            )
        body = dict(
            version=VERSION,
            freeze_identity=identity(frozen),
            instance_root=str(instance.resolve()),
            output_root=str(output.resolve()),
            installation_sha256=installation,
            instance_id=record["instance_id"],
            owner=record["owner"],
            grant_identities={
                k: blob_hash(raw.encode()) for k, raw in rt.journal.entries(dev.GRANTS)
            },
            rows=rows,
            real_provider_calls=0,
            scientific_admission=False,
        )
        TraceRecorder(output).record("RECEIVER_INSTALLATION.json", body)
        return cls(
            frozen,
            instance,
            output,
            blob_hash((output / "RECEIVER_INSTALLATION.json").read_bytes()),
        )


def main() -> None:
    """Install exact current receivers only; never call a model or issue Pins."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    f = FrozenExperiment.model_validate_json(args.freeze.read_bytes())
    factory = CurrentCampaignReceiverFactory.install(f, args.instance, args.output)
    checks = [
        factory.authority().check(
            next(c for c in f.dataset.cases if c.case_id == q.case_id), q
        )
        for q in f.requests
    ]
    TraceRecorder(args.output).record(
        "ALL_TWELVE_CURRENT_CHECKS.json", dict(checks=checks, real_provider_calls=0)
    )
    print(
        json.dumps(
            dict(
                installed=len(checks),
                instance_id=factory.binding["instance_id"],
                real_provider_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
