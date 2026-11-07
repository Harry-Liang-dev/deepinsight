"""Offline platform, release, immutable trace and semantic-boundary tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from research_eval.compiler import RequestCompiler
from research_eval.demo import make_demo
from research_eval.evaluation import (
    ExperimentComparator,
    FailureClusterer,
    MechanicalEvaluator,
    collect_results,
    evaluate_archive,
    write_evaluations,
)
from research_eval.export import ExperienceExporter
from research_eval.models import (
    Dataset,
    Failure,
    FailureKind,
    FrozenExperiment,
    PromptVariant,
    encoded,
    identity,
)
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import (
    RELEASE_CONTRACT,
    CampaignReleaseGate,
    CurrentAuthorityAdapter,
    OfflineAuthority,
    release_projection,
)
from research_eval.storage import PromptRegistry, TraceRecorder
from tools import g113_r3_execute as release
from tools.minimal_semantic_carrier import MinimalSemanticProposal

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def demo(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, FrozenExperiment, dict[str, Any]]:
    folder = tmp_path_factory.mktemp("platform") / "demo"
    result = make_demo(ROOT, folder)
    frozen = FrozenExperiment.model_validate_json((folder / "freeze.json").read_bytes())
    return folder, frozen, result


def proposal(**changes: Any) -> bytes:
    obj = dict(
        verdict="UNDETERMINED",
        evidence_handles=["H1"],
        reasoning="The source does not prove the cause.",
        missing_premises=["Causal link"],
        counterevidence_handles=[],
        uncertainty="Unknown mechanism.",
    )
    obj.update(changes)
    return encoded(obj)


def rebind(frozen: FrozenExperiment, **changes: Any) -> FrozenExperiment:
    data = frozen.campaign.model_dump(mode="json")
    data.update(changes)
    campaign = type(frozen.campaign).model_validate(data)
    variants = tuple(
        v.model_copy(update={"immutable_boundary_identity": identity(campaign)})
        for v in frozen.variants
    )
    spec = frozen.spec.model_copy(
        update={
            "campaign_identity": identity(campaign),
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    return RequestCompiler().compile(spec, campaign, frozen.dataset, variants)


def test_parallel_sdk_demo_and_full_denominator(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    folder, frozen, result = demo
    assert result["run"]["peak_inflight"] >= 2
    assert result["run"]["mock_attempts"] == 6
    assert result["run"]["real_provider_attempts"] == 0
    assert result["comparison"]["planned"] == 6
    assert all(r["status"] == "RESPONSE_CAPTURED" for r in result["run"]["rows"])
    assert (
        result["comparison"]["variants"]["baseline"]["source_selection"]["counts"][
            "FAIL"
        ]
        == 1
    )
    assert (
        result["comparison"]["variants"]["candidate"]["source_selection"]["counts"].get(
            "FAIL", 0
        )
        == 0
    )
    assert (
        result["comparison"]["variants"]["candidate"]["verdict_reasoning_consistency"][
            "counts"
        ]["UNKNOWN"]
        == 3
    )
    RequestCompiler().verify(frozen)
    assert len(list((folder / "evaluations").glob("*.json"))) == 6


@pytest.mark.parametrize(
    "raw",
    [
        b"```json\n{}\n```",
        b'{"a":1,"a":2}',
        b"{} {}",
        b'{"a":',
        b"not json",
        b'{"a":NaN}',
    ],
)
def test_strict_invalid_preservation(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], raw: bytes
) -> None:
    _, frozen, _ = demo
    before = hashlib.sha256(raw).hexdigest()
    result = MechanicalEvaluator("0" * 64).evaluate(
        frozen.dataset.cases[0], raw, "1" * 64
    )
    assert result.failures[0].kind == FailureKind.PROTOCOL_FAILURE
    assert hashlib.sha256(raw).hexdigest() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("uncertainty", None),
        ("evidence_handles", "H1"),
        ("verdict", "UNKNOWN"),
        ("extra", True),
    ],
)
def test_schema_is_separate(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], field: str, value: Any
) -> None:
    _, frozen, _ = demo
    result = MechanicalEvaluator("0" * 64).evaluate(
        frozen.dataset.cases[0], proposal(**{field: value}), "1" * 64
    )
    assert result.metrics["json"].status == "PASS"
    assert result.metrics["schema"].status == "FAIL"
    assert any(f.pointer == "/" + field for f in result.failures)


def test_task_compatible_empty_uncertainty_without_historical_repair(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    raw = proposal(uncertainty="")
    with pytest.raises(ValidationError):
        MinimalSemanticProposal.model_validate_json(raw)
    check = MechanicalEvaluator("0" * 64)
    tech = check.evaluate(frozen.dataset.cases[0], raw, "1" * 64)
    finance = check.evaluate(frozen.dataset.cases[1], raw, "2" * 64)
    assert tech.metrics["schema"].status == finance.metrics["schema"].status == "PASS"
    assert tech.metrics["local_guard"].status == "PASS"
    assert finance.metrics["local_guard"].status == "FAIL"
    assert finance.failures[0].pointer == "/uncertainty"


@pytest.mark.parametrize(
    "changes,kind",
    [
        ({"evidence_handles": ["H_FAKE"]}, FailureKind.EVIDENCE_RESOLUTION_FAILURE),
        (
            {"reasoning": "Amount 999999 million."},
            FailureKind.NUMERIC_GROUNDING_FAILURE,
        ),
        ({"reasoning": ""}, FailureKind.LOCAL_GUARD_FAILURE),
        ({"evidence_handles": ["H1", "H1"]}, FailureKind.LOCAL_GUARD_FAILURE),
        ({"verdict": "SUPPORTED"}, FailureKind.UNSUPPORTED_CAUSAL_ACCEPTANCE),
    ],
)
def test_precise_mechanical_failures(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
    changes: dict[str, Any],
    kind: FailureKind,
) -> None:
    _, frozen, _ = demo
    r = MechanicalEvaluator("0" * 64).evaluate(
        frozen.dataset.cases[1], proposal(**changes), "1" * 64
    )
    assert kind in {f.kind for f in r.failures}
    assert r.scientific_admission is False


def test_c003_semantics_requires_evaluator_not_keywords(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    raw = proposal(
        verdict="SUPPORTED",
        missing_premises=[],
        reasoning="The evidence cannot establish the complete claim.",
    )
    r = MechanicalEvaluator("0" * 64).evaluate(frozen.dataset.cases[1], raw, "1" * 64)
    assert r.metrics["verdict_reasoning_consistency"].status == "UNKNOWN"
    annotation = r.model_copy(
        update={
            "evaluator_id": "synthetic-evaluator-contract-test",
            "provenance": "INTERNAL_PRECHECK",
            "gold_status": "DEVELOPMENT_EXPECTATION",
            "failures": (
                Failure(
                    kind=FailureKind.VERDICT_REASONING_CONTRADICTION,
                    pointer="/verdict",
                    rule="EXPLICIT_SYNTHETIC_ANNOTATION_NOT_FINANCIAL_GOLD",
                ),
            ),
        }
    )
    assert "VERDICT_REASONING_CONTRADICTION" in str(
        FailureClusterer().report([annotation])
    )


def test_prompt_registry_hash_immutability(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, frozen, _ = demo
    v = frozen.variants[0]
    registry = PromptRegistry(tmp_path)
    assert registry.register(v) == registry.register(v)
    changed = v.model_dump()
    changed.update(
        content="Different", prompt_sha256=hashlib.sha256(b"Different").hexdigest()
    )
    with pytest.raises(ValueError, match="IMMUTABLE"):
        registry.register(PromptVariant.model_validate(changed))
    with pytest.raises(ValidationError):
        PromptVariant.model_validate(dict(v.model_dump(), prompt_sha256="0" * 64))
    with pytest.raises(ValidationError):
        PromptVariant.model_validate(dict(v.model_dump(), authorized=True))
    with pytest.raises(ValueError):
        registry.load("../escape")


def test_prompt_cannot_expand_source_or_endpoint(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    with pytest.raises(ValidationError):
        type(frozen.campaign).model_validate(
            dict(frozen.campaign.model_dump(), endpoint="https://other.invalid")
        )
    with pytest.raises(ValueError, match="SOURCE_OR_AUTHORITY"):
        rebind(frozen, permitted_source_hashes=[])
    with pytest.raises(ValueError, match="POPULATION_BUDGET"):
        rebind(frozen, budget=dict(frozen.campaign.budget.model_dump(), max_samples=1))


def test_request_drift_and_duplicate_compile(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    changed = frozen.model_copy(
        update={
            "requests": (
                frozen.requests[0].model_copy(update={"raw_body": "{}"}),
                *frozen.requests[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="FROZEN_REQUEST_DRIFT"):
        RequestCompiler().verify(changed)
    v = frozen.variants[0].model_copy(update={"variant_id": "different-name"})
    spec = frozen.spec.model_copy(
        update={
            "variant_identities": tuple(identity(x) for x in (frozen.variants[0], v))
        }
    )
    with pytest.raises(ValueError, match="DUPLICATE_REQUEST"):
        RequestCompiler().compile(
            spec, frozen.campaign, frozen.dataset, (frozen.variants[0], v)
        )


@pytest.mark.parametrize("failure", ["expired", "revoked", "cas", "source"])
def test_current_authority_fail_closed(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path, failure: str
) -> None:
    folder, frozen, _ = demo
    policy = dict(frozen.campaign.budget.model_dump(), concurrency=1)
    f = rebind(frozen, budget=policy)
    authority = OfflineAuthority(
        expires_at=datetime.now(UTC)
        + timedelta(days=-1 if failure == "expired" else 1),
        denied=(
            frozenset({f.dataset.cases[0].case_id})
            if failure == "revoked"
            else frozenset()
        ),
        stale_cas=failure == "cas",
    )
    if failure == "source":
        # Tampering occurs in a fresh temporary copy of the synthetic source only.
        original = Path(f.dataset.cases[0].sources[0].path)
        raw = original.read_bytes()
        original.write_bytes(b"changed synthetic")
    try:
        result = TrustedExperimentRunner(
            tmp_path, authority, CampaignReleaseGate(ROOT)
        ).run(
            f,
            scenario=OfflineScenario(
                json.loads((folder / "scenario.json").read_bytes())
            ),
        )
        assert result["mock_attempts"] == 0
        assert result["stop_reason"] is not None
        assert len(result["rows"]) == 6
    finally:
        if failure == "source":
            original.write_bytes(raw)


@pytest.mark.parametrize("system_error", ["UNKNOWN_SEND", "MISSING_USAGE"])
def test_unknown_send_consumed_and_stops(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
    tmp_path: Path,
    system_error: str,
) -> None:
    folder, frozen, _ = demo
    f = rebind(frozen, budget=dict(frozen.campaign.budget.model_dump(), concurrency=1))
    plan = json.loads((folder / "scenario.json").read_bytes())
    plan["baseline/technical"]["system_error"] = system_error
    runner = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    )
    result = runner.run(f, scenario=OfflineScenario(plan))
    assert result["mock_attempts"] == 1 and result["stop_reason"]
    assert sum(r["status"] == "NOT_ATTEMPTED" for r in result["rows"]) == 5
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        runner.run(f, scenario=OfflineScenario(plan))


def test_budget_exhaustion_before_send(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    folder, frozen, _ = demo
    f = rebind(
        frozen,
        budget=dict(frozen.campaign.budget.model_dump(), max_tokens=1, concurrency=1),
    )
    r = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    ).run(
        f, scenario=OfflineScenario(json.loads((folder / "scenario.json").read_bytes()))
    )
    assert r["mock_attempts"] == 0 and r["stop_reason"]


def test_no_live_releases_or_current_receiver(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    with pytest.raises(ValueError, match="RELEASES_REQUIRED"):
        CampaignReleaseGate(ROOT).check(frozen.campaign)
    with pytest.raises(ValueError, match="NOT_INSTALLED"):
        CurrentAuthorityAdapter({}).check(frozen.dataset.cases[0], frozen.requests[0])


def test_fixture_cannot_be_live(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, frozen, _ = demo
    f = frozen.model_copy(
        update={"spec": frozen.spec.model_copy(update={"mode": "LIVE"})}
    )
    with pytest.raises(ValueError, match="CAMPAIGN_EXECUTION_MODE|FIXTURE_LIVE"):
        TrustedExperimentRunner(
            tmp_path,
            OfflineAuthority(expires_at=f.campaign.expires_at),
            CampaignReleaseGate(ROOT),
        ).run(f)


def fixture_pin(
    tmp_path: Path, issuer: str, frozen: FrozenExperiment
) -> release.ReviewPin:
    policy = release_projection(frozen.campaign)
    directory = tmp_path / issuer
    directory.mkdir()
    receipt = dict(
        policy,
        issuer=issuer,
        status="PASS",
        source_commit=frozen.campaign.source_commit,
        freeze_sha256=hashlib.sha256(encoded(policy)).hexdigest(),
        issued_at=datetime.now(UTC).isoformat(),
        scope=(
            "EVAL_CAMPAIGN_RUNNER_SOURCE_AND_AUTHORITY"
            if issuer == "W4"
            else "EVAL_CAMPAIGN_DATASET_AND_EVALUATOR_PROTOCOL"
        ),
        context_fit_unknown_acknowledged=True,
    )
    raw = encoded(receipt)
    (directory / "receipt.json").write_bytes(raw)
    manifest = encoded(
        dict(files=[dict(path="receipt.json", sha256=hashlib.sha256(raw).hexdigest())])
    )
    (directory / "manifest.json").write_bytes(manifest)
    return release.ReviewPin(
        issuer,
        directory,
        "receipt.json",
        hashlib.sha256(raw).hexdigest(),
        "manifest.json",
        hashlib.sha256(manifest).hexdigest(),
        engineering_fixture=True,
    )


def test_reusable_contract_fixture_precheck_not_live(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, frozen, _ = demo
    pins = tuple(fixture_pin(tmp_path, x, frozen) for x in ("W4", "W5"))
    assert (
        len(
            release.reviews(
                pins,
                release_projection(frozen.campaign),
                frozen.campaign.source_commit,
                fixture=True,
                release_contract=RELEASE_CONTRACT,
            )
        )
        == 2
    )
    with pytest.raises(ValueError, match="PROVENANCE"):
        release.reviews(
            pins,
            release_projection(frozen.campaign),
            frozen.campaign.source_commit,
            fixture=False,
            release_contract=RELEASE_CONTRACT,
        )
    with pytest.raises(ValueError):
        release.reviews(
            pins[:1],
            release_projection(frozen.campaign),
            frozen.campaign.source_commit,
            fixture=True,
            release_contract=RELEASE_CONTRACT,
        )
    changed = frozen.campaign.model_copy(update={"evaluator_protocol_sha256": "0" * 64})
    with pytest.raises(ValueError):
        release.reviews(
            pins,
            release_projection(changed),
            frozen.campaign.source_commit,
            fixture=True,
            release_contract=RELEASE_CONTRACT,
        )
    with pytest.raises(ValueError):
        release.reviews(
            pins,
            release_projection(frozen.campaign),
            frozen.campaign.source_commit,
            fixture=True,
            release_contract="MINIMAL2_TWO_PROBE_V1",
        )


def test_result_dedup_export_and_unknown_gold(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, frozen, result = demo
    archive = Path(result["run"]["archive"])
    results = evaluate_archive(frozen, archive)
    write_evaluations(tmp_path, results)
    files = list(tmp_path.glob("*.json"))
    assert len(collect_results(frozen, archive, files + files)) == 6
    with pytest.raises(ValueError):
        ExperimentComparator().compare(frozen, results[:1])
    export = ExperienceExporter().export(frozen, archive, results, "PREFERENCE")
    assert len(export) == 6 and all(
        x.chosen is None and x.reward is None and not x.training_eligible
        for x in export
    )
    forged = results[0].model_copy(update={"provenance": "W5_INDEPENDENT"})
    path = tmp_path / "forged.json"
    path.write_bytes(encoded(forged))
    with pytest.raises(ValueError, match="ISSUANCE_NOT_INSTALLED"):
        collect_results(frozen, archive, [path])


def test_archive_exclusive_and_path(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    recorder.write("raw", b"original")
    with pytest.raises(FileExistsError):
        recorder.write("raw", b"repair")
    with pytest.raises(ValueError):
        recorder.write("../escape", b"bad")


def test_holdout_and_future_source(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    c = frozen.dataset.cases[0]
    with pytest.raises(ValidationError):
        type(c).model_validate(
            dict(c.model_dump(), research_as_of=datetime(2000, 1, 1, tzinfo=UTC))
        )
    with pytest.raises(ValidationError):
        Dataset.model_validate(
            dict(frozen.dataset.model_dump(), cases=[c.model_dump(), c.model_dump()])
        )


def test_cli_entry_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "research_eval", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and "campaign" in result.stdout


def test_content_failure_does_not_stop_independent_samples(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    folder, frozen, _ = demo
    plan = json.loads((folder / "scenario.json").read_bytes())
    plan["baseline/technical"]["assistant"] = "```json\n{}\n```"
    result = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=frozen.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    ).run(frozen, scenario=OfflineScenario(plan))
    assert result["mock_attempts"] == 6 and result["stop_reason"] is None
    evaluated = evaluate_archive(frozen, Path(result["archive"]))
    assert evaluated[0].metrics["json"].status == "FAIL"
    assert len(evaluated) == 6


def test_campaign_rejects_new_experiment_for_consumed_body(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    folder, frozen, _ = demo
    plan = json.loads((folder / "scenario.json").read_bytes())
    f = rebind(
        frozen,
        budget=dict(
            frozen.campaign.budget.model_dump(),
            max_samples=12,
            max_attempts=12,
            max_tokens=12 * 1000512,
            max_reference_cost_cny="14",
        ),
    )
    runner = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    )
    runner.run(f, scenario=OfflineScenario(plan))
    next_spec = f.spec.model_copy(update={"experiment_id": "renamed-experiment"})
    other = RequestCompiler().compile(next_spec, f.campaign, f.dataset, f.variants)
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        runner.run(other, scenario=OfflineScenario(plan))


def test_unknown_send_persistently_stops_new_prompts(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    folder, frozen, _ = demo
    plan = json.loads((folder / "scenario.json").read_bytes())
    plan["baseline/technical"]["system_error"] = "UNKNOWN_SEND"
    f = rebind(
        frozen,
        budget=dict(
            frozen.campaign.budget.model_dump(),
            concurrency=1,
            max_samples=12,
            max_attempts=12,
            max_tokens=12 * 1000512,
            max_reference_cost_cny="14",
        ),
    )
    runner = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    )
    runner.run(f, scenario=OfflineScenario(plan))
    variants = tuple(
        v.model_copy(
            update={
                "content": v.content + " New candidate.",
                "prompt_sha256": hashlib.sha256(
                    (v.content + " New candidate.").encode()
                ).hexdigest(),
            }
        )
        for v in f.variants
    )
    spec = f.spec.model_copy(
        update={
            "experiment_id": "second",
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    other = RequestCompiler().compile(spec, f.campaign, f.dataset, variants)
    with pytest.raises(ValueError, match="CAMPAIGN_STOPPED"):
        runner.run(other, scenario=OfflineScenario(plan))


def test_holdout_cannot_compile_with_forged_visible_flag(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, _ = demo
    dataset = frozen.dataset.model_copy(
        update={
            "cases": tuple(
                c.model_copy(update={"holdout": True}) for c in frozen.dataset.cases
            )
        }
    )
    campaign = frozen.campaign.model_copy(
        update={"dataset_identity": identity(dataset)}
    )
    variants = tuple(
        v.model_copy(
            update={
                "dataset_identity": identity(dataset),
                "immutable_boundary_identity": identity(campaign),
            }
        )
        for v in frozen.variants
    )
    spec = frozen.spec.model_copy(
        update={
            "campaign_identity": identity(campaign),
            "dataset_identity": identity(dataset),
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    with pytest.raises(ValueError, match="HOLDOUT_AUTHORITY"):
        RequestCompiler().compile(spec, campaign, dataset, variants)


def test_no_independent_gold_import_from_worker(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, frozen, result = demo
    archive = Path(result["run"]["archive"])
    r = evaluate_archive(frozen, archive)[0]
    forged = r.model_copy(
        update={"trace_sha256": "0" * 64, "gold_status": "INDEPENDENT"}
    )
    path = tmp_path / "forged.json"
    path.write_bytes(encoded(forged))
    with pytest.raises(
        ValueError, match="WORKER_RESULT_IDENTITY|INDEPENDENT_GOLD_PROVENANCE"
    ):
        collect_results(frozen, archive, [path])


def test_source_f01_projection_rejects_other_observation_handle(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    from types import SimpleNamespace

    from tools.evidence_v2_runtime import CurrentAccessChecker

    _, frozen, _ = demo
    c = frozen.dataset.cases[1]
    request = frozen.requests[1]
    checker = cast(Any, object.__new__(CurrentAccessChecker))
    checker.row = {"invocation_candidate_id": request.run_id, "role": c.specialist_role}
    checker.claim = SimpleNamespace(statement=c.full_claim)
    checker.packet = {"trusted_research_as_of": c.research_as_of.isoformat()}
    checker.registry = SimpleNamespace(
        entries={
            "H1": SimpleNamespace(
                source_id="WRONG_OBSERVATION_SOURCE", allowed_scope="TEST"
            )
        }
    )
    adapter = CurrentAuthorityAdapter(
        {c.case_id: (c.authority_binding, "TEST", lambda _: checker)}
    )
    with pytest.raises(ValueError, match="F01_HANDLE_SOURCE_BINDING"):
        adapter.check(c, request)


@pytest.mark.parametrize("index", range(24))
def test_actual_24_failure_metadata_is_immutable(index: int) -> None:
    private_root = os.environ.get("DEEPINSIGHT_PRIVATE_REGRESSION_ROOT")
    if not private_root:
        pytest.skip("Private immutable model archives are not distributed publicly")
    evidence = json.loads(
        (
            Path(private_root) / "artifacts/eval-platform/HISTORICAL_REGRESSION.json"
        ).read_bytes()
    )
    row = evidence["AB_original_failures"][index]
    assert row["original_native_status"] == "FAIL"
    assert row["pointer"] == "/proposals"
    assert (
        hashlib.sha256(Path(row["original_path"]).read_bytes()).hexdigest()
        == row["raw_sha256"]
    )
    assert row["original_result_changed"] is False


def test_metrics_include_observed_usage_without_scientific_score(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, frozen, result = demo
    scores = evaluate_archive(frozen, Path(result["run"]["archive"]))
    assert sum(r.metrics["input_tokens"].value or 0 for r in scores) == 600
    assert all(
        r.metrics["input_tokens"].evidence == ("SIMULATED_USAGE",) for r in scores
    )
    assert all(r.metrics["task_completion"].status == "UNKNOWN" for r in scores)


def test_durable_budget_across_new_prompt_batches(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    folder, frozen, _ = demo
    plan = json.loads((folder / "scenario.json").read_bytes())
    f = rebind(
        frozen,
        budget=dict(
            frozen.campaign.budget.model_dump(),
            concurrency=1,
            max_samples=12,
            max_attempts=7,
            max_tokens=12 * 1000512,
            max_reference_cost_cny="14",
        ),
    )
    runner = TrustedExperimentRunner(
        tmp_path,
        OfflineAuthority(expires_at=f.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    )
    first = runner.run(f, scenario=OfflineScenario(plan))
    assert first["mock_attempts"] == 6
    variants = tuple(
        v.model_copy(
            update={
                "content": v.content + " Additional policy.",
                "prompt_sha256": hashlib.sha256(
                    (v.content + " Additional policy.").encode()
                ).hexdigest(),
            }
        )
        for v in f.variants
    )
    spec = f.spec.model_copy(
        update={
            "experiment_id": "next-batch",
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    other = RequestCompiler().compile(spec, f.campaign, f.dataset, variants)
    second = runner.run(other, scenario=OfflineScenario(plan))
    assert second["mock_attempts"] == 1 and second["campaign_reserved_attempts"] == 7
    assert second["stop_reason"] and len(second["rows"]) == 6


def test_authority_is_checked_after_rate_reservation(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_eval.runner import BudgetController

    folder, frozen, _ = demo
    events: list[str] = []
    old_reserve = BudgetController.reserve

    def reserve(self: BudgetController, request: Any) -> None:
        old_reserve(self, request)
        events.append("reserve:" + request.run_id)

    monkeypatch.setattr(BudgetController, "reserve", reserve)

    class Checked(OfflineAuthority):
        def check(self, case: Any, request: Any) -> dict[str, Any]:
            assert "reserve:" + request.run_id in events
            return super().check(case, request)

    result = TrustedExperimentRunner(
        tmp_path,
        Checked(expires_at=frozen.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    ).run(
        frozen,
        scenario=OfflineScenario(json.loads((folder / "scenario.json").read_bytes())),
    )
    assert result["mock_attempts"] == 6


def test_stop_during_authority_check_prevents_dispatch(
    demo: tuple[Path, FrozenExperiment, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_eval.runner import BudgetController

    folder, frozen, _ = demo
    controllers: list[BudgetController] = []
    original = BudgetController.reserve

    def reserve(self: BudgetController, request: Any) -> None:
        original(self, request)
        controllers.append(self)

    monkeypatch.setattr(BudgetController, "reserve", reserve)

    class Interrupted(OfflineAuthority):
        def check(self, case: Any, request: Any) -> dict[str, Any]:
            receipt = super().check(case, request)
            controllers[0].stop("SIBLING_SYSTEM_FAILURE_DURING_AUTHORITY")
            return receipt

    result = TrustedExperimentRunner(
        tmp_path,
        Interrupted(expires_at=frozen.campaign.expires_at),
        CampaignReleaseGate(ROOT),
    ).run(
        frozen,
        scenario=OfflineScenario(json.loads((folder / "scenario.json").read_bytes())),
    )
    assert result["mock_attempts"] == 0
    assert result["stop_reason"] == "SIBLING_SYSTEM_FAILURE_DURING_AUTHORITY"
    assert len(result["rows"]) == 6
