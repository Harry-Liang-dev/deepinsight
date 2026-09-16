# Current Status

Phase 3 Final Gate blocker integration was executed on 2026-08-13. Main-owned
offline fixtures now use `agent_output_v2`; full offline E2E, strict Evidence
validation, cache reliability, type checking, formatting, and the offline
Benchmark are green. Gateway schema failures now retain credential-safe schema
identity, validation paths, and Expected/Actual/Missing/Extra/Type-mismatch
diagnostics instead of collapsing into `agent_execution`.

The live seven-Agent hard gate is still blocked. Latest candidate
`agent_contract_20260812T193505Z_785547ec` passed 5/7. Fundamental failed
claim/binding cardinality after its single repair attempt; Bear failed exact
numeric grounding after its single repair attempt. Risk, eight-Agent gate,
fresh acceptance, report, and Evaluation were therefore not run.

Phase 3 coordination is established. Window 1 owns architecture, shared
interfaces, integration, and quality gates. Windows 2–5 report through their
own files and do not directly change another window's module.

Day 22 completed a read-only reverse audit of live run `20260808T082315Z`.
The result is specified in `docs/tasks/phase3_data_completeness.md`. No
production code, Prompt, Evaluation rule, or live artifact was changed.

## Numeric Grounding Semantics v2 integration

Main centralized Analyst and Sector direct-Evidence numeric validation in
`src.agents.numeric_grounding`. Exact canonical identifier components are not
facts, explicit window metadata is required for human-readable durations, and
high-precision Decimal rendering uses versioned deterministic equivalence with
Evidence-ID provenance. Partial disclosure, HIGH-event final accepted coverage,
minimum Claim cardinality, PIT, and Manager no-new-number semantics are
unchanged. The original failed S02 artifact moves only from 1 to 2 accepted
Claims; a separate fresh exact-cutoff S02 live smoke passed 8/8 Claims with
HIGH-event coverage 1/1, numeric grounding 6/6, zero invalid citations, zero
future leakage, and zero retries.

The current runtime has eight Agents and one shared `AgentContext`. The four
Analysts consume structured features, retrieved documents, and Memory. The
four Managers consume validated Analyst outputs plus shared context; they must
not fetch Provider data.

## Current Task

Close producer/consumer drift without weakening Evidence validation. Technical,
Sentiment, News/Event, Bull, and Bear now generate one authoritative Claim
object collection and deterministically assemble their public prose/binding
shape. Fundamental and Research retain their current public generation shape;
the remaining blocker proves Fundamental still needs the same producer-side
single-source treatment. Bear additionally needs a producer-side way to omit
an unsupported numeric claim within its one allowed repair, not validator
relaxation or ID correction.

Define the Phase 3 Agent data contract before adding more Providers. The live
audit establishes the following integration order:

1. attributable structured Evidence and one availability manifest;
2. SEC structured fundamentals and multi-period history;
3. attributable adjusted market/technical data;
4. macro and market/industry context;
5. licensed event, news, sentiment and consensus coverage.

### Canonical capability layers

```text
Provider records
  -> normalized facts/events/bars/documents
  -> attributable Evidence Package
  -> role-specific Agent input view
  -> Analyst outputs
  -> Manager global context + Analyst outputs
  -> report + Evaluation
```

Every role input must answer four questions:

1. What data is present?
2. What required or optional data is absent?
3. What time window and as-of boundary apply?
4. Which source reference grounds every fact and numeric value?

### Eight-Agent data matrix

| Agent | Direct inputs | Must-have data | Optional context | Must not do | Missing-data behavior |
|---|---|---|---|---|---|
| Fundamental Analyst | Fundamental role view | Asset identity; report/as-of date; normalized income, balance-sheet and cash-flow facts when available; filing evidence; fiscal period/unit/currency; source lineage | Valuation inputs, issuer L2 Memory, industry comparison, corporate actions | Fetch data; calculate undisclosed metrics; use unattributable structured numbers | Name each absent statement/metric/period and lower certainty |
| Technical Text Analyst | Technical role view | Attributable OHLCV window; adjustment/feed/calendar metadata; deterministic indicators; price evidence references | Corporate actions, volatility regime, market/industry relative series, L0/L4 Memory | Fetch prices; calculate indicators in the LLM; cite filing text as price evidence | State insufficient history, stale bars, missing adjustment or benchmark series |
| Sentiment Analyst | Sentiment role view | Timestamped attributable text sample; source class; sample window/count; language; issuer/entity match | L1/L2 Memory, source-quality and coverage metadata | Treat one filing as broad investor sentiment; infer unsampled social sentiment | Disclose sample, channel, recency and market-coverage limits |
| News Event Analyst | Event role view | Timestamped events/documents; event type; issuer/entity mapping; original locator; publication/effective time | Materiality metadata, prior related events, market/macro context | Fetch news; invent event impact or merge unrelated entities | Separate confirmed event, possible impact and unresolved facts |
| Research Manager | Validated Analyst outputs + global context | Analyst coverage manifest; evidence links; contradictions; missing-data manifest; as-of boundary | Macro, market/industry and relevant Memory summaries | Re-read Providers; add new facts; hide failed Analyst coverage | Preserve disagreements and missing roles explicitly |
| Bull Manager | Research summary + validated Analyst outputs | Constructive evidence, required conditions, counterevidence, coverage manifest | Macro/industry context and historical analog Memory | Add facts, targets, trades or Provider calls | Reduce confidence and state which constructive premise lacks evidence |
| Bear Manager | Research summary + validated Analyst outputs | Adverse evidence, required conditions, invalidators, coverage manifest | Risk/event/macro context and historical analog Memory | Add facts, targets, trades or Provider calls | Reduce confidence and distinguish confirmed weakness from scenario |
| Risk Manager | Bull/Bear outputs + research summary + validated evidence | Confirmed risks, scenario risks, missing data, conflicting evidence, time validity | Liquidity, regulatory, macro and event Memory | Add unsupported facts, execute trades or call Providers | Treat missing coverage as risk and keep scenarios conditional |

