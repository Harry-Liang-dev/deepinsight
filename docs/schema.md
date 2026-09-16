# Domain Schema

## Phase 4C Research-to-Quant architecture contract

Day44 defined the ownership and vocabulary boundary. Day45–47 added typed
Satellite observations, Research qualification, and State-transition
descriptors. Day48 implements the final reference-only handoff and canonical
JSON/JSONL export; it does not add a table, endpoint, or Quant runtime.

```text
Raw Evidence
→ Validated Claim
→ Research State Feature
→ Satellite Alpha Observation
→ ResearchQuantHandoffBundle
→ future deepinsight-quant
→ Processed Factor Exposure
→ Alpha Signal
→ Strategy
→ Portfolio
```

The first five objects are Research-side concepts and are implemented through
Day48. Future Research-side objects must preserve stable Asset identity,
`research_as_of`, point-in-time lineage, source Claim/Feature references,
version metadata, data quality, and explicit missingness. They must not carry
Quant ranks, normalized/neutralized/z-score exposures, IC statistics,
buy/sell scores, position weights, orders, or execution instructions.

`Planetary Alpha`（行星阿尔法）is Quant-owned traditional Alpha computed over
an independent, broad Base PIT Market Universe. `Satellite Alpha`（卫星阿尔法）
is a Research-produced descriptor intended for future `SELECTION`, `TIMING`,
or `BOTH` processing. A Research Candidate Universe is a sparse expensive-
research subset and cannot serve as the Factor validation universe.

Prefer attributable structured components such as business-binding depth,
revenue exposure, earnings-increment potential, Evidence quality, catalyst
quality, risk burden, Sector/Chain alignment, expectation revision, or thesis
transition. A single opaque `AI_STOCK_SCORE` or `chain_benefit_score` is not an
accepted Research handoff design. Categorical states may remain categorical;
future Quant owns any versioned numeric mapping.

The existing nullable `p2_*` database fields and reserved phase-two interfaces
are legacy compatibility placeholders. They remain unread and non-operational
in this repository and do not define the future handoff schema. Existing
ResearchState, Episode, Attribution, Dataset, Temporal, and Golden Replay
schemas retain their identities unchanged.

This document describes cross-module contracts and their persistence
boundaries. Pydantic models and Protocol interfaces perform no I/O themselves;
the later sections identify the Repositories and services that implement
DuckDB and FAISS storage.

## Shared conventions

- Models use Pydantic v2 and reject unknown fields.
- Dates use `date`; event and ingestion times use `datetime`.
- JSON metadata uses recursive JSON-compatible types rather than `Any`.
- Phase Two reserved fields remain nullable and are not interpreted.
- Module implementations depend on Protocol interfaces and domain contracts.

## Canonical security identity

`AssetId` is a Pydantic root model with these accepted formats:

| Market | Format | Example |
|---|---|---|
| A-share | `CN:<six digits>.<SH or SZ>` | `CN:600519.SH` |
| Hong Kong | `HK:<four or five digits>.HK` | `HK:0700.HK` |
| US | `US:<uppercase ticker>` | `US:AAPL` |

Asset normalization from provider-specific symbols is outside the domain model
task. The model validates canonical values only. The Data Ingestion module now
owns this conversion through `AssetIdentifierNormalizer`; ambiguous bare CN
symbols require an explicit exchange rather than inferring one.

## Central enumerations

| Enum | Values |
|---|---|
| `Market` | `CN`, `HK`, `US` |
| `MarketScope` | `CN`, `HK`, `US`, `GLOBAL`, `MIXED` |
| `ReportMarketScope` | `CN`, `HK`, `US`, `MIXED` |
| `MemoryLevel` | `L0` through `L4` |
| `ReportType` | `single_asset`, `market_daily`, `watchlist`, `macro_weekly` |
| `DocumentType` | `filing`, `news`, `research`, `macro`, `social`, `policy` |
| `AgentStatus` | `ok`, `error` |
| `TaskStatus` | `queued`, `running`, `completed`, `failed` |
| `IngestionJobType` | `full`, `incremental`, `repair` |
| `EventSeverity` | `low`, `medium`, `high`, `critical` |
| `SectorId` | Stable `S01` through `S18` Sector Ontology v1 IDs |
| `SectorMembershipRole` | `core`, `upstream`, `downstream`, `supplier`, `customer`, `competitor`, `beneficiary` |
| `ResearchScopeType` | `global`, `macro`, `sector`, `industry_chain`, `asset`, `research_episode` |
| `SectorEdgeType` | `belongs_to`, `supplies`, `customer_of`, `competes_with`, `benefits_from`, `exposed_to`, `drives` |
| `MacroCycleDirection` | `rising`, `falling`, `stable`, `mixed`, `unknown` |
| `SectorAnomalyType` | `price_volume`, `breadth`, `earnings`, `news_event`, `macro_shock`, `supply_chain_propagation` |
| `AnomalyDirection` | `positive`, `negative`, `mixed`, `unknown` |
| `SectorAnomalyStatus` | `detected`, `propagation_candidate` |

`AgentName` contains the four analyst and four manager names declared in
MASTER_SPEC.

## Data records

| Contract | Purpose |
|---|---|
| `RawDataRecord` | Provider payload plus source, scope, object type, and receive time |
| `InstrumentRecord` | Canonical security master record |
| `EodBarRecord` | End-of-day price and volume observation |
| `FundamentalRecord` | Issuer fundamental observation |
| `MacroObservationRecord` | Regional or global macro series observation |
| `CorporateEventRecord` | Issuer or market event |
| `TextDocumentRecord` | Canonical document metadata |
| `DocumentChunkRecord` | Chunk text and FAISS vector mapping metadata |
| `RetrievedDocument` | Evidence chunk supplied to an agent |
| `SourceReference` | Document, chunk, provider, or URL citation |

Instrument, event, and document models validate that an optional asset belongs
to the declared market.

## Memory contracts

- `MemoryWriteRequest`
- `MemoryWriteResult`
- `MemorySearchRequest`
- `MemorySearchResult`
- `MemorySearchResponse`

