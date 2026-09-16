# Module Status

| Module | Status | Progress | Notes |
|---|---|---:|---|
| Repository Scaffold | Complete | 100% | Directory and Python package structure only |
| Foundation | Complete | 100% | Conda Python 3.12, uv, pytest, Ruff, Black, mypy, and health checks |
| Configuration | Complete | 100% | Shell-only typed environment settings, secret handling, and structlog initialization; no `.env` loading |
| Domain Models | Complete | 100% | Pydantic contracts, canonical asset identity, enums, and module Protocols |
| Database Schema | Complete | 100% | MASTER_SPEC tables plus durable `report_jobs`; idempotent tables and indexes |
| DuckDB Layer | Complete | 100% | Scoped connections, transactions, cross-process read/write local file lock, typed mappings, and Repository CRUD |
| FAISS Layer | Complete | 100% | Private cosine index Repository, namespace manifests, Parquet vector metadata, persistence, reload, removal, and rebuild |
| Memory | Complete | 100% | Attributable L0–L4 writes, document chunk embedding, namespace/asset isolation, semantic retrieval, DuckDB sidecars, and offline Fake Embedding |
| Data Ingestion | Complete | 100% | SEC EDGAR filing/XBRL, FMP standardized US metrics, Alpaca market/news, FRED macro, and Stocktwits sentiment with controlled clients, canonical normalization, lineage, idempotent DuckDB ingestion, offline fixtures, and isolated live smokes |
| LLM Gateway | Complete | 100% | Configuration-selected OpenAI/Qwen Responses Providers, deterministic DuckDB cache, safe metadata logging, explicit missing-credential failure, offline Fake injection, and one unified live smoke path |
| Analyst Agent | Complete | 100% | Four cited role Agents, explicit facts/inferences, exact evidence-grounded numeric claims, normalized scores, missing-data/trading validation, and offline Fake Gateway tests |
| Manager Agent | Complete | 100% | Research, Bull, Bear, and Risk Managers with strict prompts and normalized score scales, fixed coordination, evidence inheritance, run audit, and degraded-chain tests |
| Report Generator | Complete | 100% | Ten-section single-asset Markdown/JSON, fact/inference separation, numeric/citation validation, failed-state persistence, and compensating L3 trace deletion |
| FastAPI | Complete | 100% | Application factory, injected services, durable production task/status/query, Memory, snapshot query, health, unified errors, and Phase Two 501 routes |
| Scheduler and Worker | Complete | 100% | Single UTC Scheduler submits public API requests; single Worker claims durable DuckDB jobs from Redis ID queue and recovers interruptions |
| Web UI | Complete | 100% | Read-only Streamlit task-status and report viewer through FastAPI |
| Docker | Complete | 100% | Python 3.12 image and Compose topology for API, one Worker, Scheduler, Web, and Redis with named volumes |
| Integration Testing | Complete | 100% | Deterministic offline API loop plus isolated SEC-to-DashScope live report acceptance with citation trace audit |
| Deployment | Complete | 100% | Single-node Compose inherits its prepared parent shell; atomic snapshot/backup scripts, logical snapshot query, and documented commands |
| Report Evaluation | Complete | 100% | Versioned 12-dimension rules, deterministic checks, Gateway-backed/Fake Judge separation, auditable scoring, and immutable DuckDB persistence |
| Research Benchmark | Complete | 100% | Versioned seven-case CN/HK/US offline corpus, provenance and expectation contracts, deterministic threshold gates, machine JSON results, and isolated live Judge boundary |
| Live Agent Benchmark | Complete | 100% | Immutable US snapshot, six real-Agent scenarios, real LLM/Judge hard gate, per-case artifacts, input fingerprints, and neutral baseline/candidate comparison |
| Phase 3 Shared Research Context | Complete | 100% | Canonical ResearchDataBundle + ResearchContextBundle, eight role projections, structured Evidence citation bridge, point-in-time orchestration, and LLM run metadata wiring |
| Phase 4 Sector Ontology | Complete | 100% | Fixed 18-sector ontology, dynamic Industry Chains, temporal memberships, hierarchical research scopes, minimal DuckDB graph, and non-exhaustive five-asset seed |
| Phase 4 Sector Universe | Complete | 100% | Immutable point-in-time snapshots over versioned memberships, optional market-validated ETF benchmarks, coverage diagnostics, and a scoped five-asset US live smoke |
| Phase 4 Deterministic Sector State | Complete | 100% | Versioned market, breadth, fundamental, and valuation state with explicit sample coverage, strict point-in-time inputs, immutable DuckDB snapshots, and no LLM computation |
| Phase 4 Sector Cycle & Macro Sensitivity | Complete | 100% | Five-dimensional descriptive macro cycle state plus rolling univariate Sector sensitivity with explicit sample gates, PIT lineage, immutable snapshots, and no Regime model |
| Phase 4 Sector Anomaly Radar | Complete | 100% | Deterministic price/volume, breadth, earnings, news/event, macro-shock and graph-grounded propagation candidates with immutable PIT events and existing hierarchical Memory scopes |
| Phase 4 Sector Research Agent | Complete | 100% | Upstream claim-first Sector synthesis over deterministic state, Macro, Radar, Industry Chain, and PIT Memory contracts with exact numeric/citation grounding and explicit degradation |
| Phase 4 Sector-to-Asset Integration | Complete | 100% | PIT asset-to-Sector/Chain routing, compact role-specific Sector context, direct-upstream Claim provenance, usage diagnostics, graceful Phase 3 fallback, and real Qwen 8/8 validation |
| Phase 4 Unified Temporal Contract | Complete | 100% | Shared UTC-aware TemporalMetadata, half-open effective intervals, unified usable-at validator, explicit DuckDB UTC compatibility, and cross-module Data/Sector/Event/Memory leakage rejection |
| Phase 4 ResearchStateSnapshot | Complete | 100% | Immutable PIT-safe machine research state over frozen Data/Sector/Claim/Memory projections; no Report parsing, LLM, live Provider, Factor, Regime, or training behavior |
| Phase 4 ResearchEpisode | Complete | 100% | Immutable process audit over ResearchState, Agent runs, Claim identities/counts, reused Sector usage diagnostics, and version/result references; no private reasoning or Outcome behavior |
| Phase 4 Learning Memory v1 | Complete | 100% | Additive Scope/Time/Episode/provenance metadata over L0–L4, EPISODIC persistence and retrieval, explicit Semantic lifecycle and reference-only Performance reservation |
| Phase 4 Research Context Attribution | Complete | 100% | Episode-scoped Memory/Sector/Radar provided-selected-used lineage, explicit Memory RetrievalRecord, canonical sources, PIT enforcement, and no Outcome scoring |
| Phase 4 PIT Research Dataset v1 | Complete | 100% | Stable reference-only State/Episode/Attribution samples, shared PIT validation, explicit historical completeness, empty pending labels, immutable DuckDB rows, and credential-free manifests |
| Phase 4 Golden PIT Replay Gate | Complete | 100% | Two frozen AAPL runs deterministically reproduce State/Episode/Attribution/Sample identities with zero Provider/LLM calls and five deliberate future-input rejections |
| Phase 4C Research/Quant Boundary | Complete | 100% | Documentation-only ownership freeze: Research Intelligence remains here; Planetary Alpha, Quant processing, strategy, portfolio, and execution move to future deepinsight-quant |
| Phase 4C Satellite Alpha Ontology v1 | Complete | 100% | Versioned Selection/Timing/Both Research descriptors, explicit comparison/missing semantics, deterministic PIT State mapping, compact provenance, and zero LLM/Provider calls |
| Phase 4C Timing Satellite / State Transition v1 | Complete | 100% | Deterministic nearest-prior State continuity, seven existing Timing observations, strict PIT Event/Memory lineage, and no Quant/trading semantics |
| Phase 4C Research → Quant Handoff v1 | Complete | 100% | Reference-only State/Episode/Candidate/Transition and Selection/Timing Satellite export with deterministic JSON/JSONL identity, mixed coverage, PIT validation, and no Quant runtime |
| Numeric Grounding Semantics v2 | Complete | 100% | Shared identifier/window/Decimal-format classification with Evidence-specific provenance; no epsilon or unit conversion and no change to quarantine, HIGH-event, PIT, or cardinality policy |

