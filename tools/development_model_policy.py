"""Development-only standing inference policy; no scientific authority or Gateway.

The direct current user instruction installs this policy, not approved=true in
experiment JSON. W5 is an independent pre-output protocol record, not paid consent.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.services.native_preservation import blob_hash
from src.services.pilot_capacity_budget import CapacityMeter
from src.services.retained_pilot_budget import PilotStop

POLICY = "DEVELOPMENT_MODEL_EXECUTION_POLICY_V1"
EXPERIMENT = "G106-D1-GOOGL-CLOUD-v1"
EXPERIMENT_SHA = "59cbb9b305660a3c5517c15f531855f279d049a598d4c9b2492f49c547c6e1a9"
BASELINE = "fc3b88a4c7f52435c17c844e5f672c64e1d38996d7b1d903b1c02e860aad78bf"
REQUESTS = (
    "56841992679bdba70d5387f4b064d79d5d8b18aa3f6fcd21f863f6991e6fbeff",
    "b7e3acd66799cda1cc7e3c195f4efdf37d14c58154d8ce18a04c04b800c93c2f",
)
W5_REPO = Path("/home/harry/deepinsight-w5/g106-standing-auth-policy")
W5_PARENT = "7a189b412be3f2eca513262e08fb9516654d9608"
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RecoveryOperation:
    """New operation and independent W5 episode; never reuse a stopped archive."""

    operation_id: str
    evaluation_episode_id: str
    w5_repository: Path
    w5_commit: str
    w5_path: str
    w5_sha256: str


@dataclass(frozen=True)
class DevelopmentOperation:
    """Explicit local operation trigger, never an approval JSON or science permit."""

    environment: str
    experiment_id: str
    w5_commit: str
    w5_path: str
    w5_sha256: str
    w5_repository: Path = W5_REPO
    recovery: RecoveryOperation | None = None


@dataclass(frozen=True)
class DevelopmentExecution:
    """Bound development operation with immutable independent protocol provenance."""

    origin: str
    results_root: str
    record: dict[str, Any]


def w5_record(operation: DevelopmentOperation, *, fixture: bool) -> dict[str, Any]:
    """Read committed pre-output W5 record; never edit or issue its decision."""
    repo = operation.w5_repository.resolve()
    if not fixture and repo != W5_REPO.resolve():
        raise ValueError("DEV_W5_INDEPENDENT_REPOSITORY")
    if not operation.w5_commit or not operation.w5_sha256:
        raise ValueError("DEV_W5_PREOUTPUT_RECORD_REQUIRED")
    if len(operation.w5_commit) != 40 or any(
        c not in "0123456789abcdef" for c in operation.w5_commit
    ):
        raise ValueError("DEV_W5_COMMIT_IDENTITY")
    if Path(operation.w5_path).is_absolute() or ".." in Path(operation.w5_path).parts:
        raise ValueError("DEV_W5_RECORD_PATH")

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
        )

    if not fixture:
        git("merge-base", "--is-ancestor", W5_PARENT, operation.w5_commit)
    raw = git("show", f"{operation.w5_commit}:{operation.w5_path}")
    if blob_hash(raw) != operation.w5_sha256:
        raise ValueError("DEV_W5_RECORD_IDENTITY")
    row = json.loads(raw)
    expected = {
        "schema": "G106_W5_DEVELOPMENT_STANDING_AUTHORIZATION_POLICY_V1",
        "experiment_sha256": EXPERIMENT_SHA,
        "original_baseline_sha256": BASELINE,
        "decision": "ACCEPTED",
        "per_batch_user_approval": "NOT_REQUIRED",
        "separate_token_paid_authorization": "NOT_REQUIRED",
        "cost_admission_gate": "NOT_REQUIRED",
        "current_task_model_calls": 0,
        "current_task_provider_calls": 0,
        "original_D1_addendum_commit": W5_PARENT,
        "original_rubric_sha256": (
            "6d0c5de39594857f9ecf1819c479aafc0e840921a445001b67310d9c306f74b6"
        ),
        "original_hard_gates_sha256": (
            "a1395e109433b1243ff42923f1a725fc1ce699c6fd3ee7a43811eb79f8d2fbe7"
        ),
    }
    if any(type(row.get(k)) is not type(v) or row[k] != v for k, v in expected.items()):
        raise ValueError("DEV_W5_PROTOCOL_SCOPE")
    protocol = row["unchanged_protocol"]
    if (
        tuple(x["sha256"] for x in row["frozen_requests"]) != REQUESTS
        or protocol["denominator"] != 2
        or protocol["max_calls"] != 2
        or protocol["roles"] != ["fundamental_analyst", "news_event_analyst"]
        or protocol["model_visible_input_mutations"] != 0
        or row["interpretability"]["economic_value_rubric"] != "UNCHANGED"
    ):
        raise ValueError("DEV_W5_PROTOCOL_SCOPE")
    status = json.loads(git("show", f"{operation.w5_commit}:policy/FINAL_STATUS.json"))
    if (
        status.get("MODEL_OUTPUT_OBSERVED") != "NO"
        or status.get("SCORING_PROGRAM_CHANGES") != 0
    ):
        raise ValueError("DEV_W5_ALREADY_OBSERVED_OUTPUT")
    if fixture != (row.get("engineering_fixture") is True):
        raise ValueError("DEV_W5_FIXTURE_ORIGIN")
    issued = datetime.fromisoformat(row["recorded_at"])
    committed = datetime.fromisoformat(
        git("show", "-s", "--format=%cI", operation.w5_commit).decode().strip()
    )
    if issued.tzinfo is None or not issued <= committed <= datetime.now(UTC):
        raise ValueError("DEV_W5_PREOUTPUT_CHRONOLOGY")
    return {
        "record": row,
        "raw_sha256": blob_hash(raw),
        "commit": operation.w5_commit,
        "repository": str(repo),
        "path": operation.w5_path,
        "committed_at": committed.isoformat(),
    }


def recovery_record(operation: RecoveryOperation, *, fixture: bool) -> dict[str, Any]:
    """Bind independently registered episode, immutable old failure and new source."""
    repo = operation.w5_repository.resolve()
    expected_repo = Path("/home/harry/deepinsight-w5/g106-transport-recovery-prereg")
    if not fixture and repo != expected_repo:
        raise ValueError("RECOVERY_INDEPENDENT_W5_REPOSITORY")
    for identity in (operation.operation_id, operation.evaluation_episode_id):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity) is None:
            raise ValueError("RECOVERY_OPERATION_IDENTITY")
    if (
        re.fullmatch(r"[a-f0-9]{40}", operation.w5_commit) is None
        or operation.w5_path != "recovery/EVALUATION_EPISODE.json"
    ):
        raise ValueError("RECOVERY_REGISTRATION_IDENTITY")

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
        )

    if not fixture:
        git(
            "merge-base",
            "--is-ancestor",
            "94a223830cb5af558949fae6e27f45ede5d7571b",
            operation.w5_commit,
        )
    raw = git("show", f"{operation.w5_commit}:{operation.w5_path}")
    if blob_hash(raw) != operation.w5_sha256:
        raise ValueError("RECOVERY_REGISTRATION_HASH")
    row = json.loads(raw)
    expected = {
        "schema": "G106_W5_TRANSPORT_RECOVERY_EVALUATION_EPISODE_V1",
        "EvaluationEpisodeID": operation.evaluation_episode_id,
        "decision": "ACCEPTED",
        "MODEL_OUTPUT_OBSERVED": "NO",
        "frozen_experiment_sha256": EXPERIMENT_SHA,
        "baseline_sha256": BASELINE,
        "registration_kind": "PROSPECTIVE_NEW_EPISODE_NOT_RESUMPTION",
        "security": "US:GOOGL",
        "CIK": "0001652044",
        "model": "qwen3.7-flash-2026-07-15",
        "output_cap": 8192,
        "max_new_provider_calls": 2,
        "max_new_calls_per_role": 1,
        "retries": 0,
        "fallback": "NONE",
        "intended_evaluation_denominator": 2,
        "source_readset_sha256": (
            "45e149c64d27ec6d9b78df3e03f71235f6166a7b23a9f8676cdb70313450b1f1"
        ),
        "Native_Scientific_Admission": "BLOCKED",
    }
    if any(type(row.get(k)) is not type(v) or row[k] != v for k, v in expected.items()):
        raise ValueError("RECOVERY_EPISODE_SCOPE")
    if (
        tuple(x["request_sha256"] for x in row["requests"]) != REQUESTS
        or row["roles"] != ["fundamental_analyst", "news_event_analyst"]
        or row["model_memory"] != []
        or row["cross_role_feedback"] is not False
    ):
        raise ValueError("RECOVERY_EPISODE_REQUESTS")
    if fixture != (row.get("engineering_fixture") is True):
        raise ValueError("RECOVERY_FIXTURE_ORIGIN")
    registered = datetime.fromisoformat(row["registered_at"])
    committed = datetime.fromisoformat(
        git("show", "-s", "--format=%cI", operation.w5_commit).decode().strip()
    )
    if registered.tzinfo is None or not registered <= committed <= datetime.now(UTC):
        raise ValueError("RECOVERY_REGISTRATION_CLOCK")
    # Independently fixed evaluation bytes remain exactly the inherited originals.
    for name, sha in row["protected_evaluation_file_hashes"].items():
        if blob_hash(git("show", f"{operation.w5_commit}:{name}")) != sha:
            raise ValueError("RECOVERY_EVALUATION_DRIFT")
    old = json.loads(
        git("show", f"{operation.w5_commit}:recovery/OLD_STOPPED_EPISODE.json")
    )
    previous = Path(
        "/home/harry/deepinsight-g106-dev-standing-execution/data/runtime/g106-dev-standing-execution"
    )
    if old["archive_root"] != str(previous) or old["provider_requests"] != 0:
        raise ValueError("RECOVERY_OLD_FAILURE_IDENTITY")
    for item in old["files"]:
        name = Path(item["path"])
        if name.is_absolute() or ".." in name.parts:
            raise ValueError("RECOVERY_OLD_FILE_PATH")
        for base in (previous, ROOT / "data/runtime/g106-dev-standing-execution"):
            if blob_hash((base / name).read_bytes()) != item["sha256"]:
                raise ValueError("RECOVERY_OLD_ARCHIVE_CHANGED")
    source = (
        subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    modules = [
        "tools/g106_transport.py",
        "tools/g106_d1_experiment.py",
        "tools/development_model_policy.py",
    ]
    identities = {name: blob_hash((ROOT / name).read_bytes()) for name in modules}
    if not fixture:
        if Path(row["repair_worktree"]).resolve() != ROOT:
            raise ValueError("RECOVERY_EXECUTION_WORKTREE")
        for name, sha in identities.items():
            original = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", source + ":" + name]
            )
            if blob_hash(original) != sha:
                raise ValueError("RECOVERY_EXECUTION_SOURCE_NOT_FROZEN")
    return {
        "operation_id": operation.operation_id,
        "EvaluationEpisodeID": operation.evaluation_episode_id,
        "registration": row,
        "registration_sha256": blob_hash(raw),
        "registration_commit": operation.w5_commit,
        "registration_repository": str(repo),
        "registration_commit_at": committed.isoformat(),
        "ExecutionSourceCommit": source,
        "TransportFixIdentity": identities["tools/g106_transport.py"],
        "executing_modules": identities,
        "old_stopped_archive_preserved": True,
    }


def bind_development(
    operation: DevelopmentOperation, raw: bytes, *, fixture: bool
) -> DevelopmentExecution:
    """Bind the current explicit task; W5 recording remains a separate prerequisite."""
    if operation.environment != "DEVELOPMENT" or operation.experiment_id != EXPERIMENT:
        raise ValueError("DEV_ENVIRONMENT_OR_TASK")
    if blob_hash(raw) != EXPERIMENT_SHA:
        raise ValueError("DEV_FROZEN_EXPERIMENT_IDENTITY")
    plan = json.loads(raw)
    if tuple(row["request_sha256"] for row in plan["requests"]) != REQUESTS:
        raise ValueError("DEV_REQUEST_IDENTITY")
    # Do not touch or resume the historical D1 result location.
    if not fixture and Path(plan["results_root"]).exists():
        raise ValueError("DEV_PRIOR_EXPERIMENT_EXISTS")
    record = w5_record(operation, fixture=fixture)
    origin = (
        "SYNTHETIC_ENGINEERING_FIXTURE" if fixture else "DEVELOPMENT_STANDING_POLICY"
    )
    destination = ROOT / "data/runtime/g106-dev-standing-execution"
    recovery = None
    if operation.recovery is not None:
        recovery = recovery_record(operation.recovery, fixture=fixture)
        destination = (
            ROOT
            / "data/runtime/g106-transport-recovery"
            / operation.recovery.evaluation_episode_id
        )
    if fixture:
        destination = operation.w5_repository / "isolated-fixture-results"
    return DevelopmentExecution(
        origin,
        str(destination.resolve()),
        {
            "policy": POLICY,
            "recovery": recovery,
            "environment": "DEVELOPMENT",
            "origin": origin,
            "operation_source": "EXPLICIT_LOCAL_CLI" if not fixture else "OFFLINE_TEST",
            "operation_at": datetime.now(UTC).isoformat(),
            "experiment_id": EXPERIMENT,
            "experiment_sha256": blob_hash(raw),
            "w5": record,
            "per_batch_user_approval": "NOT_REQUIRED",
            "per_batch_paid_approval": "NOT_REQUIRED",
            "token_cost_as_admission_gate": "DISABLED",
            "cost_reporting": "REFERENCE_ONLY",
            "w4_live_boundary_review": "NOT_COMPLETED",
            "scientific_execution": "BLOCKED",
            "production_execution": "NOT_AUTHORIZED",
            "real_trading": "NOT_AUTHORIZED",
            "original_results_root": plan["results_root"],
            "results_root": str(destination.resolve()),
        },
    )


class DevelopmentAccountingMeter(CapacityMeter):
    """Reuse request/usage checks; remove token and money admission comparisons only."""

    development_accounting = True

    def _reserve(self, inputs: int, *, retry: bool) -> int:
        if self.stopped:
            raise PilotStop(self.stopped)
        if self.active is not None:
            raise PilotStop("PILOT_CONCURRENT_CALL")
        if self.clock() - self.started >= self.limits.seconds:
            raise PilotStop("PILOT_TIME_EXHAUSTED")
        if self.calls >= self.limits.calls or retry:
            raise PilotStop("PILOT_CALL_OR_RETRY_LIMIT")
        # CapacityMeter.reserve already checked exact request, model and output cap.
        number = self.calls + 1
        tokens = inputs + self.limits.output_per_call
        self._record(
            dict(
                event="RESERVED",
                attempt=number,
                retry=False,
                token_cost_gate="DISABLED",
                cost_reporting="REFERENCE_ONLY",
            )
        )
        self.calls = number
        self.active = number, tokens, Decimal(0)
        self.tokens += tokens
        return number

    def _record(self, row: dict[str, Any]) -> None:
        super()._record(
            {**row, "cost_reporting": "REFERENCE_ONLY", "token_cost_gate": "DISABLED"}
        )