### Shared data capabilities

| Capability | Minimum attributable content | Primary consumers |
|---|---|---|
| Fundamental | Period, report type, unit, currency, statement facts, derived-feature provenance | Fundamental, Research, Bull/Bear, Risk |
| Technical | Raw/adjusted flag, feed, trading dates, OHLCV, computed-feature window/version | Technical, Research, Bull/Bear, Risk |
| Sentiment | Channel, sample count/window, language, source quality, texts | Sentiment, Research, Risk |
| News/Event | Entity, event type, publish/effective time, source locator, text | News, Research, Bull/Bear, Risk |
| Macro | Series/event identity, geography, effective time, release vintage, source | All Analysts when relevant; all Managers |
| Market/Industry | Benchmark identity, constituent/industry mapping, relative window, source | Fundamental, Technical, Managers |
| Memory | Level, namespace, effective time, retrieval score, source reference, snapshot/version | All roles through role-filtered retrieval |
| Evidence | Stable evidence ID, source/provider, locator, observed/published/effective time, content hash, unit and transformation lineage | Every claim-producing component |

### Current gaps to resolve before Provider expansion

- `structured_features` is a generic JSON object rather than typed role views.
- Structured numeric features do not carry first-class `SourceReference` links;
  report citations currently favor documents/Memory.
- Data availability and freshness are inferred from nulls instead of one
  canonical manifest.
- All four Analysts receive the same context rather than least-privilege role
  projections.
- Fundamental structured extraction from filings is incomplete; current SEC
  strength is attributable filing text.
- Real sentiment, general news, macro, market benchmark, and industry datasets
  are not yet complete across CN/HK/US.
- Manager inputs need an explicit global-context/evidence package contract,
  even though Managers already avoid direct Provider calls.

### Day 22 live evidence

- DuckDB contains 63 real Alpaca bars and one SEC filing, but zero rows in
  `fundamentals`, `macro_series`, and `corporate_events`.
- All fundamental structured metrics were null. Only close, SMA20/SMA60,
  20-day return, and trend label were populated.
- Technical failed because a structured numeric claim lacked attributable
  evidence; Sentiment failed because no proper sentiment dataset existed.
- All eight Agents retrieved two SEC chunks and zero Memory items. The only
  L3 Memory item was written after report completion.
- The final report contains two unique SEC citations and no Alpaca citation,
  despite the real bar ingestion.
- Saved Evaluation scores include evidence consistency 0.3, Bull/Bear balance
  0.2, and factual correctness 0.6302. The saved single numeric failure was a
  known punctuation-scanner false positive; the deeper gap is pre-report
  structured numeric lineage.

## API Changes

- `LLMSchemaValidationError` now carries safe schema name/version, field paths,
  error types, and contract diff without rejected values, Prompt, or credential.
- Invalid provider JSON is classified as `LLMInvalidJSONError`.
- Real Gateway Agent calls allow at most one structured-output repair with
  unchanged Evidence/input; Fake Gateway never repairs.
- Agent/LLM metadata records structured-output attempt count and repair state.
- Technical, Sentiment, News/Event, Bull, and Bear use Claim-object generation
  schemas; public response schemas remain unchanged after deterministic
  assembly.

Proposed for Main Agent review; not yet approved or implemented:

- `EvidenceItem`: stable evidence identity plus provider, locator, timestamps,
  content hash, unit, currency and transformation lineage.
- `DataAvailabilityManifest`: requested/present/missing/stale fields, reason,
  as-of time and source coverage.
- `ResearchEvidenceBundle`: fundamental, technical, sentiment, event,
  macro, market/industry, Memory and evidence collections.
- Four role-specific Analyst input views derived from the bundle.
- `ManagerResearchContext`: validated Analyst outputs, coverage, conflicts,
  global context and evidence index; no Provider clients.

These names describe required boundaries, not final accepted schemas. Main
must reconcile them with `AgentContext`, ingestion records and Memory APIs.

The full required fields, SLA proposals, Provider order, ownership split, and
acceptance criteria are now recorded in
`docs/tasks/phase3_data_completeness.md`. Final schema names remain pending an
interface review; no parallel schema family is approved yet.

## Files Changed

Main blocker-integration files include `apps/api/offline.py`, the shared Agent
base/contracts and role implementations, Agent/LLM schemas, LLM Gateway and
Provider boundaries, `scripts/live_agent_contract.py`, affected Prompts, and
their regression tests.

- `AGENTS.md`
- `docs/coordination/MAIN.md`
- `docs/coordination/DATA.md`
- `docs/coordination/AGENTS.md`
- `docs/coordination/MEMORY.md`
- `docs/coordination/LLM_GATEWAY.md`
- `docs/tasks/phase3_data_completeness.md`