Importance values are constrained to `[0, 1]`. Similarity score is a plain
float because MASTER_SPEC does not define a normalized score range. Every
Memory write requires a `SourceReference`; search results return that source,
the Memory type, importance score, and creator so callers can cite evidence
without reconstructing or inventing attribution. Searches may additionally
filter canonical `asset_ids`.

## Memory and vector boundary

`MemoryService` maps each `MemoryLevel` to exactly one persistent namespace:

| Level | FAISS namespace |
|---|---|
| `L0` | `memory_L0_v1` |
| `L1` | `memory_L1_v1` |
| `L2` | `memory_L2_v1` |
| `L3` | `memory_L3_v1` |
| `L4` | `memory_L4_v1` |

The namespace key inside a Memory record remains a separate exact-match
isolation boundary. It can identify a market, asset, report, or research task.
FAISS implementation objects never cross `FaissVectorRepository`; upper
layers receive only validated vector IDs and similarity candidates.

Each namespace directory contains `index.faiss`, `vector_meta.parquet`, and
`manifest.json`. The manifest records namespace, embedding model and
dimension, cosine distance, authoritative source table, `IndexFlatIP`, and
creation time. Dense vectors are normalized before insertion and query, so
inner product implements cosine similarity. DuckDB remains authoritative for
Memory text, source, creator, times, importance, and filters.

`EmbeddingService` is the replaceable text-to-vector interface.
`OpenAIEmbeddingService` is the configured production adapter and
`FakeEmbeddingService` is deterministic and offline. `DocumentEmbeddingService`
advances existing document chunks from `embedding_status = pending` to
`indexed` only after the matching vector is persisted.

## Learning Memory metadata v1

Day40 extends, rather than replaces, the existing Memory record. The optional
`LearningMemoryMetadata` is stored by the DuckDB Repository and returned by
both Memory search boundaries. FAISS receives no Scope, Episode, lifecycle, or
temporal implementation object.

The independent dimensions are:

| Dimension | Values or meaning |
|---|---|
| Memory level | Existing L0–L4 only |
| Research Scope | GLOBAL, MACRO, SECTOR, INDUSTRY_CHAIN, ASSET, RESEARCH_EPISODE |
| Usage class | EPISODIC, SEMANTIC, PERFORMANCE |
| Semantic lifecycle | CANDIDATE, VALIDATED, RETIRED |
| Episodic content | validated Claim, thesis, risk, catalyst, important Event, State reference, Episode reference |

Structured metadata contains `scope_type`, `scope_id`, optional
`parent_scope_id`, `episode_id`, `research_state_id`, source Claim/Event IDs,
Day37 `TemporalMetadata`, `memory_version`, and only reference fields for a
future Outcome/Factor/research artifact. EPISODIC records require Episode and
State linkage. A Semantic record linked to one Episode may only be CANDIDATE;
there is no automatic promotion to durable truth. PERFORMANCE contains no
computed return, label, reward, or fabricated Outcome.

`MemoryWriteRequest.metadata` is optional for backward compatibility. New
structured writes require `namespace_key == scope_id`; ASSET scope also
requires the canonical `asset_id`. `memory_items.metadata_json` is added by an
idempotent migration. Existing null rows and Day35 JSON-header summaries remain
readable without inferred metadata.

`MemorySearchRequest` may filter `scope_ids`, usage classes, Episode IDs, and
an optional historical `as_of`. `ResearchContextRequest` additionally supports
Scope-type filtering. Both retrieval paths call Unified Temporal Contract v1;
the effective time, persisted creation time, and structured availability must
all be visible at the cutoff. Context results retain metadata, source,
effective/available time, retrieval score and retrieval reason. A zero-result
bundle sets `no_relevant_memory = true` and `empty_valid = true`; no historical
analogy is generated from similarity alone.

## Research Context Attribution v1

Day41 adds one Episode-scoped attribution family for Memory, accepted Sector
Claims, and Radar Events. It does not change L0–L4, Research Scope, the
Day36 Agent pipeline, or ResearchEpisode identity.

`ResearchContextAttribution` records `provided`, `selected`, and `used`
separately. Selected context must have been provided; used context must have
been selected. Only an explicit structured reference from an accepted Claim
sets `used = true` and populates `used_by_claim_ids`. A reference from a
rejected Claim is retained in `rejected_by_claim_ids` but leaves `used =
false`. Every entry retains role/run, Episode/cutoff, Scope, temporal metadata,
and canonical source references. Memory entries additionally retain retrieval
ID, rank, score, and reason.

`MemoryRetrievalRecord` records one query and purpose for one Agent run:

- PIT-eligible candidate and selected Memory IDs;
- contiguous relevance rank, score, reason, Scope, source, and effective /
  available times;
- namespace, L0–L4, Scope, usage, Episode, asset, market, and importance
  filters;
- vector snapshot identity and future-exclusion count; and
- `empty_valid = true` when and only when no Memory was selected.

Candidates enter the record only after Day37 Unified Temporal Contract and
DuckDB metadata filters. FAISS implementation objects remain private. Day36
`SectorContextUsageDiagnostic` is adapted rather than replaced. A historical
PARTIAL Episode whose accepted Claim IDs were not persisted may retain its
known used state with `claim_link_status = not_available_at_source_run`; it
must not invent `used_by_claim_ids`.

`ResearchEpisodeAttribution` is a deterministic immutable JSON artifact tied
to one Episode and cutoff. Outcome and future usefulness states are limited to
`PENDING` / `NOT_AVAILABLE`; `future_usefulness_score` is null in Day41.

## Sector Ontology and hierarchical research scope

`SectorOntology` v1 fixes exactly 18 first-level research Sectors (`S01`–`S18`).
An `IndustryChainDefinition` is a dynamic, versioned object belonging to one
Sector. `SectorMembership` maps an `AssetId` to a Sector, zero or more chains,
and an economic role with weight, confidence, source, and validity interval.

All ontology intervals use `[valid_from, valid_to)` semantics: the start is
inclusive and an optional end is exclusive. New membership revisions append
rows and never overwrite prior periods. Point-in-time reads require
`valid_from <= as_of < valid_to`, with a null end representing an open interval.

`ResearchScopeDefinition` establishes the independent research hierarchy:

```text
GLOBAL → MACRO → SECTOR → INDUSTRY_CHAIN → ASSET → RESEARCH_EPISODE
```