## Phase Four status

- Day44 freezes the three-layer long-term architecture: Research Intelligence,
  Quant Alpha/Strategy, and Portfolio/Execution. This repository owns only the
  first layer and now emits raw Satellite Alpha descriptors through the
  versioned, reference-only `ResearchQuantHandoffBundle v1` implemented on
  Day48.
- Planetary Alpha and all broad PIT universe maintenance, Factor processing,
  IC/RankIC/ICIR, selection/timing/holdings ranking, Regime/MoE routing,
  backtesting, portfolio construction, position sizing, orders, and execution
  belong to the future independent `deepinsight-quant` repository.
- Satellite Alpha is a Research-produced descriptor with `SELECTION`,
  `TIMING`, or `BOTH` intent—not a Factor exposure or trading signal. The
  Research Candidate Universe cannot replace the complete Base Quant PIT
  Market Universe. Opaque single AI stock scores are prohibited.
- Older Phase-Two Factor/router/strategy/training/backtest/execution stubs,
  501 routes, and `p2_*` fields are superseded as ownership plans. They remain
  inactive historical compatibility artifacts; no stable Phase 3/4A/4B code
  or identity was changed by Day44.
- Day44 Gate A: `565 passed, 5 deselected`; Ruff, mypy (316 source files),
  Black, and `git diff --check` pass. Day44 changed no Python production or
  test code.

- Day43 closes the Golden point-in-time replay gate. Phase 3 AAPL run
  `20260814T100747Z` and Day36 Sector-aware run
  `agent_contract_20260830T135643Z_70442a96` reproduce their exact State,
  Episode, Attribution where present, and Dataset Sample semantic identities
  from frozen artifacts only. Provider calls and LLM calls are both zero.
- The Phase 3 replay preserves null Sector/Chain/Memory/Attribution history;
  no later Phase 4 context is backfilled. The Day36 replay preserves 24/10
  provided/used Sector Claim references, 6/4 provided/used Radar Event
  references, and `EMPTY_VALID` Memory with zero retrievals.
- Five deliberate future inputs—News, Radar Event, Memory, Sector Membership,
  and Filing—are rejected by Unified Temporal Contract v1. Repeated replay
  preserves State, Episode, Sample, and Replay identities while audit
  `created_at` remains non-semantic.
- Day43 artifacts are under `data/golden_replay/day43/`. The Day36 source did
  not persist accepted downstream Asset Claim IDs, so its two sampled
  context-to-Claim traces remain explicitly PARTIAL rather than inferred.
- Day43 Gate A: `565 passed, 5 deselected`; Ruff, mypy (316 source files),
  Black, and `git diff --check` pass. Phase 3 and Phase 4A regression paths
  remain green under the full offline suite.

- Day42 establishes `ResearchDatasetSample v1` as a stable replay/evaluation
  unit. It indexes State, Episode, optional Attribution/context, Agent runs,
  hierarchy and version identities without copying Claims, Evidence, Memory,
  Report, or SectorContext payloads.
- The builder is deterministic, performs zero LLM/Provider calls, and reuses
  Unified Temporal Contract v1. Labels are empty and PENDING; no later price or
  Outcome is read. DuckDB rows are immutable and validated against their
  stored Sample JSON, with one credential-free manifest per artifact.
- Phase 3 Golden materialized as PARTIAL with its original null Sector,
  Memory, and Attribution references. Day36 AAPL materialized as PARTIAL with
  its real Consumer Electronics/Apple Chain context and Day41 Attribution;
  historical partial Agent identities and missing Memory remain unchanged.
- Day42 focused Builder/Repository/schema suite: `26 passed`; full Gate A:
  `559 passed, 5 deselected`. Ruff, mypy (312 source files), Black, and
  `git diff --check` pass.

- Day41 establishes `ResearchEpisodeAttribution v1` as an immutable companion
  artifact rather than mutating ResearchEpisode or the eight-Agent pipeline.
  One composable context contract covers Memory, Sector Claims, and Radar
  Events while Day36 `SectorContextUsageDiagnostic` remains authoritative.
