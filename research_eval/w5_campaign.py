"""Executable W1/W5 integration using actual sources and strictly offline traces."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from research_eval.compiler import RequestCompiler
from research_eval.demo import runtime_identity
from research_eval.evaluation import (
    ExperimentComparator,
    FailureClusterer,
    MechanicalEvaluator,
    evaluate_archive,
    write_evaluations,
)
from research_eval.models import (
    Budget,
    Dataset,
    ExperimentSpec,
    PromptVariant,
    TrustedExperimentCampaign,
    encoded,
    identity,
)
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import CampaignReleaseGate, OfflineAuthority
from research_eval.storage import TraceRecorder
from research_eval.w5_adapter import W5_DELIVERY, W5_MANIFEST, W5_ROOT, W5Benchmark, sha

# Fixed before outcomes; exposed REGRESSION inputs, never disguised as new DEVELOPMENT.
CASES = (
    "HIST-AB-EV2-AB-DEV-C003",  # Financial quantities and denominator/scope.
    "HIST-AB-EV2-AB-DEV-C001",  # Unsupported attribution of aggregate increment.
    "HIST-AB-EV2-AB-DEV-C011",  # Document-specific scope and counterevidence.
    "HIST-AB-EV2-AB-DEV-C005",  # Conditional claim versus actual occurrence.
)


def replay_history(benchmark: W5Benchmark, output: Path) -> dict[str, Any]:
    """Evaluate every original W5 trace without routing history through a new Sender."""
    recorder = TraceRecorder(output)
    mechanical = MechanicalEvaluator(benchmark.protocol_sha256)
    rows = []
    paired: dict[str, list[tuple[Any, Any]]] = {"AB_A": [], "AB_B": []}
    started = time.perf_counter()
    for trace in benchmark.traces:
        own = benchmark.cases[trace.case_id]
        benchmark.export(own.case_id)  # Enforce published developer split policy.
        score = benchmark.port.engine.evaluate(own, trace)
        port_result = None
        if trace.assistant:
            raw = benchmark.read(trace.assistant.path)
            case = benchmark.project(own.case_id)
            local = mechanical.evaluate(case, raw, identity(trace.trace_id))
            port_result = benchmark.evaluate(case, raw, local).model_dump(mode="json")
        request = (
            benchmark.io.strict_json(benchmark.read(trace.request.path))
            if trace.request
            else None
        )
        row = dict(
            origin="HISTORICAL_REAL_RESPONSE_REPLAY",
            trace=trace.model_dump(),
            score=score.model_dump(),
            port_result=port_result,
            original_prompt_sha256=(
                sha(request["instructions"].encode()) if request else None
            ),
            mechanical_scope=(
                "New six-field diagnostics on old text "
                "are NOT original Native rescoring"
            ),
            new_provider_attempts=0,
            historical_native_preserved=True,
        )
        rows.append(row)
        if trace.variant_id in paired:
            paired[trace.variant_id].append((trace, score))
    recorder.record("original-trace-scores.json", rows)
    contrast = benchmark.comparison.compare(paired["AB_A"], paired["AB_B"])
    recorder.record("historical-ab-paired-comparison.json", contrast)
    result = dict(
        planned=len(rows),
        historical_complete_responses=sum(
            r["trace"]["execution_state"] == "COMPLETED" for r in rows
        ),
        historical_unexecuted=[
            r["trace"]["trace_id"]
            for r in rows
            if r["trace"]["execution_state"] != "COMPLETED"
        ],
        evaluated_with_original_W5_engine=len(rows),
        elapsed_seconds=time.perf_counter() - started,
        new_real_provider_executions=0,
        original_native_result_mutations=0,
        scientific_effect="NOT_DEMONSTRATED",
        original_score_file=str(output / "original-trace-scores.json"),
    )
    recorder.record("replay-receipt.json", result)
    return result


def mock_trace(
    benchmark: W5Benchmark,
    root: Path,
    request: Any,
    row: dict[str, Any],
    local: Any,
    recorder: TraceRecorder,
) -> Any:
    """Convert actual archived MockTransport entities into W5's exact trace schema."""
    own = benchmark.cases[request.case_id]
    folder = Path(row["ResultRoot"])

    def copy(name: str, kind: str) -> Any:
        raw = (folder / name).read_bytes()
        relative = "new-traces/" + request.run_id + "/" + name
        recorder.write(relative, raw)
        return benchmark.models.ArtifactRef(path=relative, sha256=sha(raw), kind=kind)

    request_ref = copy("request.raw", "NEW_MOCK_REQUEST")
    if request_ref.sha256 != request.request_sha256:
        raise ValueError("MOCK_REQUEST_DRIFT")
    response = copy("response.raw", "NEW_MOCK_HTTP_ENTITY")
    assistant = copy("assistant.txt", "NEW_MOCK_ASSISTANT")
    schema_raw = encoded(request.response_schema)
    relative = "new-traces/" + request.run_id + "/schema.json"
    recorder.write(relative, schema_raw)
    schema = benchmark.models.ArtifactRef(
        path=relative, sha256=sha(schema_raw), kind="NEW_NATIVE_SIX_FIELD_SCHEMA"
    )
    envelope = benchmark.io.strict_json((root / response.path).read_bytes())
    native = not local.failures and local.metrics["schema"].status == "PASS"
    return benchmark.models.ArchivedTrace(
        trace_id="MOCK:" + request.run_id,
        case_id=own.case_id,
        case_version=own.case_version,
        variant_id=request.variant_id,
        run_id="MOCK:W1_W5_INTEGRATION_V1",
        task_identity=benchmark.io.task_fingerprint(own),
        source_context_fingerprint=benchmark.io.case_fingerprint(own),
        research_as_of=own.research_as_of,
        rights_fingerprint=sha(benchmark.io.canonical(own.rights_and_access_profile)),
        execution_state="COMPLETED",
        request=request_ref,
        response=response,
        assistant=assistant,
        native_schema=schema,
        original_native_result=dict(
            valid=native, scope="NEW_MOCK_MECHANICAL_ONLY_NOT_SCIENTIFIC"
        ),
        model=envelope["model"],
        usage=envelope["usage"],
        latency_seconds=local.metrics["latency_seconds"].value,
        reference_cost_cny=row.get("fixed_rate_cost_reference"),
        scientific_admission=False,
    )


