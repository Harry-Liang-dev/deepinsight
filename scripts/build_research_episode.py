"""Materialize ResearchEpisode v1 from frozen run metadata only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

import duckdb

from src.models.enums import AgentName, AgentStatus
from src.models.types import JsonObject, JsonValue
from src.schemas.agents import ClaimEvidenceBinding, RejectedClaim
from src.schemas.research_episode import (
    AgentExecutionTrace,
    ResearchEpisodeBuildInput,
    ResearchEpisodeTraceQuality,
)
from src.schemas.research_state import ResearchStateSnapshot
from src.schemas.sector_context import SectorContextBundle
from src.schemas.sector_usage import SectorContextUsageDiagnostic
from src.services.research_episode import ResearchEpisodeBuilder
from src.services.sector_context import build_sector_context_usage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze a research process without LLM, Provider, or report prose."
    )
    parser.add_argument("--state", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-manifest", type=Path)
    source.add_argument("--contract-summary", type=Path)
    parser.add_argument("--agent-db", type=Path)
    parser.add_argument("--sector-context", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _read_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return cast(JsonObject, value)


def _walk_claims(
    value: JsonValue,
) -> tuple[tuple[ClaimEvidenceBinding, ...], tuple[RejectedClaim, ...]]:
    accepted: dict[str, ClaimEvidenceBinding] = {}
    rejected: list[RejectedClaim] = []

    def walk(item: JsonValue) -> None:
        if isinstance(item, dict):
            if item.get("status") == "accepted" and isinstance(
                item.get("claim_id"), str
            ):
                claim = ClaimEvidenceBinding.model_validate(item)
                assert claim.claim_id is not None
                prior = accepted.get(claim.claim_id)
                if prior is not None and prior != claim:
                    raise ValueError(f"conflicting accepted Claim {claim.claim_id}")
                accepted[claim.claim_id] = claim
                return
            if item.get("status") == "rejected" and isinstance(
                item.get("claim_path"), str
            ):
                rejected.append(RejectedClaim.model_validate(item))
                return
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return tuple(accepted.values()), tuple(rejected)


def _rejected_id(run_id: str, claim: RejectedClaim) -> str:
    payload = json.dumps(
        {"run_id": run_id, **claim.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"rejected_claim_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _complete_traces(
    path: Path,
    state: ResearchStateSnapshot,
    provider: str,
    report_id: str,
) -> tuple[AgentExecutionTrace, ...]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT run_id, agent_name, model_name, prompt_template_ver,
                   input_payload_json, output_payload_json, status, latency_ms
            FROM agent_runs
            WHERE report_id = ?
            ORDER BY created_at, run_id
            """,
            [report_id],
        ).fetchall()
    finally:
        connection.close()
    traces: list[AgentExecutionTrace] = []
    context_ids = tuple(
        item
        for item in (
            state.research_state_id,
            state.lineage.data_bundle_id,
            state.lineage.sector_context_id,
            state.lineage.memory_context_id,
        )
        if item is not None
    )
    for (
        run_id,
        agent_name,
        model_name,
        prompt_version,
        input_payload,
        output_payload,
        status,
        latency_ms,
    ) in rows:
        provided, _ = _walk_claims(_json_value(input_payload))
        accepted, rejected = _walk_claims(_json_value(output_payload))
        accepted_ids = tuple(
            claim.claim_id for claim in accepted if claim.claim_id is not None
        )
        rejected_ids = tuple(_rejected_id(str(run_id), claim) for claim in rejected)
        traces.append(
            AgentExecutionTrace(
                agent_role=AgentName(str(agent_name)),
                agent_run_id=str(run_id),
                status=AgentStatus(str(status)),
                input_context_ids=context_ids,
                provided_claim_ids=tuple(
                    claim.claim_id for claim in provided if claim.claim_id is not None
                ),
                output_claim_ids=(*accepted_ids, *rejected_ids),
                accepted_claim_ids=accepted_ids,
                rejected_claim_ids=rejected_ids,
                accepted_claim_count=len(accepted_ids),
                rejected_claim_count=len(rejected_ids),
                latency_ms=None if latency_ms is None else int(latency_ms),
                provider=provider,
                model=str(model_name),
                prompt_version=str(prompt_version),
                trace_quality=ResearchEpisodeTraceQuality.COMPLETE,
            )
        )
    return tuple(traces)


