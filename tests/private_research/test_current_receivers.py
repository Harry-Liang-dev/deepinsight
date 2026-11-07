"""Exact12 Owner installation and actual original access checks; offline only."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from research_eval import receivers as r
from research_eval.claim_campaign import compile_candidate
from research_eval.compiler import profile
from research_eval.models import encoded
from src.memory.delivery import record_checkpoint
from src.memory.vnext_contracts import Scope
from src.models.enums import ResearchScopeType
from src.models.types import JsonObject
from src.schemas.research_v2_shared import digest
from src.services.llm_provider import LLMProviderCall
from src.services.native_preservation import blob_hash
from tools import evidence_v2_runtime as base
from tools import g107_matrix as engine
from tools import g113_r3_execute as sender
from tools import g113_r5_replay as dev
from tools.g111_r1_msft import MSFTMemory
from tools.g113_r1_prepare import check_delivery
from tools.g113_r7_memory import population_receipt

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("DEEPINSIGHT_PRIVATE_REGRESSION_ROOT"),
    reason="Requires separately retained licensed evidence; never shipped publicly",
)


def inject_f01(memory: MSFTMemory) -> dict[str, Any]:
    """Genuine foreign quote/hash/locator; ONLY the synthetic association is false."""
    fact = next(f for f in memory.facts if f.get("numeric_observation") is not None)
    evidence = next(
        e
        for f in memory.facts
        for e in f["evidence"]
        if e not in fact["evidence"] and e["source_id"] == "G105-GET-05"
    )
    memory.validate_support(evidence)
    row = dict(
        fact_id=fact["id"],
        memory_id=memory.id_map()[fact["id"]],
        evidence=evidence,
        created_at=memory.at.isoformat(),
        qualification="FROZEN_OBSERVATION_SOURCE_CONTEXT",
    )
    stream = "g111-r1-support"
    memory.journal.append(
        stream,
        digest((row["fact_id"], row["evidence"])),
        json.dumps(row, sort_keys=True),
        len(memory.journal.entries(stream)),
    )
    return row


@pytest.fixture(scope="module")
def installed(
    tmp_path_factory: pytest.TempPathFactory,
) -> r.CurrentCampaignReceiverFactory:
    root = tmp_path_factory.mktemp("exact12-receivers")
    f = compile_candidate(ROOT, root / "freeze")
    return r.CurrentCampaignReceiverFactory.install(
        f, root / "instance", root / "receivers"
    )


def test_exact_twelve_reopen_actual_access_and_population(installed: Any) -> None:
    factory = r.CurrentCampaignReceiverFactory(
        installed.frozen,
        installed.instance,
        installed.output,
        blob_hash((installed.output / "RECEIVER_INSTALLATION.json").read_bytes()),
    )
    assert len(factory.runtime().journal.entries(dev.GRANTS)) == 12
    assert not factory.authority().engineering_fixture
    for q in factory.frozen.requests:
        case = next(c for c in factory.frozen.dataset.cases if c.case_id == q.case_id)
        receipt = factory.authority().check(case, q)
        assert receipt and factory.checker(q).claim.statement == case.full_claim
    pop = population_receipt(factory.runtime())
    assert [
        pop[k]
        for k in (
            "memory_count",
            "msft_observation_count",
            "source_support_count",
            "relation_count",
        )
    ] == [27, 11, 13, 4]
    assert [q.raw_body for q in factory.frozen.requests] == [
        q.raw_body for q in r.parent().requests
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_action", "WRITE"),
        ("asset_scope", "ASSET:US:META"),
        ("freeze_identity", "0" * 64),
        ("expires_at", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_registration_cannot_widen(installed: Any, field: str, value: str) -> None:
    plan = deepcopy(installed.runtime().record["campaign_registration"])
    plan[field] = value
    with pytest.raises(ValueError):
        r.validate_registration(plan)


@pytest.mark.parametrize(
    "field", ["claim", "rights_fingerprint", "request_sha256", "research_as_of", "role"]
)
def test_exact_claim_rights_source_and_request_membership(
    installed: Any, field: str
) -> None:
    plan = deepcopy(installed.runtime().record["campaign_registration"])
    plan["receivers"][0][field] = "drift"
    with pytest.raises(ValueError, match="MEMBERSHIP"):
        r.validate_registration(plan)


def test_no_thirteenth_wrong_role_or_duplicate_grant(installed: Any) -> None:
    rt = installed.runtime()
    q = installed.frozen.requests[0]
    case = installed.frozen.dataset.cases[0]
    task = installed.row(q)["operational_task_id"]
    for role, invocation in (
        ("fundamental_analyst", "thirteenth"),
        ("trader", q.run_id),
    ):
        with pytest.raises(ValueError):
            rt.receiver(role, case.research_as_of, task, invocation, datetime.now(UTC))
    with pytest.raises(ValueError, match="ALREADY_INSTALLED"):
        rt.receiver(
            "fundamental_analyst",
            case.research_as_of,
            task,
            q.run_id,
            datetime.now(UTC),
        )
    with pytest.raises(ValueError, match="PURPOSE_BOUNDARY"):
        rt.receiver(
            "fundamental_analyst",
            case.research_as_of,
            "G113-R5-NOCHANGE",
            "extra",
            datetime.now(UTC),
        )
    assert len(rt.journal.entries(dev.GRANTS)) == 12


def test_changed_request_and_missing_current_grant(
    installed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = installed.frozen.requests[0]
    with pytest.raises(ValueError, match="MEMBERSHIP"):
        installed.checker(q.model_copy(update={"request_sha256": "0" * 64}))
    rt = installed.runtime()
    original = rt.journal.entries
    monkeypatch.setattr(
        rt.journal,
        "entries",
        lambda stream: () if stream == dev.GRANTS else original(stream),
    )
    with pytest.raises(ValueError, match="GRANT_DEPENDENCY_DRIFT"):
        rt.check_root(rt.path)


def test_current_clock_expiry(installed: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class ExpiredClock:
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime.fromisoformat(
                installed.frozen.campaign.expires_at.isoformat()
            ) + timedelta(seconds=1)

    monkeypatch.setattr(r, "datetime", ExpiredClock)
    with pytest.raises(ValueError, match="EXPIRED"):
        installed.runtime()


def test_original_acl_cas_ttl_and_raw_source_reject(installed: Any) -> None:
    q = installed.frozen.requests[0]
    checker = installed.checker(q)
    rt = checker.runtime
    m, candidate, _ = sender.current_memory(
        ROOT, installed.output, checker.row, rt.authority(), catalog=checker.catalog
    )
    with pytest.raises(ValueError):
        m.access.require(
            "READ_HISTORY",
            Scope(scope_type=ResearchScopeType.ASSET, scope_id="ASSET:US:META"),
        )
    with pytest.raises(ValueError):
        m.access.require("APPEND_EVENT", m.history_scopes[0])
    with pytest.raises(ValueError, match="STALE"):
        record_checkpoint(m.journal, candidate.checkpoint, expected=())
    delivery = m.retrieve("test-expiry")
    later = max(x.record.review_due_at for x in delivery.supplied_records) + timedelta(
        days=1
    )
    with pytest.raises(ValueError, match="EXPIRED"):
        check_delivery(m, delivery, checker.catalog, later)
    assert candidate.mode == "ACTUAL_NOCHANGE"
    assert len(candidate.delta_census) == 11
    assert {x["kind"] for x in candidate.delta_census} == {"UNCHANGED"}
    assert not candidate.dispatch_authorized
    raw = (
        rt.path
        / "native/G105-GET-05"
        / (m.temporal_sources["G105-GET-05"].raw_sha256 + ".raw")
    )
    original = raw.read_bytes()
    raw.write_bytes(original + b"DISPOSABLE_SOURCE_FAULT")
    try:
        with pytest.raises(ValueError):
            checker.check(checker.registry.identity, base.SCOPE, checker.checked_at)
    finally:
        raw.write_bytes(original)


@pytest.mark.parametrize(
    "field,value",
    [
        ("permitted_source_hashes", ["0" * 64]),
        ("authority_bindings", ["0" * 64]),
        ("output_cap", 512),
    ],
)
def test_registered_policy_cannot_expand(
    installed: Any, field: str, value: Any
) -> None:
    plan = deepcopy(installed.runtime().record["campaign_registration"])
    plan["campaign_policy"][field] = value
    with pytest.raises(ValueError, match="POLICY_SCOPE"):
        r.validate_registration(plan)


def test_sdk_before_send_uses_real_current_authority(
    installed: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "SYNTHETIC_OFFLINE_ONLY")
    monkeypatch.setenv("QWEN_MODEL_NAME", "qwen3.8-flash")
    q = installed.frozen.requests[0]
    case = next(c for c in installed.frozen.dataset.cases if c.case_id == q.case_id)
    checked: list[dict[str, Any]] = []

    def before(wire: httpx.Request) -> None:
        assert wire.content == q.raw_body.encode()
        checked.append(installed.authority().check(case, q))

    text = encoded(
        dict(
            verdict="UNDETERMINED",
            evidence_handles=[],
            reasoning="Synthetic control.",
            missing_premises=["No economic inference."],
            counterevidence_handles=[],
            uncertainty="Unknown.",
        )
    ).decode()

    def transport(wire: httpx.Request) -> httpx.Response:
        assert len(checked) == 1 and not checked[0]["engineering_fixture"]
        return httpx.Response(
            200,
            json=dict(
                id="mock-current-receiver",
                object="response",
                model="qwen3.8-flash",
                status="completed",
                output=[
                    dict(
                        type="message",
                        role="assistant",
                        content=[dict(type="output_text", text=text)],
                    )
                ],
                usage=dict(input_tokens=100, output_tokens=50, total_tokens=150),
            ),
        )

    call = LLMProviderCall(
        "qwen3.8-flash",
        q.system_prompt,
        cast(JsonObject, q.input_payload),
        cast(JsonObject, q.response_schema),
    )
    target = tmp_path / "capture"
    result = engine.sample(
        dict(sample_id=q.run_id, ordinal=1, role=case.specialist_role),
        target,
        fixture_transport=httpx.MockTransport(transport),
        operation_id=installed.frozen.campaign.campaign_id,
        episode_id=installed.row(q)["episode_candidate_id"],
        call_loader=lambda _: (q.raw_body.encode(), call),
        diagnostic=lambda *_: dict(schema_valid=True, synthetic=True),
        before_send=before,
        model_profile=profile(1024),
    )
    assert result["response_received"] and not result["stop_remaining"]
    assert (target / "assistant.txt").read_bytes() == text.encode()
    assert checked


def test_last_f01_then_revocation_disposable_instance(installed: Any) -> None:
    checker = installed.checker(installed.frozen.requests[0])
    rt = checker.runtime
    m, _, _ = sender.current_memory(
        ROOT, installed.output, checker.row, rt.authority(), catalog=checker.catalog
    )
    inject_f01(m)
    with pytest.raises(ValueError, match="SOURCE_SUPPORT_MISMATCH"):
        checker.check(checker.registry.identity, base.SCOPE, checker.checked_at)
    dev.append(
        rt.journal,
        dev.REVOKED,
        {
            "instance_id": rt.record["instance_id"],
            "reason": "DISPOSABLE_TEST_REVOCATION",
        },
    )
    with pytest.raises(ValueError, match="REVOKED"):
        installed.runtime()
