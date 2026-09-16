# Research → Quant Handoff Contract v1

## Purpose

`ResearchQuantHandoffBundle v1` is the only formal, versioned boundary from
this Research repository to a future `deepinsight-quant` repository. It lets
Quant consume stable Research identities, Satellite descriptors, coverage,
versions, and provenance without understanding Agent, Memory, Provider,
DuckDB, or report internals.

```text
Evidence → Claim → ResearchState → SatelliteAlphaObservation
                              ├── OpportunityCandidate
                              └── ResearchStateTransition
                                           ↓
                          ResearchQuantHandoffBundle
                                           ↓
                              future deepinsight-quant
```

The Builder and exporter are deterministic and make zero LLM and Provider
calls.

## Ownership boundary

DeepInsight Research guarantees canonical Asset identity, one explicit
`research_as_of`, PIT-safe frozen inputs, versioned Selection and Timing
Satellite references, optional Opportunity and Transition references,
explicit coverage/quality, deterministic semantic identity, and compact
provenance.

Future `deepinsight-quant` owns the Base PIT Universe, Planetary Alpha,
normalization, neutralization, Factor exposure and validation, IC/RankIC,
Alpha Models, Top-K selection, timing decisions, Holdings, Regime/MoE,
portfolio construction, risk transforms, backtests, and execution. None of
those outputs exists in the v1 handoff.

## Bundle schema

The Bundle contains:

- deterministic `bundle_id`, canonical `asset_id`/`market`, and
  `research_as_of`;
- optional canonical Sector and ordered Industry-Chain IDs;
- required ResearchState and ResearchEpisode IDs;
- optional OpportunityCandidate and ResearchStateTransition IDs;
- compact Selection and Timing Satellite references;
- optional catalyst, risk, invalidator, and research-horizon references copied
  only from the validated Candidate;
- aggregate coverage and existing deterministic data-quality vocabulary;
- source run/data snapshot IDs, a centralized version manifest, compact
  provenance indexes, and non-semantic `created_at`.

It does not copy ResearchState, Episode, Claims, Evidence payloads, Agent
outputs, Memory records, report prose, embeddings, or database rows.

## Selection payload

Selection references may identify the seven existing Selection/Both families:

- `CHAIN_BENEFIT_ELASTICITY`
- `EXPECTATION_REVISION`
- `LOGIC_CERTAINTY`
- `RISK_BURDEN`
- `EVIDENCE_STRENGTH`
- `SECTOR_CHAIN_ALIGNMENT`
- `RESEARCH_DISAGREEMENT`

Each compact reference retains observation ID, family, usage, coverage,
definition/transform version, and availability. It is not a rank or score.

## Timing payload

Timing references may identify:

- `STATE_TRANSITION`
- `EXPECTATION_REVISION_VELOCITY`
- `THESIS_UPGRADE_DOWNGRADE`
- `RISK_ESCALATION`
- `EVIDENCE_CONFIRMATION`
- `EVENT_WINDOW`
- `CATALYST_PROXIMITY`

When a Transition is supplied, it must terminate at the Bundle's current
ResearchState and cutoff. A missing Transition is legal; history-dependent
observations remain `REQUIRES_HISTORY` or preserve their source-run status.
Timing describes State evolution, never entry, exit, Buy, Sell, or sizing.

## OpportunityCandidate semantics

Candidate linkage is optional. A Bundle can carry a `QUALIFIED` Candidate, an
`INSUFFICIENT_RESEARCH` Candidate, or no Candidate at all. Satellite and State
export therefore does not select only favorable assets and does not erase
negative, weak, incomplete, or history-poor examples.

## Coverage and quality

The handoff reuses Satellite coverage unchanged:

`AVAILABLE`, `PARTIAL`, `EMPTY_VALID`, `MISSING_INPUT`, `NOT_RESEARCHED`,
`NOT_AVAILABLE_AT_SOURCE_RUN`, `NOT_APPLICABLE`, `REQUIRES_HISTORY`, and
`UNSUPPORTED`.

Every Satellite reference retains its own status. Mixed branches produce an
explicit aggregate `PARTIAL`; uniform unavailable branches retain their exact
status. Missing is never encoded as zero or as an empty numeric score.
`data_quality` uses the existing `DataQualityStatus` vocabulary and introduces
no new score.

## Identity and versioning

`bundle_id` is a canonical SHA-256 semantic identity over Asset/cutoff,
State/Episode/Candidate/Transition identities, canonically ordered Satellite
references, coverage, source lineage, and all interpretation versions.
`created_at` is deliberately excluded.

The version manifest records ResearchState schema/state versions,
ResearchEpisode schema version, Satellite observation schema and per-family
definition versions, optional Candidate/Transition versions, and the handoff
Builder version. A future consumer must not mix incompatible versions without
an explicit Quant-side migration.