An Asset scope may attach directly to a Sector when no chain is appropriate.
The hierarchy requires one GLOBAL root, existing parents, valid parent-child
types, contained validity intervals, and no cycles. This scope does not replace
Memory L0–L4 or the existing per-request Agent `ResearchScopeV1`.

The minimal DuckDB knowledge graph stores typed `SectorNode` and `SectorEdge`
contracts. It provides versioned relationship rows only; no graph database or
complex graph algorithm is introduced.

`SectorUniverseSnapshot` materializes one Sector's immutable research universe
at an `as_of` date. It records sorted canonical assets, only market-validated
optional benchmark assets, the membership version, source, deterministic
coverage diagnostics, and quality. Its content-derived `snapshot_id` and an
append-only Repository prevent future membership changes from rewriting an
old snapshot.

`SectorBenchmarkCandidate` is configuration, not Evidence that an ETF exists.
Only a real price observation promotes a candidate to a temporal
`SectorBenchmarkMapping`; an unvalidated or unavailable candidate is stored as
MISSING and never enters a snapshot.

`SectorResearchSnapshot v1` is the deterministic state derived from one
`SectorUniverseSnapshot`. It contains `SectorMarketState`,
`SectorBreadthState`, `SectorFundamentalState`, and `SectorValuationState`.
Every `CoveredSectorMetric` includes its value, `coverage_count`,
`universe_count`, and AVAILABLE/PARTIAL/MISSING status. Cross-sectional
aggregates require at least two valid constituents; otherwise the value stays
null and the metric is PARTIAL rather than presenting a single issuer as a
Sector statistic.

Sector return, volatility, drawdown, fundamental, and valuation aggregates use
the constituent median. Breadth ratios use only valid constituent inputs;
return dispersion uses sample standard deviation. The two excess-return fields
use a 20-session horizon against SPY and the first validated Sector benchmark.
The operator rejects observations after `as_of`, uses FMP standardized records
as the canonical ratio source, and never invokes an LLM.

`SectorMacroSnapshot` adds the deterministic Macro-to-Sector projection
without defining a market Regime. Its `SectorCycleState` contains rates,
inflation, labor, growth, and financial-stress dimensions. Each dimension
retains its underlying series signals, current value, three- and twelve-month
reference values, coverage, direction, as-of date, and source lineage.

`MacroSensitivity` aligns monthly benchmark returns with monthly macro
changes. It stores one independent `MacroSensitivityEstimate` per FRED series:
OLS beta, Pearson correlation, observation count, required count, rolling
window, status, and source ID. The v1 window is 36 months with a minimum of 24
aligned observations. CPI, core PCE, payrolls, industrial production, and GDP
use year-over-year changes; other series use level changes. Missing or short
history produces PARTIAL/MISSING output and never an extrapolated coefficient.
The operator rejects future prices, observations, vintages, and ingestion
timestamps.

`SectorAnomalyEvent` is the authoritative Day34 Radar event. It stores its
deterministic anomaly type, Sector and Industry Chain identities, source and
candidate affected assets, direction, severity, confidence, five explicit
timestamps, canonical Evidence IDs, summary, optional propagation hypothesis,
status, and ruleset version. Validation requires timezone-aware timestamps and
enforces `event_time <= available_at`, `published_at <= available_at`,
`available_at <= as_of`, and `ingested_at <= as_of`.

Radar rules are deterministic: trailing price-return z-score and volume ratio,
Sector breadth divergence/dispersion, attributable structured earnings
surprise, material event/news classification, Day33 macro-change plus
sensitivity thresholds, and effective Day30 membership/graph traversal.
Propagation output is explicitly a candidate and keeps direction UNKNOWN when
the graph establishes exposure but not impact. It is not an Agent, Regime,
Factor, or investment recommendation.

`sector_anomaly_events` stores one immutable canonical body.
`sector_anomaly_scopes` links that event ID to existing SECTOR, CHAIN, and
source-ASSET scopes without duplicating structured content. The Memory
projection uses existing L1/L2 namespaces, one identical summary per linked
scope, and an attributable `SourceReference`; no Radar-specific Memory level
or hierarchy exists.

## Sector research Agent contracts

`SectorResearchInput v1` is the Day35 point-in-time composition contract. It
requires one UTC `research_as_of` shared by the Sector universe/state, Macro
snapshot, Radar events, and `ResearchContextBundle`. Industry Chain,
membership, node, edge, benchmark, Event, and Memory revisions must already be
effective at that cutoff. The contract composes existing Day30-Day34 models;
it does not define a second temporal validator or persistence schema.

`SectorResearchEvidence` is a compact projection over direct upstream objects.
Each entry reuses `RoleEvidenceManifestEntry` and adds only interpretation
constraints: Evidence kind, availability status, Chain/Event lineage,
historical-association-only, propagation-candidate-only, and explicit
degradation requirements. Only exact manifest IDs are citable.

`SectorResearchOutput v1` is claim-first:

| Field | Meaning |
|---|---|
| `claims` | Authoritative accepted `ValidatedClaim` collection with Sector category and direct Evidence IDs |
| `cycle_assessment` | Interpretive Sector phase, confidence, uncertainty, and accepted supporting Claim IDs |
| `uncertainties` / `missing_data` | Explicit PARTIAL, proxy, missing Radar/Memory, or other coverage limits |
| `rejected_claims` | Invalid producer output retained only for audit and excluded from downstream facts |
| `evidence_manifest` | Exact invocation-local direct-upstream citation namespace |
| `model_version` / `prompt_version` | Reproducible inference identities |

The Sector phase enum is `accelerating`, `expanding`, `mature`, `slowing`,
`contracting`, `recovering`, or `uncertain`. It is an Evidence-backed research
interpretation, not `MacroCycleDirection`, Market Regime, Factor, or trading
signal. Numeric literals are extracted from final Claim text by Python and
must occur exactly in at least one bound Evidence entry. The LLM cannot
calculate ratios, percentages, unit conversions, dates, aggregates, or rounded
values.

`SectorResearchAgent` remains outside `AgentName`; that enum continues to
contain exactly the four Phase 3 analysts and four managers.

