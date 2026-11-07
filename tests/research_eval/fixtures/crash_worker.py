"""Isolated crash injector: all SDK sends are MockTransport, never network."""

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research_eval.models import FrozenExperiment
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import CampaignReleaseGate, OfflineAuthority
from research_eval.storage import TraceRecorder
from tools import g107_matrix as sender

f = FrozenExperiment.model_validate_json(Path(sys.argv[1]).read_bytes())
root, stage = Path(sys.argv[2]), sys.argv[3]
original = sender.durable
record = TraceRecorder.record


def crash_durable(path: Path, raw: bytes) -> None:
    if stage == "before_invocation" and path.name == "invocation.json":
        os._exit(86)
    original(path, raw)
    if (stage == "after_invocation" and path.name == "invocation.json") or (
        stage == "after_http" and path.name == "response.raw"
    ):
        os._exit(86)


def crash_record(self: TraceRecorder, relative: str, value: Any) -> None:
    record(self, relative, value)
    if stage == "reservation" and relative.startswith("attempts/"):
        os._exit(86)


sender.durable = crash_durable
setattr(TraceRecorder, "record", crash_record)
plan = OfflineScenario(
    {r.variant_id + "/" + r.case_id: {"assistant": "{}"} for r in f.requests}, delay=0
)
if stage == "transport":
    import httpx

    def transport(request: Any) -> httpx.MockTransport:
        def die(wire: httpx.Request) -> httpx.Response:
            os._exit(86)

        return httpx.MockTransport(die)

    setattr(plan, "transport", transport)
TrustedExperimentRunner(
    root,
    OfflineAuthority(expires_at=f.campaign.expires_at),
    CampaignReleaseGate(Path.cwd()),
).run(f, scenario=plan)
raise SystemExit("CRASH_NOT_REACHED")