## Asset identity and PIT contract

The Bundle reuses `AssetId` and its `Market`; it creates no ticker convention
or Quant Security Master. A future permanent issuer/listing master may join to
this canonical identity under its own versioned contract.

Every State, Episode, Candidate, Satellite, and Transition must match the same
Asset and `research_as_of`. State features remain validated at their original
cutoff. Derived artifacts may be materialized later, but must exist by the
handoff `created_at`; that later artifact clock cannot introduce a later
research cutoff or future source fact. Transition predecessors remain strictly
earlier than the current State.

## Provenance

The Bundle stores sorted Claim, Evidence, Event, Sector-Claim, and artifact ID
indexes. The Builder verifies State/Episode/Candidate/Transition identity,
Satellite branch usage, State-feature references, and Candidate observation
closure. The recursive path remains:

```text
Bundle → Candidate / Observation / Transition → ResearchState / Episode
       → State Feature / Claim / Sector Event → Evidence → Provider lineage
```

No Evidence body crosses the boundary.

## Quant-facing Satellite wire payload

Each Selection or Timing item is a compact, self-contained descriptor
projection. It contains the Observation ID and Alpha family together with its
exact definition/transform versions, usage, comparison scope, coverage,
value, structured value components, quality, confidence, missing reasons, and
availability time. These fields are copied faithfully from the source
`SatelliteAlphaObservation`; the Handoff does not reinterpret them.

Components retain stable provenance references, but the wire payload does not
inline Evidence, Claims, ResearchState, Agent output, or Memory internals. An
external consumer can therefore interpret the descriptor from JSON alone and
use `observation_id` to resolve its deeper Research provenance when needed.

## Serialization and batch export

Single-Bundle export is canonical sorted-key JSON with stable compact
separators. Batch export writes Bundles ordered by `bundle_id` to JSONL and a
credential-free manifest containing deterministic export ID, canonical
cutoffs, asset/Bundle counts, ordered IDs, source runs, coverage counts, schema
version, artifact name, and generation time.

The canonical Quant join key in v1 is `(asset_id, research_as_of)` and it must
be unique within one batch. Duplicate keys are rejected before artifact
creation; there is no first-write, last-write, or implicit variant behavior.
Different Assets may share a cutoff, and one Asset may appear at different
cutoffs. A single-cutoff manifest exposes `research_as_of`; a multi-cutoff
manifest sets it to null and lists every cutoff in `research_as_of_values`.

A batch may mix available, partial, missing-input, source-run-unavailable, and
history-required Bundles. Incomplete Research is exportable; only invalid
identity, temporal, version, or provenance contracts hard-fail.

## Historical behavior

- Phase 3 AAPL retains no later Sector, Chain, or Timing backfill.
- Phase 4A uses only the Sector/Chain information retained by its source run.
- Frozen rebuild may deterministically regenerate Satellite, Candidate,
  Transition when legal, and Handoff IDs with zero new LLM/Provider calls.
- Contract fixtures demonstrate multi-coverage and history behavior; they are
  not Quant Alpha validation or performance evidence.

## Forbidden fields

The contract excludes raw prompts, chain-of-thought, model scratchpads, raw
model responses, private embeddings, FAISS IDs, DuckDB row IDs, Planetary
Alpha, Factor exposure/z-score/rank, IC/RankIC, Alpha forecast, expected return,
Top-K, trade signals, Buy/Sell, entry/exit, positions, portfolio weights,
MoE weights, orders, and execution instructions.

## Known limitations

- Permanent issuer identity across ticker/listing changes remains a future
  Quant Asset Master concern.
- `PEER_GROUP` comparison remains unsupported.
- Real continuous ResearchState and positive historical Memory coverage remain
  limited; several Timing references are partial or require history.
- JSON/JSONL is an artifact contract, not a network transport or service SLA.
- Day48 validates structure, replay, PIT, and lineage—not Factor efficacy,
  ranking quality, predictive Alpha, or investment performance.

## Phase 4 Golden Acceptance

Day49 accepts Handoff v1 as the terminal Research artifact. Frozen Phase3 and
Phase4A scenarios reproduce stable identities with zero Provider and LLM calls;
an external consumer reads Selection/Timing values, components, scopes,
coverage, Candidate state, and versions from JSON/JSONL without importing
Research services. The canonical batch join key remains unique
`(asset_id, research_as_of)`.

This readiness means the future Quant system can integrate against a stable
contract. It does not mean `deepinsight-quant`, a Quant universe, Factor
validation, ranking, strategy, portfolio, or execution exists. Full acceptance
evidence and retained limitations are in
`data/golden_replay/day49/acceptance_summary.json`.
