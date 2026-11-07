"""G87 bounded adapters for existing source repositories and deterministic L0."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd  # type: ignore[import-untyped]

from src.memory.incremental import ResearchDependency, SourceSnapshot
from src.memory.vnext_contracts import ArtifactRef, Scope
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.operators.technical_features import TechnicalFeatureOperator
from src.repositories.sectors import SectorOntologyRepository
from src.schemas.market_data import EodBarRecord
from src.schemas.research_v2_shared import Reference
from src.schemas.sectors import SectorMembership
from src.services.research_vnext.contracts import RetainedReader, resolve


def recompute_l0(
    bars: Sequence[EodBarRecord],
    *,
    asset: AssetId,
    cutoff: datetime,
    source: ArtifactRef,
    reader: RetainedReader,
) -> JsonObject:
    """Verify exact retained bars and clocks, then call the original operator."""
    import json

    raw = resolve(source, reader)
    source.require_recorded_by(cutoff)
    restored = tuple(EodBarRecord.model_validate(v) for v in json.loads(raw))
    if restored != tuple(bars) or not bars:
        raise ValueError("L0_SOURCE_POPULATION_MISMATCH")
    if any(b.asset_id != asset or b.ingestion_ts > cutoff for b in bars):
        raise ValueError("L0_OWNER_OR_FUTURE_SOURCE")
    dates = [b.trade_date for b in bars]
    if dates != sorted(set(dates)):
        raise ValueError("L0_DUPLICATE_OR_UNORDERED_SESSIONS")
    values = TechnicalFeatureOperator().compute(
        pd.DataFrame(b.model_dump(mode="python") for b in bars)
    )
    return {
        "operator": TechnicalFeatureOperator.version,
        "source_sha256": source.sha256_digest,
        "values": values,
        "fund_flow": None,
        "fund_flow_status": "MISSING",
        "production_admission": False,
    }


def membership_dependency(
    repository: SectorOntologyRepository,
    *,
    member: SectorMembership,
    member_source: ArtifactRef,
    reader: RetainedReader,
    event: SourceSnapshot,
    target: Reference,
    target_scope: Scope,
    cutoff: datetime,
    valid_until: datetime,
) -> tuple[ResearchDependency, ResearchDependency]:
    """Only an exact dated, sourced membership supports a directed review edge.

    This grants no economic-benefit statement. The target is one already known
    role dependency, not all roles or all companies in the Sector.
    """
    actual = SectorMembership.model_validate_json(resolve(member_source, reader))
    member_source.require_recorded_by(cutoff)
    registered = repository.list_memberships(member.asset_id, as_of=cutoff.date())
    if (
        actual != member
        or member not in registered
        or not member.is_effective(cutoff.date())
    ):
        raise ValueError("BLOCKED_MISSING_EVIDENCE:MEMBERSHIP")
    if target_scope.scope_id != "ASSET:" + str(member.asset_id):
        raise ValueError("MEMBERSHIP_OWNER")
    valid_scopes = {
        "SECTOR:" + member.sector_id.value,
        *("CHAIN:" + c for c in member.chain_ids),
    }
    if event.scope.scope_id not in valid_scopes:
        raise ValueError("BLOCKED_MISSING_EVIDENCE:RELATION_SCOPE")
    if event.scope.scope_id.startswith("CHAIN:"):
        nodes = repository.list_nodes(as_of=cutoff.date())
        edges = repository.list_edges(as_of=cutoff.date())
        asset_nodes = {n.node_id for n in nodes if n.asset_id == member.asset_id}
        chain_nodes = {
            n.node_id
            for n in nodes
            if n.chain_id == event.scope.scope_id.removeprefix("CHAIN:")
        }
        if not any(
            {e.source_node_id, e.target_node_id} & asset_nodes
            and {e.source_node_id, e.target_node_id} & chain_nodes
            for e in edges
        ):
            raise ValueError("BLOCKED_MISSING_EVIDENCE:CHAIN_EDGE")
    upstream = event.evidence[0]
    return (
        ResearchDependency(
            artifact=upstream,
            scope=event.scope,
            source_keys=(event.key,),
            upstream=(),
            valid_from=cutoff,
            valid_until=valid_until,
        ),
        ResearchDependency(
            artifact=target,
            scope=target_scope,
            source_keys=(),
            upstream=(upstream,),
            relationship_evidence=(member_source,),
            valid_from=cutoff,
            valid_until=valid_until,
        ),
    )
