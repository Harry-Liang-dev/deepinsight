# ResearchStateTransition v1

## Boundary

`ResearchStateTransition` is a reference-only derived research artifact. It
describes how two immutable ResearchState snapshots for one Asset differ. It
is not a Memory level, Quant timing rule, signal, recommendation, position, or
execution instruction.

```text
ResearchState(T1) + ResearchState(T2)
→ ResearchStateTransition
→ existing SatelliteAlphaObservation (usage = TIMING)
```

The builder makes zero LLM and Provider calls and never parses report prose.
It consumes only frozen structured State features and compact typed Event,
Episode, and existing Memory-result references.

## Identity and lineage

The transition records canonical Asset identity, previous/current State IDs,
optional matching Episode IDs, both cutoffs, changed State dimensions,
structured change details, compact Claim/Event/Evidence/artifact references,
coverage, and comparison versions. Its semantic SHA-256 identity excludes
`created_at` and `available_at`; audit scheduling cannot change identity.

`SatelliteAlphaObservation` remains the only Satellite output. Day47 adds
optional `previous_research_state_id` and `source_transition_id` references to
that existing contract. No second Timing feature schema exists.

## History selection and PIT

For current `State(T2)`, the predecessor is the nearest State satisfying:

- same canonical `asset_id`;
- `T1 < T2` (equal cutoffs are invalid);
- every feature in `State(T1)` is independently valid at T1;
- every feature in `State(T2)` is independently valid at T2.

Selection is deterministic by cutoff and State ID. It never uses vector
similarity, report text, a future State, or a synthetic predecessor. All State,
Event, and Memory visibility checks reuse Unified Temporal Contract v1. A
scheduled future event may be described only when its schedule was available
at the current cutoff. A later outcome is validated on its own availability
clock and cannot enter a pre-event Observation.

Existing Memory remains L0–L4. A retrieved Memory may join transition lineage
only when it is PIT-visible and its source Claim is retained by the current
State. The transition ID is an artifact reference; there is no L5, Timing
Memory store, new DuckDB table, or exposed FAISS object.

## Timing family mappings

| Family | Structured source | Minimum history | Day47 behavior |
|---|---|---:|---|
| `STATE_TRANSITION` | exact `satellite.logic_certainty` | 2 | UPGRADE, DOWNGRADE, UNCHANGED, MIXED, UNKNOWN |
| `EXPECTATION_REVISION_VELOCITY` | numeric expectation value or categorical direction | 2 for direction/rate; 3 for second order | two points never claim acceleration/deceleration |
| `THESIS_UPGRADE_DOWNGRADE` | exact thesis disposition | 2 | UPGRADED, UNCHANGED, DOWNGRADED, INVALIDATED, UNCERTAIN |
| `RISK_ESCALATION` | component keys under `satellite.risk.*` | 2 | NEW_RISK, ESCALATING, STABLE, DEESCALATING, RESOLVED, MIXED, UNCERTAIN |
| `EVIDENCE_CONFIRMATION` | matching hypothesis key with new Evidence lineage | 2 | CONFIRMED, PARTIALLY_CONFIRMED, CONTRADICTED, UNRESOLVED, MIXED |
| `EVENT_WINDOW` | typed canonical Event ID/time/availability | 1 State + Event | versioned ±1-day focal window and ±30-day context |
| `CATALYST_PROXIMITY` | typed catalyst ID/time/availability | 1 State + catalyst | IMMINENT ≤7d, NEAR_TERM ≤30d, MEDIUM_TERM ≤90d, otherwise DISTANT |

Exact names are a versioned projection convention over the existing generic
ResearchState feature contract. Missing fields produce explicit coverage;
prose is never parsed to guess a category. Missing risk is not resolution, and
a still-positive thesis is not Evidence confirmation.

## Two-point and three-point semantics

Two grounded numeric expectation points permit a signed delta and calendar-
day change rate. They produce `PARTIAL` coverage because second-order change
is unavailable. Three ordered grounded points permit comparison of adjacent
rates and `ACCELERATING`, `DECELERATING`, or `STEADY`. Categorical-only history
remains `PARTIAL` and does not manufacture numeric deltas.

## Historical compatibility and limitations

Phase 3 and Phase 4A frozen single-State paths return `REQUIRES_HISTORY` or
`NOT_AVAILABLE_AT_SOURCE_RUN`; Day47 does not backfill them. Tests include
three-point upgrade/confirmation and downgrade CONTRACT FIXTURES. They prove
determinism and PIT behavior, not real Alpha, predictive value, or timing
performance.

The positive Memory test is also a deterministic contract fixture. There is
still no real historical Golden Replay with `memory_retrieval_count > 0` that
passes the complete PIT replay:

`REAL_HISTORICAL_MEMORY_REPLAY = NOT_YET_AVAILABLE`.