## Sector-to-asset context contracts

Day36 adds `SectorContextBundle v1` without adding a persistence table. The
bundle binds one asset and UTC `research_as_of` to an effective temporal
membership, one primary Sector, active Industry Chains, the accepted
`SectorResearchOutput` Claim collection, its cycle assessment, aligned Sector
and Macro snapshot IDs, and compact Radar Event references. Event references
are valid only when an accepted Sector Claim carries the corresponding
`event:<event_id>` Evidence ID. Future events and identity/time mismatches are
rejected.

`SectorRoleContext v1` is a least-privilege projection. The four Analysts see
only relevant presentation context and keep their existing role-local asset
Evidence contract. Research/Bull/Bear/Risk receive relevant accepted Sector
Claims in the existing `validated_claims` shape and may cite their Claim IDs as
direct upstream. Recursive lineage remains:

```text
Asset Manager Claim
→ Sector Claim
→ Sector state or Radar Evidence
→ canonical Provider source
```

`SectorContextUsageDiagnostic` records only context ID, role, provided/used
Claim and Event IDs, and serialized projection size. It is not a trajectory,
reward, Factor, Regime, or new Memory model. No Sector context is a valid
empty/degraded state; the asset workflow then retains the Phase 3 behavior.

## Unified Temporal Contract v1

Day37 introduces `TemporalMetadata` as a compatibility contract over existing
Data, Sector, Event, Claim, and Memory fields. It does not rename Provider
schemas or create a historical dataset. Nullable fields have distinct meaning:

| Field | Meaning |
|---|---|
| `event_time` | When the underlying event happened; not proof that research knew it |
| `period_start` / `period_end` | Economic, accounting, or observation period; not publication time |
| `published_at` | When the source published or accepted the item |
| `available_at` | Earliest canonical time the item can be considered available to research |
| `ingested_at` | When DeepInsight acquired the item; it cannot precede actual system use |
| `effective_from` / `effective_to` | Inclusive start and exclusive end of a membership or validity interval |
| `as_of` | Cutoff used to produce a snapshot, Claim collection, or research context |

`validate_temporal_access(metadata, research_as_of)` is the shared hard
boundary. All datetimes must be timezone-aware and are normalized to UTC.
Historical replay mode requires every present availability, ingestion, and
snapshot time to be no later than `research_as_of`; effective intervals use
`effective_from <= research_as_of < effective_to`. Event or fiscal-period time
alone never makes a record usable.

Live acquisition mode freezes the exact information cutoff before retrieval.
It still requires source `available_at` and snapshot time to be no later than
the cutoff, while `ingested_at` may record the later HTTP/persistence execution
time. This does not admit information published during the run. Date-mode CLIs
retain legacy UTC-end-of-day semantics; instant-mode CLIs preserve the exact
aware instant. `market_session_date` is a provider projection, never an alias
for `research_as_of`.

Provider-native time is authoritative at the ingestion boundary. Every source
timestamp is interpreted and validated using the Provider's native timezone,
calendar, and precision before it is normalized onto the canonical UTC
timeline. This projection is source-specific and must be explicit and
deterministic: a Provider-local date never replaces global `research_as_of`,
and its UTC calendar date must not be blindly reused as the Provider's local
date semantic. Date-level source metadata remains date precision; conversion
must not fabricate second-level availability.

Current compatibility mappings are:

- SEC/FMP fundamentals: period end plus accepted/filing availability and
  separate ingestion lineage.
- Alpaca daily bars: trade period plus completed US-session availability and
  separate ingestion lineage; ingestion before trade date remains invalid.
- Alpaca News and community evidence: publication availability plus separate
  ingestion lineage.
- FRED/ALFRED: observation period plus `realtime_start` vintage availability
  and separate ingestion lineage.
- Sector membership: existing half-open `valid_from`/`valid_to`.
- Sector anomaly: event, publication, availability, ingestion, and snapshot.
- Sector accepted Claims: visibility inherits the producing
  `SectorResearchOutput.research_as_of`.
- Memory: effective time plus persisted creation/availability and optional
  expiry; backdating `effective_ts` cannot make a later-created item visible.
- ResearchDataBundle and ResearchContextBundle: each projected item is checked
  again at the shared bundle cutoff.

DuckDB legacy `TIMESTAMP` values are timezone-naive. Only persistence-facing
`utc_from_storage()` may attach their documented UTC meaning. Public contracts
reject naive datetimes and never assume the host's local timezone.

## LLM contracts

- `LLMRequest`
- `LLMUsage`
- `LLMResponse`

These models are provider-independent. They do not invoke OpenAI or define
retry and caching behavior.

## Agent and manager contracts

- `AgentContext`
- `AgentRequest`
- `FundamentalAnalysis`
- `FundamentalAnalystResponse`
- `AnalystAnalysis`
- `AnalystResponse`
- `ResearchManagerRequest`
- `ResearchSummary`
- `ResearchManagerResponse`
- `BullManagerRequest` / `BullManagerResponse`
- `BearManagerRequest` / `BearManagerResponse`
- `RiskManagerRequest` / `RiskManagerResponse`

All scores explicitly defined by MASTER_SPEC are constrained to `[0, 1]`.
The Agent execution layer adds the following strict wrappers without changing
the role-specific domain payloads:

- `PromptTemplate`
- `AgentInvocation`
- `EvidenceLink`
- `AgentExecutionResult`
- `ResearchTaskRequest`
- `ResearchTaskResult`

`AgentInvocation` carries one role payload, model, optional report identity,
and optional public Memory query. `AgentExecutionResult` always contains either
a validated role output or a stable error. Every accepted claim is linked by
JSON path to citations that were present in the input document chunks or
Memory source references. Missing data and uncertainty remain separate fields.
`ResearchTaskResult` retains successful and failed roles when the fixed Agent
chain degrades.

## Report contracts

- `GenerateReportRequest`
- `ReportSection`
- `ResearchReport`
- `TaskStatusResponse`
- `ErrorInfo`

The final report contains Markdown, JSON, ordered sections, citations, status,
and Phase Two reserved nullable fields. It does not contain an order, position,
portfolio, backtest result, or executable trading signal.

## Module Protocols

