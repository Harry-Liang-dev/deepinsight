# Current Status

Window 4 has implemented a Memory-owned, point-in-time
`ResearchContextBundle` boundary while retaining the existing L0–L4 hierarchy
and private FAISS Repository boundary. No Agent, Prompt, Provider, report,
Evaluation, `MODULE_STATUS.md`, or `DECISIONS.md` file was changed.

The bundle converts semantic candidates into explicit sections:

- `current_snapshot`
- `macro_events`
- `asset_events`
- `prior_research`
- `prior_risk`
- `historical_analogs`
- `regime_context`
- `retrieval_metadata`
- `missing_context`

Every returned item retains its original `SourceReference`, `effective_ts`,
importance, retrieval score, retrieval reason, Memory level/type, namespace,
asset, market and creator. Empty retrieval is represented by
`RetrievalStatus.EMPTY`, `no_relevant_memory = true`, and one explicit
`MissingContext` per requested empty section.

## Current Task

The Phase 3 Memory implementation now provides:

1. `MemoryService.retrieve_context(ResearchContextRequest)` as the structured
   retrieval entry point.
2. A mandatory timezone-aware `as_of`; eligibility requires
   `effective_ts <= as_of` before any result enters the bundle.
3. Exact namespace, asset, market and minimum-importance filtering.
4. `GLOBAL` context availability for a requested market without allowing
   another market's Memory.
5. L3 report-trace lookup by the same asset when
   `include_prior_reports = true`, with explicit `current_report_id` exclusion.
6. Deterministic relevance ordering by semantic score, then importance,
   effective time and Memory ID.
7. Provider-independent vector snapshot identity stable across Repository
   restart; no FAISS object or raw vector crosses the boundary.
8. Historical analog output only for stored L4 Memory whose explicit
   `memory_type` is `historical_analog` or `historical_analogue`. Similarity
   alone never creates an analog.
9. UTC-naive encoding for aware Memory timestamps written to DuckDB's
   timezone-naive `TIMESTAMP`, preventing host/session timezone drift during
   point-in-time comparison.

## API Changes

Implemented inside the Memory-owned package:

- `ResearchContextRequest`
- `ResearchContextMemory`
- `ResearchContextSection`
- `ResearchContextBundle`
- `RetrievalMetadata`
- `RetrievalStatus`
- `MissingContext`
- `MissingContextReason`
- `ResearchContextRetrievalError`
- `MemoryService.retrieve_context(request) -> ResearchContextBundle`
- `VectorRepository.snapshot_id(namespaces) -> str`

Requested from Main Agent before cross-module integration:

- Add `retrieve_context` to the shared Memory service Protocol or approve a
  separate Protocol owned by the integration layer.
- Replace raw `MemorySearchResult[]` consumption in `ResearchWorkflow` and
  Agent context projection with the approved `ResearchContextBundle` view.
- Supply report `as_of`, market, asset, namespaces and current report ID at the
  composition boundary. Do not derive `as_of` from wall-clock time.
- Decide whether FastAPI receives a new bundle route or keeps this as an
  internal research-pipeline contract.
- Reconcile `ResearchContextMemory.source` with the pending common
  `EvidenceItem` identity without creating a second evidence lineage family.
- Audit or migrate Memory rows written before UTC-naive normalization; their
  persisted naive timestamps may reflect the old DuckDB session timezone.
- Record the accepted point-in-time, snapshot-identity, historical-report and
  UTC timestamp policies in `docs/DECISIONS.md` if Main approves them.

## Files Changed

- `src/memory/contracts.py`
- `src/memory/retrieval.py`
- `src/memory/service.py`
- `src/memory/__init__.py`
- `src/repositories/memory.py`
- `src/repositories/vector.py`
- `tests/integration/memory/test_research_context_bundle.py`
- `docs/coordination/MEMORY.md`

## Tests

Memory-focused verification:

- `26 passed` across Memory integration, Memory Repository integration and
  vector Repository tests.
- Memory-scoped Ruff: passed.
- Memory-scoped strict mypy: passed (`9 source files`).
- Memory-scoped Black: passed.

