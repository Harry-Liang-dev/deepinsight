"""Project current uncertainties along a scenario's actual reference graph."""

from src.schemas.research_v2_collaboration import AnalystResult, Scenario, Statement
from src.schemas.research_v2_shared import Reference, canonical


def scenario_uncertainties(
    case: Scenario, results: tuple[AnalystResult, ...], primary_role: str
) -> tuple[Statement, ...]:
    """Preserve exact source statements, not unrelated same-asset concerns.

    Unscoped uncertainty qualifies only when its current result contributes to
    this scenario. Explicitly scoped uncertainty additionally needs a consumed
    support/counter-reference. Shared evidence does not expand to all facts in
    the contributing result. Never infer relevance from similar prose.
    """
    refs = set((*case.major_evidence, *case.opposing_evidence))
    statements = (*case.statements, *case.assumptions, *case.mechanisms)
    for s in (
        *statements,
        *(
            t.statement
            for t in (
                *case.catalysts,
                *case.risk_triggers,
                *case.thesis_change_conditions,
            )
        ),
    ):
        refs.update((*s.support, *s.counter_evidence, *s.confidence.support))
    for q in case.open_questions:
        refs.update(q.subject_refs)
    for c in case.contradictions:
        refs.update((c.left, c.right))
    direct = {canonical(s) for s in statements}
    current = {r.reference: r for r in results}
    selected: set[Reference] = {
        r.reference
        for r in results
        if r.participant == primary_role
        or bool(refs.intersection((*r.claims, *r.evidence_refs)))
        or any(canonical(s) in direct for s in (*r.findings, *r.hypotheses))
    }
    # Follow only exact, current Analyst dependencies; never stale read-State contents.
    pending = list(selected)
    while pending:
        r = current[pending.pop()]
        for dependency in r.dependencies:
            if dependency in current and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    found: dict[bytes, Statement] = {}
    for r in sorted(
        results, key=lambda r: (r.scope_id, r.participant, r.reference.sha256)
    ):
        if r.reference not in selected:
            continue
        for s in r.uncertainties:
            scope = (*s.support, *s.counter_evidence)
            if scope and not refs.intersection(scope):
                continue
            found.setdefault(canonical(s), s)
    return tuple(found.values())


def project_uncertainties(
    case: Scenario, results: tuple[AnalystResult, ...], primary_role: str
) -> Scenario:
    """Add current relevant uncertainty without rewriting existing provenance."""
    found = {canonical(s): s for s in case.uncertainties}
    for s in scenario_uncertainties(case, results, primary_role):
        found.setdefault(canonical(s), s)
    return case.model_copy(update={"uncertainties": tuple(found.values())})