## Tests

Final offline evidence:

- pytest: `395 passed, 5 deselected`
- fixed-bundle Fake contract: `7/7 PASS`
- offline `research_benchmark_v1`: `7/7 PASS`
- Ruff: PASS
- mypy: `0 errors / 255 source files`
- Black: PASS
- `git diff --check`: PASS

Latest live candidate used `qwen/qwen3.7-flash` and
`phase3_research_completeness_final_v1`: `5/7 PASS`. Fundamental failed after
one repair with an unbound business claim; Bear failed after one repair with
an unsupported exact numeric literal. No fuzzy matching, ID correction, or
Fake fallback occurred.

First Main integration quality gates on 2026-08-09:

- pytest: `314 passed, 5 deselected`
- offline `research_benchmark_v1`: `7/7 passed`
- Ruff: PASS
- mypy: PASS (`230 source files`)
- Black: PASS (`230 files unchanged`)
- `git diff --check`: PASS

## Blockers

- P0: Fundamental producer still independently emits prose and bindings; one
  real run produced a cardinality mismatch after the only allowed repair.
- P0: Bear Claim schema is synchronized, but one real run still emitted a
  numeric thesis whose bound Evidence lacked that exact literal after repair.
- Gate consequence: Risk and Fresh Acceptance are prohibited until one live
  candidate reaches 7/7 with zero invalid citations, schema errors, unbound
  claims, and ungrounded numeric claims.

- Shared interface blockers are resolved under ADR-0025.
- Historical resolved blockers: canonical Evidence conversion, role-specific
  contracts, Workflow bundle pairing, Memory schema version, Gateway metadata
  call-site wiring, and full mypy.
- Real CN/HK fixed-source coverage remains incomplete.
- Real sentiment/news licensing and retention policy is not settled.
- Macro and market/industry context Providers are not implemented end to end.
- Current Alpaca-derived technical features still need Data-owned field-level
  Evidence before they can be cited as first-class research facts.
- Real data coverage remains incomplete; this is the next Phase 3 task, not a
  cross-module integration blocker.

## Required Changes From Other Modules

- AGENTS: converge Fundamental generation to one authoritative Claim
  collection while retaining its normalized scores and public schema.
- LLM_GATEWAY: no cache redesign is required. Preserve the one-repair maximum
  and new safe diagnostics.
- DATA / MEMORY: no blocker or change request.

- Resolved: the four child interfaces are accepted and wired by Main.
- DATA should next extend the accepted Bundle rather than create a new input.
- AGENTS, MEMORY and LLM_GATEWAY have no cross-module change request pending.
- Any future shared Schema change still requires Main review.

## Ready For Integration

NO — offline integration is green, but the live seven-Agent hard gate is 5/7;
Risk and Fresh Acceptance remain correctly blocked.

---

# Phase 4A Day36 Integration Closure — 2026-08-30

## Current Status

Day30-Day35 Sector Intelligence is now connected to the frozen eight-Agent
asset chain through `SectorContextBundle v1`. The older Phase 3 blocker record
above is retained as history and is no longer current.

## Current Task

Phase 4A final integration is complete. Macro/sector state, Sector Macro,
Radar, Sector Research Claims, effective Industry Chains, and asset research
now form one point-in-time path.

## API Changes

- Added optional PIT `SectorContextBundle` and eight `SectorRoleContext`
  projections.
- Added Repository-backed asset-to-Sector/Chain resolution with explicit
  missing/PARTIAL degradation.
- Added optional `ResearchWorkflowService` Sector resolver injection.
- Added ID-only `SectorContextUsageDiagnostic`; no trajectory or reward model.
- Managers reuse accepted Sector Claims as direct upstream; Phase 3 Claim,
  grounding, quarantine, and compliance contracts are unchanged.

## Files Changed

- `src/schemas/sector_context.py`
- `src/services/sector_context.py`
- `src/agents/contracts.py`
- `src/agents/input_contracts.py`
- `src/agents/coordinator.py`
- `src/agents/base.py`
- `src/orchestration/research_workflow.py`
- `scripts/live_agent_contract.py`
- `scripts/smoke_sector_asset_integration.py`
- `tests/unit/services/test_sector_context.py`
- shared status/schema/decision documentation

## Tests

- Full pytest: `506 passed, 5 deselected`.
- Ruff, mypy, Black, `git diff --check`: PASS.
- Three-asset real-snapshot routing/projection `20260830T134805Z`: NVDA, MU,
  AAPL PASS.
- Real Qwen integrated AAPL contract using a real Qwen S03 Sector output:
  `agent_contract_20260830T135643Z_70442a96`, 8/8 PASS.
- Actual Sector use: 10 Sector Claim references and 4 Radar Event references;
  invalid citations/schema errors/unbound Claims: 0. All 38 accepted numeric
  Claims were grounded.

## Blockers

NONE for the Phase 4A contract or the validated S03/AAPL live LLM path. The
S01 live Sector run still has a local Claim-promotion failure and remains a
non-blocking coverage limitation; it was not hidden or replaced by Fake.

## Required Changes From Other Modules

NONE. Day35 JSON-header Memory lineage remains accepted technical debt for
Phase 4B; Day36 did not alter the Memory storage contract.

## Ready For Integration

YES — `DAY36_SECTOR_INTEGRATION = PASS` and Phase 4A is ready for Phase 4B
planning, but Day36 does not start Phase 4B.