Required Phase 3 cases implemented and passing:

- temporal leakage
- asset isolation
- market isolation
- explicit no-result state
- relevance ordering and importance filtering
- persistence/restart with stable snapshot identity
- rebuild
- historical report retrieval excluding future/current/other-asset reports
- L0–L4 section classification and no fabricated historical analogs

Full repository gates:

- pytest: `290 passed, 5 deselected`
- Ruff: passed
- Black: passed (`227 files unchanged`)
- `git diff --check`: passed
- full mypy: blocked by six existing non-Memory errors in
  `tests/unit/test_live_report.py` (object indexing, non-exported live smoke
  attributes, and one untyped function)

No live test or external service was invoked. No credential value was read,
printed, copied or persisted.

## Blockers

- No shared-interface blocker remains. Main integrated
  `ResearchContextBundle`, added `research_context_v1`, and resolved full
  mypy.
- Historical resolved blockers: Workflow migration, common citation policy
  and UTC timestamp policy were pending before ADR-0025.
- Existing pre-normalization rows are not rewritten automatically. A snapshot
  with uncertain timezone provenance must be audited or rebuilt before a
  point-in-time baseline.
- Real L0/L1/L2/L4 content coverage remains a data-population gap, not an
  interface blocker; empty sections continue to be explicit.

## Required Changes From Other Modules

- Resolved by Main: Protocol/composition migration, Agent projection,
  schema-version decision, citation policy and timestamp ADR.
- Future DATA writes must continue preserving UTC effective/release time and
  canonical asset/market lineage. No direct LLM Gateway dependency is needed.

## Ready For Integration

YES — integrated by Main under ADR-0025; historical concerns remain above.

---

# Report Completeness Evidence Eligibility — 2026-08-14

## Current Status

No Memory mechanism changed. Newly derived fundamental, valuation, technical,
macro snapshot, news, and aggregate sentiment Evidence is eligible for future
normal report/event Memory writes through the existing lineage path.

## Blockers

NONE. Historical Memory remains `EMPTY_VALID` when no attributable prior item
exists; no synthetic history was created.

## Ready For Integration

YES

---

# Phase 4B Day38 — ResearchState Memory Projection

## Current Status

ResearchState references an already completed Memory retrieval through a
compact snapshot ID, cutoff, status, and result count. It does not copy Memory
text or introduce a new Memory hierarchy.

## API Changes

- Added `ResearchStateMemoryContextInput` as a narrow projection boundary.
- Missing historical structured Memory context is
  `NOT_AVAILABLE_AT_SOURCE_RUN`; no synthetic history is created.

## Blockers

Day36's contract summary did not persist a canonical asset Memory context
object. This is explicit historical absence, not a Day38 build failure.

## Ready For Integration

YES

---

# Final Enrichment Eligibility — 2026-08-14

## Current Status

FMP standardized metrics and FRED MacroSnapshot Claims retain canonical source
lineage and are eligible for normal future report/Memory writes. No Memory
layer or synthetic historical item was added.

## Blockers

NONE. The final run's historical retrieval remains `EMPTY_VALID`.

## Ready For Integration

YES

---

# Phase 4B Day40 — Learning Memory v1

## Current Status

Learning Memory v1 is implemented as a backward-compatible metadata and
retrieval extension over the existing L0–L4 DuckDB/FAISS system. Scope is not
a new Memory level, and FAISS remains private.

## Current Task

- EPISODIC is operational for selected structured Claim, thesis, risk,
  catalyst, Event, State, and Episode references.
- MACRO, SECTOR, INDUSTRY_CHAIN, ASSET, and RESEARCH_EPISODE scopes can be
  persisted and filtered.
- SEMANTIC exposes CANDIDATE/VALIDATED/RETIRED schema state; one Episode cannot
  directly create VALIDATED truth.
- PERFORMANCE reserves reference fields only. No Outcome or performance value
  is computed.
- Legacy search and `ResearchContextBundle` both reuse Day37 PIT validation.

## API Changes