- `MemoryRetrievalRecord v1` retains query purpose, role/run identity,
  PIT-eligible candidate/selected IDs, rank, score, Scope filters, snapshot,
  future exclusion count, and an explicit `empty_valid`. Candidate traces are
  emitted only after DuckDB metadata and Unified Temporal Contract filtering;
  no FAISS object crosses the Repository boundary.
- `provided`, `selected`, and `used` are distinct. Only an explicit reference
  from a final accepted Claim makes context `used`; rejected-Claim linkage is
  retained separately and never counts as use. Outcome/usefulness status is
  only `PENDING` or `NOT_AVAILABLE`, and usefulness score is always null.
- The historical Day36 AAPL Episode materializes 30 source-preserving
  attributions with 10 used Sector Claim and four used Radar Event entries.
  Its source summary omitted accepted asset Claim IDs and Memory retrieval
  details, so 14 used entries are explicitly
  `NOT_AVAILABLE_AT_SOURCE_RUN` at Claim-link level and no historical Memory
  RetrievalRecord is fabricated.
- Day41 focused Memory/Sector/Temporal/Episode suite: `62 passed`; full Gate A:
  `548 passed, 5 deselected`. Ruff, mypy (306 source files), Black, and
  `git diff --check` pass. No live Provider or external Embedding was invoked.

- Day40 establishes `LearningMemoryMetadata v1` without replacing L0–L4,
  DuckDB, FAISS, or `ResearchContextBundle`. Research Scope and Memory level
  remain independent dimensions.
- EPISODIC Memory persists selected Claim, thesis, risk, catalyst, Event,
  State, and Episode references with canonical source lineage. Macro, Sector,
  Industry Chain, Asset, and ResearchEpisode scopes are exercised; whole
  reports are not embedded as episodes.
- Legacy rows remain compatible through nullable `metadata_json`. Day35 JSON
  headers are not guessed or rewritten. SEMANTIC has an explicit lifecycle and
  cannot become validated truth from one Episode; PERFORMANCE stores no
  computed outcome.
- Both Memory retrieval paths reuse Unified Temporal Contract v1 and require
  the strict effective/created/available cutoff. Empty retrieval remains
  `EMPTY_VALID`, and no historical analog is synthesized.
- Day40 focused Memory/Temporal/Repository tests: `58 passed`; full pytest:
  `540 passed, 5 deselected`. No live Provider was invoked.

- Day39 establishes `ResearchEpisode v1` as the third formal artifact and
  keeps it separate from ResearchState: State records what was knowable;
  Episode records the structured process actually executed under that State.
- The Episode stores only references and execution metadata. It never stores
  private reasoning, chain-of-thought, prompts, report prose, credentials, or
  unrelated local data. Day36 Sector usage diagnostics are reused unchanged.
- The Phase 3 AAPL Golden run materialized a COMPLETE Episode with eight Agent
  runs, 54 accepted and two rejected Claim identities, 20 final research
  Claims, and its real report identity. The Day36 Sector-aware AAPL run
  materialized PARTIAL with eight run identities, 52 accepted/5 rejected
  counts, six Sector Claims, and eight usage records because the historical
  summary did not retain asset Claim IDs or latency; no identities were
  invented.
- Day39 focused Episode/Sector-context tests: `17 passed`; full Gate A:
  `532 passed, 5 deselected`. Ruff, mypy (301 source files), Black, and
  `git diff --check` pass.

- Day38 establishes `ResearchStateSnapshot v1` as the second formal research
  artifact. `ResearchStateBuilder` is deterministic and accepts no Report,
  Gateway, Provider, or live Repository dependency.
- Feature types are explicitly deterministic numeric, versioned normalized
  research state, or semantic/categorical. Provenance is ID-only and closes
  through accepted Claim graphs to Evidence; Prompt/model/data versions remain
  centralized in snapshot lineage.
- The Phase 3 Golden Run `20260814T100747Z` materialized 54 accepted Claims at
  its original cutoff with Sector/Chain correctly marked
  `NOT_AVAILABLE_AT_SOURCE_RUN`. No later Phase 4 context was backfilled.
- The Day36 AAPL source run materialized Macro (PARTIAL), Sector, Apple Chain,
  and asset state from its own frozen Bundle and real-Qwen Sector context. Its
  missing asset Agent/Memory payloads remain explicit because the Day36
  contract summary did not persist those full structured objects.
- Day38 focused contract tests: `7 passed`; both acceptance materializations
  reported `llm_calls=0` and `network_calls=0`. Full Gate A: `525 passed, 5
  deselected`; Ruff, mypy, Black, and `git diff --check` pass.

- Day30 establishes `SectorOntology v1` with exactly 18 stable first-level
  research categories; no additional first-level Sector was introduced.
- Dynamic Industry Chains and asset memberships use immutable versioned rows
  with inclusive `valid_from` and exclusive optional `valid_to` boundaries.
- Unified scopes cover GLOBAL, MACRO, SECTOR, INDUSTRY_CHAIN, ASSET, and
  RESEARCH_EPISODE without changing Memory L0–L4 or Phase 3 Agent contracts.
- DuckDB persists the minimal `sector_nodes`, `sector_edges`,
  `sector_memberships`, and `research_scopes` model. No graph engine, graph
  algorithm, Sector Agent, Radar, Factor, Backtest, or trading behavior exists.
- The AAPL/NVDA/AMD/TSM/MU seed is explicitly a test fixture, not a complete
  security universe or production classification claim.
- Day30 Gate A: `455 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day31 adds immutable `SectorUniverseSnapshot` rows and temporal
  `SectorBenchmarkMapping` rows. All 18 Sectors have explicit optional US ETF
  candidates; only candidates with a real Alpaca bar are promoted into a
  snapshot. Empty benchmarks remain valid MISSING mappings.
- The scoped live smoke `20260830T024104Z` validated AAPL, NVDA, AMD, TSM, MU
  and 17 unique ETF candidates. S01 contains AMD/NVDA/TSM with SOXX; S02
  contains MU with SOXX as a PARTIAL proxy; S03 contains AAPL with XLK as a
  PARTIAL proxy. Classification uses the non-exhaustive internally curated
  `sector_universe_membership_v1`, not a test-fixture identity or a claimed
  full US constituent universe.
- The checked-in FMP adapter has standardized fundamentals but no
  profile/screener/classification contract. Automatic exhaustive constituent
  discovery therefore remains PARTIAL and does not trigger a new Provider in
  Day31. The detailed audit is in `docs/SECTOR_CAPABILITY_MATRIX.md`.
- Day31 Gate A: `461 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day32 establishes `SectorResearchSnapshot v1`. Constituent price features
  reuse `TechnicalFeatureOperator`; cross-sectional medians, breadth ratios,
  dispersion, benchmark-relative returns, FMP fundamental breadth, and
  valuation medians are computed only by deterministic Python operators.
