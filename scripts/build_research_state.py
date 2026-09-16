"""Build a ResearchStateSnapshot from frozen structured run artifacts only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

import duckdb

from src.models.enums import AgentName
from src.models.types import JsonObject, JsonValue
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_data import ResearchDataBundle
from src.schemas.research_state import (
    ResearchStateBuildInput,
    ResearchStateClaimInput,
    ResearchStateSectorContextInput,
    ResearchStateVersionReference,
)
from src.schemas.sector_context import SectorContextBundle
from src.services.research_state import ResearchStateBuilder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build PIT-safe machine state without network or LLM calls."
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sector-context", type=Path)
    parser.add_argument("--agent-db", type=Path)
    parser.add_argument(
        "--report-id",
        help="Limit Agent lineage to one persisted report execution.",
    )
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _read_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return cast(JsonObject, value)


def _accepted_claims(value: JsonValue) -> tuple[ClaimEvidenceBinding, ...]:
    found: dict[str, ClaimEvidenceBinding] = {}

    def walk(item: JsonValue) -> None:
        if isinstance(item, dict):
            if (
                item.get("status") == "accepted"
                and isinstance(item.get("claim_id"), str)
                and isinstance(item.get("claim_text"), str)
            ):
                claim = ClaimEvidenceBinding.model_validate(item)
                assert claim.claim_id is not None
                prior = found.get(claim.claim_id)
                if prior is not None and prior != claim:
                    raise ValueError(f"conflicting accepted Claim {claim.claim_id}")
                found[claim.claim_id] = claim
                return
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return tuple(found[key] for key in sorted(found))


def load_agent_claims(
    path: Path,
    report_id: str | None = None,
) -> tuple[
    tuple[ResearchStateClaimInput, ...],
    tuple[ResearchStateVersionReference, ...],
    tuple[ResearchStateVersionReference, ...],
]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT run_id, agent_name, prompt_template_ver, model_name,
                   output_payload_json
            FROM agent_runs
            WHERE status = 'ok' AND output_payload_json IS NOT NULL
              AND (? IS NULL OR report_id = ?)
            ORDER BY run_id
            """,
            [report_id, report_id],
        ).fetchall()
    finally:
        connection.close()
    claims: list[ResearchStateClaimInput] = []
    prompt_versions: list[ResearchStateVersionReference] = []
    model_versions: list[ResearchStateVersionReference] = []
    for run_id, agent_name, prompt_version, model_name, payload in rows:
        role = AgentName(str(agent_name))
        value = json.loads(str(payload))
        if not isinstance(value, dict):
            raise ValueError(f"Agent run {run_id} output is not a JSON object")
        for claim in _accepted_claims(cast(JsonObject, value)):
            claims.append(
                ResearchStateClaimInput(
                    agent_role=role,
                    agent_run_id=str(run_id),
                    claim=claim,
                )
            )
        prompt_versions.append(
            ResearchStateVersionReference(
                component="prompt",
                name=role.value,
                version=str(prompt_version),
            )
        )
        model_versions.append(
            ResearchStateVersionReference(
                component="model",
                name=role.value,
                version=str(model_name),
            )
        )
    return tuple(claims), tuple(prompt_versions), tuple(model_versions)


def state_sector_context_input(
    context: SectorContextBundle,
) -> ResearchStateSectorContextInput:
    """Project one frozen Sector context into the Day38 State contract."""

    return ResearchStateSectorContextInput(
        context_id=context.context_id,
        asset_id=context.asset_id,
        sector_id=context.sector_id.value,
        sector_scope_id=context.sector_scope_id,
        research_as_of=context.research_as_of,
        active_chain_ids=context.active_chain_ids,
        cycle_phase=context.cycle_assessment.phase.value,
        cycle_confidence=context.cycle_assessment.confidence,
        cycle_supporting_claim_ids=context.cycle_assessment.supporting_claim_ids,
        accepted_claims=context.accepted_claims,
        macro_claim_ids=tuple(
            claim.claim_id
            for claim in context.accepted_claims
            if claim.claim_id is not None
            and claim.category.value in {"macro_environment", "macro_sensitivity"}
        ),
        sector_snapshot_id=context.sector_snapshot_id,
        macro_snapshot_id=context.macro_snapshot_id,
        context_version=context.sector_context_version,
    )


def main(argv: list[str] | None = None) -> int:
    """Build and save one ResearchStateSnapshot without external I/O."""

    args = _parser().parse_args(argv)
    try:
        bundle = ResearchDataBundle.model_validate(_read_object(args.bundle))
        raw_sector_context = (
            SectorContextBundle.model_validate(_read_object(args.sector_context))
            if args.sector_context is not None
            else None
        )
        sector_context = (
            state_sector_context_input(raw_sector_context)
            if raw_sector_context is not None
            else None
        )
        if args.agent_db is None:
            claims: tuple[ResearchStateClaimInput, ...] = ()
            prompts: tuple[ResearchStateVersionReference, ...] = ()
            models: tuple[ResearchStateVersionReference, ...] = ()
        else:
            claims, prompts, models = load_agent_claims(
                args.agent_db,
                args.report_id,
            )
        snapshot = ResearchStateBuilder().build(
            ResearchStateBuildInput(
                research_data_bundle=bundle,
                sector_context=sector_context,
                accepted_claims=claims,
                prompt_versions=prompts,
                model_versions=models,
                source_run_id=args.source_run_id,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            snapshot.model_dump_json(indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "research_state_id": snapshot.research_state_id,
                    "asset_id": str(snapshot.asset_id),
                    "research_as_of": snapshot.research_as_of.isoformat(),
                    "output": str(args.output),
                    "agent_claim_count": len(claims),
                    "sector_context": sector_context is not None,
                    "network_calls": 0,
                    "llm_calls": 0,
                },
                sort_keys=True,
            )
        )
    except (OSError, ValueError, duckdb.Error) as exc:
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


if __name__ == "__main__":
    raise SystemExit(main())