- Added `LearningMemoryMetadata`, `LearningMemoryUsageClass`,
  `SemanticMemoryLifecycleStatus`, and `EpisodicMemoryContentKind`.
- Added optional structured metadata to `MemoryWriteRequest`,
  `MemorySearchResult`, and `ResearchContextMemory`.
- Added Scope/usage/Episode filters and historical `as_of` support.
- Added explicit `RetrievalMetadata.empty_valid` and structured-filter trace.
- Added nullable `memory_items.metadata_json` with idempotent migration.

## Files Changed

- `src/schemas/memory.py`
- `src/schemas/__init__.py`
- `src/memory/__init__.py`
- `src/memory/contracts.py`
- `src/memory/retrieval.py`
- `src/memory/service.py`
- `src/repositories/records.py`
- `src/repositories/memory.py`
- `src/repositories/schema.py`
- `src/services/temporal.py`
- `tests/integration/memory/test_learning_memory.py`
- `tests/unit/repositories/test_database.py`
- Memory status/schema/decision documentation

## Tests

- Day40 focused Memory/Temporal/Repository suite: `58 passed`.
- Full pytest: `540 passed, 5 deselected`.
- No live Provider, LLM, or external Embedding call was made.

## Blockers

NONE for Day40. Historical Day35 JSON headers deliberately remain legacy
content until an explicit evidence-backed migration exists.

## Required Changes From Other Modules

NONE. Future Outcome work may reference `episode_id` but must not mutate
Episode or populate PERFORMANCE fields without a real Outcome contract.

## Ready For Integration

YES — `DAY40_LEARNING_MEMORY = PASS`; ready for Day41 planning only. Day41 was
not started.

---

# Phase 4B Day41 — Research Context & Retrieval Attribution

## Current Status

Day41 is implemented as an additive, Episode-scoped attribution artifact.
Memory, Sector Claim, and Radar Event context share one provided / selected /
used contract. Existing L0–L4, DuckDB/FAISS, Day36 diagnostics, Agent pipeline,
and ResearchEpisode remain unchanged.

## Current Task

- Record exact context provision, selection, accepted-Claim use, rejected-Claim
  references, Scope, source, time, rank, score, and reason.
- Emit `MemoryRetrievalRecord` for observed retrievals, including explicit
  `empty_valid` results.
- Reuse Unified Temporal Contract v1 and reject future Memory/Event context.
- Materialize the existing Day36 AAPL Sector-aware Episode without inventing
  its historically omitted Claim or Memory identities.

## API Changes

- Added `ResearchContextAttribution`, `ResearchEpisodeAttribution`,
  `ResearchContextClaimLink`, and closed context/link/status enums.
- Added `MemoryRetrievalRecord`, `MemoryRetrievalCandidate`, and
  `MemoryRetrievalScopeFilters`.
- Added pure `ResearchAttributionBuilder` and `MemoryContextProvision`.
- Added PIT-eligible candidate trace to existing `RetrievalMetadata`; this is
  backward compatible and contains no FAISS object.
- Added offline `python -m scripts.build_research_attribution` materializer.

## Files Changed

- `src/schemas/research_attribution.py`
- `src/services/research_attribution.py`
- `src/memory/contracts.py`
- `src/memory/retrieval.py`
- `src/schemas/__init__.py`
- `scripts/build_research_attribution.py`
- `tests/unit/services/test_research_attribution.py`
- `tests/integration/memory/test_research_context_bundle.py`
- `data/research_attribution/day41/phase4a_aapl_sector_aware.research_attribution.json`
- Memory status/schema/decision/coordination documentation

## Tests

- Day41 focused tests cover Memory used/unused, Sector Claim use, Radar Event
  use, rejected downstream Claims, empty-valid retrieval, future Memory,
  future Event, multiple Scopes, and old Phase3 no-Sector compatibility.
- Memory/Sector/Temporal/Episode focused suite: `62 passed` before final gate.
- Real Day36 AAPL offline materialization: 30 attributions, 10 used Sector
  Claim entries, four used Radar Event entries, zero LLM/network calls.