| Protocol | Boundary |
|---|---|
| `ProviderAdapterProtocol` | Instruments, EOD bars, documents, health metadata |
| `MemoryServiceProtocol` | Memory write and search |
| `LLMGatewayProtocol` | Structured LLM request and response |
| `AgentProtocol` | Generic typed agent execution |
| `ReportPipelineProtocol` | Research request to final report |

Protocols contain no implementation and perform no I/O.

## Data ingestion boundary

`BaseProviderAdapter` is the concrete ingestion contract. Its four methods
return the stable adapter vocabulary for instruments, EOD bars, and documents.
Provider SDK response objects and provider-specific field names are converted
inside adapters and are never exposed to Repositories or upper layers.

`DataNormalizer` converts adapter records into `InstrumentRecord`,
`EodBarRecord`, and `TextDocumentRecord`. Pydantic validation is supplemented
with finite/non-negative numeric checks and OHLC consistency checks. Optional
missing values stay null; missing required values fail the ingestion job.

`DocumentChunker` uses explicitly configured character windows and overlap.
Chunk IDs, indexes, and reserved vector IDs are deterministic. Because Data
Ingestion does not generate embeddings, each chunk stores
`metadata_json.embedding_status = "pending"` and leaves `token_count` null.
The target embedding model, dimension, and namespace must be supplied to the
chunker; they are not hard-coded by the ingestion service.

`DataIngestionService` persists records through existing Repositories and
records every run in `ingestion_jobs`. Its row count includes instruments,
bars, documents, and chunks actually committed. A later stream failure leaves
an explicit failed job with the committed row count rather than an ambiguous
job state.

## Minimum-design assumptions

MASTER_SPEC leaves the following fields incomplete. Phase One models use the
smallest contract needed to connect modules:

- Hong Kong canonical identifiers accept four or five digits.
- US tickers accept uppercase letters, digits, dot, and hyphen after the first
  letter.
- All Analyst analyses expose direct evidence observations as `facts` and
  interpretations as `key_points`; both require claim-level citations.
- Technical Text, Sentiment, and News Event analysts otherwise share only
  risks, uncertainties, and citations until their exact schemas are confirmed.
- Research Manager exposes summary points, conflicts, uncertainties, and
  citations until its exact output schema is confirmed.
- `final_recommendation` and `confidence_band` remain narrative strings; no
  trading taxonomy is inferred.
- `report_json` and provider metadata remain typed JSON objects until their
  exact nested schemas are confirmed.
- A request may carry multiple `asset_ids`, but this layer does not decide
  whether that produces one or multiple reports.
- `LLMGatewayProtocol.invoke_json` accepts one typed `LLMRequest` and returns
  one typed `LLMResponse`; provider SDK argument expansion belongs to the later
  gateway implementation.

## DuckDB persistence schema

DuckDB is the Phase One structured source of truth. The executable,
idempotent DDL is owned by `src/repositories/schema.py`; it is kept separate
from the cross-module Pydantic contracts described above.

| Table | Primary key | Purpose |
|---|---|---|
| `instruments` | `asset_id` | Canonical security master |
| `source_registry` | `source_id` | Credential-free provider metadata |
| `eod_bars` | `asset_id`, `trade_date` | End-of-day price observations |
| `fundamentals` | `asset_id`, `fiscal_period_end`, `report_type` | Fundamental observations |
| `macro_series` | `series_key`, `observation_date` | Macroeconomic observations |
| `corporate_events` | `event_id` | Issuer and market events |
| `text_documents` | `document_id` | Document metadata |
| `document_chunks` | `chunk_id` | Chunk text and FAISS sidecar identifiers |
| `memory_items` | `memory_id` | L0–L4 Memory, optional Learning metadata, and FAISS sidecar identifiers |
| `agent_runs` | `run_id` | Reproducible Agent invocation records |
| `reports` | `report_id` | Final report artifacts |
| `report_sections` | `report_id`, `section_name` | Ordered report sections |
| `llm_cache` | `cache_key` | Structured LLM response cache |
| `ingestion_jobs` | `job_id` | Ingestion lifecycle records |
| `report_jobs` | `job_id` | Durable report request, lifecycle, safe error, and report reference |
| `sector_nodes` | `node_id`, `version`, `valid_from` | Versioned Sector, Industry Chain, and Asset graph nodes |
| `sector_edges` | `edge_id`, `version`, `valid_from` | Versioned directed Sector graph relationships |
| `sector_memberships` | `asset_id`, `sector_id`, `role`, `valid_from`, `version` | Point-in-time asset classification and chain roles |
| `research_scopes` | `scope_id`, `version`, `valid_from` | Unified hierarchical research scopes |
| `phase2_registry` | `module_name` | Disabled Phase Two extension registry |

`fundamentals` retains raw SEC Company Facts including total/current assets,
total/current liabilities, consolidated debt, equity, cash flow, EPS, and
shares where published. Growth, margins, ratios, and valuation are derived
Evidence with parent IDs; they are not silently persisted as Provider facts.
Alpaca OHLC coverage metadata records `adjustment=raw|all|...` so adjusted and
raw research series remain distinguishable.

The following indexes are initialized:

- `idx_eod_bars_asset_date`
- `idx_fundamentals_asset_period`
- `idx_macro_series_key_date`
- `idx_corporate_events_asset_date`
- `idx_text_documents_asset_publish`
- `idx_memory_items_level_namespace_ts`
- `idx_memory_items_faiss_mapping` (unique namespace/vector mapping)
- `idx_agent_runs_report_agent`
- `idx_reports_date_market`
- `idx_report_jobs_status_created`
- `idx_sector_nodes_type_time`
- `idx_sector_edges_source_target`
- `idx_sector_memberships_asset_time`
- `idx_research_scopes_parent`

DuckDB FTS is not enabled in Phase One database bootstrap.

## Persistence boundary

Application modules do not execute SQL. They pass validated values to explicit
Repository classes:

| Domain or persistence input | Repository | DuckDB table |
|---|---|---|
| `InstrumentRecord` | `InstrumentRepository` | `instruments` |
| `SourceRegistryRecord` | `SourceRegistryRepository` | `source_registry` |
| `EodBarRecord`, `FundamentalRecord`, `MacroObservationRecord`, `CorporateEventRecord` | `MarketDataRepository` | structured market tables |
| `TextDocumentRecord`, `DocumentChunkRecord` | `DocumentRepository` | document tables |
| `MemoryItemRecord` | `MemoryItemRepository` | `memory_items` |
| `AgentRunRecord` | `AgentRunRepository` | `agent_runs` |
| `ResearchReport`, `ReportSection` | `ReportRepository` | report tables |
| `LLMCacheRecord` | `LLMCacheRepository` | `llm_cache` |
| `IngestionJobRecord` | `IngestionJobRepository` | `ingestion_jobs` |
| `ReportJobRecord` | `ReportJobRepository` | `report_jobs` |
| `EvaluationResult` | `EvaluationRepository` | `report_evaluations` |
| `SectorNode`, `SectorEdge`, `SectorMembership`, `ResearchScopeDefinition` | `SectorOntologyRepository` | `sector_nodes`, `sector_edges`, `sector_memberships`, `research_scopes` |
| `SectorBenchmarkMapping`, `SectorUniverseSnapshot` | `SectorOntologyRepository` | `sector_benchmark_mappings`, `sector_universe_snapshots` |
| `SectorResearchSnapshot` | `SectorOntologyRepository` | `sector_research_snapshots` |
| `SectorMacroSnapshot` | `SectorOntologyRepository` | `sector_macro_snapshots` |
| `SectorAnomalyEvent` | `SectorOntologyRepository` | `sector_anomaly_events`, `sector_anomaly_scopes` |

Repository-owned persistence records live under `src/repositories/` and are
not cross-module business contracts. Repository mapping converts `AssetId`,
enums, and JSON values to DuckDB scalar columns and back. Phase Two columns are
created exactly as specified but remain null and are not parsed or returned as
operational inputs.

Report and section writes share one transaction. Other Repository writes use
the same explicit commit-or-rollback boundary. Connections are scoped to an
operation and are never opened during module import.

## Standard single-asset report

The Phase One report generator accepts one completed, structured
`ResearchTaskResult` and does not invoke an Agent, LLM, Provider, DuckDB, or
FAISS directly. The only implemented report shape is `single_asset`.

The standard report requires each section exactly once, in this order:

1. `executive_view`
2. `macro_context`
3. `fundamentals`
4. `technical_text`
5. `sentiment`
6. `news_events`
7. `bull_case`
8. `bear_case`
9. `risk_review`
10. `final_synthesis`

Every JSON section uses the same epistemic structure:

| Field | Meaning |
|---|---|
| `facts` | Attributable evidence supplied in the Agent context |
| `inferences` | Evidence-linked Analyst or Manager conclusions |
| `risk_warnings` | Evidence-linked conflicts, invalidators, and risks |
| `uncertainties` | Explicit limits or missing evidence; citations are not invented |

Each fact, inference, and risk warning contains text plus one or more
`SourceReference` objects. References must already exist in the supplied
document or Memory context. They are deduplicated by document, excerpt,
provider, and source URL while preserving first occurrence order.

`report_json` stores the ten section objects by section name. `report_markdown`
is rendered from those same objects, so the two formats cannot diverge through
separate assembly logic. `ReportSection.citations` contains the deduplicated
references used by that section, and `ResearchReport.source_trace` contains
the ordered report-wide union.

The report is first persisted with `running` status. It becomes `completed`
only after its attributable L3 report-trace Memory write succeeds.

## Integration read models

The end-to-end application workflow adds no table, column, or index.
`MarketDataRepository.list_eod_bars` and `list_fundamentals` read normalized
feature inputs by canonical asset and inclusive report date.
`DocumentRepository.list_documents` reads attributable asset documents
available through that date; ordered chunks remain available through
`list_chunks`.

These methods return existing domain records and keep SQL inside Repository
classes. The workflow never introduces a database model into Agent, Memory,
report, or API contracts.

## Report evaluation

The first Phase Two storage addition is `report_evaluations`:

| Column | Meaning |
|---|---|
| `evaluation_id` | Immutable evaluation primary key |
| `report_id` | Evaluated report identifier |
| `ruleset_version` | Exact versioned scoring rules |
| `judge_model` | Judge model or explicit Fake identifier |
| `input_fingerprint` | SHA-256 of report, evidence, missing-data inputs, rules, and model |
| `overall_score` | Weighted twelve-dimension score in `[0, 1]` |
| `deterministic_score` | Score derived only from deterministic checks |
| `judge_score` | Score derived only from LLM Judge checks |
| `result_json` | Complete validated `EvaluationResult` audit object |
| `created_at` | Evaluation instant normalized to UTC before DuckDB storage |

`idx_report_evaluations_report_created` locates historical evaluations by
report and creation time. A duplicate evaluation ID fails rather than
overwriting prior audit evidence.

The result JSON retains eight deterministic checks, six Judge checks, and
twelve unique dimension results. Every check and dimension includes a reason,
evidence locator, score, and pass state. Repository reads compare the
duplicated audit columns with the JSON result and fail if either representation
is invalid or inconsistent.

## ResearchStateSnapshot v1

`ResearchStateSnapshot` is the second formal research artifact after the human
report. It is an immutable, versioned, machine-facing view of what was legally
knowable at one `research_as_of`. It is built only from frozen structured
artifacts; the builder has no LLM, Provider, Report, or live database boundary.

The hierarchy is explicit:

```text
MACRO scope → SECTOR scope → INDUSTRY_CHAIN scope → ASSET scope
```

The v1 sections are identity, macro, Sector, Industry Chain, fundamental,
valuation, technical, sentiment, event, market context, debate, risk, thesis,
data quality, and Memory context. Every section is `present`, `partial`,
`missing`, or `not_available_at_source_run`. The last value prevents newer
Sector or Memory data from being backfilled into an older source run.

`ResearchStateFeature` has three closed feature families:

| Type | Source rule |
|---|---|
| `deterministic_numeric` | Existing canonical/derived Evidence; the builder performs no financial calculation |
| `normalized_research_state` | An explicit transform name and version plus Claim/Evidence references |
| `semantic_categorical` | Accepted Claim or attributable artifact identity |