def _complete_sector_usage(
    path: Path,
    sector_context: SectorContextBundle,
    report_id: str,
) -> tuple[SectorContextUsageDiagnostic, ...]:
    """Rebuild coordinator usage from persisted accepted Agent Claims."""

    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT agent_name, output_payload_json
            FROM agent_runs
            WHERE report_id = ?
            ORDER BY created_at, run_id
            """,
            [report_id],
        ).fetchall()
    finally:
        connection.close()
    claims_by_role: dict[AgentName, tuple[ClaimEvidenceBinding, ...]] = {}
    for agent_name, output_payload in rows:
        accepted, _ = _walk_claims(_json_value(output_payload))
        claims_by_role[AgentName(str(agent_name))] = accepted
    return build_sector_context_usage(sector_context, claims_by_role)


def _partial_traces(
    summary: JsonObject,
    state: ResearchStateSnapshot,
    usage: tuple[SectorContextUsageDiagnostic, ...],
) -> tuple[AgentExecutionTrace, ...]:
    agents = _object(summary, "agents")
    prompts = _object(summary, "prompt_versions")
    usage_by_role = {item.agent_role: item for item in usage}
    context_ids = tuple(
        item
        for item in (
            state.research_state_id,
            state.lineage.data_bundle_id,
            state.lineage.sector_context_id,
        )
        if item is not None
    )
    traces: list[AgentExecutionTrace] = []
    for role in AgentName:
        raw_metrics = agents.get(role.value)
        if not isinstance(raw_metrics, dict):
            continue
        metrics = raw_metrics
        accepted_count = _integer(metrics, "valid_claims")
        rejected_count = _integer(metrics, "rejected_claims")
        missing = ["accepted_claim_ids_not_persisted", "latency_ms_not_persisted"]
        if rejected_count:
            missing.append("rejected_claim_ids_not_persisted")
        role_usage = usage_by_role.get(role)
        traces.append(
            AgentExecutionTrace(
                agent_role=role,
                agent_run_id=f"fixed:{role.value}",
                status=AgentStatus(str(metrics.get("status"))),
                input_context_ids=context_ids,
                provided_claim_ids=(
                    () if role_usage is None else role_usage.provided_sector_claim_ids
                ),
                output_claim_ids=(),
                accepted_claim_ids=(),
                rejected_claim_ids=(),
                accepted_claim_count=accepted_count,
                rejected_claim_count=rejected_count,
                provider=str(summary.get("provider")),
                model=str(summary.get("model")),
                prompt_version=str(prompts.get(role.value)),
                trace_quality=ResearchEpisodeTraceQuality.PARTIAL,
                missing_metadata=tuple(missing),
            )
        )
    return tuple(traces)


def _json_value(value: object) -> JsonValue:
    parsed = json.loads(str(value))
    return cast(JsonValue, parsed)


def _object(value: JsonObject, key: str) -> JsonObject:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"{key} must be an object")
    return item


def _integer(value: JsonObject, key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} must be an integer")
    return item


def _sector_usage(summary: JsonObject) -> tuple[SectorContextUsageDiagnostic, ...]:
    raw = summary.get("sector_context_usage", [])
    if not isinstance(raw, list):
        raise ValueError("sector_context_usage must be a list")
    return tuple(SectorContextUsageDiagnostic.model_validate(item) for item in raw)


def manifest_episode_input(
    manifest_path: Path,
    db_path: Path | None,
    state: ResearchStateSnapshot,
    sector_context: SectorContextBundle | None = None,
) -> ResearchEpisodeBuildInput:
    if db_path is None:
        raise ValueError("--agent-db is required with --run-manifest")
    manifest = _read_object(manifest_path)
    llm = _object(manifest, "llm")
    provider = str(llm.get("provider"))
    report_id = str(manifest.get("report_id") or "")
    if not report_id:
        raise ValueError("run manifest must identify its report")
    traces = _complete_traces(db_path, state, provider, report_id)
    usage = (
        ()
        if sector_context is None
        else _complete_sector_usage(db_path, sector_context, report_id)
    )
    return ResearchEpisodeBuildInput(
        research_state=state,
        agent_traces=traces,
        sector_usage=usage,
        report_id=(report_id),
        created_at=datetime.fromisoformat(
            str(manifest["timestamp"]).replace("Z", "+00:00")
        ),
        source_artifact_ids=(str(manifest_path), str(db_path)),
    )


def summary_episode_input(
    summary_path: Path,
    state: ResearchStateSnapshot,
) -> ResearchEpisodeBuildInput:
    summary = _read_object(summary_path)
    usage = _sector_usage(summary)
    return ResearchEpisodeBuildInput(
        research_state=state,
        agent_traces=_partial_traces(summary, state, usage),
        sector_usage=usage,
        created_at=datetime.fromisoformat(
            str(summary["timestamp"]).replace("Z", "+00:00")
        ),
        source_artifact_ids=(str(summary_path),),
        missing_metadata=(
            "asset_claim_identities_not_persisted_by_day36_summary",
            "agent_latency_not_persisted_by_day36_summary",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Build and save one immutable Episode from frozen source artifacts."""

    args = _parser().parse_args(argv)
    try:
        state = ResearchStateSnapshot.model_validate_json(
            args.state.read_text(encoding="utf-8")
        )
        sector_context = (
            None
            if args.sector_context is None
            else SectorContextBundle.model_validate_json(
                args.sector_context.read_text(encoding="utf-8")
            )
        )
        inputs = (
            manifest_episode_input(
                args.run_manifest,
                args.agent_db,
                state,
                sector_context,
            )
            if args.run_manifest is not None
            else summary_episode_input(args.contract_summary, state)
        )
        episode = ResearchEpisodeBuilder().build(inputs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(episode.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "episode_id": episode.episode_id,
                    "asset_id": str(episode.asset_id),
                    "trace_quality": episode.trace_quality.value,
                    "agent_run_count": len(episode.agent_run_ids),
                    "accepted_claim_count": episode.accepted_claim_count,
                    "rejected_claim_count": episode.rejected_claim_count,
                    "sector_usage_count": len(episode.sector_usage),
                    "output": str(args.output),
                    "llm_calls": 0,
                    "network_calls": 0,
                    "private_reasoning_saved": False,
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