---

# Phase 4B Day37 — Unified Temporal Contract v1

## Current Status

Data, Sector, Event, accepted Sector Claims, Memory, and research context now
share one UTC-aware point-in-time access decision. Existing field names remain
compatible through explicit adapters.

## Current Task

Day37 temporal foundation is complete. ResearchState, ResearchEpisode, Factor,
Reward, Regime, historical Dataset, Backtest, and training remain out of scope.

## API Changes

- Added `TemporalMetadata`, `TemporalAccessDecision`, `is_usable_at()`, and
  `validate_temporal_access()`.
- Added mappings for SEC/FMP, Alpaca bars/news, FRED vintages, Sector temporal
  objects, Research Evidence, and Memory/context.
- Memory retrieval now uses persisted creation availability as well as
  effective time; legacy naive DuckDB timestamps have explicit UTC-only
  decoding.

## Tests

- Temporal/Sector/Memory focused tests: `46 passed` before full regression.
- Full pytest: `518 passed, 5 deselected`.
- Ruff, mypy, Black, and `git diff --check`: PASS.

## Blockers

No Day37 P0 blocker. Legacy pre-policy timestamp provenance may require audit
or snapshot rebuild before a strict historical replay baseline.

## Required Changes From Other Modules

Future Phase 4B producers must map their records into TemporalMetadata rather
than implementing a new local visibility rule.

## Ready For Integration

YES — Day37 contract is ready for Day38 planning; Day38 is not started here.

---

# Phase 4B Day38 — ResearchStateSnapshot v1

## Current Status

ResearchState v1 is implemented as an immutable, versioned, PIT-safe machine
artifact. Phase 3 Golden and Day36 Sector-aware AAPL artifacts both materialize
offline without LLM or Provider calls.

## Current Task

Day38 State contract, builder, materializer, validation, and historical
compatibility are complete. Dataset, ResearchEpisode, Factor, Reward, Regime,
Backtest, and training remain out of scope.

## API Changes

- Added `ResearchStateSnapshot`, typed sections, three feature families,
  hierarchy, lineage, and compact Sector/Memory build projections.
- Added pure `ResearchStateBuilder` and offline
  `python -m scripts.build_research_state` materializer.
- State input has no Report field and validates recursive Claim provenance and
  Day37 temporal access.

## Files Changed

- `src/schemas/research_state.py`
- `src/services/research_state.py`
- `scripts/build_research_state.py`
- `tests/unit/services/test_research_state.py`
- shared schema/status/decision documentation

## Tests

- Focused ResearchState tests: `7 passed`.
- Phase 3 Golden and Day36 AAPL State materialization: PASS, 0 LLM and 0
  network calls.
- Full Gate A: `525 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check`: PASS.

## Blockers

No Day38 blocker. Day36 did not persist complete asset Agent outputs or a
canonical Memory context object; those sections are explicitly
`NOT_AVAILABLE_AT_SOURCE_RUN` rather than reconstructed from summaries.

## Required Changes From Other Modules

Future dataset builders should consume ResearchState directly and retain its
Claim/Evidence IDs. They must not parse report prose or backfill newer context.

## Ready For Integration

YES — Day38 is ready for Day39 planning; Day39 is not started here.

---

# Phase 4B Day39 — ResearchEpisode v1

## Current Status

ResearchEpisode v1 is implemented as an immutable, reference-only process
artifact distinct from ResearchState. Phase 3 Golden and Day36 Sector-aware
AAPL runs both materialize offline without LLM or Provider calls.

## Current Task

Day39 Episode contract, pure builder, offline materializer, historical trace
quality semantics, and acceptance materialization are complete. Outcome,
Reward, Factor, Regime, Backtest, training trajectory, and private reasoning
remain out of scope.

## API Changes

- Added `ResearchEpisode`, `AgentExecutionTrace`, version references, and
  COMPLETE/PARTIAL trace quality.
- Reused Day36 `SectorContextUsageDiagnostic` from a neutral schema module.
- Added pure `ResearchEpisodeBuilder` and
  `python -m scripts.build_research_episode` materializer.

## Files Changed

- `src/schemas/research_episode.py`
- `src/schemas/sector_usage.py`
- `src/services/research_episode.py`
- `scripts/build_research_episode.py`
- `tests/unit/services/test_research_episode.py`
- shared schema/status/decision documentation

## Tests

- Focused Episode/Sector-context tests: `17 passed`.
- Phase 3 Golden COMPLETE and Day36 PARTIAL materialization: PASS, 0 LLM and
  0 network calls.
- Full Gate A: `532 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check`: PASS.

## Blockers

No Day39 blocker. The Day36 summary did not persist accepted/rejected asset
Claim IDs or latency, so its Episode is deliberately PARTIAL rather than
claiming false historical completeness.

## Required Changes From Other Modules

Future Outcome materialization must reference `episode_id` and must not mutate
the frozen Episode. It must not ingest private reasoning or reconstruct Claims
from report prose.

## Ready For Integration

YES — Day39 is ready for Day40 planning; Day40 is not started here.

---

# Phase 4B Day42 — Point-in-Time Research Dataset v1

## Current Status

ResearchDatasetSample v1 is implemented as an immutable reference index over
frozen State, Episode, optional Attribution/context, Agent runs, hierarchy,
and versions. It contains no future label or copied upstream payload.