- Every metric records `coverage_count`, `universe_count`, and
  AVAILABLE/PARTIAL/MISSING. Sector aggregates require at least two valid
  constituents, so one-name S02/S03 snapshots do not present an issuer value
  as Sector breadth.
- Live smoke `20260830T034235Z` wrote 720 real Alpaca bars and four real FMP
  standardized records, then generated S01 AVAILABLE plus S02/S03 PARTIAL
  snapshots. FMP returned a visible `ProviderUnavailableError` for MU; no
  value was fabricated and the S02 fundamental coverage is 0/1.
- Day32 Gate A: `469 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day33 adds deterministic `SectorCycleState` and `MacroSensitivity` outputs.
  The cycle view describes rates, inflation, labor, growth, and financial
  stress from the existing 12-series FRED pack using current, three-month,
  and twelve-month comparisons. It is descriptive state, not a trained or
  hand-labelled Regime.
- Macro sensitivity aligns monthly Sector benchmark returns with monthly
  macro changes over a rolling 36-month window. Each series uses an
  independent OLS beta and Pearson correlation and requires at least 24
  aligned observations; insufficient series remain PARTIAL without
  extrapolation.
- Live smoke `20260830T051233Z` persisted 2,128 real Alpaca bars, 6,192 FRED
  point-in-time observations, and three immutable S01/S02/S03 macro
  snapshots. Eleven of twelve sensitivity series met the sample gate for
  each Sector; quarterly GDP remained PARTIAL. No LLM call was made.
- Day33 Gate A: `474 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day34 adds the independent deterministic `SectorAnomalyRadar`. Its v1 rule
  set covers price/volume spikes, breadth divergence, structured earnings
  surprise, material company/news events, macro-to-Sector shocks, and
  membership/graph-grounded supply-chain propagation candidates. Radar does
  not call an Agent or LLM and does not make an investment judgment.
- `SectorAnomalyEvent` enforces publication, availability, ingestion, and
  `as_of` cutoffs and retains canonical Evidence, Sector, Chain, source asset,
  affected asset, severity, confidence and candidate status. One structured
  event body is linked to multiple existing SECTOR/CHAIN/ASSET scopes; Memory
  projections reuse the exact same summary and existing L1/L2 hierarchy.
- Live smoke `20260830T074510Z` detected six real events from the audited
  Day32/Day33 data: one TSM price/volume anomaly, four macro-shock candidates,
  and one NVIDIA AI Infrastructure propagation candidate. Ten Evidence links
  were retained, future leakage was zero, and real Qwen embedding/FAISS
  retrieval returned S01/S02/S03 Sector-scope results of 3/1/2. Propagation
  direction remained UNKNOWN. No LLM anomaly calculation occurred.
- Day34 Gate A: `480 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day35 adds `SectorResearchAgent` as an independent upstream research
  component, not a ninth peer in the frozen eight-Agent asset chain. It accepts
  aligned Day31-Day34 snapshots plus the existing `ResearchContextBundle`,
  projects compact direct-upstream Evidence, and emits only validated Sector
  Claims plus an Evidence-backed interpretive cycle assessment.
- The Agent does not calculate Sector or Macro features, query a Provider,
  DuckDB, or FAISS directly, mutate the Industry Chain graph, or emit a trade,
  position, order, target price, Factor, or Regime. Invalid Claims are
  quarantined and never become accepted output or Memory.
- Selected accepted anomaly, catalyst, risk, chain, and cycle Claims may be
  written through the existing public Memory boundary to SECTOR/CHAIN L3 trace
  scopes. The current Memory write schema has no structured metadata bag, so
  Day35 stores the required lineage metadata in a deterministic JSON header;
  it does not persist an undifferentiated narrative or create L4 Memory.
- Fixed real-snapshot smoke `20260830T081642Z` reused the audited Day32 state,
  Day33 Macro, and Day34 Radar databases. S01/S02/S03 all passed with zero
  invalid citations and all numeric Claims exactly grounded. All three HIGH
  Radar events were represented; S02/S03 remained explicitly PARTIAL/proxy.
- The real Qwen rerun on Day36 exposed one Prompt/schema responsibility drift:
  the Prompt asked the model to self-report `claim_intent`. The field was
  removed from the Prompt and the authoritative Draft schema now applies its
  deterministic analytical-inference default. S02 and S03 then produced real,
  strictly validated Qwen Sector outputs; S01 remains a visible local Claim
  promotion failure and is not represented as a successful live result.
- Day35 Gate A: `496 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day36 adds `SectorContextBundle v1` and eight least-privilege role
  projections. Asset routing uses effective `SectorMembership` rows and
  Industry Chain IDs; it never infers a Sector from ticker text. Analysts see
  presentation-only conditional Sector context while retaining their existing
  asset-Evidence contract. Managers receive accepted Sector Claims as direct
  upstream Claims and reuse the existing recursive provenance validator.
- `ResearchWorkflowService` accepts an optional Sector resolver. Missing
  membership, chain, Radar events, Sector output, or a PARTIAL snapshot remains
  explicit and safely falls back to the frozen Phase 3 path without Fake data.
  No Provider, Memory schema, Agent role, Prompt, Report, or database table was
  added.
- Fixed real-snapshot smoke `20260830T134805Z` resolved NVDA to
  S01/NVIDIA_AI_INFRA, MU to S02/HBM, and AAPL to S03/APPLE_CHAIN. All three
  contexts retained real Day32-Day34 snapshot/Event lineage; S02/S03 and other
  limited coverage remained PARTIAL rather than being upgraded.
