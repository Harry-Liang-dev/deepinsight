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