## Current Task

Day42 schema, pure Builder, DuckDB Repository, offline materializer, manifest,
and Phase3/Phase4 historical materialization are complete. Outcome, Reward,
Factor, Regime, Backtest, SFT, DPO, Offline RL, and training are out of scope.

## API Changes

- Added `ResearchDatasetSample`, explicit component/overall quality, empty
  label status, version lineage, and `ResearchDatasetArtifactManifest`.
- Added pure `ResearchDatasetBuilder`; all upstream visibility calls the Day37
  temporal validator.
- Added immutable `research_dataset_samples` DuckDB table and Repository.
- Added `python -m scripts.build_research_dataset` offline materializer.

## Files Changed

- `src/schemas/research_dataset.py`
- `src/services/research_dataset.py`
- `src/repositories/research_dataset.py`
- `src/repositories/schema.py`
- `src/repositories/records.py`
- `scripts/build_research_dataset.py`
- Dataset/Repository tests and shared schema/status/decision documentation

## Tests

- Day42 focused Builder/Repository/schema suite: `26 passed` before full Gate.
- Phase3 Golden and Day36 Sector-aware materialization: PASS; two immutable
  DuckDB rows, two manifests, 0 LLM calls, 0 Provider calls, 0 labels.
- Full Gate A: `559 passed, 5 deselected`; Ruff, mypy (312 source files),
  Black, and `git diff --check`: PASS.

## Blockers

No Day42 contract blocker. Both historical samples are PARTIAL for truthful,
different reasons; neither is rewritten. Outcome labels are deliberately
pending until their separately approved factory exists.

## Required Changes From Other Modules

Future label producers must append a separately versioned Outcome artifact
referencing `sample_id`/`episode_id`. They must not mutate Day42 samples or
read future data inside this builder.

## Ready For Integration

YES — Day42 is ready for Day43 planning; Day43 is not started here.

---

# Phase 4B Day43 — Golden Point-in-Time Replay Gate

## Current Status

Golden Replay v1 is complete. Phase 3 and Day36 AAPL runs reproduce their
frozen State, Episode, Attribution where present, and Dataset Sample identities
with zero Provider and zero LLM calls.

## Current Task

The Phase 4B final composition gate, determinism checks, five future-input
leakage challenges, traceability samples, and versioned manifests are
implemented. No new research, Factor, Outcome, Regime, Backtest, training, or
trading capability was added.

## API Changes

- Added `GoldenReplayManifest` and focused check/trace/version contracts.
- Added pure `GoldenReplayService` and
  `python -m scripts.replay_golden` offline gate.
- Exposed existing frozen-artifact decoder helpers for reuse; materialization
  behavior is unchanged.

## Files Changed

- `src/schemas/golden_replay.py`
- `src/services/golden_replay.py`
- `scripts/replay_golden.py`
- `tests/unit/services/test_golden_replay.py`
- shared schema/status/decision documentation

## Tests

- Focused Golden Replay suite: `6 passed` before full Gate A.
- Both Golden manifests: PASS; exact State/Episode/Sample identities; Day36
  Attribution identity retained; 0 Provider calls; 0 LLM calls.
- Future News, Radar, Memory, Membership, and Filing: all rejected.
- Full Gate A: `565 passed, 5 deselected`; Ruff, mypy (316 source files),
  Black, and `git diff --check`: PASS.

## Blockers

No Day43 blocker. Day36 accepted downstream Asset Claim IDs were absent from
the frozen source summary; two sampled context-to-Claim paths remain explicitly
PARTIAL and are not fabricated.

## Required Changes From Other Modules

None for Phase 4B closure. Future runs should persist accepted Asset Claim IDs
to make corresponding Attribution traces COMPLETE.

## Ready For Integration

YES — Phase 4B Structured Research is ready for final gate reporting. Phase 4C
is not started here.

---

# Phase 4C Day44 — Research / Quant Boundary Freeze

## Current Status

The architecture reset is documentation-only. `deepinsight` is the Research
Intelligence and Opportunity Discovery repository; future `deepinsight-quant`
owns Quant Alpha/Strategy and Portfolio/Execution.

## Current Task

Freeze vocabulary, repository ownership, Satellite handoff direction,
selection-bias safeguards, and Window responsibilities. Do not implement the
Day45 schemas or alter Phase 3/4A/4B contracts.

## API Changes

- No runtime API or Python schema changed.
- Reserved future Research boundary:
  `SatelliteAlphaObservation → ResearchQuantHandoffBundle`.
- Quant begins only after the handoff and owns processed Factor exposures,
  signals, strategies, holdings, portfolio, and execution.

## Files Changed

Governance documentation only: `AGENTS.md`, `MASTER_SPEC`, Decisions, Module
Status, schema documentation, and all five coordination files.

## Tests

Full Gate A: `565 passed, 5 deselected`; Ruff, mypy (316 source files), Black,
and `git diff --check` pass. No Python code changed on Day44.

## Blockers

None for Day44. No formal Satellite Alpha or handoff schema exists yet; this
is intentional architecture preparation rather than an incomplete runtime.

## Required Changes From Other Modules

- DATA: own identity/time/join integrity, not a Factor library.
- AGENTS: own semantic Research outputs and candidates, not ranking/Top-K.
- MEMORY: own historical continuity and transitions, not entry/exit logic.
- LLM_GATEWAY: support future structured contracts without a scoring call.

