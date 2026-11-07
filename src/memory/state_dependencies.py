"""Project original accepted Claim/State provenance into G85 dependency inputs."""

from __future__ import annotations

from datetime import datetime

from src.memory.incremental import ResearchDependency, SourceSnapshot
from src.memory.vnext_contracts import Scope
from src.models.enums import ResearchScopeType
from src.schemas.research_state import ResearchStateBuildInput, ResearchStateSection
from src.schemas.research_v2_shared import Reference, reference
from src.services.research_state import ResearchStateBuilder


def dependencies_from_state(
    inputs: ResearchStateBuildInput,
    sources: tuple[SourceSnapshot, ...],
    *,
    valid_until: datetime,
) -> tuple[ResearchDependency, ...]:
    """Use original builder checks and exact accepted Claim provenance.

    A source must resolve to a retained snapshot. Sector membership alone never
    invalidates all company research. This projection creates reference edges,
    not another ResearchState implementation or new accepted Claims.
    """
    state = ResearchStateBuilder().build(inputs)
    scope = Scope(
        scope_type=ResearchScopeType.ASSET, scope_id=state.hierarchy.asset_scope_id
    )
    by_evidence: dict[str, set[str]] = {}
    for source in sources:
        for evidence in source.evidence:
            by_evidence.setdefault(evidence.id, set()).add(source.key)
    claims = [c.claim for c in inputs.accepted_claims]
    if inputs.sector_context is not None:
        claims.extend(inputs.sector_context.accepted_claims)
    refs: dict[str, Reference] = {}
    for claim in claims:
        if claim.claim_id is None:
            raise ValueError("CLAIM_ID_REQUIRED")
        refs[claim.claim_id] = reference(
            "CLAIM", claim.claim_id, "claim_evidence_binding_v1", claim
        )
    result = []
    for claim in claims:
        assert claim.claim_id is not None
        if set(claim.evidence_ids) - set(by_evidence):
            raise ValueError("UNRESOLVED_CLAIM_SOURCE_SNAPSHOT")
        keys = {key for eid in claim.evidence_ids for key in by_evidence[eid]}
        result.append(
            ResearchDependency(
                artifact=refs[claim.claim_id],
                scope=scope,
                source_keys=tuple(sorted(keys)),
                upstream=tuple(refs[c] for c in claim.upstream_claim_ids),
                valid_from=state.research_as_of,
                valid_until=valid_until,
            )
        )
    state_keys: set[str] = set()
    by_artifact = {source.source.artifact_id: source.key for source in sources}
    for name in type(state).model_fields:
        section = getattr(state, name)
        if not isinstance(section, ResearchStateSection):
            continue
        for feature in section.features:
            for eid in feature.source_evidence_ids:
                if eid not in by_evidence:
                    raise ValueError("UNRESOLVED_STATE_EVIDENCE")
                state_keys.update(by_evidence[eid])
            for aid in feature.source_artifact_ids:
                if aid not in by_artifact:
                    raise ValueError("UNRESOLVED_STATE_ARTIFACT")
                state_keys.add(by_artifact[aid])
    result.append(
        ResearchDependency(
            artifact=reference(
                "STATE", state.research_state_id, state.research_state_version, state
            ),
            scope=scope,
            source_keys=tuple(sorted(state_keys)),
            upstream=tuple(refs.values()),
            valid_from=state.research_as_of,
            valid_until=valid_until,
        )
    )
    return tuple(result)
