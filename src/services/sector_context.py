"""Day36 PIT routing and least-privilege Sector context projection."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from src.models.enums import AgentName, SectorCapabilityStatus, SectorId
from src.models.identifiers import AssetId
from src.repositories.sectors import SectorOntologyRepository
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.sector_context import (
    SectorContextBundle,
    SectorContextClaimSummary,
    SectorContextCoverage,
    SectorContextEventReference,
    SectorContextResolution,
    SectorRoleContext,
)
from src.schemas.sector_research import (
    SectorClaimCategory,
    SectorResearchOutput,
)
from src.schemas.sector_usage import SectorContextUsageDiagnostic
from src.schemas.sectors import (
    IndustryChainDefinition,
    SectorAnomalyEvent,
    SectorMacroSnapshot,
    SectorMembership,
    SectorResearchSnapshot,
)
from src.services.sector_ontology import build_sector_ontology_seed_v1

_ANALYSTS = {
    AgentName.FUNDAMENTAL_ANALYST,
    AgentName.TECHNICAL_TEXT_ANALYST,
    AgentName.SENTIMENT_ANALYST,
    AgentName.NEWS_EVENT_ANALYST,
}
_MANAGERS = {
    AgentName.RESEARCH_MANAGER,
    AgentName.BULL_MANAGER,
    AgentName.BEAR_MANAGER,
    AgentName.RISK_MANAGER,
}
_ROLE_CATEGORIES: dict[AgentName, frozenset[SectorClaimCategory]] = {
    AgentName.FUNDAMENTAL_ANALYST: frozenset(
        {
            SectorClaimCategory.FUNDAMENTALS,
            SectorClaimCategory.VALUATION,
            SectorClaimCategory.CYCLE,
            SectorClaimCategory.ANOMALIES,
        }
    ),
    AgentName.TECHNICAL_TEXT_ANALYST: frozenset(
        {
            SectorClaimCategory.TREND,
            SectorClaimCategory.BREADTH,
            SectorClaimCategory.LEADERS_LAGGARDS,
            SectorClaimCategory.CYCLE,
            SectorClaimCategory.ANOMALIES,
        }
    ),
    AgentName.SENTIMENT_ANALYST: frozenset(
        {
            SectorClaimCategory.ANOMALIES,
            SectorClaimCategory.CATALYSTS,
            SectorClaimCategory.RISKS,
        }
    ),
    AgentName.NEWS_EVENT_ANALYST: frozenset(
        {
            SectorClaimCategory.ANOMALIES,
            SectorClaimCategory.INDUSTRY_CHAINS,
            SectorClaimCategory.CATALYSTS,
            SectorClaimCategory.RISKS,
        }
    ),
    AgentName.RESEARCH_MANAGER: frozenset(SectorClaimCategory),
    AgentName.BULL_MANAGER: frozenset(
        {
            SectorClaimCategory.TREND,
            SectorClaimCategory.FUNDAMENTALS,
            SectorClaimCategory.MACRO_ENVIRONMENT,
            SectorClaimCategory.INDUSTRY_CHAINS,
            SectorClaimCategory.CATALYSTS,
            SectorClaimCategory.CYCLE,
        }
    ),
    AgentName.BEAR_MANAGER: frozenset(
        {
            SectorClaimCategory.TREND,
            SectorClaimCategory.BREADTH,
            SectorClaimCategory.MACRO_SENSITIVITY,
            SectorClaimCategory.ANOMALIES,
            SectorClaimCategory.RISKS,
            SectorClaimCategory.CYCLE,
        }
    ),
    AgentName.RISK_MANAGER: frozenset(
        {
            SectorClaimCategory.MACRO_ENVIRONMENT,
            SectorClaimCategory.MACRO_SENSITIVITY,
            SectorClaimCategory.INDUSTRY_CHAINS,
            SectorClaimCategory.ANOMALIES,
            SectorClaimCategory.RISKS,
            SectorClaimCategory.CYCLE,
        }
    ),
}


def build_sector_context_usage(
    bundle: SectorContextBundle,
    claims_by_role: dict[AgentName, tuple[ClaimEvidenceBinding, ...]],
) -> tuple[SectorContextUsageDiagnostic, ...]:
    """Derive exact role-level Sector use from accepted Claim lineage."""

    claim_index: dict[str, ClaimEvidenceBinding] = {
        claim.claim_id: claim
        for claim in bundle.accepted_claims
        if claim.claim_id is not None
    }
    for claims in claims_by_role.values():
        claim_index.update(
            {claim.claim_id: claim for claim in claims if claim.claim_id is not None}
        )
    sector_ids = {
        claim.claim_id for claim in bundle.accepted_claims if claim.claim_id is not None
    }

    def sector_ancestors(claim_id: str, visited: set[str]) -> set[str]:
        if claim_id in visited:
            return set()
        if claim_id in sector_ids:
            return {claim_id}
        claim = claim_index.get(claim_id)
        if claim is None:
            return set()
        next_visited = {*visited, claim_id}
        return set().union(
            *(
                sector_ancestors(parent, next_visited)
                for parent in claim.upstream_claim_ids
            )
        )

    diagnostics: list[SectorContextUsageDiagnostic] = []
    for role in AgentName:
        projection = SectorContextProjector.for_role(bundle, role)
        provided = tuple(
            item.claim_id
            for item in (
                projection.validated_claims
                if projection.validated_claims
                else projection.context_claims
            )
            if item.claim_id is not None
        )
        used: set[str] = set()
        for claim in claims_by_role.get(role, ()):
            for upstream_id in claim.upstream_claim_ids:
                used.update(sector_ancestors(upstream_id, set()))
        used_ordered = tuple(item for item in provided if item in used)
        provided_events = tuple(item.event_id for item in projection.event_references)
        used_events = tuple(
            event.event_id
            for event in projection.event_references
            if set(event.supporting_sector_claim_ids) & set(used_ordered)
        )
        serialized = json.dumps(
            projection.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        diagnostics.append(
            SectorContextUsageDiagnostic(
                sector_context_id=bundle.context_id,
                agent_role=role,
                provided_sector_claim_ids=provided,
                used_sector_claim_ids=used_ordered,
                provided_event_ids=provided_events,
                used_event_ids=used_events,
                serialized_context_chars=len(serialized),
            )
        )
    return tuple(diagnostics)


_EVENT_ROLES = {
    AgentName.NEWS_EVENT_ANALYST,
    AgentName.RESEARCH_MANAGER,
    AgentName.RISK_MANAGER,
}


class SectorContextBuilder:
    """Build one context from already-resolved Sector inputs without I/O."""

    @staticmethod
    def build(
        *,
        asset_id: AssetId,
        research_as_of: datetime,
        sector_name: str,
        memberships: tuple[SectorMembership, ...],
        sector_output: SectorResearchOutput | None,
        sector_snapshot: SectorResearchSnapshot | None,
        macro_snapshot: SectorMacroSnapshot | None,
        anomaly_events: tuple[SectorAnomalyEvent, ...] = (),
        industry_chains: tuple[IndustryChainDefinition, ...] = (),
    ) -> SectorContextResolution:
        """Resolve one primary PIT membership or return explicit empty-valid state."""

        effective = tuple(
            item
            for item in memberships
            if item.asset_id == asset_id and item.is_effective(research_as_of.date())
        )
        if not effective:
            return SectorContextResolution(
                asset_id=asset_id,
                research_as_of=research_as_of,
                status=SectorCapabilityStatus.MISSING,
                reason="No effective Sector membership exists at research_as_of.",
            )
        ordered = sorted(
            effective,
            key=lambda item: (
                -item.weight,
                -item.confidence,
                item.sector_id.value,
                item.version,
            ),
        )
        primary = ordered[0]
        same_sector = tuple(
            item for item in effective if item.sector_id is primary.sector_id
        )
        if sector_output is None:
            return SectorContextResolution(
                asset_id=asset_id,
                research_as_of=research_as_of,
                status=SectorCapabilityStatus.MISSING,
                reason="Sector Research Agent output is unavailable.",
            )
        if sector_snapshot is None or macro_snapshot is None:
            return SectorContextResolution(
                asset_id=asset_id,
                research_as_of=research_as_of,
                status=SectorCapabilityStatus.MISSING,
                reason="Aligned deterministic Sector snapshots are unavailable.",
            )
        _validate_alignment(
            research_as_of=research_as_of,
            sector_id=primary.sector_id,
            sector_output=sector_output,
            sector_snapshot=sector_snapshot,
            macro_snapshot=macro_snapshot,
        )
        chain_ids = tuple(
            dict.fromkeys(
                chain_id for item in same_sector for chain_id in item.chain_ids
            )
        )
        known_chains = {
            item.chain_id
            for item in industry_chains
            if item.sector_id is primary.sector_id
            and item.is_effective(research_as_of.date())
        }
        active_chain_ids = tuple(item for item in chain_ids if item in known_chains)
        events = tuple(
            item
            for item in anomaly_events
            if item.sector_id is primary.sector_id
            and item.available_at <= research_as_of
            and item.ingested_at <= research_as_of
            and (
                not item.chain_ids
                or bool(set(item.chain_ids) & set(active_chain_ids))
                or asset_id in item.source_asset_ids
                or asset_id in item.affected_asset_ids
            )
        )
        claims_by_event = _claims_by_event(sector_output)
        event_refs = tuple(
            SectorContextEventReference(
                event_id=event.event_id,
                event_type=event.event_type.value,
                severity=event.severity.value,
                status=event.status.value,
                available_at=event.available_at,
                chain_ids=tuple(
                    item for item in event.chain_ids if item in active_chain_ids
                ),
                supporting_sector_claim_ids=claims_by_event.get(event.event_id, ()),
            )
            for event in sorted(
                events,
                key=lambda item: (item.available_at, item.event_id),
            )
            if claims_by_event.get(event.event_id)
        )
        seed_only = all("seed" in item.source.casefold() for item in same_sector)
        quality = _combined_quality(
            sector_snapshot.status,
            macro_snapshot.status,
            seed_only=seed_only,
        )
        uncertainties = list(sector_output.uncertainties)
        if seed_only:
            uncertainties.append(
                "Asset-to-Sector membership comes from the non-exhaustive Day30 seed."
            )
        if len({item.sector_id for item in effective}) > 1:
            uncertainties.append(
                "Multiple effective Sector memberships exist; the highest-weight "
                "membership was selected deterministically."
            )
        context_id = _context_id(
            asset_id=asset_id,
            research_as_of=research_as_of,
            sector_output=sector_output,
            membership_versions=tuple(item.version for item in same_sector),
        )
        bundle = SectorContextBundle(
            context_id=context_id,
            asset_id=asset_id,
            sector_id=primary.sector_id,
            sector_name=sector_name,
            sector_scope_id=sector_output.sector_scope_id,
            research_as_of=research_as_of,
            membership_versions=tuple(
                dict.fromkeys(item.version for item in same_sector)
            ),
            membership_sources=tuple(
                dict.fromkeys(item.source for item in same_sector)
            ),
            membership_confidence=max(item.confidence for item in same_sector),
            active_chain_ids=active_chain_ids,
            cycle_assessment=sector_output.cycle_assessment,
            accepted_claims=sector_output.claims,
            active_events=event_refs,
            sector_snapshot_id=sector_snapshot.snapshot_id,
            macro_snapshot_id=macro_snapshot.snapshot_id,
            coverage=SectorContextCoverage(
                membership_count=len(same_sector),
                claim_count=len(sector_output.claims),
                chain_count=len(active_chain_ids),
                event_count=len(event_refs),
                sector_state=sector_snapshot.status,
                macro_state=macro_snapshot.status,
                seed_only_membership=seed_only,
            ),
            quality=quality,
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            missing_data=sector_output.missing_data,
        )
        return SectorContextResolution(
            asset_id=asset_id,
            research_as_of=research_as_of,
            status=quality,
            bundle=bundle,
        )


class SectorContextProjector:
    """Project one compact role-specific view from a Sector context bundle."""

    @staticmethod
    def for_role(
        bundle: SectorContextBundle,
        agent_role: AgentName,
    ) -> SectorRoleContext:
        """Return only categories and events relevant to one existing role."""

        if agent_role not in _ROLE_CATEGORIES:
            raise ValueError("Sector context projection requires an eight-Agent role")
        selected = tuple(
            item
            for item in bundle.accepted_claims
            if item.category in _ROLE_CATEGORIES[agent_role]
        )
        selected_ids = {item.claim_id for item in selected}
        events = (
            tuple(
                item
                for item in bundle.active_events
                if set(item.supporting_sector_claim_ids) & selected_ids
            )
            if agent_role in _EVENT_ROLES
            else ()
        )
        common = {
            "context_id": bundle.context_id,
            "agent_role": agent_role,
            "asset_id": bundle.asset_id,
            "sector_id": bundle.sector_id,
            "sector_name": bundle.sector_name,
            "research_as_of": bundle.research_as_of,
            "quality": bundle.quality,
            "cycle_assessment": bundle.cycle_assessment,
            "active_chain_ids": bundle.active_chain_ids,
            "event_references": events,
            "uncertainties": bundle.uncertainties,
            "missing_data": bundle.missing_data,
        }
        if agent_role in _ANALYSTS:
            return SectorRoleContext.model_validate(
                {
                    **common,
                    "context_claims": tuple(
                        SectorContextClaimSummary(
                            claim_id=item.claim_id or "",
                            category=item.category,
                            claim_text=item.claim_text,
                            confidence=item.confidence,
                        )
                        for item in selected
                    ),
                    "usage_policy": (
                        "Sector Claims are conditional background only; accepted "
                        "asset Claims still require role-visible asset Evidence."
                    ),
                }
            )
        if agent_role not in _MANAGERS:  # pragma: no cover - guarded above
            raise ValueError("Unsupported Agent role")
        return SectorRoleContext.model_validate(
            {
                **common,
                "validated_claims": selected,
                "usage_policy": (
                    "Manager Claims may reference these accepted Sector Claim IDs "
                    "as direct upstream; do not introduce new numeric facts."
                ),
            }
        )


class RepositorySectorContextResolver:
    """Resolve Day36 context through existing Sector repositories and outputs."""

    def __init__(
        self,
        *,
        ontology_repository: SectorOntologyRepository,
        macro_repository: SectorOntologyRepository,
        radar_repository: SectorOntologyRepository,
        sector_outputs: dict[SectorId, SectorResearchOutput],
    ) -> None:
        """Bind repositories while keeping Sector Agent execution external."""

        self._ontology = ontology_repository
        self._macro = macro_repository
        self._radar = radar_repository
        self._outputs = dict(sector_outputs)

    def resolve(
        self,
        *,
        asset_id: AssetId,
        research_as_of: datetime,
    ) -> SectorContextResolution:
        """Load PIT memberships, state, events, and accepted Sector Claims."""

        memberships = tuple(
            self._ontology.list_memberships(
                asset_id,
                as_of=research_as_of.date(),
            )
        )
        if not memberships:
            return SectorContextBuilder.build(
                asset_id=asset_id,
                research_as_of=research_as_of,
                sector_name="Unknown Sector",
                memberships=(),
                sector_output=None,
                sector_snapshot=None,
                macro_snapshot=None,
            )
        primary = sorted(
            memberships,
            key=lambda item: (
                -item.weight,
                -item.confidence,
                item.sector_id.value,
                item.version,
            ),
        )[0]
        output = self._outputs.get(primary.sector_id)
        sector_snapshot = self._ontology.get_latest_research_snapshot(
            primary.sector_id,
            as_of=research_as_of.date(),
        )
        macro_snapshot = self._macro.get_latest_macro_snapshot(
            primary.sector_id,
            as_of=research_as_of.date(),
        )
        seed = build_sector_ontology_seed_v1()
        sector_name = next(
            item.name
            for item in seed.ontology.sectors
            if item.sector_id is primary.sector_id
        )
        chains = tuple(
            item
            for item in seed.chains
            if item.sector_id is primary.sector_id
            and item.is_effective(research_as_of.date())
        )
        events_by_id: dict[str, SectorAnomalyEvent] = {}
        scope_ids = {
            f"SECTOR:{primary.sector_id.value}",
            *(
                f"CHAIN:{chain_id}"
                for item in memberships
                for chain_id in item.chain_ids
            ),
        }
        if output is not None:
            scope_ids.add(output.sector_scope_id)
        for scope_id in scope_ids:
            for event in self._radar.list_anomalies_for_scope(
                scope_id,
                as_of=research_as_of,
            ):
                events_by_id[event.event_id] = event
        return SectorContextBuilder.build(
            asset_id=asset_id,
            research_as_of=research_as_of,
            sector_name=sector_name,
            memberships=memberships,
            sector_output=output,
            sector_snapshot=sector_snapshot,
            macro_snapshot=macro_snapshot,
            anomaly_events=tuple(events_by_id.values()),
            industry_chains=chains,
        )


class FrozenSectorContextResolver:
    """Expose one already-built PIT Sector context through the runtime protocol."""

    def __init__(self, bundle: SectorContextBundle) -> None:
        """Retain one validated artifact without rebuilding Sector intelligence."""

        self._bundle = bundle

    def resolve(
        self,
        *,
        asset_id: AssetId,
        research_as_of: datetime,
    ) -> SectorContextResolution:
        """Return the exact aligned artifact or an explicit missing resolution."""

        if self._bundle.asset_id != asset_id:
            return SectorContextResolution(
                asset_id=asset_id,
                research_as_of=research_as_of,
                status=SectorCapabilityStatus.MISSING,
                reason="Configured Sector context belongs to another asset.",
            )
        if self._bundle.research_as_of != research_as_of:
            return SectorContextResolution(
                asset_id=asset_id,
                research_as_of=research_as_of,
                status=SectorCapabilityStatus.MISSING,
                reason="Configured Sector context does not match research_as_of.",
            )
        return SectorContextResolution(
            asset_id=asset_id,
            research_as_of=research_as_of,
            status=self._bundle.quality,
            bundle=self._bundle,
        )


def _validate_alignment(
    *,
    research_as_of: datetime,
    sector_id: object,
    sector_output: SectorResearchOutput,
    sector_snapshot: SectorResearchSnapshot,
    macro_snapshot: SectorMacroSnapshot,
) -> None:
    if sector_output.sector_id is not sector_id:
        raise ValueError("Sector output does not match asset membership")
    if sector_snapshot.sector_id is not sector_id:
        raise ValueError("Sector state does not match asset membership")
    if macro_snapshot.sector_id is not sector_id:
        raise ValueError("Sector macro state does not match asset membership")
    if sector_output.research_as_of != research_as_of:
        raise ValueError("Sector output must share the asset research cutoff")
    if sector_snapshot.as_of > research_as_of.date():
        raise ValueError("future Sector state cannot enter asset research")
    if macro_snapshot.as_of > research_as_of.date():
        raise ValueError("future Sector macro state cannot enter asset research")
    if macro_snapshot.source_sector_snapshot_id != sector_snapshot.snapshot_id:
        raise ValueError("Sector macro lineage does not match Sector state")


def _claims_by_event(
    output: SectorResearchOutput,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for claim in output.claims:
        if claim.claim_id is None:
            continue
        for evidence_id in claim.evidence_ids:
            if not evidence_id.startswith("event:"):
                continue
            result.setdefault(evidence_id.removeprefix("event:"), []).append(
                claim.claim_id
            )
    return {key: tuple(dict.fromkeys(value)) for key, value in result.items()}


def _combined_quality(
    sector: SectorCapabilityStatus,
    macro: SectorCapabilityStatus,
    *,
    seed_only: bool,
) -> SectorCapabilityStatus:
    if SectorCapabilityStatus.MISSING in {sector, macro}:
        return SectorCapabilityStatus.MISSING
    if seed_only or SectorCapabilityStatus.PARTIAL in {sector, macro}:
        return SectorCapabilityStatus.PARTIAL
    return SectorCapabilityStatus.AVAILABLE


def _context_id(
    *,
    asset_id: AssetId,
    research_as_of: datetime,
    sector_output: SectorResearchOutput,
    membership_versions: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "asset_id": str(asset_id),
            "research_as_of": research_as_of.isoformat(),
            "sector_id": sector_output.sector_id.value,
            "claim_ids": [item.claim_id for item in sector_output.claims],
            "membership_versions": membership_versions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sector_context_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"