## Ready For Integration

YES — Day44 full regression passed. Day45 is not started.

---

# Phase 4C Day45 — Satellite Alpha Ontology Integration

## Current Status

Day45 is integrated. `SatelliteAlphaDefinition` and
`SatelliteAlphaObservation` are stable Research-side contracts over frozen
ResearchState artifacts. OpportunityCandidate, historical transition building,
ResearchQuantHandoffBundle, and every Quant/Trading concept remain unstarted.

## Current Task

Main reviewed the Window 2 Data, Window 3 Agent, Window 4 Memory, and Window 5
Gateway contracts; closed shared exports and documentation; and ran the full
repository acceptance gate.

## API Changes

- Added a 14-family Satellite Alpha ontology with explicit
  `SELECTION`/`TIMING`/`BOTH`, comparison scope, coverage, value-shape, and
  maturity semantics.
- Added immutable typed components and observations with deterministic IDs,
  section-qualified State feature references, compact Claim/Evidence/artifact
  provenance, and explicit availability.
- Added a pure ResearchState mapper and semantic-support audit. The mapper
  performs zero LLM, Provider, report parsing, ranking, or trading operations.
- ResearchState v1, ResearchEpisode identity, Temporal Contract, Agent Prompts,
  and LLMGateway are unchanged.

## Files Changed

- `src/schemas/satellite_alpha.py`
- `src/services/satellite_alpha.py`
- shared schema/service exports
- `tests/unit/services/test_satellite_alpha.py`
- `docs/SATELLITE_ALPHA.md`
- shared status/schema/decision and five Window coordination documents

## Tests

- Day45 focused suite: `15 passed`.
- Phase 3/4A/4B explicit regression selection: `63 passed`.
- Full pytest: `580 passed, 5 deselected`.
- Leakage selection: `3 passed, 582 deselected`.
- Ruff, mypy (319 source files), Black, and `git diff --check`: PASS.

## Blockers

None for Day45. Timing families that need ordered history correctly remain
`REQUIRES_HISTORY`; formal peer-group comparison remains `UNSUPPORTED`.

## Required Changes From Other Modules

None for Day45. A later approved State version may retain additional already
validated semantics, but it must not add an LLM scoring pass or backfill old
runs.

## Ready For Integration

YES — `DAY45_SATELLITE_ALPHA_ONTOLOGY = PASS`; ready for Day46 planning only.

---

# Phase 4C Day46 — Independent Acceptance

## Current Status

Main independently accepted Window 3's Selection Satellite production and
`OpportunityCandidate v1`. The contracts remain Research qualification
artifacts and do not implement Quant selection, ranking, timing, portfolio, or
trading behavior.

## Current Task

Validated all seven Selection-capable families, Candidate identity and
lineage, same-cutoff multi-asset structural comparability, historical rebuild,
ResearchState compatibility, PIT enforcement, and Research/Quant scope.

## API Changes

None during independent acceptance. Main did not modify the Window 3
implementation.

## Files Changed

- `docs/coordination/MAIN.md` acceptance record only.

## Tests

- Day45+Day46 focused suite: `31 passed`.
- Phase 3/4A/4B/Day45/Day46 explicit regression selection: `94 passed`.
- Full pytest: `596 passed, 5 deselected`.
- Leakage selection: `3 passed, 598 deselected`.
- Ruff, mypy (322 source files), Black, and `git diff --check`: PASS.

## Blockers

None for Day46. Current partial observations are caused by source-run semantic
gaps rather than hidden implementation failures. `PEER_GROUP` remains
unsupported, and the multi-asset fixture proves schema comparability only—not
real Alpha, ranking, or historical performance.

## Required Changes From Other Modules

None for Day46 acceptance. Day47 requires separate authorization and must not
be inferred from this result.

## Ready For Integration

YES — `DAY46_SELECTION_SATELLITE = PASS`; ready for Day47 planning only.

---

# Phase 4C Day47 — Independent Acceptance

## Current Status

Main independently accepted Window 4's `ResearchStateTransition v1` and the
seven Timing Satellite production mappings. They describe Research-state
evolution only and do not introduce Quant timing, ranking, portfolio, or
trading behavior.

## Current Task

Validated deterministic nearest-prior history selection, strict temporal
ordering, two-point versus three-point semantics, PIT rejection, compact
provenance, frozen-run compatibility, existing Memory architecture reuse, and
the Research/Quant boundary.

## API Changes

None during independent acceptance. Main did not modify the Window 4
implementation.

## Files Changed

- `docs/coordination/MAIN.md` acceptance record only.

## Tests

- Day47 focused suite: `23 passed`.
- Day45/Day46/Day47 and Phase 3/4A/4B explicit regression selection:
  `149 passed`.
- Full pytest: `619 passed, 5 deselected`.
- Leakage selection: `7 passed, 617 deselected`.
- Ruff, mypy (`325 source files`), Black (`325 files`), and
  `git diff --check`: PASS.

## Blockers

None for the Day47 contract. Real continuous ResearchState history remains
limited, so several Timing families are source-conditional or partial. The
positive Memory and three-State paths are deterministic contract fixtures;
`REAL_HISTORICAL_MEMORY_REPLAY = NOT_YET_AVAILABLE`. No predictive Timing
Alpha has been validated.

## Required Changes From Other Modules