- Full pytest: `548 passed, 5 deselected`.
- Ruff: passed.
- mypy: passed (`306 source files`).
- Black: passed (`306 files unchanged`).
- `git diff --check`: passed.

## Blockers

NONE for the Day41 contract. Historical Day36 source data did not persist
accepted asset Claim IDs or its asset Memory retrieval details. The artifact
therefore records 14 known used entries as
`NOT_AVAILABLE_AT_SOURCE_RUN` without Claim IDs and emits no fabricated
historical Memory RetrievalRecord.

## Required Changes From Other Modules

New Agent orchestration may supply `ResearchContextClaimLink` from its already
validated accepted/rejected Claim collection when Main integrates Day41. Do
not add a second Sector/Event collection pass or expose FAISS.

## Ready For Integration

YES — `DAY41_RESEARCH_ATTRIBUTION = PASS`; ready for Day42 planning only.
Day42 was not started.

---

# Phase 4C Day44 — Memory Research Boundary

## Current Status

Learning Memory remains a PIT-safe Research continuity layer. It is a source
for future Timing Satellite descriptors, not a Quant decision engine.

## Current Task

Preserve historical ResearchState/Episode continuity, state-transition
lineage, and attributable retrieval. Do not change L0–L4 or Day40/41 schemas.

## API Changes

None. Future handoff may reference Memory/transition identities but must not
copy private reasoning or create performance semantics without approved data.

## Files Changed

`docs/coordination/MEMORY.md` only for Window synchronization.

## Tests

Full offline Gate A passed: `565 passed, 5 deselected`; Ruff, mypy, Black, and
`git diff --check` pass. Existing PIT, retrieval, attribution, and Golden
Replay contracts did not change.

## Blockers

No Day44 blocker. Golden Replay has so far validated only absent/empty-valid
Memory retrieval; a positive-retrieval replay remains a known future coverage
gap, not permission to invent Memory.

## Required Changes From Other Modules

Memory must not implement entry/exit decisions, timing rules, Holdings decay,
Reward, Regime routing, Factor evaluation, or portfolio logic.

## Ready For Integration

YES — Day44 ownership is frozen; no Day45 implementation has begun.

---

# Phase 4C Day45 — Timing Satellite Historical Continuity Audit

## Current Status

Memory compatibility audit is complete. Existing L0–L4 levels,
`LearningMemoryUsageClass` (`EPISODIC`, `SEMANTIC`, `PERFORMANCE`), Semantic
lifecycle (`CANDIDATE`, `VALIDATED`, `RETIRED`), DuckDB sidecars, FAISS
encapsulation, and Day41 retrieval attribution remain unchanged. Day45 does
not need a new Timing Memory subsystem or a Memory schema migration.

The future Day47 `ResearchStateTransition` should be a separate,
reference-only artifact. It should pair existing immutable State/Episode
identities rather than add `previous_*` and `current_*` pairs to each Memory
record.

## Current Task

Audit whether current historical references can support future Timing
Satellite source continuity without implementing a transition builder,
entry/exit logic, Quant timing, or predictive evaluation.

### Existing reference coverage

| Required continuity field | Existing authoritative location | Audit result |
| --- | --- | --- |
| `previous_state_id` / `current_state_id` | Two `ResearchStateSnapshot.research_state_id` values | SUPPORTED by a future transition artifact; not a Memory-row field |
| `previous_episode_id` / `current_episode_id` | Two `ResearchEpisode.episode_id` values | SUPPORTED; each Episode already closes to one State |
| `asset_id` | State and Episode canonical `AssetId` | SUPPORTED; Day47 must require equality across both points |
| `research_as_of` | State and Episode UTC cutoff | SUPPORTED; Day47 must require `T1 < T2` |
| State lineage | `ResearchStateLineage`, State input fingerprint, feature/source references and versions | SUPPORTED |
| Claim lineage | `ResearchStateFeature.source_claim_ids`, Episode accepted/provided Claim indexes, Day41 `used_by_claim_ids` | SUPPORTED when retained; historical PARTIAL gaps remain explicit |
| Event lineage | State Evidence/artifact references, Episode Sector usage, Day41 Radar Event attribution, Memory `source_event_ids` | SUPPORTED when present |
| Memory lineage | `episode_id`, `research_state_id`, Scope, temporal metadata, retrieval record and attribution IDs | SUPPORTED; positive historical replay coverage remains absent |

