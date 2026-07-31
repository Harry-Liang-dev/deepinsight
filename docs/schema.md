# Domain Schema

This document describes Phase One cross-module contracts. These are Pydantic
models and Protocol interfaces only; they do not create DuckDB tables, FAISS
indexes, LLM calls, or agent behavior.

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
float because MASTER_SPEC does not define a normalized score range.

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
- Technical Text, Sentiment, and News Event analysts share only key points,
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
| `phase2_registry` | `module_name` | Disabled Phase Two extension registry |

The following indexes are initialized:

- `idx_eod_bars_asset_date`
- `idx_fundamentals_asset_period`
- `idx_macro_series_key_date`
- `idx_corporate_events_asset_date`
- `idx_text_documents_asset_publish`
- `idx_memory_items_level_namespace_ts`
- `idx_agent_runs_report_agent`
- `idx_reports_date_market`

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

Repository-owned persistence records live under `src/repositories/` and are
not cross-module business contracts. Repository mapping converts `AssetId`,
enums, and JSON values to DuckDB scalar columns and back. Phase Two columns are
created exactly as specified but remain null and are not parsed or returned as
operational inputs.

Report and section writes share one transaction. Other Repository writes use
the same explicit commit-or-rollback boundary. Connections are scoped to an
operation and are never opened during module import.
