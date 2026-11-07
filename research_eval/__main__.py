"""Executable offline platform commands; no JSON option grants live authority."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_eval.compiler import RequestCompiler
from research_eval.demo import make_demo
from research_eval.evaluation import (
    ExperimentComparator,
    FailureClusterer,
    collect_results,
    evaluate_archive,
    write_evaluations,
)
from research_eval.export import ExperienceExporter
from research_eval.models import (
    Dataset,
    EvaluationResult,
    ExperimentSpec,
    FrozenExperiment,
    PromptVariant,
    TrustedExperimentCampaign,
)
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import CampaignReleaseGate, OfflineAuthority
from research_eval.storage import PromptRegistry, TraceRecorder


def load(path: str) -> Any:
    """Read an explicit artifact path; it is data, never an executable plugin."""
    return json.loads(Path(path).read_bytes())


def main() -> None:
    """Expose actual dataset/prompt/campaign/evaluation/export operations."""
    parser = argparse.ArgumentParser(prog="python -m research_eval")
    parser.add_argument(
        "area",
        choices=["dataset", "prompt", "campaign", "failures", "experience", "demo"],
    )
    parser.add_argument(
        "action",
        choices=[
            "validate",
            "register",
            "compile",
            "dry-run",
            "evaluate",
            "compare",
            "collect",
            "report",
            "export",
            "run",
        ],
    )
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset")
    parser.add_argument("--campaign")
    parser.add_argument("--spec")
    parser.add_argument("--variants", nargs="*")
    parser.add_argument("--scenario")
    parser.add_argument("--archive")
    parser.add_argument("--results", nargs="*")
    parser.add_argument("--format", choices=["SFT", "PREFERENCE", "RL"], default="SFT")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    out = Path(args.output)
    result: Any = None
    pair = (args.area, args.action)
    if pair == ("dataset", "validate"):
        dataset = Dataset.model_validate(load(args.input))
        result = dict(valid=True, cases=len(dataset.cases))
    elif pair == ("prompt", "register"):
        result = dict(
            identity=PromptRegistry(out).register(
                PromptVariant.model_validate(load(args.input))
            )
        )
        print(json.dumps(result))
        return
    elif pair == ("campaign", "compile"):
        result = (
            RequestCompiler()
            .compile(
                ExperimentSpec.model_validate(load(args.spec)),
                TrustedExperimentCampaign.model_validate(load(args.campaign)),
                Dataset.model_validate(load(args.dataset)),
                tuple(PromptVariant.model_validate(load(p)) for p in args.variants),
                workers=args.workers,
            )
            .model_dump(mode="json")
        )
    elif pair == ("campaign", "dry-run"):
        frozen = FrozenExperiment.model_validate(load(args.input))
        if frozen.spec.mode != "OFFLINE":
            raise ValueError("DRY_RUN_REQUIRES_OFFLINE_IDENTITY")
        result = TrustedExperimentRunner(
            out,
            OfflineAuthority(expires_at=frozen.campaign.expires_at),
            CampaignReleaseGate(Path.cwd()),
        ).run(frozen, scenario=OfflineScenario(load(args.scenario)))
        print(json.dumps(result))
        return
    elif pair == ("campaign", "evaluate"):
        frozen = FrozenExperiment.model_validate(load(args.input))
        values = evaluate_archive(frozen, Path(args.archive))
        write_evaluations(out, values)
        print(json.dumps(dict(results=len(values))))
        return
    elif pair == ("campaign", "compare"):
        result = ExperimentComparator().compare(
            FrozenExperiment.model_validate(load(args.input)),
            [EvaluationResult.model_validate(load(p)) for p in args.results],
        )
    elif pair == ("campaign", "collect"):
        result = [
            r.model_dump(mode="json")
            for r in collect_results(
                FrozenExperiment.model_validate(load(args.input)),
                Path(args.archive),
                [Path(p) for p in args.results],
            )
        ]
    elif pair == ("failures", "report"):
        result = FailureClusterer().report(
            [EvaluationResult.model_validate(load(p)) for p in args.results]
        )
    elif pair == ("experience", "export"):
        result = [
            r.model_dump(mode="json")
            for r in ExperienceExporter().export(
                FrozenExperiment.model_validate(load(args.input)),
                Path(args.archive),
                [EvaluationResult.model_validate(load(p)) for p in args.results],
                args.format,
            )
        ]
    elif pair == ("demo", "run"):
        result = make_demo(Path.cwd(), out)
        print(
            json.dumps(
                dict(
                    archive=result["run"]["archive"],
                    peak_inflight=result["run"]["peak_inflight"],
                    real_calls=0,
                )
            )
        )
        return
    else:
        parser.error("Unsupported command combination")
    TraceRecorder(out.parent).record(out.name, result)
    print(json.dumps(dict(output=str(out), completed_at=datetime.now(UTC).isoformat())))


if __name__ == "__main__":
    main()