- Real Qwen integrated run `agent_contract_20260830T134209Z_e0291bba` passed
  all eight asset Agents. The role projections supplied 17 Sector Claim slots;
  recursive diagnostics observed 5 actual Sector Claim uses and 2 Radar Event
  uses across Research/Bull/Bear/Risk. Accepted numeric Claims were `26/26`
  grounded, with zero invalid citations, schema errors, or unbound Claims.
- The stronger real Sector-to-asset rerun used the real Qwen S03 output from
  `data/live_sector_research/20260830T135456Z/` directly in AAPL contract run
  `agent_contract_20260830T135643Z_70442a96`. All eight asset Agents passed.
  The projections supplied 24 Sector Claim slots and six Event slots; recursive
  diagnostics observed ten Sector Claim uses and four Event uses. All `38/38`
  accepted numeric Claims were grounded, with zero invalid citations, schema
  errors, or unbound Claims. No Fake fallback was used.
- The same fixed asset/as-of baseline without Sector context
  (`agent_contract_20260830T134349Z_248ca374`) also passed 8/8. Because these
  are independent stochastic model samples, Claim-count differences are
  integration diagnostics only and are not evidence of research or investment
  performance improvement.
- Day36 Gate A: `506 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- Day37 adds `TemporalMetadata v1`, `TemporalAccessDecision`,
  `is_usable_at()`, and `validate_temporal_access()` as the shared PIT rule.
  Existing Provider and domain fields remain compatible and are mapped rather
  than renamed. Event/period time describes occurrence; research eligibility
  depends on canonical availability, ingestion, snapshot, or half-open
  effective bounds.
- SEC/FMP fundamentals, Alpaca daily bars/news, FRED vintages, Research
  Evidence, Sector memberships/anomalies/Claims, and Memory/context records
  now share the same access decision. Sector state/macro/Radar operators and
  ResearchDataBundle/ResearchContextBundle boundaries reuse that decision.
- Memory persistence now retains the service clock's `created_at`; retrieval
  rejects a Memory created after the replay cutoff even when its
  `effective_ts` was backdated. Existing UTC-naive DuckDB timestamps are
  accepted only through an explicitly named UTC storage compatibility
  function, never through a local-time assumption.
- Day37 Gate A: `518 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.

## Phase Three status

**Phase 3 — Research Completeness v1 = FROZEN**

- Release baseline: `data/live_acceptance/20260814T100747Z/`.
- Release report: `rep_27ce48e18b5443f297c485405792c535`.
- Release Evaluation: `eval_041e4ae3647d43c6a8dacc498102d2ca`.
- Public release documentation is maintained in
  `docs/releases/PHASE3_RESEARCH_COMPLETENESS_V1.md`; the generated live
  acceptance directory remains Git-ignored.

- Final data enrichment closed on fresh live run `20260814T100747Z` with
  Financial Modeling Prep as the primary standardized US ratio/TTM source and
  SEC retained as the authoritative filing/XBRL/event source. FMP supplied all
  15 required AAPL growth, profitability, liquidity and valuation metrics for
  reporting period `2026-06-27`; no required standardized metric was missing.
- Canonical Bundle projection is authoritative over legacy feature flags.
  Provider-standardized FMP facts and the existing FRED MacroSnapshot are
  promoted deterministically into Claims and still pass the unchanged
  Evidence-ID and exact-literal validators. The report contains five
  Fundamental categories, six Technical categories, five Macro categories,
  Stocktwits aggregates, and attributable Alpaca News.
- Fresh Acceptance completed real SEC, FMP, Alpaca, FRED, Stocktwits, Qwen,
  Memory, all eight Agents, Report and real Evaluation without Fake fallback.
  Report `rep_27ce48e18b5443f297c485405792c535` traced `56/56` citations and
  retained accepted grounding for `42/42` numeric Claims. Evaluation
  `eval_041e4ae3647d43c6a8dacc498102d2ca` scored `0.9674999999999999`; every
  required threshold passed. Remaining data limitations are Alpaca raw-series
  adjusted-close/turnover coverage and valid empty historical Memory.
- Final Gate A: `447 passed, 5 deselected`; Ruff, mypy, Black and
  `git diff --check` pass. Research Completeness v1 is frozen on this enriched
  baseline.
- Report Completeness Polish on 2026-08-14 closed projection/operator gaps
  using existing SEC, Alpaca, FRED, and Stocktwits data. A copied
  `20260813T163645Z` acceptance DB deterministically produced 17 fundamental
  fields, three of six valuation fields, twenty technical fields, twelve friendly macro
  snapshot fields, attributable Alpaca News, and aggregate sentiment fields.
  The original acceptance DB was not modified and no network call was made.
- Missing current assets/current liabilities/consolidated debt remain explicit
  for the old snapshot. They are now mapped for future SEC ingestion; no value
  is estimated. EPS TTM/PE TTM/earnings yield also remain missing in the fixed
  snapshot because four discrete recent quarters are unavailable; the older
  annual EPS is not mislabeled as current TTM. Alpha Vantage remains an optional P1 backlog only and is not a
  Research Completeness dependency.
