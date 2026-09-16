"""Materialize Day41 attribution from frozen Episode and Sector artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb

from src.models.enums import AgentName
from src.models.types import JsonValue
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_attribution import (
    ContextClaimLinkStatus,
    ResearchContextClaimLink,
    ResearchContextType,
)
from src.schemas.research_episode import ResearchEpisode
from src.schemas.sector_context import SectorContextBundle
from src.services.research_attribution import ResearchAttributionBuilder


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    """Build the offline Day41 materializer argument parser."""

    parser = argparse.ArgumentParser(
        description="Build ResearchEpisode attribution from frozen artifacts."
    )
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--sector-context", type=Path)
    parser.add_argument("--agent-db", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _accepted_claims(value: JsonValue) -> tuple[ClaimEvidenceBinding, ...]:
    """Collect accepted Claim objects from one persisted Agent output."""

    result: dict[str, ClaimEvidenceBinding] = {}

    def walk(item: JsonValue) -> None:
        if isinstance(item, dict):
            if item.get("status") == "accepted" and isinstance(
                item.get("claim_id"), str
            ):
                claim = ClaimEvidenceBinding.model_validate(item)
                assert claim.claim_id is not None
                result[claim.claim_id] = claim
                return
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return tuple(result.values())


def _claim_links(
    path: Path,
    episode: ResearchEpisode,
    sector_context: SectorContextBundle,
) -> tuple[ResearchContextClaimLink, ...]:
    """Recover exact context-to-Claim links from the frozen Agent graph."""

    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute("""
            SELECT run_id, agent_name, output_payload_json
            FROM agent_runs
            ORDER BY created_at, run_id
            """).fetchall()
    finally:
        connection.close()
    claims_by_run: dict[str, tuple[ClaimEvidenceBinding, ...]] = {}
    roles_by_run: dict[str, AgentName] = {}
    claim_index: dict[str, ClaimEvidenceBinding] = {
        claim.claim_id: claim
        for claim in sector_context.accepted_claims
        if claim.claim_id is not None
    }
    for run_id, agent_name, raw_output in rows:
        parsed = json.loads(str(raw_output))
        claims = _accepted_claims(parsed)
        claims_by_run[str(run_id)] = claims
        roles_by_run[str(run_id)] = AgentName(str(agent_name))
        claim_index.update(
            {claim.claim_id: claim for claim in claims if claim.claim_id is not None}
        )
    sector_ids = {
        claim.claim_id
        for claim in sector_context.accepted_claims
        if claim.claim_id is not None
    }

    def ancestors(claim_id: str, visited: set[str]) -> set[str]:
        if claim_id in visited:
            return set()
        if claim_id in sector_ids:
            return {claim_id}
        claim = claim_index.get(claim_id)
        if claim is None:
            return set()
        return set().union(
            *(
                ancestors(parent, {*visited, claim_id})
                for parent in claim.upstream_claim_ids
            )
        )

    event_by_claim: dict[str, set[str]] = {}
    for event in sector_context.active_events:
        for claim_id in event.supporting_sector_claim_ids:
            event_by_claim.setdefault(claim_id, set()).add(event.event_id)
    usage_by_role = {item.agent_role: item for item in episode.sector_usage}
    links: list[ResearchContextClaimLink] = []
    identities: set[tuple[str, ResearchContextType, str, str]] = set()
    for trace in episode.agent_traces:
        role = roles_by_run.get(trace.agent_run_id)
        if role is None or role is not trace.agent_role:
            continue
        usage = usage_by_role.get(role)
        if usage is None:
            continue
        for claim in claims_by_run.get(trace.agent_run_id, ()):
            if claim.claim_id is None:
                continue
            sector_ancestors = set().union(
                *(ancestors(parent, set()) for parent in claim.upstream_claim_ids)
            )
            for sector_id in sorted(sector_ancestors):
                if sector_id not in usage.used_sector_claim_ids:
                    continue
                contexts = [(ResearchContextType.SECTOR_CLAIM, sector_id)]
                contexts.extend(
                    (ResearchContextType.RADAR_EVENT, event_id)
                    for event_id in sorted(event_by_claim.get(sector_id, set()))
                    if event_id in usage.used_event_ids
                )
                for context_type, context_id in contexts:
                    identity = (
                        trace.agent_run_id,
                        context_type,
                        context_id,
                        claim.claim_id,
                    )
                    if identity in identities:
                        continue
                    identities.add(identity)
                    links.append(
                        ResearchContextClaimLink(
                            agent_role=role,
                            agent_run_id=trace.agent_run_id,
                            context_type=context_type,
                            context_id=context_id,
                            claim_id=claim.claim_id,
                            claim_status=ContextClaimLinkStatus.ACCEPTED,
                        )
                    )
    return tuple(links)


def main() -> int:
    """Build and persist one credential-free attribution JSON artifact."""

    args = build_parser().parse_args()
    episode = ResearchEpisode.model_validate(_read_json(args.episode))
    sector_context = (
        None
        if args.sector_context is None
        else SectorContextBundle.model_validate(_read_json(args.sector_context))
    )
    if args.agent_db is not None and sector_context is None:
        raise ValueError("--agent-db attribution requires --sector-context")
    claim_links = (
        ()
        if args.agent_db is None or sector_context is None
        else _claim_links(args.agent_db, episode, sector_context)
    )
    result = ResearchAttributionBuilder().build(
        episode=episode,
        sector_context=sector_context,
        claim_links=claim_links,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
