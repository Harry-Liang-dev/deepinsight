"""Materialize one PIT ResearchDatasetSample from frozen artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from src.repositories import (
    DatabaseInitializationError,
    DuckDBDatabase,
    RepositoryError,
    ResearchDatasetRepository,
)
from src.schemas.research_attribution import ResearchEpisodeAttribution
from src.schemas.research_dataset import (
    ResearchDatasetArtifactManifest,
    ResearchDatasetBuildInput,
    ResearchDatasetSample,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.research_state import ResearchStateSnapshot
from src.services.research_dataset import ResearchDatasetBuilder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one reference-only PIT research dataset sample."
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--attribution", type=Path)
    parser.add_argument("--dataset-build-version", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Build, persist, and manifest one frozen sample without external calls."""

    args = _parser().parse_args(argv)
    try:
        state = ResearchStateSnapshot.model_validate_json(
            args.state.read_text(encoding="utf-8")
        )
        episode = ResearchEpisode.model_validate_json(
            args.episode.read_text(encoding="utf-8")
        )
        attribution = (
            None
            if args.attribution is None
            else ResearchEpisodeAttribution.model_validate_json(
                args.attribution.read_text(encoding="utf-8")
            )
        )
        sample = ResearchDatasetBuilder().build(
            ResearchDatasetBuildInput(
                research_state=state,
                research_episode=episode,
                attribution=attribution,
                dataset_build_version=args.dataset_build_version,
                created_at=datetime.fromisoformat(
                    args.created_at.replace("Z", "+00:00")
                ),
            )
        )
        database = DuckDBDatabase(args.database)
        database.bootstrap()
        ResearchDatasetRepository(database).save(sample)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(sample.model_dump_json(indent=2), encoding="utf-8")
        manifest = _manifest(sample, args.output)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "sample_id": sample.sample_id,
                    "asset_id": str(sample.asset_id),
                    "research_as_of": sample.research_as_of.isoformat(),
                    "quality": sample.quality.status.value,
                    "label_status": sample.label_status.value,
                    "output": str(args.output),
                    "manifest": str(args.manifest),
                    "database": str(args.database),
                    "llm_calls": 0,
                    "provider_calls": 0,
                },
                sort_keys=True,
            )
        )
    except (DatabaseInitializationError, OSError, RepositoryError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 0


def _manifest(
    sample: ResearchDatasetSample,
    output: Path,
) -> ResearchDatasetArtifactManifest:
    payload = {
        "sample_id": sample.sample_id,
        "input_fingerprint": sample.input_fingerprint,
        "dataset_schema_version": sample.dataset_schema_version,
        "dataset_build_version": sample.dataset_build_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return ResearchDatasetArtifactManifest(
        manifest_id=f"research_dataset_manifest_{digest[:24]}",
        sample_id=sample.sample_id,
        sample_artifact=str(output),
        dataset_schema_version=sample.dataset_schema_version,
        dataset_build_version=sample.dataset_build_version,
        input_fingerprint=sample.input_fingerprint,
        created_at=sample.created_at,
    )


if __name__ == "__main__":
    raise SystemExit(main())