`LearningMemoryMetadata` deliberately references one originating Episode and
State. A future transition owns the pair. If a later approved workflow stores
a selective transition-derived Memory, it should reference the transition
artifact through the normal research/artifact lineage boundary; Day45 does not
embed a whole transition or add duplicate previous/current fields to Memory.

### Timing family history requirements

| Timing family | Minimum history requirement | Required source objects | PIT requirements | Current support status |
| --- | --- | --- | --- | --- |
| `STATE_TRANSITION` | Exactly two comparable State points for one transition | Two `ResearchStateSnapshot` objects; paired Episodes; section-qualified feature and lineage references | Same asset; `T1 < T2`; each State independently PIT-valid; compare only compatible feature semantics/versions | CONTRACT-SUPPORTED; Day47 artifact/builder not implemented |
| `EXPECTATION_REVISION_VELOCITY` | Two comparable expectation points permit direction and first change rate; at least three ordered points are required for acceleration/deceleration | Numeric or explicitly ordered ResearchState expectation features plus Claim/Evidence lineage, units, transform version and elapsed time | Every point visible at its own cutoff; later revisions cannot alter the earlier observation | CONDITIONAL / `REQUIRES_HISTORY`; no two-point acceleration claim is allowed |
| `EVENT_WINDOW` | One State plus one known focal Event can describe current window/proximity; two States are required to describe pre/post-event change | Canonical Event or Radar Event, State event feature, Episode usage and/or Day41 Event attribution | Event `available_at <= State research_as_of`; scheduled future event time may be later only when the schedule was already known; never use future publication/availability | PARTIALLY SUPPORTED; Day36 has Radar lineage, while its State event section is unavailable |
| `THESIS_UPGRADE_DOWNGRADE` | Two comparable thesis observations | State thesis features, accepted thesis/Research Manager Claims, Episodes and Claim lineage | Both thesis observations independently visible; text difference alone is not an upgrade/downgrade without explicit comparable semantics | SCHEMA-SUPPORTED but current T2 AAPL thesis State/accepted asset Claim IDs are unavailable |
| `RISK_ESCALATION` | Two comparable risk observations | State risk features, accepted Risk Claims, relevant Events/Attribution and Episodes | Risk evidence must be visible at each cutoff; missing risk is not zero or de-escalation | SCHEMA-SUPPORTED but current T2 AAPL risk State/accepted asset Claim IDs are unavailable |
| `EVIDENCE_CONFIRMATION` | A prior hypothesis at T1 and later distinct confirming/contradicting Evidence at T2; normally two points | Prior Claim/State feature, later accepted Claim, canonical Evidence IDs, Episodes and optional Attribution | T2 Evidence must not be reachable from T1; repeated citation of the same Evidence is not independent confirmation | LINEAGE-SUPPORTED; Day47 must enforce distinct provenance and historical completeness |
| `CATALYST_PROXIMITY` | One current State plus one attributable scheduled catalyst permits a proximity descriptor; two States are needed for a change-in-proximity descriptor | Catalyst/Event identity and schedule, State/Claim provenance, Episode and optional episodic Memory | The schedule/publication must be known by the State cutoff; event occurrence may be future; cancellation/revision uses its own later availability | CONDITIONAL; no general canonical positive historical catalyst sequence is currently replayed |

For every family, an unavailable required input yields `REQUIRES_HISTORY`,
`NOT_AVAILABLE_AT_SOURCE_RUN`, `MISSING`, or `PARTIAL` as appropriate. It must
not produce a neutral value, synthetic delta, inferred historical analogy, or
Timing decision.

### Current historical continuity evidence

- The frozen AAPL artifacts provide two ordered State/Episode points:
  `2026-08-14T23:59:59.999999Z` and
  `2026-08-30T23:59:59.999999Z`, with the same canonical `US:AAPL` identity.