Feature provenance stores only Claim, Evidence, and artifact IDs. Prompt,
model, dataset, source run, data snapshot, Sector context, Memory snapshot, and
input fingerprint versions are centralized in `ResearchStateLineage` rather
than repeated in each feature. Manager/Bull/Bear/Risk features reference their
accepted Claim ID; recursive Claim validation closes at Analyst or Sector
Evidence.

All feature and context times reuse Unified Temporal Contract v1. A future
feature, Sector context with a different cutoff, Memory context with a
different cutoff, unknown upstream Claim, open direct-Evidence root, or Claim
cycle rejects the build. UTC-aware timestamps are mandatory.

The offline materializer is:

```bash
python -m scripts.build_research_state --bundle <bundle.json> \
  --source-run-id <run-id> --output <research-state.json>
```

Optional `--agent-db` reads structured accepted Claims from the frozen
`agent_runs` table; optional `--sector-context` reads a frozen
`SectorContextBundle`. Neither option parses report Markdown/JSON prose.

## ResearchEpisode v1

`ResearchEpisode` is the immutable process artifact paired with, but distinct
from, `ResearchStateSnapshot`. State answers what was legally knowable at a
cutoff; Episode answers which frozen inputs, Agent executions, structured
outputs, accepted/rejected Claims, Sector usage, versions, and result
identities formed one actual research process.

```text
ResearchStateSnapshot
  + AgentExecutionTrace[]
  + SectorContextUsageDiagnostic[]
  + result/version references
  -> ResearchEpisode
```

An `AgentExecutionTrace` retains only role, run ID, input-context IDs,
provided/output/accepted/rejected Claim IDs, counts, latency when the source
run persisted it, Provider/model/Prompt versions, and status. The Episode does
not store prompts, model-private reasoning, chain-of-thought, or copied report
prose. Day36 Sector diagnostics are reused through the same
`SectorContextUsageDiagnostic` contract rather than duplicated.

Episode trace quality is explicit. `complete` requires every accepted and
rejected Claim identity to match its count. `partial` preserves known counts
and references while naming each unavailable historical identity; it never
creates synthetic accepted Claim IDs. The complete Phase 3 Golden run and the
historically partial Day36 Sector-aware run therefore remain truthful under
one schema.

Episode identity is a SHA-256 fingerprint of its typed frozen inputs. The
builder is pure: it has no LLM, Provider, live Repository, report parser,
Outcome, Reward, Factor, Regime, Backtest, or trading dependency. Future
Outcome records must reference `episode_id` without mutating the Episode.

## Point-in-Time Research Dataset v1

`ResearchDatasetSample` is a compact, immutable index for one Asset research
run at one `research_as_of`. It does not copy ResearchState, Claims, Evidence,
Memory, Report, or SectorContext payloads. Its traceability paths are:

```text
Sample → Episode → State → Claim → Evidence
Sample → Attribution → Retrieval / Memory / Sector Claim / Radar Event
```

The Sample stores State, Episode, data snapshot, optional Sector/Memory and
Attribution identities, Agent run IDs, hierarchy IDs, inherited model/Prompt/
feature versions, dataset schema/build versions, and an explicit quality
object. Missing historical Sector, Memory, or Attribution remains
`not_available_in_source_run`; an observed zero-result Memory retrieval is
`empty_valid`. Neither condition alone makes a sample invalid.

Day42 labels are always empty and `label_status` is `pending` or
`not_available`. The builder never reads later prices and contains no Outcome
calculation. A normalized JSON fingerprint over only frozen upstream IDs,
upstream fingerprints, and the dataset build version determines `sample_id`;
dictionary ordering and materialization time cannot change identity.

The pure builder calls Unified Temporal Contract v1 for State, Episode, and
optional Attribution visibility. Identity or cutoff disagreement fails before
persistence. DuckDB table `research_dataset_samples` stores searchable audit
columns plus the complete validated Sample JSON; duplicated columns are
checked on read and inserts never overwrite an existing Sample. Each JSON
artifact has a credential-free `ResearchDatasetArtifactManifest`.

The offline materializer is:

```bash
python -m scripts.build_research_dataset \
  --state <research-state.json> --episode <research-episode.json> \
  --dataset-build-version pit_research_dataset_build_v1 \
  --created-at <UTC-time> --database <dataset.duckdb> \
  --output <sample.json> --manifest <manifest.json>
```

`--attribution` is optional only when the source run did not retain that
artifact. The materializer performs zero LLM and zero live Provider calls.

## Golden point-in-time replay manifest v1

`GoldenReplayManifest` is the Phase 4B composition gate over frozen research
artifacts. It references the source run and artifacts, reproduced State,
Episode, optional Attribution, and Dataset Sample identities, Claim and Sector
usage counts, Memory status, schema/build versions, and sampled provenance.
It never copies upstream payloads or invokes a Provider or LLM.

```text
Frozen Data/Context/Agent artifacts
  → ResearchStateSnapshot
  → ResearchEpisode
  → ResearchEpisodeAttribution (when present in source run)
  → ResearchDatasetSample
  → GoldenReplayManifest
```

`provider_call_count` and `llm_call_count` are literal zero fields. A passing
manifest requires three deterministic identity checks and rejection of future
News, Radar Event, Memory, Sector Membership, and Filing inputs through
Unified Temporal Contract v1. `created_at` is audit metadata and is excluded
from semantic identities.

Traceability examples record reference paths only. `complete` means the
source run retained every sampled identity. `partial` requires an explicit
historical limitation. Day36 retained role-level Sector/Radar usage but not
accepted downstream Asset Claim IDs; replay preserves that gap and never
synthesizes an ID.

The offline gate is:

```bash
python -m scripts.replay_golden --output-dir data/golden_replay/day43
```

It reconstructs the Phase 3 AAPL Golden run and the Day36 Sector-aware AAPL
run from frozen artifacts only.

## Satellite Alpha ontology v1

`SatelliteAlphaDefinition` is a versioned, machine-readable research
descriptor definition. `SatelliteAlphaObservation` binds one definition to a
canonical Asset, PIT cutoff, explicit coverage, typed value/components, frozen
ResearchState/Episode references, and compact Claim/Evidence/Sector lineage.
`SatelliteAlphaRegistry` requires exactly one definition for every Day45
Selection and Timing family.

