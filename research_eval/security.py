"""Campaign release and per-send authority are owned by trusted composition."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from research_eval.models import (
    DatasetCase,
    FrozenRequest,
    TrustedExperimentCampaign,
    identity,
)
from tools import g113_r3_execute as releases
from tools.evidence_v2_runtime import CurrentAccessChecker
from tools.minimal_semantic_carrier import proposal_schema

RELEASE_CONTRACT = "RESEARCH_EVAL_CAMPAIGN_V1"


def release_projection(campaign: TrustedExperimentCampaign) -> dict[str, Any]:
    """Bind the policy envelope; individual exact requests are subordinate freezes."""
    return dict(
        created_at=campaign.created_at.isoformat(),
        operation_id=campaign.campaign_id,
        campaign_identity=identity(campaign),
        campaign_policy=campaign.model_dump(mode="json"),
        population_identity=campaign.dataset_identity,
        request_sha256s=[],
        schema_identities=[identity(proposal_schema())],
        planned_samples=campaign.budget.max_samples,
        model=campaign.model,
        release_contract=RELEASE_CONTRACT,
    )


class CampaignReleaseGate:
    """No CLI/JSON grants: operator installs genuine independently issued Pins."""

    def __init__(self, root: Path, pins: tuple[releases.ReviewPin, ...] = ()) -> None:
        self.root, self.pins = root, pins

    def check(self, campaign: TrustedExperimentCampaign) -> list[dict[str, Any]]:
        """Validate actual Git source and dual releases, never historical pins."""
        now = datetime.now(UTC)
        if not campaign.created_at <= now < campaign.expires_at:
            raise ValueError("CAMPAIGN_EXPIRED")
        if (
            len({p.git_repository.resolve() for p in self.pins if p.git_repository})
            != 2
        ):
            raise ValueError("CAMPAIGN_INDEPENDENT_RELEASES_REQUIRED")
        if not campaign.runtime_hashes:
            raise ValueError("RUNTIME_IDENTITY_REQUIRED")
        from tools.minimal2_live import runtime

        required = set(runtime()) | {
            str(p.relative_to(self.root))
            for p in (self.root / "research_eval").glob("*.py")
        }
        if set(campaign.runtime_hashes) != required:
            raise ValueError("INCOMPLETE_RUNTIME_CLOSURE")
        for relative, expected in campaign.runtime_hashes.items():
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root.resolve()):
                raise ValueError("RUNTIME_PATH_ESCAPE")
            raw = path.read_bytes()
            stored = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "show",
                    campaign.source_commit + ":" + relative,
                ]
            )
            if raw != stored or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("RUNTIME_DRIFT")
        return releases.reviews(
            self.pins,
            release_projection(campaign),
            campaign.source_commit,
            fixture=False,
            release_contract=RELEASE_CONTRACT,
        )


class Authority(Protocol):
    """Current state must be checked inside the original HTTP before_send hook."""

    engineering_fixture: bool

    def check(self, case: DatasetCase, request: FrozenRequest) -> dict[str, Any]:
        """Return current source/Memory proof or reject."""
        ...


class CurrentAuthorityAdapter:
    """Reuse the existing CurrentAccessChecker, never grant from dataset fields."""

    engineering_fixture = False

    def __init__(
        self,
        bindings: dict[
            str, tuple[str, str, Callable[[FrozenRequest], CurrentAccessChecker]]
        ],
    ) -> None:
        self._bindings = dict(bindings)

    def check(self, case: DatasetCase, request: FrozenRequest) -> dict[str, Any]:
        """Reject old receivers and re-open actual Source/ACL/TTL/F01/CAS state."""
        if case.case_id not in self._bindings:
            raise ValueError("CURRENT_CAMPAIGN_RECEIVER_NOT_INSTALLED")
        binding_identity, scope, factory = self._bindings[case.case_id]
        checker = factory(request)
        if not isinstance(checker, CurrentAccessChecker):
            raise ValueError("CURRENT_CHECKER_TYPE")
        if (
            binding_identity != case.authority_binding
            or checker.row.get("role") != case.specialist_role
            or checker.row.get("invocation_candidate_id") != request.run_id
        ):
            raise ValueError("CURRENT_RECEIVING_IDENTITY_MISMATCH")
        if checker.claim.statement != case.full_claim:
            raise ValueError("FULL_CLAIM_AUTHORITY_MISMATCH")
        if (
            datetime.fromisoformat(checker.packet["trusted_research_as_of"])
            != case.research_as_of
        ):
            raise ValueError("RESEARCH_CUTOFF_AUTHORITY_MISMATCH")
        sources = {s.source_id: s for s in case.sources}
        for handle, source_id in case.handles.items():
            entry = checker.registry.entries.get(handle)
            if (
                entry is None
                or entry.source_id != source_id
                or entry.allowed_scope != scope
            ):
                raise ValueError("F01_HANDLE_SOURCE_BINDING")
            source = sources[source_id]
            if (
                entry.provenance().get("source_identity", {}).get("raw_sha256")
                != source.sha256
            ):
                raise ValueError("SOURCE_REGISTRY_HASH_BINDING")
            if (
                hashlib.sha256(Path(source.path).read_bytes()).hexdigest()
                != source.sha256
            ):
                raise ValueError("SOURCE_RAW_HASH_DRIFT")
        receipt = checker.check(checker.registry.identity, scope, checker.checked_at)
        return dict(
            current_receipts=checker.receipts,
            receipt_identity=receipt.receipt_identity,
            engineering_fixture=False,
        )


class OfflineAuthority:
    """Explicit fixture authority for concurrency tests; unusable in live mode."""

    engineering_fixture = True

    def __init__(
        self,
        *,
        expires_at: datetime,
        denied: frozenset[str] = frozenset(),
        stale_cas: bool = False,
    ) -> None:
        self.expires_at, self.denied, self.stale_cas = expires_at, denied, stale_cas

    def check(self, case: DatasetCase, request: FrozenRequest) -> dict[str, Any]:
        """Check fixture source bytes, clocks and injected permission failures."""
        if (
            datetime.now(UTC) >= self.expires_at
            or case.case_id in self.denied
            or self.stale_cas
        ):
            raise ValueError("OFFLINE_AUTHORITY_EXPIRED_REVOKED_OR_STALE_CAS")
        for source in case.sources:
            if (
                hashlib.sha256(Path(source.path).read_bytes()).hexdigest()
                != source.sha256
            ):
                raise ValueError("SOURCE_RAW_HASH_DRIFT")
            if source.available_at > case.research_as_of:
                raise ValueError("FUTURE_SOURCE")
        return dict(
            engineering_fixture=True,
            checked_at=datetime.now(UTC).isoformat(),
            authority_binding=case.authority_binding,
            invocation=request.run_id,
            scope="READ_HISTORY",
            scientific_admission=False,
        )