- The two State snapshots expose 58 common feature names, so a deterministic
  future fixture can exercise compatible-feature pairing. Day47 must still
  check section-qualified identity, value type, unit/transform semantics and
  feature version rather than joining by a bare name alone.
- The first Episode is COMPLETE. The second is PARTIAL: its source run did not
  retain accepted/rejected asset Claim IDs, and its State has thesis, risk and
  event sections unavailable at source run. Those gaps prohibit a complete
  historical thesis/risk/evidence transition claim.
- Day41 preserves the second run's known Sector/Radar usage without inventing
  downstream Claim IDs. This is valid Event context continuity, not a complete
  asset Claim transition.

## API Changes

None. No production schema, Repository, retrieval path, Prompt, Agent, or
Temporal Contract changed.

## Files Changed

- `docs/coordination/MEMORY.md` only.

## Tests

No production code changed. The audit inspected the frozen Day38 State,
Day39 Episode, Day41 Attribution, and Day43 Golden Replay artifacts. Existing
Day43 acceptance records both replays as PASS with zero Provider/LLM calls.
Full offline Gate A: `565 passed, 5 deselected`; Ruff passed; mypy passed for
316 source files; Black passed for 316 files; `git diff --check` passed.

## Blockers

No Memory schema blocker for Day47.

Historical predictive validation remains unavailable: no Golden Replay sample
currently has `memory_retrieval_count > 0`. Phase 3 AAPL is
`NOT_AVAILABLE_AT_SOURCE_RUN`; the Day36 replay is `EMPTY_VALID`. A future
deterministic positive-path fixture may validate contracts, but contract
validation is not historical predictive validation.

## Required Changes From Other Modules

Day47, when explicitly approved, should:

- define a reference-only `ResearchStateTransition` containing previous/current
  State and Episode IDs, canonical asset, both cutoffs, transition availability,
  source feature/Claim/Event references, comparison/version metadata, and
  explicit completeness status;
- require same-asset identity, `T1 < T2`, independent PIT validity for both
  States, and compatible feature semantics before comparison;
- preserve each source State unchanged and prohibit T2 facts, Claims, Events,
  Memory or membership from being backfilled into T1;
- use at least three ordered expectation points before emitting
  acceleration/deceleration; and
- keep transition description separate from entry/exit, ranking, position,
  reward, performance, Factor, Regime, or Quant timing decisions.

Memory retrieval used by Day47 must continue calling the Day37 contract with
`available_at <= query_as_of`, exact asset/Scope isolation, and explicit
EMPTY_VALID handling. A known State/Episode reference should be resolved
directly from frozen artifacts; semantic retrieval must not be used to guess a
missing predecessor.

## Ready For Integration

YES — `DAY45_MEMORY_TIMING_AUDIT = PASS`; no Memory schema change recommended.
Day47 was not started.

---

# Phase 4C Day47 — Timing Satellite and ResearchStateTransition v1

## Current Status

Window 4 implemented Day47 historical continuity. Existing Memory L0–L4,
Research Scope, DuckDB/FAISS storage, Retrieval Attribution, ResearchState v1,
ResearchEpisode v1, and Day45 Satellite Alpha contracts remain intact.
`ResearchStateTransition` is a separate derived reference artifact, not a new
Memory layer.

## Current Task

Implemented nearest-prior same-Asset State selection, strict `T1 < T2`,
independent source-State PIT validation, deterministic transition identity,
and seven Timing-family projections into existing
`SatelliteAlphaObservation` records.

## API Changes

- Added `ResearchStateTransition`, component change enums/contracts,
  `TimingEventReference`, and `TimingSatelliteBuildInput`.
- Added `ResearchStateTransitionBuilder.select_predecessor()`,
  `build_transition()`, and `build_timing()`.
- Extended `SatelliteAlphaObservation` with optional
  `previous_research_state_id` and `source_transition_id` lineage fields.
- Existing L0–L4 Memory schema, Repository, vector abstraction, and Agent
  contracts are unchanged.

### Capability matrix

