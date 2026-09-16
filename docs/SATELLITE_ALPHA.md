# Satellite Alpha Ontology v1

## Terminology and boundary

Satellite Alpha is an attributable structured **research descriptor** derived
from frozen Evidence, accepted Claims, ResearchState, Sector/Industry-Chain
context, events, debate, risk, and Memory. It is not a Quant Factor exposure,
rank, signal, recommendation, target price, or portfolio instruction.

```text
Evidence → Validated Claim → ResearchState Feature
         → SatelliteAlphaObservation → future ResearchQuantHandoffBundle
```

`usage = selection | timing | both` describes potential downstream research
use. It does not perform selection or timing. Those transformations belong to
the future `deepinsight-quant` repository.

## Lifecycle and identity

`SatelliteAlphaDefinition` versions stable meaning independently from one
`SatelliteAlphaObservation`. The v1 mapper consumes a frozen ResearchState and
optional matching ResearchEpisode. It makes zero LLM and Provider calls and
does not parse reports.

Observation identity is a canonical SHA-256 fingerprint of asset, cutoff,
definition, value semantics, coverage, State/Episode identity, and compact
lineage. `created_at` is audit metadata and cannot change identity. Numeric
components require explicit unit, scale, transform version, section-qualified
State feature references, and Claim/Evidence/artifact provenance.

## Comparison and coverage

Comparison scopes are `MARKET`, `SECTOR`, `INDUSTRY_CHAIN`, `PEER_GROUP`, and
`ASSET_TIME_SERIES`. `PEER_GROUP` is schema vocabulary only because no formal
PIT peer-group contract exists. It must remain `UNSUPPORTED` until one exists.

Coverage is explicit: `AVAILABLE`, `PARTIAL`, `EMPTY_VALID`, `MISSING_INPUT`,
`NOT_RESEARCHED`, `NOT_AVAILABLE_AT_SOURCE_RUN`, `NOT_APPLICABLE`,
`REQUIRES_HISTORY`, or `UNSUPPORTED`. Missing is never encoded as numeric zero.

## Family registry

| Family | Usage | Scope | Day47 production capability |
|---|---|---|---|
| CHAIN_BENEFIT_ELASTICITY | SELECTION | INDUSTRY_CHAIN | PARTIAL |
| EXPECTATION_REVISION | BOTH | ASSET_TIME_SERIES | PARTIAL |
| LOGIC_CERTAINTY | SELECTION | ASSET_TIME_SERIES | PARTIAL |
| RISK_BURDEN | SELECTION | MARKET | PARTIAL |
| EVIDENCE_STRENGTH | SELECTION | MARKET | IMPLEMENTED |
| SECTOR_CHAIN_ALIGNMENT | SELECTION | INDUSTRY_CHAIN | IMPLEMENTED |
| RESEARCH_DISAGREEMENT | SELECTION | MARKET | PARTIAL |
| STATE_TRANSITION | TIMING | ASSET_TIME_SERIES | IMPLEMENTED (2) |
| EXPECTATION_REVISION_VELOCITY | TIMING | ASSET_TIME_SERIES | IMPLEMENTED; 2-point first order, 3-point second order |
| EVENT_WINDOW | TIMING | ASSET_TIME_SERIES | IMPLEMENTED / source-conditional |
| THESIS_UPGRADE_DOWNGRADE | TIMING | ASSET_TIME_SERIES | IMPLEMENTED / source-conditional (2) |
| RISK_ESCALATION | TIMING | ASSET_TIME_SERIES | IMPLEMENTED / source-conditional (2) |
| EVIDENCE_CONFIRMATION | TIMING | ASSET_TIME_SERIES | IMPLEMENTED / source-conditional (2) |
| CATALYST_PROXIMITY | TIMING | ASSET_TIME_SERIES | IMPLEMENTED / source-conditional |

Chain benefit keeps business binding, exposure, incremental potential,
capacity readiness, competitive position, and evidence quality as separate
component semantics. Missing components are reported; no `0.87`-style opaque
score is generated. Evidence strength inventories attributable State coverage
and does not copy the report evaluator score. Risk burden reuses, rather than
redefines, the Risk Agent taxonomy. Alignment never treats mere Sector context
as positive. Disagreement consumes accepted structured debate only, never
private model reasoning.

