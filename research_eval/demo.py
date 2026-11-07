"""Reproducible multi-variant synthetic campaign; no real scientific labels."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from research_eval.compiler import RequestCompiler
from research_eval.evaluation import (
    ExperimentComparator,
    FailureClusterer,
    evaluate_archive,
    write_evaluations,
)
from research_eval.export import ExperienceExporter
from research_eval.models import (
    Budget,
    Dataset,
    DatasetCase,
    ExperimentSpec,
    PromptVariant,
    SourceRef,
    TrustedExperimentCampaign,
    encoded,
    identity,
)
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import CampaignReleaseGate, OfflineAuthority
from research_eval.storage import PromptRegistry, TraceRecorder


def runtime_identity(root: Path) -> dict[str, str]:
    """Include platform, original authority, Provider, SDK and meter code."""
    from tools.minimal2_live import runtime

    return {
        **runtime(),
        **{
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / "research_eval").glob("*.py")
        },
    }


def make_demo(root: Path, output: Path) -> dict[str, Any]:
    """Run two policies × three cases using actual SDK + concurrent MockTransport."""
    output.mkdir(parents=True, exist_ok=False)
    recorder = TraceRecorder(output)
    source = output / "synthetic-source.txt"
    recorder.write(
        "synthetic-source.txt",
        (
            b"SYNTHETIC OFFLINE FIXTURE ONLY. Marker is BLUE. "
            b"A reported total does not identify component causes. "
            b"Amount 12 USD million."
        ),
    )
    now = datetime.now(UTC)
    source_ref = SourceRef(
        source_id="fixture-source",
        path=str(source.resolve()),
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        available_at=now - timedelta(days=1),
        license="SYNTHETIC_LOCAL_DEVELOPMENT_ONLY",
    )
    cases = tuple(
        DatasetCase(
            case_id=name,
            task_kind=cast(Literal["technical", "financial"], kind),
            specialist_role=(
                "technical_schema_probe"
                if kind == "technical"
                else "fundamental_analyst"
            ),
            full_claim=claim,
            research_as_of=now,
            sources=(source_ref,),
            handles={"H1": "fixture-source"},
            visible_input={"evidence": {"H1": source.read_text()}},
            authority_binding=identity(["fixture-authority", name]),
            local_export_allowed=True,
        )
        for name, kind, claim in [
            ("technical", "technical", "The synthetic marker is BLUE."),
            (
                "causal",
                "financial",
                "The synthetic aggregate proves the component cause.",
            ),
            (
                "reference",
                "financial",
                "The provided source establishes the synthetic observation.",
            ),
        ]
    )
    dataset = Dataset(dataset_id="synthetic-demo-v1", cases=cases)
    campaign = TrustedExperimentCampaign(
        campaign_id="offline-demo",
        ledger_root=str((output / "runs").resolve()),
        source_commit=subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"]
        )
        .decode()
        .strip(),
        runtime_hashes=runtime_identity(root),
        dataset_identity=identity(dataset),
        permitted_source_hashes=(source_ref.sha256,),
        authority_bindings=tuple(c.authority_binding for c in cases),
        evaluator_protocol_sha256=identity("W5_PENDING_MECHANICAL_DEMO_ONLY"),
        budget=Budget(
            max_samples=6,
            max_attempts=6,
            max_tokens=6 * 1000512,
            max_reference_cost_cny=Decimal("7"),
            concurrency=3,
            requests_per_second=100,
        ),
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    variants = tuple(
        PromptVariant(
            variant_id=name,
            content=prompt,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            task_types=("technical", "financial"),
            dataset_identity=identity(dataset),
            created_by="offline-demo-worker",
            experiment_group=name,
            hypothesis="Synthetic harness contrast, not measured model improvement",
            immutable_boundary_identity=identity(campaign),
        )
        for name, prompt in [
            ("baseline", "Assess the complete claim using only offered evidence."),
            (
                "candidate",
                (
                    "Assess the complete claim, preserving unknown premises "
                    "and selecting only offered handles."
                ),
            ),
        ]
    )
    for v in variants:
        PromptRegistry(output / "prompts").register(v)
    spec = ExperimentSpec(
        experiment_id="demo-six",
        campaign_identity=identity(campaign),
        dataset_identity=identity(dataset),
        variant_identities=tuple(identity(v) for v in variants),
    )
    frozen = RequestCompiler().compile(spec, campaign, dataset, variants, workers=3)
    recorder.record("dataset.json", dataset)
    recorder.record("campaign.json", campaign)
    recorder.record("spec.json", spec)
    recorder.record("freeze.json", frozen)
    valid = dict(
        verdict="UNDETERMINED",
        evidence_handles=["H1"],
        reasoning="The supplied source does not establish the component cause.",
        missing_premises=["A valid bridge to the proposed cause."],
        counterevidence_handles=[],
        uncertainty="The component mechanism is unknown.",
    )
    outcomes = {}
    for v in variants:
        for c in cases:
            obj = dict(valid)
            if c.task_kind == "technical":
                obj.update(
                    verdict="SUPPORTED",
                    evidence_handles=[],
                    missing_premises=[],
                    uncertainty="",
                    reasoning="The supplied synthetic marker equals BLUE.",
                )
            if v.variant_id == "baseline" and c.case_id == "causal":
                obj["verdict"] = "SUPPORTED"
            if v.variant_id == "baseline" and c.case_id == "reference":
                obj["evidence_handles"] = ["H_FAKE"]
            outcomes[v.variant_id + "/" + c.case_id] = dict(
                assistant=encoded(obj).decode()
            )
    recorder.record("scenario.json", outcomes)
    runner = TrustedExperimentRunner(
        output / "runs",
        OfflineAuthority(expires_at=campaign.expires_at),
        CampaignReleaseGate(root),
    )
    result = runner.run(frozen, scenario=OfflineScenario(outcomes, delay=0.2))
    archive = Path(result["archive"])
    evaluations = evaluate_archive(frozen, archive)
    write_evaluations(output / "evaluations", evaluations)
    comparison = ExperimentComparator().compare(frozen, evaluations)
    recorder.record("comparison.json", comparison)
    recorder.record("failures.json", FailureClusterer().report(evaluations))
    for kind in ("SFT", "PREFERENCE", "RL"):
        recorder.record(
            kind.lower() + "-references.json",
            [
                x.model_dump(mode="json")
                for x in ExperienceExporter().export(frozen, archive, evaluations, kind)
            ],
        )
    summary = dict(
        run=result,
        comparison=comparison,
        evaluation_count=len(evaluations),
        actual_provider_calls=0,
        labels="NO_GOLD_SYNTHETIC_ENGINEERING_SCENARIO",
        training_started=False,
    )
    recorder.record("demo.json", summary)
    return summary