def run_integration(
    root: Path, output: Path, benchmark_root: Path = W5_ROOT
) -> dict[str, Any]:
    """Run genuine W5 data → unchanged W1 compiler/runner → raw trace → W5 scoring."""
    output.mkdir(parents=True, exist_ok=False)
    recorder = TraceRecorder(output)
    benchmark = W5Benchmark(benchmark_root)
    historical = replay_history(benchmark, output / "historical")
    dataset = Dataset(
        dataset_id="W5-REGRESSION-INTEGRATION-V1",
        cases=tuple(benchmark.project(k) for k in CASES),
    )
    now = datetime.now(UTC)
    campaign = TrustedExperimentCampaign(
        campaign_id="W1-W5-OFFLINE-" + now.strftime("%Y%m%dT%H%M%S%fZ"),
        execution_mode="OFFLINE",
        ledger_root=str((output / "runs").resolve()),
        source_commit=subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        runtime_hashes=runtime_identity(root),
        dataset_identity=identity(dataset),
        permitted_source_hashes=tuple(
            sorted({s.sha256 for c in dataset.cases for s in c.sources})
        ),
        authority_bindings=tuple(c.authority_binding for c in dataset.cases),
        evaluator_protocol_sha256=benchmark.protocol_sha256,
        budget=Budget(
            max_samples=4,
            max_attempts=4,
            max_tokens=4 * 1000512,
            max_reference_cost_cny=Decimal("5"),
            concurrency=2,
            requests_per_second=100,
        ),
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    prompt, prompt_provenance = benchmark.baseline_prompt()
    baseline = PromptVariant(
        variant_id="published-six-field-baseline",
        content=prompt,
        prompt_sha256=sha(prompt.encode()),
        task_types=("financial",),
        dataset_identity=identity(dataset),
        created_by="W1_EXACT_ADOPTION_OF_PUBLISHED_BASELINE",
        experiment_group="OFFLINE_INTERFACE_ONLY",
        hypothesis="Test integration; no claimed prompt optimization",
        immutable_boundary_identity=identity(campaign),
    )
    spec = ExperimentSpec(
        experiment_id="W5-regression-four",
        campaign_identity=identity(campaign),
        dataset_identity=identity(dataset),
        variant_identities=(identity(baseline),),
    )
    start = time.perf_counter()
    frozen = RequestCompiler().compile(spec, campaign, dataset, (baseline,), workers=2)
    compile_seconds = time.perf_counter() - start
    recorder.record("freeze.json", frozen)
    recorder.record("baseline-prompt-provenance.json", prompt_provenance)
    recorder.record(
        "adopted-case-map.json",
        [
            dict(
                case_id=c.case_id,
                w1_identity=identity(c),
                w5_task_identity=c.visible_input["w5_task_identity"],
                source_context=c.visible_input["w5_source_context_fingerprint"],
                rights=c.visible_input["w5_rights_fingerprint"],
                source_hashes={s.source_id: s.sha256 for s in c.sources},
                offered_handles=len(c.handles),
                raw_source_documents_included=len(c.visible_input["source_documents"]),
                live_grant=False,
            )
            for c in dataset.cases
        ],
    )
    proposal = dict(
        verdict="UNDETERMINED",
        evidence_handles=["H0006"],
        reasoning=(
            "Offline interface fixture, not a financial finding " "or model prediction."
        ),
        missing_premises=["This mock does not evaluate economic premises."],
        counterevidence_handles=[],
        uncertainty="No new real model judgement exists.",
    )
    outcomes = {}
    for index, case in enumerate(dataset.cases):
        body = dict(proposal)
        if index == 1:
            body["evidence_handles"] = ["H_FORGED"]
        text = encoded(body).decode()
        if index == 2:
            text = "```json\n" + text + "\n```"
        outcomes[baseline.variant_id + "/" + case.case_id] = dict(assistant=text)
    recorder.record(
        "mock-scenario.json",
        dict(origin="NEW_MOCK_EXECUTION", not_gold=True, outcomes=outcomes),
    )
    run = TrustedExperimentRunner(
        output / "runs",
        OfflineAuthority(expires_at=campaign.expires_at),
        CampaignReleaseGate(root),
    ).run(frozen, scenario=OfflineScenario(outcomes, delay=0.15))
    start = time.perf_counter()
    evaluations = evaluate_archive(frozen, Path(run["archive"]), evaluator=benchmark)
    write_evaluations(output / "port-results", evaluations)
    scorer_root = output / "w5-scoring-data"
    engine = benchmark.stage_evaluator(scorer_root, list(CASES))
    score_recorder = TraceRecorder(scorer_root)
    results = []
    for request, row, local in zip(
        frozen.requests, run["rows"], evaluations, strict=True
    ):
        if row["status"] != "RESPONSE_CAPTURED":
            raise ValueError("OFFLINE_INTEGRATION_SYSTEM_FAILURE")
        trace = mock_trace(benchmark, scorer_root, request, row, local, score_recorder)
        score = engine.evaluate(benchmark.cases[request.case_id], trace)
        results.append(
            dict(
                origin="NEW_MOCK_EXECUTION",
                trace=trace.model_dump(),
                score=score.model_dump(),
                real_provider_attempts=0,
                usage_origin="SIMULATED_NOT_PROVIDER_BILL",
            )
        )
    evaluate_seconds = time.perf_counter() - start
    recorder.record("new-mock-scorer-results.json", results)
    recorder.record(
        "port-comparison.json", ExperimentComparator().compare(frozen, evaluations)
    )
    recorder.record("failures.json", FailureClusterer().report(evaluations))
    development = []
    for n in range(1, 5):
        case_id = f"DEV-TASK-{n:03}"
        export = benchmark.export(case_id)
        recorder.record("development-exports/" + case_id + ".json", export)
        own = benchmark.cases[case_id]
        development.append(
            dict(
                case_id=case_id,
                task_identity=benchmark.io.task_fingerprint(own),
                source_fingerprint=benchmark.io.case_fingerprint(own),
                rights_fingerprint=sha(
                    benchmark.io.canonical(own.rights_and_access_profile)
                ),
                dataset_split=own.dataset_split,
                request_sha256=None,
                original_complete_claim=own.original_complete_claim,
                source_document_mapping=own.provenance.get("source_document_hashes"),
                required_adaptation=[
                    "Versioned question task/carrier compatible with W3",
                    "W5 published canonical raw source mapping for this exact case",
                    "W5 scorer-port acceptance for null Claim questions",
                    "Approved tool-plan versus actual tool permissions "
                    "(current runner tools empty)",
                ],
            )
        )
    recorder.record(
        "first-real-campaign-template.json",
        dict(
            status="PENDING_W3_AND_W5_CASE_BINDING_NOT_FROZEN",
            case_count=4,
            development_cases=development,
            baseline_prompt_hash=baseline.prompt_sha256,
            W3_candidate_count=0,
            W3_slots=[None, None, None],
            max_variants=4,
            max_attempts=16,
            concurrency=2,
            retry=0,
            fallback="NONE",
            actual_requests_frozen=0,
            operation=None,
            population=None,
            current_receiver_installed=False,
            live_campaign_ready=False,
        ),
    )
    result = dict(
        version="W1_W5_INTEGRATION_V1",
        w5_delivery=W5_DELIVERY,
        w5_manifest=W5_MANIFEST,
        w5_protocol=benchmark.protocol_sha256,
        source_commit=campaign.source_commit,
        origin_counts=dict(
            HISTORICAL_REAL_RESPONSE_REPLAY=historical["historical_complete_responses"],
            NEW_MOCK_EXECUTION=run["mock_attempts"],
            NEW_REAL_PROVIDER_EXECUTION=0,
        ),
        historical=historical,
        mock=dict(
            planned=4,
            completed=len(results),
            peak_inflight=run["peak_inflight"],
            archive=run["archive"],
            content_failures=sum(bool(r.failures) for r in evaluations),
            system_failures=0,
            not_attempted=0,
        ),
        performance=dict(
            compile_seconds=compile_seconds,
            dispatch_seconds=run["elapsed_seconds"],
            completed_mock_per_second=4 / run["elapsed_seconds"],
            evaluation_seconds=evaluate_seconds,
            budget_reserved_attempts=run["campaign_reserved_attempts"],
            budget_reserved_token_envelope=run["campaign_reserved_tokens"],
            reused_sdk_and_scorer=True,
            no_real_throughput_certification=True,
        ),
        W1_W5_END_TO_END_INTEGRATION="PASS_OFFLINE_REGRESSION_POPULATION",
        FINANCIAL_BENCHMARK_CONNECTED=True,
        PARALLEL_CAMPAIGN_OFFLINE_VALID=True,
        FIRST_REAL_CAMPAIGN_FREEZE_READY=False,
        LIVE_CAMPAIGN_READY=False,
        SCIENTIFIC_EFFECT_DEMONSTRATED="NOT_DEMONSTRATED",
        business_writes=0,
    )
    recorder.record("integration-receipt.json", result)
    return result


def main() -> None:
    """Execute a fresh isolated offline integration; no live option or pin bypass."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_integration(Path(__file__).resolve().parents[1], args.output.resolve())
    print(
        json.dumps(
            dict(
                status=result["W1_W5_END_TO_END_INTEGRATION"],
                origins=result["origin_counts"],
                peak=result["mock"]["peak_inflight"],
            )
        )
    )


if __name__ == "__main__":
    main()