## PIT, provenance, and historical compatibility

The mapper calls Unified Temporal Contract v1 for every source State feature.
An Observation has its own `available_at` and cannot be consumed earlier.
Provenance retains compact reference paths:

```text
Observation → ResearchState → Claim → Evidence
Observation → Sector Claim → Sector/Radar/Macro source artifact
```

Phase 3 artifacts keep later Sector/Chain semantics as
`NOT_AVAILABLE_AT_SOURCE_RUN`; they are never backfilled. Phase 4A artifacts
use only context retained by their source run. ResearchState v1 stores a
Sector scope but not canonical `sector_id`, so the mapper leaves `sector_id`
empty rather than inferring it.

## ResearchState semantic support audit

| Dimension | Current source | Support | Missing semantic |
|---|---|---|---|
| logic stage | event/thesis accepted Claims | PARTIAL | finite stage |
| expectation direction | event/thesis accepted Claims | PARTIAL | direction/subtype |
| risk taxonomy | risk accepted Claims | PARTIAL | component type |
| catalyst | event/thesis accepted Claims | PARTIAL | canonical ID/time |
| invalidator | debate accepted Claims | PARTIAL | path/disposition |
| sector-chain relationship | hierarchy and sections | PARTIAL | sector ID/alignment |
| research disagreement | debate accepted Claims | PARTIAL | role/disposition |
| event timing | feature clocks | PARTIAL | event ID/event time |

Future State versions may retain these semantics only when they already exist
in accepted structured upstream research. Day45 does not add another LLM score
and does not modify ResearchState v1.

## Day46 Selection production

`build_selection()` emits the seven `SELECTION`/`BOTH` definitions only. It
recognizes exact versioned State feature names for alignment, expectation
direction/subtype, logic stage, and chain-benefit components. It never scans
Claim text for keywords. Existing Risk paths (`confirmed_risks`,
`scenario_risks`, `watch_items`) become separate counts. Bull and Bear paths
deterministically establish that both debate sides are present, but remain
`MIXED/PARTIAL` because State v1 lacks an explicit disagreement disposition.

If an exact semantic State feature is absent, fluent Claim prose is not used
as a substitute. Current Phase3/Phase4A artifacts therefore retain their
historical coverage. An optional compact Day36 SectorContext projection adds
canonical Sector, Radar/Event, and Sector Claim IDs without embedding the
whole context payload.

The downstream research-only qualification contract is documented in
`docs/OPPORTUNITY_CANDIDATE.md`.

## Day47 Timing production

`ResearchStateTransitionBuilder` selects the nearest strictly earlier,
same-Asset, independently PIT-valid State. It creates a deterministic
reference-only `ResearchStateTransition` and projects all seven Timing
families into the existing `SatelliteAlphaObservation` contract. Optional
`previous_research_state_id` and `source_transition_id` fields close the
Observation lineage without introducing a second Timing schema.

Two expectation points support direction, delta, and elapsed-time rate only.
At least three ordered grounded numeric points are required for acceleration
or deceleration. Event and catalyst calendars use versioned deterministic
windows; an unavailable schedule, later Event outcome, future State, or future
Memory is rejected through Unified Temporal Contract v1. Missing structured
semantics remain explicit and are never inferred from report prose.

Full transition semantics, window definitions, Memory relationship, and
historical limitations are in `docs/RESEARCH_STATE_TRANSITION.md`.

## Phase 4 freeze status

Day49 accepts the ontology and deterministic Selection/Timing production
contracts. Satellite observations remain versioned, PIT-safe Research
descriptors with explicit missingness and provenance. They are not validated
Quant factors: Quant validation, incremental IC, and predictive Alpha remain
`NOT_STARTED` / `NOT_VALIDATED`. The NVDA/MU/AMD comparison and T1/T2/T3 timing
examples are `CONTRACT_FIXTURE`, not performance evidence.
