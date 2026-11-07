"""First three-Prompt/four-Claim candidate; compile and dry-run without live grants."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from research_eval.compiler import RequestCompiler, profile
from research_eval.demo import runtime_identity
from research_eval.evaluation import (
    FailureClusterer,
    evaluate_archive,
    write_evaluations,
)
from research_eval.models import (
    Budget,
    Dataset,
    ExperimentSpec,
    FrozenExperiment,
    PromptVariant,
    TrustedExperimentCampaign,
    encoded,
    identity,
)
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import (
    CampaignReleaseGate,
    CurrentAuthorityAdapter,
    OfflineAuthority,
    release_projection,
)
from research_eval.storage import PromptRegistry, TraceRecorder
from research_eval.w5_adapter import sha
from research_eval.w5_calibrated import (
    CASES,
    DELIVERY,
    MANIFEST,
    PROFILE,
    CalibratedBenchmark,
    CalibratedComparator,
)
from src.services.development_model_profile import reference_cost

W3_ROOT = Path(
    os.environ.get(
        "DEEPINSIGHT_W3_PROMPT_ROOT",
        str(Path.home() / ".local/share/deepinsight/prompt-delivery-v1"),
    )
)
W3_SOURCE = "6299d7d5cc5dcf56b85524350d4e841d1d0b98d1"
W3_DELIVERY = "0ffedb96925d5792147f6e0f1c98961b2287e791"
W3_MANIFEST = "27e0e12e7dc0c740f26bf2aac66c7cb5c8a919f1d1a4c23eb918bfed5b624e9a"
VARIANTS = ("W1_MINIMAL2_FINANCIAL_CORE_V1", "w3-causal-v1", "w3-b-evidence-v1")


def git(root: Path, *args: str) -> bytes:
    """Read actual local Git objects, never substitute a receipt string."""
    return subprocess.check_output(["git", "-C", str(root), *args])


def adopt_prompts(
    benchmark: CalibratedBenchmark, root: Path = W3_ROOT
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Adopt original W3 bytes; no planning prompt or context intervention."""
    raw = (root / "EVIDENCE_MANIFEST.json").read_bytes()
    if (
        sha(raw) != W3_MANIFEST
        or git(root, "show", W3_DELIVERY + ":EVIDENCE_MANIFEST.json") != raw
    ):
        raise ValueError("W3_MANIFEST_DRIFT")
    manifest = json.loads(raw)
    if manifest["source_commit"] != W3_SOURCE:
        raise ValueError("W3_SOURCE_DRIFT")
    files = {f["path"]: f for f in manifest["files"]}
    for p, row in files.items():
        body = (root / p).read_bytes()
        if sha(body) != row["sha256"] or git(root, "show", W3_SOURCE + ":" + p) != body:
            raise ValueError("W3_PUBLISHED_BLOB_DRIFT")
    bundle = json.loads((root / "PROMPT_CANDIDATE_BUNDLE.json").read_bytes())
    baseline = json.loads((root / "BASELINE_IDENTITY.json").read_bytes())
    prompt, provenance = benchmark.baseline_prompt()
    if sha(prompt.encode()) != baseline["prompt_sha256"]:
        raise ValueError("BASELINE_DRIFT")
    rows = [
        dict(
            variant_id=VARIANTS[0],
            content=prompt,
            prompt_sha256=sha(prompt.encode()),
            hypothesis="Original published baseline",
            parent_variant_id=None,
            provenance=provenance,
        )
    ]
    for variant_id in VARIANTS[1:]:
        matches = [
            c for c in bundle["candidates"] if c["metadata"]["variant_id"] == variant_id
        ]
        if len(matches) != 1:
            raise ValueError("W3_CANDIDATE_MEMBERSHIP")
        candidate = matches[0]
        meta = candidate["metadata"]
        ref = meta["prompt_ref"]
        body = (root / ref["path"]).read_bytes()
        if sha(body) != ref["sha256"] or ref["path"] not in files:
            raise ValueError("W3_PROMPT_DRIFT")
        rows.append(
            dict(
                variant_id=variant_id,
                content=body.decode("utf-8"),
                prompt_sha256=sha(body),
                hypothesis=meta["improvement_hypothesis"],
                parent_variant_id=meta["parent_variant_id"],
                provenance=candidate,
            )
        )
    config = json.loads((root / "shared/MODEL_CONFIG.json").read_bytes())
    if config != baseline["model_configuration"] or config["output_cap"] != 1024:
        raise ValueError("W3_COMMON_MODEL_PROFILE_DRIFT")
    return rows, dict(
        source=W3_SOURCE,
        delivery=W3_DELIVERY,
        manifest=W3_MANIFEST,
        baseline=baseline,
        model_config=config,
        variants=rows,
        planning_excluded=True,
        prompt_bytes_changed=False,
    )