- Current Gate A: `438 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass.
- A credential-free replay of the accepted Agent outputs regenerated all ten
  report sections with 15 unique citations. It confirms presentation and
  lineage compatibility, but correctly does not retrofit new macro/news Claims
  into historical LLM output; the next normal live run will measure consumption
  of the new bundle fields.
- Research Completeness v1 is frozen after fresh live acceptance
  `20260813T163645Z`. Real SEC, Alpaca, FRED, Stocktwits, Qwen, Memory, all
  eight Agents, Report, and real Judge completed without Fake fallback.
- All ten required core capabilities were integrated with point-in-time
  safety. The run persisted a ten-section report and Evaluation, traced
  `19/19` citations, grounded `21/21` numeric claims, and scored `0.95`
  overall. Every Final Gate threshold passed.
- Final artifacts include report `rep_70fb903a3bc74aaebe2e391771fd3816`,
  Evaluation `eval_34ed61df67b54ed09f08d369f4b63da8`, and the credential-free
  manifest under `data/live_acceptance/20260813T163645Z/`.
- Gate A is `433 passed, 5 deselected`; Ruff, mypy, Black, and
  `git diff --check` pass. The production Qwen Contract Gate is `8/8`
  (`agent_contract_20260813T161431Z_dd406cc2`).
- SEC filing retrieval uses a bounded 740-day lookback independent from the
  denser price window; EOD, news, sentiment, and macro retain their own
  frequency-aware windows.

- Final Gate blocker integration on 2026-08-13 restored the Main-owned offline
  workflow to `agent_output_v2` and passed `395` default tests (`5` live tests
  deselected), Ruff, mypy, Black, `git diff --check`, fixed-bundle Fake 7/7,
  and offline Benchmark 7/7.
- Credential-safe Gateway diagnostics now distinguish invalid JSON, schema
  validation, Provider, timeout, and cache failures and retain field-level
  contract diffs. Real Agent calls permit at most one unchanged-Evidence
  structured repair; Fake/default calls do not repair.
- Historical failed Qwen contract candidates remain diagnostic artifacts; the
  current production contract and Fresh Acceptance supersede their blocked
  status without deleting that history.

- The first Main integration accepts `ResearchDataBundle` as the canonical
  structured Data contract and `ResearchContextBundle` as the canonical
  point-in-time Memory contract. No third aggregate Bundle was introduced.
- `ResearchWorkflowService` builds both bundles with one timezone-aware UTC
  `as_of`, one asset, one report window, and one dataset version. The
  `ResearchTaskRequest` rejects a missing half or an identity/time mismatch.
- `ResearchCoordinator` projects `agent_input_v1` separately for the fixed
  eight roles. Managers receive all four explicit Analyst slots, including
  failures, and no Agent receives a Provider, Repository, DuckDB, or FAISS
  object.
- `ResearchEvidenceItem.to_source_reference()` is the only structured-Data to
  Agent/Report citation bridge. Numeric grounding and report citation checks
  remain strict.
- Data `MissingData` and Memory `MissingContext` remain distinct canonical
  absence types and are combined only by `AgentCoverageManifestV1`. Legacy
  strings are compatibility presentation, not the authority.
- `LLMRunMetadata` is now a shared LLM Schema. Agent and Evaluation calls pass
  Prompt/Schema versions; real Gateway metadata reaches Agent audit fields and
  persisted Evaluation JSON. Fake/default paths remain explicit and offline.
- Current default suite: `314 passed, 5 deselected` on 2026-08-09. Ruff, mypy,
  Black, and `git diff --check` pass.
- Current offline `research_benchmark_v1`: `7/7 passed`, zero failures.
- Remaining work is data coverage rather than shared-interface integration:
  attributable Alpaca technical Evidence, broader filing/event/news/sentiment,
  macro/market context, valuation, and real historical Memory.

## Phase Two status

- Current tasks: report quality evaluation framework,
  `research_benchmark_v1`, and the single-source SEC EDGAR Provider
  reliability enhancement, followed by the Day 16 Alpaca US EOD price
  Provider.
- `report_quality_v1` evaluates twelve dimensions and records every score with
  a reason and evidence locator.
- Objective checks run in code before aggregation; semantic checks use the
  existing `LLMGateway` boundary, with an explicit offline Fake Judge for
  default tests.
- The tracked Phase One SEC/Qwen report is an offline regression artifact:
  structure and citation traceability remain complete, while unsupported
  transformed numeric tokens are surfaced rather than silently accepted.
- Provider runtime changes are isolated below the existing normalization
  boundary; no report generation, Agent, Memory, trading, backtest, training,
  or reinforcement-learning behavior was added or changed.
- Day 15 standardizes `openai|qwen` selection at the composition root. Qwen
  inference and embeddings use production service boundaries; the Qwen smoke
  delegates to the unified Gateway smoke, and missing live credentials never
  fall back to Fake.
- SEC live commands now use the canonical
  `DEEPINSIGHT_PROVIDER_SEC_USER_AGENT` typed setting and retain the production
  Fair Access limiter, bounded retries, and timeout.
- Day 16 adds only Alpaca historical `1Day` US bars: Basic-safe IEX/raw
  defaults, canonical ticker mapping, opaque pagination, explicit missing
  fields, and `(asset_id, trade_date)` idempotency. Agent, Prompt, report,
  trading, and backtesting behavior is unchanged.
- Day 17 adds a fail-closed, credential-free live Preflight, explicit live
  dataset/window identity, SEC CIK configuration mapping, audited Alpaca range
  ingestion, real-Gateway Judge composition, and a versioned run manifest.
  The `live_aapl_multisource_baseline_v1` acceptance completed on 2026-08-08:
  one SEC filing, 63 Alpaca EOD bars, eight audited Agent runs, a ten-section
  report, a real Qwen Judge evaluation, and a credential-free manifest were
  persisted and the explicit live pytest passed.
- Live credentials now use a project-external, permission-restricted shell
  loader. Qwen uses `QWEN_API_KEY`/`QWEN_MODEL_NAME`; Alpaca includes an
  injected `APCA_API_BASE_URL`; SEC identity has no tracked value. Explicit
  `live` pytest cases skip when incomplete and are deselected by default.
- Default offline suite at the Phase 2 close: `275 passed` on 2026-08-08;
  current Phase 3 gate is recorded above.
- Default Benchmark: `7/7 passed`; every default pass depends on lifecycle,
  fixed expected facts, prohibited-conclusion compliance, and deterministic
  checks rather than Fake Judge semantic scores.
- Day 18 adds `live_agent_benchmark_v1` without changing
  `research_benchmark_v1`: a detached-checksum US:AAPL SEC/Alpaca snapshot is
  projected into six fixed scenarios and measured through the existing eight
  Agents, report assembler and real Gateway Judge. CN/HK are explicitly out of
  live-v1 coverage. No live Day 18 score is recorded until the opt-in command
  is actually executed.

## Phase One closeout

- Default offline suite: `206 passed` on 2026-08-07.
- Ruff, mypy, Black, and Docker Compose configuration are release gates.
- SEC EDGAR → DuckDB/FAISS/Memory → eight Agents → report live acceptance
  succeeded with Qwen compatibility injection and traceable citations.
- P1-3 remains explicitly deferred: an official OpenAI successful live smoke
  must be repeated after account funding is restored. Qwen acceptance is not
  recorded as an OpenAI production pass.
- No Phase Two runtime is enabled. Reserved abstract contracts are
  non-instantiable and API placeholders remain side-effect-free HTTP 501.

## Phase 4C Day45 — Satellite Alpha Ontology v1

- Added versioned Satellite Alpha usage, comparison, coverage, definition,
  component, observation, registry, and ResearchState semantic-audit contracts.
- Added a pure deterministic ResearchState mapper. It performs zero LLM,
  Provider, report parsing, ranking, Factor, or trading operations.
- Evidence Strength is implemented as decomposed attributable inventory;
  chain benefit, risk burden, alignment, disagreement, and event window remain
  truthful partial projections. Unsupported State semantics remain missing.
- Five historical Timing families are schema-ready and return
  `REQUIRES_HISTORY`; Day47 history construction was not started.
- Phase 3 Golden State keeps Sector/Chain observations
  `NOT_AVAILABLE_AT_SOURCE_RUN`; Phase 4A uses only source-run context.
- ResearchState v1 was audited but not changed. Full contract and capability
  matrix: `docs/SATELLITE_ALPHA.md`.
- Day45 Engineering Gate: `580 passed, 5 deselected`; leakage gate `3 passed,
  582 deselected`; Ruff, mypy (319 files), Black, and `git diff --check` pass.

## Phase 4C Day46 — Selection Satellite and OpportunityCandidate v1

- Added exact structured Selection mappings without changing ResearchState v1:
  Sector/Chain alignment supports exact formal inputs; disagreement, coarse
  Risk, expectation, logic, and chain-benefit mappings retain honest partial
  coverage where their formal State fields are absent.
- Added `OpportunityCandidate v1` with rule-based qualification, deterministic
  identity, explicit coverage, PIT availability, and reference-only lineage.
- State/Evidence presence alone is not eligibility. No weighted score, rank,
  Factor, price, position, order, portfolio, or recommendation was added.
- Phase3 and Phase4A frozen rebuilds remain zero-LLM/zero-Provider and preserve
  source-run absence. The multi-asset fixture is contract validation only.
- Day46 focused Day45+Day46 suite: `31 passed` (`16` new tests). Full Gate A:
  `596 passed, 5 deselected`; leakage `3 passed, 598 deselected`; Ruff, mypy
  (322 files), Black, and `git diff --check` pass.

## Phase 4C Day47 — Timing Satellite and ResearchStateTransition v1

- Added deterministic, reference-only `ResearchStateTransition v1` with
  strict same-Asset `T1 < T2`, nearest-prior selection, optional Episode
  linkage, compact Claim/Event/Evidence/Memory artifact lineage, explicit
  coverage, and semantic identity independent of audit timestamps.
- Added deterministic history projection for all seven Timing families using
  the existing `SatelliteAlphaObservation`. No second Timing schema, L5
  Memory, FAISS exposure, LLM/Provider call, report parsing, Quant strategy, or
  trading semantics was added.
- Two numeric expectation points support direction/delta/rate but never
  acceleration; three points permit versioned second-order change. Event and
  catalyst observations use deterministic windows and independent availability
  clocks. Future State, Event, outcome, Evidence, and Memory inputs are
  rejected through Unified Temporal Contract v1.
- Phase3/Phase4A single-State artifacts keep honest `REQUIRES_HISTORY` or
  `NOT_AVAILABLE_AT_SOURCE_RUN` and receive no synthetic backfill. Positive
  Memory and three-State paths are deterministic CONTRACT FIXTURES only;
  `REAL_HISTORICAL_MEMORY_REPLAY = NOT_YET_AVAILABLE`.
- Day47 focused Day45–Day47 suite: `54 passed`. Full Gate A: `619 passed,
  5 deselected`; leakage `7 passed, 617 deselected`; Ruff, mypy (325 files),
  Black, and `git diff --check` pass.

## Phase 4C Day48 — Research → Quant Handoff Contract v1

- Added `ResearchQuantHandoffBundle v1` as the sole formal Research boundary
  for future `deepinsight-quant`. It carries stable IDs and compact typed
  references rather than copying State, Episode, Claim, Evidence, Memory,
  Agent, or report payloads.
- Selection and Timing Satellite branches retain family, usage, coverage,
  definition/transform version, and availability. Candidate and Transition
  are optional; insufficient, partial, negative, source-run-unavailable, and
  history-required examples remain exportable.
- Bundle identity is deterministic, independent of `created_at`, and
  insensitive to observation input ordering. State/Episode/Candidate/
  Transition identity, cutoff, temporal availability, and provenance closure
  are validated before export.
- Added canonical sorted-key JSON and Bundle-ID-ordered JSONL export with a
  credential-free deterministic batch manifest and mixed-coverage counts.
  There is no LLM, Provider, database, network, Factor, ranking, Top-K,
  signal, portfolio, or trading dependency.
- Independent-consumer repair now projects Satellite values, structured
  components, comparison scope, coverage, definition versions, quality, and
  confidence into each compact wire item. `observation_id` remains the stable
  resolver into full Research provenance; no Evidence payload is inlined.
- Canonical Quant batch join key v1 is `(asset_id, research_as_of)` and is
  unique. Duplicate keys fail before files are written; different Assets at one
  cutoff and one Asset across different cutoffs remain valid.
- Window 2 external-consumer acceptance: `2 passed`; repaired Day48 focused
  suite: `25 passed`; cross-phase State/Episode/Attribution/Dataset/Golden/
  Satellite/Opportunity/Transition/Handoff regression: `134 passed`.
- Repaired full Gate A: `644 passed, 5 deselected`; leakage selection:
  `8 passed, 641 deselected`; Ruff, mypy (`329 source files`), Black
  (`329 files`), and `git diff --check` pass.
- Day48 focused suite: `18 passed`; explicit Phase 3/4A/4B and Day45–48
  regression selection: `167 passed`. Full Gate A: `637 passed, 5
  deselected`; leakage `8 passed, 634 deselected`; Ruff, mypy (328 files),
  Black, and `git diff --check` pass.

## Phase 4 Day49 — Research Intelligence v1 Golden Acceptance and Freeze

- Status: **FROZEN / PASS**. Phase4A Sector Intelligence, Phase4B Structured
  Research, and Phase4C Satellite/Opportunity/Transition/Handoff contracts
  remain accepted with no blocking regression.
- Replayed Phase3 AAPL `20260814T100747Z` and sector-aware AAPL
  `agent_contract_20260830T135643Z_70442a96` twice from frozen artifacts with
  stable State/Episode/Sample/Replay identities, zero Provider calls, and zero
  LLM calls.
- Phase3 receives no later Sector/Chain/Timing backfill. Phase4A retains S03,
  APPLE_CHAIN, 24/10 Sector Claims provided/used, 6/4 Events provided/used,
  partial historical Claim-ID limitations, and `EMPTY_VALID` Memory.
- Day46 NVDA/MU/AMD Selection and Day47 T1/T2/T3 Timing paths remain explicitly
  `CONTRACT_FIXTURE`; they validate interfaces, not predictive Alpha.
- Phase regression suite: `343 passed`. Full pytest: `650 passed, 5
  deselected`; leakage: `8 passed, 647 deselected`; Ruff, mypy (`329 source
  files`), Black (`329 files`), and `git diff --check` pass.
- Acceptance artifact:
  `data/golden_replay/day49/acceptance_summary.json`.
- Release tag `phase4-research-intelligence-v1` is semantically ready but must
  not be created until the currently uncommitted accepted tree is reviewed and
  committed.

## Phase 4 Pre-freeze live integration repair

- Status: **PASS** for the two Main-owned blockers identified by the first live
  attempt. No Provider, Agent, Prompt, ResearchState, Satellite, Handoff, or
  Quant behavior changed.
- The checked-in `scripts.live_report` now accepts an explicit PIT-aligned
  `--sector-context` artifact and injects it through the existing
  `AssetSectorContextResolver` protocol into the single production
  `ResearchWorkflowService` graph. The legacy no-Sector Phase 3 path remains
  available by omitting the option.
- The live manifest records Sector context, Sector, Chain, Event, artifact, and
  cutoff identities. Misaligned Asset or cutoff artifacts fail before any
  Provider request.
- A full workflow integration fixture proves an accepted Sector/Chain/Radar
  Claim reaches the human-facing Markdown and retains
  `sector_anomaly_radar` lineage; context presence alone is not treated as
  report surfacing.
- The Sector CLI cycle was removed by placing legacy-record temporal mappings
  in the neutral `src.temporal_mapping` module and making runtime Memory
  service exports lazy. The public `src.services.temporal` and `src.memory`
  imports remain compatible.
- Focused wiring/CLI suite: `19 passed`; affected cross-phase regression:
  `106 passed`; full pytest: `669 passed, 5 deselected`; leakage: `8 passed,
  666 deselected`; Ruff, mypy (`332 source files`), Black (`332 files`), and
  `git diff --check` pass.

## Phase 4 canonical live research instant repair

- Live orchestration now owns one exact aware UTC information cutoff. Latest
  completed market session and FRED native date are explicit provider
  projections and never replace `research_as_of`.
- Sector State, Macro, Radar, Sector Research, and Sector-to-Asset CLIs accept
  aware ISO-8601 instants. Historical `YYYY-MM-DD` mode retains frozen UTC-EOD
  semantics.
- Unified temporal access now distinguishes strict historical replay from
  explicit live acquisition: live data still requires source availability by
  T, while later ingestion is retained as lineage rather than misclassified as
  future information.
# Phase 4 live FMP acceptance orchestration

- Main integration exposes `scripts.live_report --configuration-preflight` as
  the zero-network release precheck and removes the standalone full
  `scripts.smoke_fmp` step from the formal runbook.
- `scripts.live_report --fmp-integrated-smoke` exercises the same run-scoped
  adapter acquisition and snapshot-reuse path without running the AAPL Agent
  workflow.
- The full `scripts.live_report` path remains authoritative for one FMP
  acquisition; its formal ingestion reuses Window 2's `FMPProviderSnapshot`.
- Persistent Provider 429 remains fail-closed and is reported separately from
  correctness of the Main orchestration.
- Main focused orchestration/FMP tests: `23 passed`; full Gate A: `737 passed,
  5 deselected`; leakage: `8 passed, 734 deselected`; Ruff, mypy (`344 source
  files`), Black, and `git diff --check`: PASS.
- The configuration-only live preflight reported zero network/FMP data calls.
  The subsequent single integrated live acquisition reached the Provider once
  at the high level, made three bounded `income-statement` HTTP attempts
  (initial plus two retries), and failed closed on persistent HTTP 429. No
  snapshot was created, so downstream reuse could not occur in this live
  attempt. Main integration is complete; Provider availability is temporarily
  rate-limited and full AAPL rerun readiness remains NO.

## Phase 4 final AAPL live acceptance

- Status: **PASS / ready for independent audit**.
- Canonical run: `phase4_release_20260916T061759Z_aapl`, cutoff
  `2026-09-16T06:17:59.936450Z`, report
  `rep_247bed0b969d44a6bd37449c3c0a6b50`.
- Human report: 68 Claims, 47/47 numeric Claims grounded, 82/82 unique
  citations traced, zero invalid citations, zero future leakage, evaluation
  overall `0.9566666666666667`.
- Macro, S03 / Consumer Electronics, Radar, `APPLE_CHAIN`, and AAPL surfacing
  have explicit accepted-Claim lineage. Research Manager v7 binds the Chain
  Claim to AAPL SEC evidence without adding a new unsupported fact.
- Phase4B: State `research_state_a8b18be86d3e5add55cde272`, Episode
  `research_episode_b65bf2ab2fed387908e6307c`, and Attribution
  `research_attribution_c8a13a9db7be137531b8668c`. Memory is `EMPTY_VALID`.
- Phase4C: seven Selection and seven Timing observations, Candidate
  `opportunity_af4bd9f287b760bcf0324625`, transition
  `research_state_transition_19625e191276555b1d5f0cdd`, and Handoff
  `research_quant_handoff_c325aedcb141007a2bda4bd0`. Timing remains honestly
  `MISSING_INPUT`; external JSON consumption passes.
- Final Gate A: `751 passed, 5 deselected`; leakage: `8 passed, 748
  deselected`; Ruff, mypy (`344 source files`), Black, and diff check pass.