| Timing family | Day47 implementation | Current real historical support |
|---|---|---|
| `STATE_TRANSITION` | IMPLEMENTED | PARTIAL; frozen AAPL history lacks formal stages |
| `EXPECTATION_REVISION_VELOCITY` | IMPLEMENTED; 2-point first order, ≥3-point second order | NOT YET AVAILABLE with grounded continuous real history |
| `THESIS_UPGRADE_DOWNGRADE` | IMPLEMENTED from exact structured semantics | PARTIAL / source-conditional |
| `RISK_ESCALATION` | IMPLEMENTED by risk component | PARTIAL / source-conditional |
| `EVIDENCE_CONFIRMATION` | IMPLEMENTED with distinct later Evidence requirement | PARTIAL / source-conditional |
| `EVENT_WINDOW` | IMPLEMENTED with versioned deterministic calendar window | PARTIAL / source-conditional |
| `CATALYST_PROXIMITY` | IMPLEMENTED with 7/30/90-day windows | PARTIAL / source-conditional |

### PIT constraints

- Every State is validated at its own cutoff before comparison.
- Same-time and future predecessors are rejected; unrelated Assets are not
  predecessor candidates.
- Event schedule availability and Event outcome availability are separate.
  A post-event outcome cannot enter a pre-event Observation.
- Every supplied Memory result must satisfy `effective_ts <= research_as_of`
  and `available_at <= research_as_of` through Day37 Unified Temporal Contract.
- Frozen State T1 is never rewritten using T2 Claim, Evidence, Event, or
  Memory content.

## Files Changed

- `src/schemas/research_state_transition.py`
- `src/services/research_state_transition.py`
- backward-compatible Satellite schema/registry and public exports
- `tests/unit/services/test_research_state_transition.py`
- `docs/RESEARCH_STATE_TRANSITION.md`
- specified schema, Satellite, decision, status, and coordination docs

## Tests

Focused Day47 tests cover schema, deterministic identity, audit-time identity
independence, strict ordering, nearest predecessor, Asset isolation, upgrade,
downgrade, unchanged and missing-stage paths, risk escalation/resolution,
Evidence confirmation/contradiction, two/three-point revision semantics,
Event windows, catalyst proximity, future State/Event/outcome/Evidence/Memory
rejection, frozen Phase3/Phase4A behavior, and absence of trading/model calls.

- Focused Day45–Day47 suite: `54 passed`.
- Full pytest: `619 passed, 5 deselected`.
- Leakage selection: `7 passed, 617 deselected`.
- Ruff: PASS.
- mypy: PASS (`325 source files`).
- Black: PASS (`325 files`).
- `git diff --check`: PASS.

## Blockers

No Day47 implementation blocker. Real historical predictive validation is not
available: no Golden Replay sample has `memory_retrieval_count > 0`. The
non-empty Memory and three-State paths are deterministic CONTRACT FIXTURES,
not real Alpha, timing performance, or predictive validation.

`REAL_HISTORICAL_MEMORY_REPLAY = NOT_YET_AVAILABLE`.

## Required Changes From Other Modules

None. Future producers may retain exact structured Timing feature names in a
later approved State projection, but Day47 does not modify Agent pipelines or
infer missing semantics from prose.

## Ready For Integration

YES — `WINDOW4_DAY47_IMPLEMENTATION = PASS`;
`READY_FOR_DAY47_ACCEPTANCE = YES`.

---

# Phase 4 Day49 — Memory Contract Freeze Sync

## Current Status

Learning Memory architecture and deterministic PIT fixtures remain PASS.
`REAL_HISTORICAL_MEMORY_REPLAY = NOT_YET_AVAILABLE`; predictive usefulness is
`NOT_VALIDATED`.

## Current Task

Freeze sync only. Day49 reused L0–L4 Memory and the Unified Temporal Contract;
it created no new Memory layer.

## API Changes

None.

## Files Changed

This coordination status only.

## Tests

Future Memory exclusion and non-empty deterministic contract fixture PASS in
the eight-test leakage selection.

## Blockers

No freeze blocker. Real non-empty historical replay remains a documented
future evidence gap.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — Memory contracts are frozen with limitations preserved.