def compile_candidate(root: Path, output: Path) -> FrozenExperiment:
    """Freeze a new LIVE-mode candidate with explicit uninstalled current receivers."""
    output.mkdir(parents=True, exist_ok=False)
    recorder = TraceRecorder(output)
    benchmark = CalibratedBenchmark()
    prompts, provenance = adopt_prompts(benchmark)
    dataset = Dataset(
        dataset_id="W5-CALIBRATED-CLAIM-REGRESSION-V1",
        cases=tuple(benchmark.project(c) for c in CASES),
    )
    now = datetime.now(UTC)
    campaign = TrustedExperimentCampaign(
        campaign_id="CLAIM-CAMPAIGN-V1-" + now.strftime("%Y%m%dT%H%M%S%fZ"),
        execution_mode="LIVE",
        ledger_root=str((root / "data/runtime/claim-campaign-v1/live").resolve()),
        source_commit=git(root, "rev-parse", "HEAD").decode().strip(),
        runtime_hashes=runtime_identity(root),
        dataset_identity=identity(dataset),
        permitted_source_hashes=tuple(
            sorted({s.sha256 for c in dataset.cases for s in c.sources})
        ),
        authority_bindings=tuple(c.authority_binding for c in dataset.cases),
        evaluator_protocol_sha256=benchmark.protocol_sha256,
        output_cap=1024,
        budget=Budget(
            max_samples=12,
            max_attempts=12,
            max_tokens=12 * 1001024,
            max_reference_cost_cny=Decimal("20"),
            concurrency=2,
            requests_per_second=2,
        ),
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    variants = tuple(
        PromptVariant(
            variant_id=p["variant_id"],
            parent_variant_id=p["parent_variant_id"],
            content=p["content"],
            prompt_sha256=p["prompt_sha256"],
            task_types=("financial",),
            output_cap=1024,
            dataset_identity=identity(dataset),
            created_by="EXACT_W1_W3_PUBLISHED_ADOPTION",
            experiment_group="PROMPT_ONLY_SEEN_REGRESSION",
            hypothesis=p["hypothesis"],
            immutable_boundary_identity=identity(campaign),
        )
        for p in prompts
    )
    for v in variants:
        PromptRegistry(output / "prompts").register(v)
    spec = ExperimentSpec(
        experiment_id="THREE-PROMPT-FOUR-CLAIM-V1",
        campaign_identity=identity(campaign),
        dataset_identity=identity(dataset),
        variant_identities=tuple(identity(v) for v in variants),
        mode="LIVE",
    )
    started = time.perf_counter()
    frozen = RequestCompiler().compile(spec, campaign, dataset, variants, workers=2)
    RequestCompiler().verify(frozen)
    recorder.record("freeze.json", frozen)
    request_rows = []
    for i, req in enumerate(frozen.requests, 1):
        prefix = f"requests/{i:02}-{req.variant_id}-{req.case_id}/"
        recorder.write(prefix + "request.raw", req.raw_body.encode())
        recorder.record(prefix + "schema.json", req.response_schema)
        wire = json.loads(req.raw_body)
        if (
            wire["model"] != "qwen3.8-flash"
            or wire["text"]["format"]["type"] != "json_schema"
            or wire["text"]["format"]["strict"] is not True
            or wire["store"] is not False
            or wire["max_output_tokens"] != 1024
            or "MINIMAL_OUTPUT_CONTRACT=" not in wire["instructions"]
        ):
            raise ValueError("SDK_WIRE_PROFILE_DRIFT")
        request_rows.append(
            dict(
                order=i,
                run_id=req.run_id,
                case_id=req.case_id,
                variant_id=req.variant_id,
                task_identity=req.task_identity,
                prompt_identity=req.prompt_identity,
                schema_identity=req.schema_identity,
                sdk_request_sha256=req.request_sha256,
                raw_path=prefix + "request.raw",
                bytes=len(req.raw_body.encode()),
            )
        )
    recorder.record("request-manifest.json", request_rows)
    recorder.record("prompt-binding.json", provenance)
    recorder.record(
        "scorer-binding.json",
        dict(
            delivery=DELIVERY,
            manifest=MANIFEST,
            profile=PROFILE,
            protocol_sha256=benchmark.protocol_sha256,
            case_ids=CASES,
            case_versions={c: benchmark.cases[c].case_version for c in CASES},
            freeze_sha256=sha(
                benchmark.read("FOUR_CASE_FIRST_CAMPAIGN_EVALUATION_FREEZE.json")
            ),
            external_modules={
                p: f["sha256"]
                for p, f in benchmark.pinned_files.items()
                if p.startswith("financial_benchmark/")
            },
        ),
    )
    recorder.record("release-projection.json", release_projection(campaign))
    recorder.record(
        "source-bindings.json",
        {c.case_id: c.visible_input["source_read_bindings"] for c in dataset.cases},
    )
    current = []
    for req in frozen.requests:
        c = next(c for c in dataset.cases if c.case_id == req.case_id)
        try:
            CurrentAuthorityAdapter({}).check(c, req)
        except ValueError as exc:
            current.append(
                dict(
                    run_id=req.run_id,
                    case_id=c.case_id,
                    status="NOT_INSTALLED",
                    reason=str(exc),
                    receiving_invocation_candidate=req.run_id,
                    role=c.specialist_role,
                    scope="READ_HISTORY",
                )
            )
        else:
            raise ValueError("UNEXPECTED_CURRENT_AUTHORITY")
    try:
        CampaignReleaseGate(root).check(campaign)
    except ValueError as exc:
        release_error = str(exc)
    else:
        raise ValueError("UNEXPECTED_UNSIGNED_RELEASE")
    cap = profile(1024)
    cost = reference_cost(cap, cap.input_reservation, cap.output_cap) * 12
    if cost > campaign.budget.max_reference_cost_cny:
        raise ValueError("TWELVE_SLOT_RESERVATION_EXCEEDS_BUDGET")
    recorder.record(
        "readiness.json",
        dict(
            version="FIRST_CLAIM_CAMPAIGN_V1",
            status="FROZEN_REQUEST_CANDIDATE_PENDING_CURRENT_AUTHORITY_AND_DUAL_RELEASE",
            source_commit=campaign.source_commit,
            source_tree=git(root, "rev-parse", campaign.source_commit + "^{tree}")
            .decode()
            .strip(),
            operation=campaign.campaign_id,
            population=identity(dataset),
            campaign_identity=identity(campaign),
            freeze_sha256=sha(encoded(frozen)),
            requests=12,
            schema_identity=identity(frozen.requests[0].response_schema),
            compile_seconds=time.perf_counter() - started,
            current_receivers=current,
            release_rejection=release_error,
            LIVE_CAMPAIGN_READY=False,
            current_authority_ready=False,
            actual_provider_calls=0,
            actual_bill="UNKNOWN",
            scientific_effect="NOT_DEMONSTRATED",
            budget_reservation_tokens=12 * (cap.input_reservation + cap.output_cap),
            budget_reservation_reference_cny=str(cost),
            context_fit="UNKNOWN",
            input_token_reservations_are_not_measured=True,
            no_retry=True,
            no_fallback=True,
            immutable_scope="REGRESSION_DEVELOPMENT_ONLY_NOT_OOS",
            current_grants_must_be_installed_before_send=True,
        ),
    )
    return frozen


def dry_run(root: Path, frozen_path: Path, output: Path) -> dict[str, Any]:
    """Execute a separate Mock identity with byte-identical SDK requests and W5 1.1."""
    output.mkdir(parents=True, exist_ok=False)
    recorder = TraceRecorder(output)
    original = FrozenExperiment.model_validate_json(frozen_path.read_bytes())
    RequestCompiler().verify(original)
    campaign = original.campaign.model_copy(
        update={
            "campaign_id": original.campaign.campaign_id + "-MOCK",
            "execution_mode": "OFFLINE",
            "ledger_root": str((output / "runs").resolve()),
        }
    )
    variants = tuple(
        v.model_copy(update={"immutable_boundary_identity": identity(campaign)})
        for v in original.variants
    )
    spec = original.spec.model_copy(
        update={
            "mode": "OFFLINE",
            "campaign_identity": identity(campaign),
            "variant_identities": tuple(identity(v) for v in variants),
        }
    )
    frozen = RequestCompiler().compile(
        spec, campaign, original.dataset, variants, workers=2
    )
    if [r.raw_body for r in frozen.requests] != [r.raw_body for r in original.requests]:
        raise ValueError("MOCK_LIVE_REQUEST_BYTE_DRIFT")
    recorder.record("freeze.json", frozen)
    body = dict(
        verdict="UNDETERMINED",
        evidence_handles=["H0005"],
        reasoning="Synthetic interface test, not a financial prediction.",
        missing_premises=["No model economic reasoning is exercised by this fixture."],
        counterevidence_handles=[],
        uncertainty="Not evaluated in this Mock.",
    )
    outcomes = {}
    for i, r in enumerate(frozen.requests):
        obj = dict(body)
        if i == 1:
            obj["evidence_handles"] = ["H_FORGED"]
        text = encoded(obj).decode()
        if i == 2:
            text = "```json\n" + text + "\n```"
        outcomes[r.variant_id + "/" + r.case_id] = dict(assistant=text)
    recorder.record(
        "scenario.json",
        dict(origin="NEW_MOCK_EXECUTION", not_gold=True, outcomes=outcomes),
    )
    run = TrustedExperimentRunner(
        output / "runs",
        OfflineAuthority(expires_at=campaign.expires_at),
        CampaignReleaseGate(root),
    ).run(frozen, scenario=OfflineScenario(outcomes, delay=0.1))
    b = CalibratedBenchmark()
    start = time.perf_counter()
    results = evaluate_archive(frozen, Path(run["archive"]), evaluator=b)
    write_evaluations(output / "scores", results)
    comparison = CalibratedComparator().compare(frozen, results)
    recorder.record("paired-comparison.json", comparison)
    recorder.record("failures.json", FailureClusterer().report(results))
    receipt = dict(
        origin="NEW_MOCK_EXECUTION",
        planned=12,
        mock_attempts=run["mock_attempts"],
        complete_responses=sum(r["status"] == "RESPONSE_CAPTURED" for r in run["rows"]),
        peak_inflight=run["peak_inflight"],
        real_provider_attempts=0,
        request_bytes_equal=True,
        source_freeze_sha256=sha(frozen_path.read_bytes()),
        mock_freeze_identity=identity(frozen),
        archive=run["archive"],
        content_failures=sum(bool(r.failures) for r in results),
        calibration_axes=comparison["calibration_axes"],
        evaluation_seconds=time.perf_counter() - start,
        dispatch_seconds=run["elapsed_seconds"],
        reference_tokens_not_actual=run["campaign_reserved_tokens"],
        evaluator=PROFILE,
        unknown_preserved=True,
        scientific_effect="NOT_DEMONSTRATED",
    )
    recorder.record("receipt.json", receipt)
    return receipt


def main() -> None:
    """Compile or dry-run only; no CLI grants or implicit live activation."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("dry-run")
    run_parser.add_argument("--freeze", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "compile":
        frozen = compile_candidate(root, args.output.resolve())
        print(
            json.dumps(
                dict(
                    requests=len(frozen.requests),
                    freeze_sha256=identity(frozen),
                    live_ready=False,
                )
            )
        )
    else:
        print(json.dumps(dry_run(root, args.freeze.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