None for Day47 acceptance. Day48 requires separate authorization and must not
be inferred from this result.

## Ready For Integration

YES — `DAY47_TIMING_SATELLITE = PASS`; ready for Day48 planning only.

---

# Phase 4C Day48 — Research → Quant Handoff Contract v1

## Current Status

Window 1 implemented the sole versioned Research export boundary for future
`deepinsight-quant`. The handoff is reference-only, deterministic, PIT-safe,
coverage-preserving, and contains no Quant processing or trading semantics.

## Current Task

Implemented `ResearchQuantHandoffBundle v1`, compact Satellite/provenance and
version references, strict frozen-artifact composition, canonical single JSON
serialization, and mixed-coverage JSONL batch export with a credential-free
manifest.

## API Changes

- Added `ResearchQuantHandoffBuildInput`, `ResearchQuantHandoffBundle`, compact
  Satellite/provenance/version contracts, and batch manifest contracts.
- Added `ResearchQuantHandoffBuilder` and `ResearchQuantHandoffExporter`.
- Candidate and Transition references are optional. Qualified, insufficient,
  partial, negative, source-run-unavailable, and history-required Research is
  exportable without converting missingness to zero.

## Files Changed

- `src/schemas/research_quant_handoff.py`
- `src/services/research_quant_handoff.py`
- shared schema/service exports
- `tests/unit/services/test_research_quant_handoff.py`
- `docs/RESEARCH_QUANT_HANDOFF.md`
- Main-owned specification, schema, decision, status, and coordination docs

## Tests

- Day48 focused suite: `18 passed`.
- Phase 3/4A/4B and Day45–48 explicit regression selection: `167 passed`.
- Full pytest: `637 passed, 5 deselected`.
- Leakage selection: `8 passed, 634 deselected`.
- Ruff, mypy (`328 source files`), Black (`328 files`), and
  `git diff --check`: PASS.

## Blockers

None for the Day48 implementation contract. JSON/JSONL is an artifact
boundary, not a transport SLA. Permanent issuer mapping, PEER_GROUP, real
continuous State history, Quant universe construction, Factor validation,
ranking, signals, and portfolio behavior remain outside this repository or
future work.

## Required Changes From Other Modules

None. Day48 is ready for independent acceptance. Day49 is not authorized.

## Ready For Integration

YES — `WINDOW1_DAY48_IMPLEMENTATION = PASS`;
`READY_FOR_DAY48_ACCEPTANCE = YES`.

---

# Phase 4C Day48 — Blocking Repair

## Current Status

Closed Window 2 blockers `SATELLITE_WIRE_PAYLOAD_INCOMPLETE` and
`BATCH_JOIN_KEY_AMBIGUOUS` without changing Day45–47 or earlier contracts.

## Current Task

Made each Satellite wire item independently interpretable from JSON/JSONL and
froze the v1 batch join key as unique `(asset_id, research_as_of)`.

## API Changes

- `HandoffSatelliteReference` remains backward-compatible by name and now
  includes the faithful descriptor value/components, comparison scope,
  quality/confidence, and missing semantics from its source Observation.
- Batch manifests list canonical `research_as_of_values`; `research_as_of` is
  retained for a single-cutoff batch and is null for a multi-cutoff batch.
- Duplicate Quant join keys hard-fail before artifact output.

## Files Changed

- `src/schemas/research_quant_handoff.py`
- `src/services/research_quant_handoff.py`
- Day48 unit and external-consumer integration tests
- Main-owned Handoff/schema/status/coordination documentation

## Tests

- Window 2 external-consumer acceptance: `2 passed`.
- Repaired Day48 focused suite: `25 passed`.
- Cross-phase regression: `134 passed`.
- Full pytest: `644 passed, 5 deselected`.
- Leakage selection: `8 passed, 641 deselected`.
- Ruff, mypy (`329 source files`), Black (`329 files`), and
  `git diff --check`: PASS.

## Blockers

None known after focused repair.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — `WINDOW1_DAY48_REPAIR = PASS`;
`READY_FOR_DAY48_REACCEPTANCE = YES`.

---

# Phase 4 Day49 — Research Intelligence v1 Freeze

## Current Status

`DAY49_RESEARCH_INTELLIGENCE_GATE = PASS`. Phase4A/4B/4C contracts and the
external Handoff consumer remain green; the Research system is frozen at
`ResearchQuantHandoffBundle v1`.

## Current Task

Completed architecture/scope audit, two-run Golden replay determinism,
Selection/Timing contract-fixture acceptance, provenance and leakage
challenges, full regressions, and documentation freeze. No live service was
called and no new runtime module was added.

## API Changes

None. Day49 freezes existing v1 contracts.

## Files Changed

- `data/golden_replay/day49/acceptance_summary.json`
- Main and cross-window frozen-status documentation

## Tests

- Phase regression: `343 passed`.
- Full pytest: `650 passed, 5 deselected`.
- Leakage: `8 passed, 647 deselected`.
- Ruff, mypy (`329 source files`), Black (`329 files`), and diff check: PASS.

## Blockers

None for Research Intelligence v1. The release tag must wait for a clean,
reviewed commit because the accepted Phase 4 tree is currently uncommitted.

## Required Changes From Other Modules

None. Future work belongs behind the Handoff boundary.

## Ready For Integration

YES — Research Intelligence v1 is ready to freeze; no Quant implementation was
started.

---

