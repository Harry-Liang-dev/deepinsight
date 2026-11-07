"""Actual original SDK crash/restart, capture failure and dispatch race regression."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from research_eval.compiler import RequestCompiler
from research_eval.demo import make_demo
from research_eval.models import FrozenExperiment, encoded, identity
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import CampaignReleaseGate, OfflineAuthority
from research_eval.storage import TraceRecorder
from tools import g107_matrix as sender

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def synthetic_freeze(tmp_path_factory: pytest.TempPathFactory) -> FrozenExperiment:
    """Create four synthetic cases; no private finance input or historical output."""
    folder = tmp_path_factory.mktemp("crash-baseline") / "demo"
    make_demo(ROOT, folder)
    f = FrozenExperiment.model_validate_json((folder / "freeze.json").read_bytes())
    extra = f.dataset.cases[-1].model_copy(
        update={
            "case_id": "fourth-independent",
            "full_claim": "A fourth synthetic observation needs independent evidence.",
        }
    )
    dataset = f.dataset.model_copy(update={"cases": (*f.dataset.cases, extra)})
    campaign = f.campaign.model_copy(
        update={
            "dataset_identity": identity(dataset),
            "authority_bindings": tuple(c.authority_binding for c in dataset.cases),
            "budget": f.campaign.budget.model_copy(
                update={
                    "max_samples": 12,
                    "max_attempts": 12,
                    "max_tokens": 12006144,
                    "max_reference_cost_cny": __import__("decimal").Decimal("20"),
                }
            ),
        }
    )
    variants = tuple(
        v.model_copy(update={"dataset_identity": identity(dataset)}) for v in f.variants
    )
    return f.model_copy(
        update={
            "campaign": campaign,
            "dataset": dataset,
            "variants": variants,
            "spec": f.spec.model_copy(update={"dataset_identity": identity(dataset)}),
        }
    )


def compile_batch(f: FrozenExperiment, *, changed: bool = False) -> FrozenExperiment:
    """Change test-only prompt bytes, keeping the same approved campaign boundary."""
    variants = f.variants[:1]
    if changed:
        v = variants[0]
        text = v.content + " Offline independent next batch."
        variants = (
            v.model_copy(
                update={
                    "content": text,
                    "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            ),
        )
    variants = tuple(
        v.model_copy(update={"immutable_boundary_identity": identity(f.campaign)})
        for v in variants
    )
    spec = f.spec.model_copy(
        update={
            "experiment_id": "next" if changed else "first",
            "mode": "OFFLINE",
            "campaign_identity": identity(f.campaign),
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    return RequestCompiler().compile(spec, f.campaign, f.dataset, variants)


@pytest.fixture
def frozen(tmp_path: Path, synthetic_freeze: FrozenExperiment) -> FrozenExperiment:
    f = synthetic_freeze
    c = f.campaign.model_copy(
        update={
            "execution_mode": "OFFLINE",
            "ledger_root": str(tmp_path),
            "budget": f.campaign.budget.model_copy(
                update={"concurrency": 2, "requests_per_second": 100}
            ),
        }
    )
    return compile_batch(f.model_copy(update={"campaign": c}))


def plan(f: FrozenExperiment) -> OfflineScenario:
    return OfflineScenario(
        {r.variant_id + "/" + r.case_id: {"assistant": "{}"} for r in f.requests},
        delay=0.01,
    )


def runner(root: Path, f: FrozenExperiment) -> TrustedExperimentRunner:
    return TrustedExperimentRunner(
        root,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    )


@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize(
    "stage",
    ["reservation", "before_invocation", "after_invocation", "transport", "after_http"],
)
def test_actual_process_crash_restart(
    frozen: FrozenExperiment, tmp_path: Path, stage: str, concurrency: int
) -> None:
    f = compile_batch(
        frozen.model_copy(
            update={
                "campaign": frozen.campaign.model_copy(
                    update={
                        "budget": frozen.campaign.budget.model_copy(
                            update={"concurrency": concurrency}
                        )
                    }
                )
            }
        )
    )
    path = tmp_path / "input.json"
    path.write_bytes(encoded(f))
    child = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tests/research_eval/fixtures/crash_worker.py"),
            str(path),
            str(tmp_path),
            stage,
        ],
        cwd=ROOT,
        timeout=40,
        env={**os.environ, "QWEN_MODEL_NAME": "qwen3.8-flash"},
        capture_output=True,
    )
    assert child.returncode == 86, child.stderr.decode()
    campaign = tmp_path / identity(f.campaign)
    before = {str(p): p.read_bytes() for p in campaign.rglob("invocation.json")}
    for candidate in (compile_batch(f, changed=True), f):
        with pytest.raises(ValueError, match="UNRESOLVED_PREVIOUS_SEND"):
            runner(tmp_path, candidate).run(candidate, scenario=plan(candidate))
    assert before == {str(p): p.read_bytes() for p in campaign.rglob("invocation.json")}
    assert (
        json.loads((campaign / "QUARANTINE.json").read_bytes())["new_dispatches"] == 0
    )


@pytest.mark.parametrize(
    "missing",
    [
        "response.raw",
        "assistant.txt",
        "usage.json",
        "meter/0001.json",
        "outcome.json",
        "worker-result.json",
        "terminal.json",
        "authority.json",
        "dispatch.json",
    ],
)
def test_terminal_missing_prevents_next_prompt(
    frozen: FrozenExperiment, tmp_path: Path, missing: str
) -> None:
    result = runner(tmp_path, frozen).run(frozen, scenario=plan(frozen))
    assert result["mock_attempts"] == 4 and result["stop_reason"] is None
    folder = Path(result["archive"]) / frozen.requests[0].run_id
    (folder / missing).unlink()  # Deliberate corruption of new synthetic archives only.
    nxt = compile_batch(frozen, changed=True)
    with pytest.raises(ValueError, match="UNRESOLVED_PREVIOUS_SEND"):
        runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))


@pytest.mark.parametrize("file", ["response.raw", "usage.json", "outcome.json"])
def test_terminal_tamper_even_resealed_rejected(
    frozen: FrozenExperiment, tmp_path: Path, file: str
) -> None:
    result = runner(tmp_path, frozen).run(frozen, scenario=plan(frozen))
    folder = Path(result["archive"]) / frozen.requests[0].run_id
    obj = json.loads((folder / file).read_bytes())
    if file == "response.raw":
        obj["model"] = "wrong-model"
    elif file == "usage.json":
        obj["input_tokens"] += 1
    else:
        obj["request_sha256"] = "0" * 64
    (folder / file).write_bytes(encoded(obj))
    terminal = json.loads((folder / "terminal.json").read_bytes())
    terminal["files"][file] = hashlib.sha256((folder / file).read_bytes()).hexdigest()
    (folder / "terminal.json").write_bytes(encoded(terminal))
    nxt = compile_batch(frozen, changed=True)
    with pytest.raises(ValueError, match="UNRESOLVED_PREVIOUS_SEND"):
        runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))


@pytest.mark.parametrize("file", ["response.raw", "usage.json", "outcome.json"])
@pytest.mark.parametrize("concurrency", [1, 2])
def test_archive_io_failure_stops_queued(
    frozen: FrozenExperiment,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file: str,
    concurrency: int,
) -> None:
    f = compile_batch(
        frozen.model_copy(
            update={
                "campaign": frozen.campaign.model_copy(
                    update={
                        "budget": frozen.campaign.budget.model_copy(
                            update={"concurrency": concurrency}
                        )
                    }
                )
            }
        )
    )
    original = sender.durable

    def fail(path: Path, raw: bytes) -> None:
        if path.name == file:
            raise OSError("INJECTED_ARCHIVE_FAILURE")
        original(path, raw)

    monkeypatch.setattr(sender, "durable", fail)
    result = runner(tmp_path, f).run(f, scenario=plan(f))
    assert result["stop_reason"] and result["mock_attempts"] <= concurrency
    assert (
        sum(r["status"] == "NOT_ATTEMPTED" for r in result["rows"]) >= 4 - concurrency
    )


def test_completed_content_failure_batches_continue(
    frozen: FrozenExperiment, tmp_path: Path
) -> None:
    first = runner(tmp_path, frozen).run(frozen, scenario=plan(frozen))
    nxt = compile_batch(frozen, changed=True)
    second = runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))
    assert first["mock_attempts"] == second["mock_attempts"] == 4
    assert second["campaign_reserved_attempts"] == 8
    assert first["stop_reason"] is second["stop_reason"] is None
    assert all(r["sender_status"] == "CONTENT_OR_SCHEMA_FAILURE" for r in first["rows"])
    with pytest.raises(ValueError, match="REQUEST_ALREADY_CONSUMED"):
        runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))


@pytest.mark.parametrize("concurrency", [1, 2])
def test_stop_io_failure_queued_transport_zero(
    frozen: FrozenExperiment,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concurrency: int,
) -> None:
    f = compile_batch(
        frozen.model_copy(
            update={
                "campaign": frozen.campaign.model_copy(
                    update={
                        "budget": frozen.campaign.budget.model_copy(
                            update={"concurrency": concurrency}
                        )
                    }
                )
            }
        )
    )
    record = TraceRecorder.record
    stopped = threading.Event()
    calls: list[str] = []
    original = sender.durable

    def fail_stop(self: TraceRecorder, relative: str, value: Any) -> None:
        if relative == "STOP.json":
            stopped.set()
            raise OSError("INJECTED_STOP_IO")
        record(self, relative, value)

    def delay_second(path: Path, raw: bytes) -> None:
        if path.name == "invocation.json" and path.parent.name == f.requests[1].run_id:
            assert stopped.wait(10)
        original(path, raw)

    monkeypatch.setattr(TraceRecorder, "record", fail_stop)
    monkeypatch.setattr(sender, "durable", delay_second)

    class Scenario(OfflineScenario):
        def transport(self, request: Any) -> httpx.MockTransport:
            def respond(wire: httpx.Request) -> httpx.Response:
                calls.append(request.run_id)
                raise httpx.ReadTimeout("OFFLINE_UNKNOWN", request=wire)

            return httpx.MockTransport(respond)

    with pytest.raises(OSError, match="CAMPAIGN_STOP_PERSISTENCE_FAILED"):
        runner(tmp_path, f).run(f, scenario=Scenario({}, 0))
    assert calls == [f.requests[0].run_id]
    nxt = compile_batch(f, changed=True)
    with pytest.raises(ValueError, match="UNRESOLVED_PREVIOUS_SEND"):
        runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))


def test_inflight_sibling_can_finish_after_stop(
    frozen: FrozenExperiment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrived = threading.Barrier(2)
    stopped = threading.Event()
    original = TraceRecorder.record

    def mark(self: TraceRecorder, relative: str, value: Any) -> None:
        original(self, relative, value)
        if relative == "STOP.json":
            stopped.set()

    monkeypatch.setattr(TraceRecorder, "record", mark)
    normal = plan(frozen)
    calls: list[str] = []

    class Scenario(OfflineScenario):
        def transport(self, request: Any) -> httpx.MockTransport:
            transport = normal.transport(request)

            def respond(wire: httpx.Request) -> httpx.Response:
                calls.append(request.run_id)
                arrived.wait(10)
                if request.run_id == frozen.requests[0].run_id:
                    raise httpx.ReadTimeout("OFFLINE_UNKNOWN", request=wire)
                assert stopped.wait(10)
                return transport.handle_request(wire)

            return httpx.MockTransport(respond)

    result = runner(tmp_path, frozen).run(frozen, scenario=Scenario({}, 0))
    assert len(calls) == 2
    assert result["rows"][0]["status"] == "SYSTEM_FAILURE"
    assert result["rows"][1]["status"] == "RESPONSE_CAPTURED"
    assert all(r["status"] == "NOT_ATTEMPTED" for r in result["rows"][2:])
    assert (
        Path(result["archive"]) / frozen.requests[1].run_id / "terminal.json"
    ).exists()


def test_complete_batches_do_not_refund_budget(
    frozen: FrozenExperiment, tmp_path: Path
) -> None:
    f = compile_batch(
        frozen.model_copy(
            update={
                "campaign": frozen.campaign.model_copy(
                    update={
                        "budget": frozen.campaign.budget.model_copy(
                            update={"max_attempts": 4}
                        )
                    }
                )
            }
        )
    )
    first = runner(tmp_path, f).run(f, scenario=plan(f))
    assert first["mock_attempts"] == 4
    nxt = compile_batch(f, changed=True)
    second = runner(tmp_path, nxt).run(nxt, scenario=plan(nxt))
    assert second["mock_attempts"] == 0
    assert second["stop_reason"] == "BUDGET_EXCEEDED"
    assert second["campaign_reserved_attempts"] == 4
