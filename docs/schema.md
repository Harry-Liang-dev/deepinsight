# Domain Schema

This document describes Phase One cross-module contracts and their persistence
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
| `memory_items` | `memory_id` | Memory metadata and FAISS sidecar identifiers |
| `agent_runs` | `run_id` | Reproducible Agent invocation records |
| `reports` | `report_id` | Final report artifacts |
| `report_sections` | `report_id`, `section_name` | Ordered report sections |
| `llm_cache` | `cache_key` | Structured LLM response cache |
| `ingestion_jobs` | `job_id` | Ingestion lifecycle records |
| `report_jobs` | `job_id` | Durable report request, lifecycle, safe error, and report reference |
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