Numeric components require `unit`, `scale`, deterministic transform version,
section-qualified State feature references, and direct provenance. Missing
inputs use coverage status rather than numeric zero. Observation semantic IDs
exclude `created_at`; consumers apply Unified Temporal Contract v1 to the
Observation's independent `available_at`.

The pure `SatelliteAlphaMapper` produces one truthful Observation per
definition from frozen State artifacts with zero LLM/Provider calls. It does
not parse report prose, rank assets, normalize cross-sectionally, produce a
Factor, or emit trading semantics. Full vocabulary, lifecycle, support matrix,
and historical rules are in `docs/SATELLITE_ALPHA.md`.

## Selection Satellite and OpportunityCandidate v1

`SelectionSatelliteBuildInput` extends the frozen Day45 clocks with a compact
projection of canonical Sector ID and PIT Sector/Radar event references. It
does not duplicate accepted Claims: the authoritative accepted Claim IDs and
paths are consumed from ResearchState features. `build_selection()` returns
only definitions whose usage is `selection` or `both`.

`OpportunityCandidate` records a rule-based Research qualification outcome,
typed opportunity reasons, non-recommendation thesis disposition, optional
structured logic stage/horizon, Selection Observation IDs, compact
Claim/Event/Sector lineage, explicit coverage and quality, and source
State/Episode identities. The schema has no ranking, score, price, position,
portfolio, order, or trade-action fields.

Candidate identity uses canonical semantic content and excludes `created_at`.
The builder performs no model/Provider call and never parses prose. State
presence or Evidence Strength alone does not qualify an asset. Full eligibility
and boundary policy is in `docs/OPPORTUNITY_CANDIDATE.md`.

## ResearchStateTransition v1 and Timing projection

`ResearchStateTransition` pairs two distinct same-Asset State identities with
strictly ordered cutoffs, optional matching Episode identities, changed
dimensions, structured logic/expectation/thesis/risk/catalyst/evidence
changes, compact Claim/Event/Evidence/artifact lineage, explicit coverage, and
versioned comparison semantics. Its deterministic identity excludes
`created_at` and `available_at`.

`TimingSatelliteBuildInput` carries the current frozen State, candidate prior
States, optional matching Episodes, compact typed Event references, and
existing `MemorySearchResult` references. It creates no new persistence or
Memory layer. History selection is the nearest strictly earlier PIT-valid
State for the same canonical Asset.

`SatelliteAlphaObservation` adds backward-compatible optional
`previous_research_state_id` and `source_transition_id` fields. All Day47
Timing outputs use this existing Observation. Full semantics are documented
in `docs/RESEARCH_STATE_TRANSITION.md`.

## ResearchQuantHandoffBundle v1

`ResearchQuantHandoffBundle` is the sole formal Research output boundary for a
future `deepinsight-quant`. It references canonical Asset/cutoff,
ResearchState, ResearchEpisode, optional OpportunityCandidate and
ResearchStateTransition, and canonically ordered Selection/Timing Satellite
observations through compact typed wire descriptors. Each descriptor faithfully
projects its Observation ID, Alpha identity, definition/transform versions,
usage, comparison scope, coverage, value/components, quality, confidence,
missing reasons, and availability. It does not copy State,
Episode, Claim, Evidence, Agent, Memory, or report payloads.

The Bundle retains every Satellite family's exact coverage, aggregate
coverage, existing deterministic data quality, source run/data snapshot,
Candidate/Transition refs, compact provenance indexes, and a centralized
version manifest. Candidate linkage is optional and may be qualified,
insufficient, or absent, so negative and incomplete Research examples remain
exportable. Missing is never zero.

`bundle_id` is a canonical SHA-256 semantic identity that excludes
`created_at`; Satellite ordering cannot change it. Builder validation closes
State/Episode identity, Candidate Observation membership, Transition current
State, State-feature references, Asset/cutoff, and derived-artifact
availability. Source State features keep their original Unified Temporal
Contract cutoff.

Single export is sorted-key JSON. Batch export is Bundle-ID-ordered JSONL plus
a credential-free deterministic manifest with canonical cutoff values, source
runs, counts, and mixed-coverage summary. The v1 Quant join key
`(asset_id, research_as_of)` is unique per batch and duplicates hard-fail before
write; different Assets may share a cutoff and one Asset may have multiple
cutoffs. The Builder/exporter has no LLM, Provider,
database, network, Factor, ranking, signal, portfolio, or trading dependency.
The full wire contract and forbidden-field policy are documented in
`docs/RESEARCH_QUANT_HANDOFF.md`.

## Phase 4 frozen schema set

Day49 freezes the compatible v1 chain: `TemporalMetadata`,
`ResearchStateSnapshot`, `ResearchEpisode`, Learning Memory/Attribution,
`ResearchDatasetSample`, `SatelliteAlphaObservation`, `OpportunityCandidate`,
`ResearchStateTransition`, and `ResearchQuantHandoffBundle`. Golden replay
reconstructs semantic identities from frozen source artifacts without calling
Providers or LLMs and without parsing report prose.

The Handoff is the terminal schema in this repository. No Phase 4 schema is a
Factor exposure, forecast, rank, signal, position, or order. Scenario and
limitation evidence is indexed in
`data/golden_replay/day49/acceptance_summary.json`.

## Numeric Grounding Equivalence v1

Analyst and Sector Claim validation share
`numeric_grounding_equivalence_v1`. It classifies Claim numerals as numeric
facts, exact canonical-identifier components, explicit structured-window
metadata, or deterministically formatted grounded values. An accepted numeric
fact always maps to a numeric token on one of that Claim's cited Evidence IDs.

Exact decimal equivalence includes harmless zero formatting such as `1`,
`1.0`, and `1.00`. Deterministic rounding requires at least six significant
digits and exact `Decimal` quantization to the displayed precision. It is not a
tolerance comparison and does not permit unit transformations. Identifier
digits are exempt only inside a complete exact identifier present in bound
Evidence; `DGS10` does not independently ground the prose phrase `10-year`.
Durations require explicit window metadata. Missing metadata remains a hard
grounding failure rather than being inferred from keys such as `return_5d`.