# Phase 4 Pre-freeze Live Integration Repair

## Current Status

Main-owned live Sector wiring and Sector/ResearchState CLI import-cycle
blockers are closed. Full live acceptance was intentionally not rerun.

## Current Task

Injected an explicit aligned `SectorContextBundle` through the existing
resolver protocol into the checked-in live report composition root, verified
Sector/Chain/Radar report surfacing, and removed eager package import cycles.

## API Changes

- `python -m scripts.live_report --sector-context <path>` enables the Phase 4
  path; omitting it preserves the legacy Phase 3 path.
- `FrozenSectorContextResolver` adapts an already-built validated bundle to the
  existing runtime resolver protocol without Provider or Agent work.
- `src.services.temporal` remains compatible while delegating to the neutral
  temporal mapping module; `src.memory` service exports are lazy.

## Files Changed

- live composition and offline integration fixture
- Sector context service
- temporal mapping and Memory package initialization
- focused live wiring, report surfacing, and CLI import tests
- Main status and decision documentation

## Tests

- Focused wiring/CLI: `19 passed`.
- Cross-phase affected regression: `106 passed`.
- Full pytest: `669 passed, 5 deselected`.
- Leakage: `8 passed, 666 deselected`.
- Ruff, mypy (`332 source files`), Black (`332 files`), and diff check: PASS.

## Blockers

None for `PHASE4_LIVE_REPORT_WIRING_MISSING` or `SECTOR_CLI_IMPORT_CYCLE`.
Alpaca News and Stocktwits OAuth remain explicitly outside this repair.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — ready for a separately authorized AAPL live rerun.

---

# Phase 4 Canonical Research Instant Repair

The live time model now freezes one exact UTC `research_as_of` and projects it
into provider-native dates without reverse-overwriting the global cutoff.
Phase4 Sector CLIs share the same date/instant parser; instant mode never
expands to future UTC EOD, while date mode preserves Golden Replay behavior.

Historical access remains strict on ingestion. Explicit live acquisition uses
source availability for information eligibility and records later ingestion
as execution lineage. Stocktwits naive timestamps remain fail-closed at its
provider boundary; Main does not guess a timezone.

Deterministic fixed-instant integration smoke passed across live report,
Sector State, Macro, Radar, Sector Research, and Asset Integration. Fresh live
State and Macro also passed at the same canonical instant. Radar Memory
embedding could not be executed without separate authorization to transmit
Sector/Macro summaries to the external embedding service; no Fake fallback was
used.
# Phase 4 Final Live — FMP Main Orchestration Integration

## Current Status

Main removed the operationally duplicated full FMP acquisition from the
release sequence. The formal sequence is now a zero-network
`scripts.live_report --configuration-preflight` followed directly by the full
`scripts.live_report` invocation. The latter owns the one authoritative
high-level acquisition and reuses Window 2's exact run-scoped
`FMPProviderSnapshot` during formal ingestion.

## Contract

- PRECHECK != ACQUISITION.
- ACQUIRE ONCE; VALIDATE ON SNAPSHOT; REUSE DOWNSTREAM.
- Snapshot identity includes asset, exact research cutoff, request window, and
  acquisition contract version.
- Diagnostics retain high-level acquisition, physical endpoint, reuse, and
  retry counts.
- Persistent 429 remains a Provider availability failure; no Fake or old-run
  fallback is permitted.

## Files

- `scripts/live_report.py`
- `tests/unit/test_live_report.py`
- `README.md`
- `docs/operations.md`
- Main decision/status/coordination documentation

## Acceptance

- Focused Main/FMP suite: `23 passed`.
- Full pytest: `737 passed, 5 deselected`.
- Leakage suite: `8 passed, 734 deselected`.
- Ruff, mypy (`344 source files`), Black, and diff check: PASS.
- Real `CONFIGURATION_PREFLIGHT`: network calls `0`, FMP data requests `0`.
- Real integrated FMP attempt: high-level acquisition `1`, physical endpoint
  attempts `3`, retries `2`, snapshot reuse `0`; persistent HTTP 429 occurred
  on `income-statement`, so the path failed closed before a snapshot existed.

`MAIN_FMP_INTEGRATION_REPAIR = PASS`.

`FMP_PROVIDER_AVAILABILITY = TEMPORARILY_RATE_LIMITED`.

`READY_FOR_FULL_AAPL_LIVE_RERUN = NO`.

---

# Phase 4 Final AAPL Live Acceptance

The complete AAPL path is **PASS** and ready for independent audit. The final
report is `rep_247bed0b969d44a6bd37449c3c0a6b50`; all live objects share
`2026-09-16T06:17:59.936450Z`.

Manager v7 added a qualified Industry-Chain-to-asset synthesis using only exact
upstream Claim IDs. Same-run research reruns reuse frozen Provider snapshots,
and manifest/State/Episode lineage is scoped by report ID. Phase4A Report
surfacing, Phase4B State/Episode/Attribution, and Phase4C
Satellite/Candidate/Transition/Handoff all pass. Memory is `EMPTY_VALID` and
Timing observations are `MISSING_INPUT`; neither is presented as validated
predictive Alpha.

`READY_FOR_FINAL_INDEPENDENT_AUDIT = YES`.

Final engineering gate: `751 passed, 5 deselected`; leakage `8 passed, 748
deselected`; Ruff, mypy (`344 source files`), Black, and diff check pass.
