# Architecture Decisions

---

## ADR-0053

### Separate the canonical live research instant from provider calendars and ingestion

Status: Accepted

Decision

Capture one timezone-aware UTC `research_as_of` at the live orchestration
boundary and reuse it across Macro, Sector State, Radar, Sector Research,
asset research, State, Satellite, and Handoff. Provider adapters project that
instant into native calendars (for example US completed-session date or FRED
America/Chicago date) without replacing it. Phase4 CLIs accept aware ISO-8601
instants and retain legacy `YYYY-MM-DD` UTC-EOD mode for frozen replay.

Use `available_at <= research_as_of` as the live information-eligibility rule.
Record later HTTP/persistence time in `ingested_at`; historical replay retains
the stricter `ingested_at <= research_as_of` original-observed rule. Naive
provider timestamps remain rejected unless the provider contract establishes
their timezone.

Reason

The previous live path promoted the latest completed market date to UTC EOD,
creating a false global cutoff and future-EOD failures. It also treated a
post-cutoff fetch time as if the underlying public information appeared after
the cutoff. Separating information availability, acquisition lineage, and
provider calendar projections preserves PIT safety without backdating or
changing historical semantic identities.

---

## ADR-0001

Date

2026-07-31

Decision

Phase-one only supports AI research reports.

Reason

Reduce MVP complexity.

---

## ADR-0002

Date

2026-07-31

Decision

DuckDB is the structured data store.

Reason

Simple deployment.

---

## ADR-0003

Date

2026-07-31

Decision

FAISS is used for semantic memory retrieval.

Reason

Local vector search.

---

## ADR-0004

Date

2026-07-31

Decision

FastAPI is the backend framework.

Reason

High performance and async support.

---

## ADR-0005

Date

2026-07-31

Decision

Application configuration uses pydantic-settings as the single typed entry
point. Explicit constructor values override process environment variables,
which override a local `.env` file and typed defaults. Application processes
initialize structlog explicitly after loading settings.

Reason

Centralized validation prevents business modules from reading environment
variables directly, supports deterministic test overrides, keeps secrets out of
source control, and avoids logging side effects during module import.

---

## ADR-0006

Date

2026-07-31

Decision

Phase-one modules exchange strict Pydantic v2 domain models and depend on
structural Protocol interfaces. Canonical `asset_id` is represented by a
validated root model, central enums define closed vocabularies, unknown fields
are rejected, and undefined report or agent payloads remain minimal typed JSON
or explicitly documented provisional models.

Reason

Typed, implementation-independent boundaries prevent storage, provider, LLM,
and orchestration details from leaking between modules. Rejecting unknown
fields catches contract drift early while the minimal treatment of unspecified
payloads avoids inventing Phase Two behavior.

---

## ADR-0007

Date

2026-07-31

Decision

Phase One database bootstrap and Repository implementations use the native
DuckDB Python connection API behind `DuckDBDatabase`. Connections are scoped
per operation, writes use explicit transactions, and one database handle
serializes its writes in-process. Deployment must preserve a single writer
process for the DuckDB file.

SQLAlchemy remains an approved project dependency, but this database task does
not introduce an unapproved DuckDB SQLAlchemy dialect or migration framework.
Upper layers depend on Repository methods and typed records rather than
DuckDB connections or SQL strings.

Reason

MASTER_SPEC supplies DuckDB-native DDL, while the formal division of
responsibility between SQLAlchemy and native DuckDB and the migration strategy
are explicitly marked as pending. The native boundary implements the required
schema and transaction behavior without adding a new component. Explicit
Repositories keep the implementation replaceable when those pending decisions
are resolved.

---

## ADR-0008

Date

2026-07-31

Decision

Phase One LLM inference uses one provider implementation:
`OpenAIProvider` over the official OpenAI Responses API. `LLMGateway` depends
on a structural provider interface and accepts injected Provider and cache
implementations. The Gateway public contract remains
`invoke_json(model, system_prompt, input_payload) -> JSON object`, as specified
by `MASTER_SPEC`.

Because the Gateway contract does not yet accept a caller-supplied JSON Schema,
the provider requests Responses API JSON-object output and validates that the
returned text decodes to an object. Schema-specific structured parsing is
deferred until a schema parameter is formally specified; no inference
parameters are added speculatively.

The official SDK owns transient retries and receives the configured timeout and
maximum additional retry count. Cache keys are SHA-256 digests of canonical
JSON containing the model, full system prompt, and input payload. New entries
have no expiry, and the Gateway does not add an unspecified `force_refresh`
path.

Gateway observability is limited to provider, model, success/error status,
cache-hit state, latency, available token usage, available response ID, a
truncated request fingerprint, and a stable error code. It never logs API
keys, prompts, user payloads, or raw provider exceptions. Persisting full Agent
run inputs and outputs remains outside the Gateway and belongs to the future
Agent execution boundary.

Reason

This preserves the exact Phase One inference and cache contract while keeping
the OpenAI SDK replaceable and fully testable offline. Delegating retries to
the official SDK avoids duplicate retry loops, canonical cache keys make
results reproducible, and the narrow logging boundary supplies operational
metadata without exposing research content or credentials.

---

## ADR-0009

Date

2026-07-31

Decision

Phase One data providers implement `BaseProviderAdapter` and convert external
SDK or API payloads into a small stable ingestion vocabulary inside the
adapter boundary. `DataNormalizer` alone converts that vocabulary into strict
domain records. Unconfigured official and licensed connectors are
non-networking placeholders; offline execution uses `FakeProviderAdapter`.

Raw document text is stored verbatim as UTF-8 below an injected root, using a
source hash directory and document-ID hash file name. Canonical document
metadata stores the path, checksum, source ID, URL, and timestamps.

Document chunking uses explicit constructor-provided character window and
overlap values. Chunk IDs and reserved vector IDs are deterministic. Ingestion
does not create an embedding or update FAISS: persisted chunks explicitly set
`metadata_json.embedding_status` to `pending`, keep `token_count` null, and
carry only the configured target embedding model, dimension, and namespace.

Ingestion writes are idempotent per existing table keys. A multi-stream job is
not globally atomic across Repository calls; if a later stream fails, already
committed rows remain and the failed `ingestion_jobs` record reports their
exact count. A repair run can safely replay them.

Reason

This prevents provider response formats from leaking upward, makes licensed
access impossible by accident, preserves source evidence, and supplies stable
chunks to the future Embedding/FAISS task without pretending vectors already
exist. Explicit failed-job accounting preserves operational clarity while
reusing the existing per-operation Repository transaction boundary.

---

## ADR-0010

Date

2026-07-31

Decision

Phase One semantic storage uses a private `FaissVectorRepository` with one
cosine `IndexFlatIP` namespace per Memory level. Every namespace persists an
index, Parquet vector metadata, and a validated manifest. FAISS objects and
provider arrays never cross the Repository boundary.

DuckDB remains authoritative for Memory text, source references, creator,
timestamps, importance, and namespace/asset filters. Every new Memory write
must contain a real `SourceReference` and `created_by`; retrieval returns both
without synthesizing missing citations. Vector IDs are deterministic hashes of
new Memory IDs and are unique with their FAISS namespace in DuckDB.

Memory writes use vector-first then DuckDB-sidecar ordering. A DuckDB failure
triggers vector removal. A failed compensation raises an explicit consistency
error and requires namespace rebuild from DuckDB. File writes use temporary
files and atomic replacement per artifact, and loading rejects incomplete or
incompatible namespace state. This is an in-process single-writer contract,
not a distributed transaction or cross-process lock.

Similarity is the only first-version ranking score. `min_importance_score` is
an exact filter, while `time_decay_days` remains a validated no-op contract
until MASTER_SPEC defines a decay formula. No unstated importance/time
reranking formula is introduced.

Reason

This provides durable, attributable semantic retrieval while keeping
structured metadata under existing Repositories and preventing FAISS details
from coupling future Agents to the MVP index implementation. Explicit
compensation and rebuild behavior makes double-write failures observable and
recoverable without claiming atomicity the local stores cannot provide.

---

## ADR-0011

Date

2026-07-31

Decision

Phase One implements exactly four Analyst Agents and four Manager Agents named
by MASTER_SPEC. `ResearchCoordinator` provides only their fixed collaboration
inside `src/agents`: four Analysts, Research Manager, a single Bull review, a
single Bear review, then Risk Manager. Bull and Bear are logical peers but are
invoked in deterministic Bull-then-Bear order. There is no multi-round debate,
dynamic routing, report assembly, or autonomous loop.

Every Agent receives its model name by dependency-injected invocation, uses
only public LLM Gateway and Memory interfaces, loads a versioned YAML prompt,
and writes one `agent_runs` audit record. Existing role-specific domain
responses remain unchanged. A common Agent execution envelope adds
claim-to-citation evidence links, explicit missing data, uncertainties, and a
stable failure object. Citations are accepted only when their document and
chunk identifiers occur in input documents or attributable Memory sources.
Manager evidence links inherit the validated analyst and Research Manager
citations supplied to that Manager.

Memory retrieval failure may degrade to existing document evidence and is
reported as uncertainty. Invalid schemas, mismatched roles, fabricated
citations, unattributed conclusions, and trading instructions fail an Agent
run. A failed Analyst can be omitted from synthesis with an explicit coverage
warning; failure of Research Manager stops thesis review, and failure of
either Bull or Bear stops Risk Manager.

Deterministic technical features follow the MASTER_SPEC windows but return a
null trend when history is insufficient. Fundamental growth compares the
latest observation with the same `report_type` and fiscal date one calendar
year earlier. Missing values, absent comparable periods, empty inputs, short
history, and zero growth denominators return null features with explicit
`missing_data`.

Reason

This is the smallest report-oriented Agent chain required by MASTER_SPEC. The
fixed topology and injected model preserve deterministic tests and avoid
premature routing or debate machinery. A separate evidence envelope strengthens
traceability without changing provisional cross-module role schemas, while
explicit degradation prevents missing evidence from being presented as a
certain investment conclusion.

---

## ADR-0012

Date

2026-07-31

Decision

Phase One exposes report task state at
`GET /v1/reports/jobs/{job_id}`. Report submission uses FastAPI background
tasks and an injected, process-local task service; state transitions are
`queued`, `running`, then `completed` or `failed`. This implementation is not
durable across restarts and requires one API worker when its status store is
used.

Routes depend only on injected report, task, Memory, and snapshot service
interfaces. The default application starts without opening DuckDB, FAISS, or
an external Provider and reports unavailable dependencies explicitly.

All HTTP failures use an `ErrorInfo` envelope with a stable code, safe message,
retryability, and optional details. Snapshot GET queries existing snapshot
metadata only and exposes logical artifact names, never absolute paths. The
six MASTER_SPEC Phase Two routes return HTTP 501 with no side effect.

Reason

The task specification requires an observable asynchronous report contract but
does not define a queue or status path. A replaceable in-process service is the
smallest reliable Phase One implementation and avoids adding an unauthorized
distributed component. Unified safe errors and query-only snapshot behavior
make the public boundary explicit without leaking storage or provider details.

---

## ADR-0013

Date

2026-07-31

Decision

`ResearchWorkflowService` is the Phase One application boundary from
`GenerateReportRequest` to a completed `ResearchReport`. It sequences existing
modules without reimplementing them: provider ingestion, normalized
Repository reads, pending document embedding, deterministic features,
attributable Memory retrieval, the fixed eight-Agent coordinator, and
`ResearchReportPipeline`.

The first executable end-to-end composition is a separate offline API entry.
It uses fixed provider records, `FakeLLMProvider`, `FakeEmbeddingService`,
temporary DuckDB, and temporary FAISS. It never falls back silently between
Fake and real OpenAI behavior. The safe default API remains unconfigured until
a deployment composition explicitly supplies real provider and model
dependencies.

Redis queues, durable report jobs, Worker and Scheduler protocols,
multi-process DuckDB locking, Web UI, snapshots, backups, and Docker Compose
are not selected by this decision. Their task specification remains
ambiguous, so the minimal workflow continues to use the existing single-process
task boundary.

Reason

A thin application service closes the report loop while preserving every
replaceable module boundary and keeping the API free of business logic. A
separate explicit offline composition makes installation and regression tests
deterministic without credentials, network access, or accidental use of Fake
research in a production entry point. Deferring unresolved distributed and
operational protocols avoids adding unapproved components under the guise of
integration.

---

## ADR-0014

Date

2026-08-06

Decision

The first controlled real-data acceptance uses official SEC EDGAR submissions
and one recent Apple 10-Q/10-K primary document. Automated access requires an
explicit `SEC_USER_AGENT` containing a monitored contact address. The adapter
does not provide or synthesize price bars, valuation data, macro observations,
or sentiment samples; those absences remain visible to deterministic operators
and the report.

The report workflow uses a 370-day disclosure lookback. Complete extracted
filing text is retained, chunked, embedded, and indexed, while no more than two
deterministically distributed chunks from each document enter the live Agent
context. This bounds Qwen input cost and avoids selecting only filing headers
without altering stored source evidence. Provider embedding
batches are configurable; the live acceptance uses DashScope
`text-embedding-v4`, 256 dimensions, and batches of ten.

Qwen remains an acceptance-time compatible client injected through the
existing `LLMGateway` and `OpenAIProvider` boundary. It is not registered as a
new production provider and does not change the MASTER_SPEC decision that
production Phase One inference is GPT via OpenAI. The live script submits the
existing workflow through FastAPI, never falls back to Fake implementations,
and fails unless every report citation joins to a stored document/chunk and
that document retains its SEC URL, raw path, timestamp, and filing metadata.
DashScope uses the standard OpenAI-compatible base URL. Live acceptance
defaults to the Responses-supported `qwen3.7-flash` with
`enable_thinking=false`; the fixed schema extraction and synthesis tasks do
not justify long-form reasoning latency. Live failures expose only
credential-redacted provider diagnostics and persisted stage state.

All eight Agent prompts require plain-string claim, risk, condition,
invalidator, watch-item, and uncertainty arrays; Analyst and Research Manager
references remain exclusively in `supporting_citations`. List lengths are
bounded and role-specific evidence limits are explicit. Score-producing
Fundamental uses prompt version `v5`; the other Analysts and Bull/Bear/Risk
Managers use `v4`, and Research Manager uses `v3`. Score-producing prompts
explicitly require the domain model's inclusive 0.0-to-1.0 scale while
forbidding 1-to-5 and 0-to-100 scales. Domain schemas do not accept
provider-invented nested claims or silently guess how out-of-range scores
should be converted. Trading
guards reject explicit buy/sell-security instructions but do not reject
operational terms such as `sell-through`; field-level trade, order, position,
and price-target bans remain unchanged.

Reason

SEC EDGAR is the only already-specified source that is both authoritative for
US issuer disclosures and usable without commercial authorization. A bounded
filing-only acceptance can prove normalization, persistence, semantic indexing,
Agent evidence discipline, report assembly, API integration, and citation
traceability while honestly exposing the absence of a configured market-price
provider. Injecting compatible clients reuses existing service boundaries and
avoids a parallel Qwen or report implementation.

---

## ADR-0015

Date

2026-08-07

Decision

Phase One closes with a single-node durable production topology. DuckDB
`report_jobs` is authoritative for the validated report request, lifecycle,
safe error, attempt count, and final report ID. Redis is delivery transport
only and contains a UTF-8 `job_id`; it never contains prompts, credentials,
evidence, or the full request. FastAPI persists then enqueues, one separate
Worker atomically claims and executes jobs, and restart recovery returns
interrupted `running` records to `queued`. Duplicate queue delivery is harmless
because only `queued` records can be claimed.

All Repository connections use both an in-process lock and a
path-specific Linux advisory file lock. Snapshot and backup creation acquires
the same file lock, copies DuckDB and FAISS into a temporary bundle, records
SHA-256 hashes, and publishes by atomic rename. This is a local single-machine
consistency boundary, not a distributed database protocol. The report
pipeline persists an explicit failed state on downstream Memory or completion
failure and deletes an already-written L3 trace when final report persistence
fails.

Analyst outputs now distinguish direct `facts` from interpretive
`key_points`. Both carry claim-level citations. Every numeric token in an
accepted textual Agent claim must occur verbatim in its cited document chunk
or Memory summary; prompts also forbid calculation, rounding, unit conversion,
annualization, and reporting-period changes. This is deliberately conservative
grounding and does not attempt financial calculation inside the LLM layer.

The Phase One auxiliary topology consists of a UTC Scheduler that submits
configured single-asset requests through FastAPI, a read-only Streamlit task
and report viewer, and Docker Compose services for API, one Worker, Scheduler,
Web, and Redis. Reserved Phase Two interfaces are abstract and
non-instantiable; no trading, backtest, strategy, optimization, or training
runtime is enabled. Future `data/live_acceptance/` output is Git-ignored; the
already tracked 2026-08-06 successful acceptance artifact remains historical
delivery evidence.

This decision supersedes ADR-0013 only for the operational items that ADR-0013
explicitly deferred. The deterministic offline composition remains unchanged
and is still the default test boundary. Official OpenAI successful live smoke
P1-3 remains deferred until account funding is restored; the successful Qwen
compatibility acceptance is not reclassified as an OpenAI production pass.

Reason

Persist-before-enqueue and claim-by-status provide restart visibility without
introducing a distributed orchestrator. A single Worker and a shared local
file lock match DuckDB and FAISS deployment constraints while keeping process
responsibilities explicit. Exact citation and numeric checks address the
observed reporting-period drift without weakening schemas to accommodate model
errors. The auxiliary services satisfy the MASTER_SPEC single-node deployment
shape while preserving the Phase One report-only boundary.

---

## ADR-0016

Date

2026-08-07

Decision

The first Phase Two capability is a report-quality evaluation boundary, not an
additional research Agent. `ReportEvaluationService` composes a versioned rule
loader, deterministic evaluator, replaceable semantic Judge, and immutable
evaluation Repository. It consumes an already-generated `ResearchReport`,
supplied evidence text, and known missing-data declarations; it does not fetch
data, retrieve Memory, or regenerate report content.

`report_quality_v1` scores twelve equally weighted dimensions on the closed
`[0, 1]` scale with a `0.8` pass threshold. Structure, citation coverage,
citation traceability, evidence time, prohibited trading language, missing-data
disclosure, explicit uncertainty presence, and verbatim numeric grounding are
computed by code. Semantic factuality, conclusion/evidence consistency,
bull/bear balance, risk quality, uncertainty quality, and readability are
judged through the existing `LLMGateway.invoke_json` boundary. Factual
correctness and uncertainty expression are deliberately hybrid dimensions.

The complete `EvaluationResult` separates deterministic checks from Judge
checks and includes a reason and evidence locator at both check and dimension
level. Its fingerprint covers the report, sorted evidence, sorted missing-data
declarations, exact rule content, and Judge model. DuckDB stores the complete
result plus duplicated audit columns in `report_evaluations`; IDs are immutable
and reads fail if duplicated fields disagree with the JSON result. The default
suite uses `FakeReportJudge` and never accesses a network.

Reason

Objective properties should not consume model calls or vary between runs.
Semantic quality cannot be reduced safely to keyword counts, but isolating it
behind the existing Gateway preserves provider replacement, caching, and safe
error handling. Versioned rules and input fingerprints make score changes
explainable, while immutable complete-result storage permits later comparison
without turning historical reports into training rewards, trading signals, or
backtest inputs.

---

## ADR-0017

Date

2026-08-07

Decision

`research_benchmark_v1` is a Git-versioned, offline corpus of seven fixed cases
covering CN, HK, and US report-quality boundaries. Each case stores explicit
source metadata, redistribution status, fixed evidence text, expected facts,
allowed missing items, prohibited conclusions, and case-specific minimum
thresholds. CN and HK cases use clearly labelled synthetic fixtures until
their real Provider acceptance paths exist; canonical asset identifiers in
those cases validate market contracts and do not assert facts about a real
issuer.

Report cases contain fixed semantic materials that are deterministically
materialized into the current ten-section `ResearchReport` contract. The
materializer is Benchmark infrastructure only: it performs no research,
Provider access, retrieval, Agent inference, or production report generation.
The Analyst-failure case instead carries an expected safe failure observation
and no report.

The default pass gate uses lifecycle compliance, expected-fact coverage across
both report and source, prohibited-conclusion compliance, deterministic
evaluation score, and named deterministic check thresholds. It records the
complete `EvaluationResult`, including Fake Judge scores, but Fake semantic
scores cannot cause a default case to pass. Live mode requires a non-Fake
`ReportJudge`, enables separately declared semantic dimension thresholds, and
is excluded from default pytest. Default output uses the manifest's fixed UTC
time and stable case ordering.

Reason

A small fixed corpus establishes repeatable quality regression before adding
more Agents. Explicit provenance and synthetic-data labels prevent test
fixtures from being confused with current financial facts. Separating
deterministic default gates from optional live semantic gates makes offline CI
reliable without pretending a Fake Judge proves readability or reasoning
quality. Structured per-metric failures are more diagnostic and durable than
whole-report snapshot equality.

---

## ADR-0018

Date

2026-08-07

Decision

SEC EDGAR is the single real Provider enhanced in the first Phase Two Provider
iteration. It remains behind the existing `BaseProviderAdapter`; no Agent,
report, Memory, or domain contract bypass is introduced. FRED is deferred
because the current Adapter interface has no macro-series method, CNINFO still
requires a confirmed official access contract, and current HKEX terms do not
permit assuming automated collection rights.

All production SEC requests pass through one injected `ProviderHTTPClient`.
The typed default is five requests per second, and configuration above SEC's
published Fair Access ceiling of ten requests per second is rejected. Every
request declares the configured contact User-Agent and timeout. Connection
failures, timeouts, HTTP 429, and HTTP 500/502/503/504 receive at most the
configured finite additional attempts. Numeric `Retry-After` is honored up to
the configured delay ceiling; other 4xx responses fail immediately. Network
errors are surfaced as stable Provider errors and are never converted into
empty data.

Document retrieval uses the request date range as its incremental boundary.
The Adapter checks `filings.recent` and loads only `filings.files` pages whose
official `filingFrom`/`filingTo` range overlaps the request. Accession numbers
produce stable document IDs and `sec:accession:<number>` Provider locators, so
existing Repository upserts remain idempotent.

SEC submissions JSON is transient Adapter input, cached only for the Adapter
lifetime. The canonical record retains selected CIK, accession, form, filing
date, primary-document name, source URL, and acceptance timestamp. Complete
extracted filing text continues through the existing `RawTextStore`; wholesale
submissions responses and unrelated filings are not persisted. A standalone
`scripts.smoke_sec_edgar` command performs an opt-in Provider-only live check
and prints no filing text. Default pytest uses injected HTTP fixtures only.

Reason

The first live acceptance proved SEC provenance and report citation flow but
also exposed that the minimal Adapter had no retry policy, rate limiter, or
historical submissions paging. Hardening the already-authorized official
source improves reproducibility and older filing coverage without adding a
second Provider, inventing unavailable market data, or widening the legal
surface. Explicit transient-response and raw-text boundaries keep external
formats below the normalization layer and make failures auditable.

---

## ADR-0019

Date

2026-08-08

Decision

Live LLM inference is selected only at the application composition boundary by
`DEEPINSIGHT_LLM_PROVIDER=openai|qwen`. OpenAI remains the default and retained
Provider. DashScope Qwen is promoted from a script-private compatibility
client to `QwenProvider`; both implement the existing `LLMProvider` contract
and both enter the existing cache, safe logging, error mapping, and structured
response validation through `LLMGateway`. Agents receive only `LLMGateway` and
model names and cannot import or inspect either SDK configuration.

`scripts.smoke_llm` is the single live LLM smoke implementation.
`scripts.smoke_qwen` only checks that Qwen is explicitly selected and delegates
to it. The SEC-to-Qwen acceptance also uses `QwenProvider` and
`QwenEmbeddingService`, eliminating its script-private inference Provider and
direct SDK client construction. Fake remains test-only and can be used only by
explicit dependency injection. Missing credentials for the selected live
Provider raise `CredentialNotConfigured`; there is no automatic Fake fallback.

The canonical SEC identity setting is
`DEEPINSIGHT_PROVIDER_SEC_USER_AGENT`, formatted as an application or company
name followed by a monitored contact email, for example
`DeepInsight ops@example.com`. Existing local environments may temporarily
use `SEC_USER_AGENT` as a migration alias, but new configuration and
documentation use the canonical name. The Provider-only live smoke loads the
same typed settings as production and retains the configured timeout, bounded
retry, and rate limiter. Its CLI CIK only bounds the requested test asset; it
does not bypass Fair Access controls. Live scripts remain outside pytest
collection and all default tests use injected offline clients or Fake
boundaries.

Reason

The successful Qwen acceptance proved that a live fallback was operational,
but the independent Qwen smoke and acceptance-local SDK setup duplicated the
production Provider boundary. Selecting a concrete implementation once at the
composition root preserves replaceability, avoids SDK leakage into Agents,
and makes live behavior explicit without changing prompts, Evaluation,
reports, or adding another supplier. A hard missing-credential failure
prevents production from silently returning deterministic Fake research.

---

## ADR-0020

Date

2026-08-08

Decision

Alpaca Market Data is the only real price Provider implemented for Closing
Sprint Day 16. It uses the existing `BaseProviderAdapter` single-date EOD
contract and adds an Adapter-specific inclusive date-range method so callers
can use Alpaca's paginated historical endpoint efficiently without changing
the MASTER_SPEC contract for every Provider.

The Adapter calls only
`GET https://data.alpaca.markets/v2/stocks/bars` with `timeframe=1Day`,
ascending order, and opaque `next_page_token` pagination. The Basic-compatible
default is `feed=iex`, which is explicitly not full SIP coverage. The default
adjustment is `raw`: Alpaca `o/h/l/c/v/vw` map to canonical OHLC, volume, and
VWAP, while unavailable `adj_close` and `turnover` remain null. The external
ticker must map to a requested canonical `US:<ticker>` identifier before the
record leaves the Adapter.

`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are environment-only `SecretStr`
settings. They enter the shared `ProviderHTTPClient` only as official
authentication headers and are never included in health metadata, errors,
logs, fixtures, or smoke output. The shared client now supports protected
additional headers and Alpaca's Unix `X-RateLimit-Reset` response header.

The Adapter proactively limits itself to 180 requests per minute and rejects
configuration above the Basic 200-per-minute allowance. HTTP 429 and transient
server/network failures receive only bounded attempts; permanent
authentication and authorization failures surface immediately. An empty
trading-day result remains empty and does not create a synthetic bar.

Canonical records continue through `DataNormalizer` and
`MarketDataRepository.upsert_eod_bar`. The existing
`(asset_id, trade_date)` primary key is the idempotency boundary, and
`source_id=alpaca_market_data` joins each row to Provider metadata in
`source_registry`. No external response object or unused trade-count field is
persisted.

A standalone `scripts.smoke_alpaca` command tests `US:AAPL`, normalizes the
returned records, and prints only bar count, first/last date, and source ID.
Missing credentials return exit code 2 without network access. Default pytest
uses injected HTTP responses and a temporary DuckDB only.

Reason

The tracked AAPL acceptance report correctly disclosed that no technical trend
analysis was possible because no price history existed. Alpaca is the
MASTER_SPEC-designated US price source and can fill that input gap without
changing Agents, prompts, evaluation behavior, report generation, or adding
trading/backtesting logic. Retaining raw adjustment and IEX provenance avoids
presenting partial or transformed data as a different market-data product.

---

## ADR-0021

Date

2026-08-08

Decision

The Day 17 live baseline is guarded by one non-networking, fail-closed
Preflight. It requires the configured LLM selector to be Qwen, real Qwen and
Alpaca credentials, a configured SEC identity, a canonical asset-to-CIK entry,
and an explicit dataset version/as-of/data window. Missing configuration stops
before every Provider smoke and never selects Fake LLM or Fake Judge.

SEC issuer identifiers continue through the existing generic
`DEEPINSIGHT_PROVIDER_SEC_CIK_MAP`; scripts no longer contain an AAPL CIK
default. Automatic SEC ticker-directory discovery is not introduced. Alpaca
range bars use its existing Adapter capability through a small generic
`DataIngestionService` range boundary, preserving normalization, source
identity, ingestion-job audit, and DuckDB idempotency.

The live run uses the existing report workflow and the existing
`ReportEvaluationService` with a real `LLMReportJudge` behind the selected
`LLMGateway`. It writes a credential-free manifest containing dataset/time
identity, ingestion snapshot IDs, model, prompt versions, evaluation rules,
Agent run IDs, report ID, and source references. No Agent prompt, report
assembly rule, or evaluation rule is changed for the baseline.

Reason

The previous live script could succeed with a script-local forced Qwen
composition and hard-coded SEC identifier while the unified runtime remained
misconfigured. A hard gate and explicit manifest make a live result
reproducible and auditable, while the generic range ingestion extension is the
minimum needed to combine SEC disclosures and Alpaca price history without a
parallel pipeline.

---

## ADR-0022

Date

2026-08-08

Decision

Live credentials are injected only through environment variables inherited
from the parent shell. Application Settings no longer load `.env` files, and
the tracked `.env.example` is removed. The repository documents a private,
project-external `~/.local/bin/load_deepinsight_keys.sh` workflow but never
creates, reads, prints, or persists that file.

The canonical Qwen runtime names are `QWEN_API_KEY` and
`QWEN_MODEL_NAME`. Alpaca uses `APCA_API_KEY_ID`,
`APCA_API_SECRET_KEY`, and `APCA_API_BASE_URL`. SEC identification uses only
`DEEPINSIGHT_PROVIDER_SEC_USER_AGENT`; its value no longer has a tracked
default or legacy alias. OpenAI remains available through its existing
environment-only Provider interface.

Real Provider pytest cases are marked `live`, use `os.getenv` only to decide
whether required runtime variables exist, and skip safely when incomplete.
Default pytest explicitly deselects the `live` marker even when a developer
machine has credentials loaded, preventing accidental quota or network use.
Offline tests continue to inject deterministic non-credential fixtures.

Reason

A shell-only credential boundary lets Codex inherit the complete environment
when launched while preventing repository files, test fixtures, and prompts
from becoming secret stores. Separating marker selection from credential
presence ensures that loading local keys never turns an ordinary regression
run into an implicit live run.

---

## ADR-0023

Date

2026-08-08

Decision

The report assembler follows the coordinator's existing degraded-Analyst
contract. A failed Analyst produces its required standard section with no
facts, inferences, or risk claims and with an explicit unavailable/missing-data
disclosure. Successful Agent claims remain subject to the same schema,
numeric-grounding, citation, and trading-instruction checks. Manager failures,
including Risk Manager failure, remain fatal to report completion.

Live Qwen runs allow one bounded transport retry, while provider smokes retain
zero retries. The exact configured SEC data window is used by both smoke and
E2E ingestion. Manifest collection uses the canonical persisted
`retrieved_context_json` column, and numeric tokenization excludes trailing
sentence punctuation while retaining internal thousands separators.

Reason

The coordinator already permits research to continue when some Analyst
outputs fail validation, but the assembler previously contradicted that
contract. Explicit empty sections preserve completeness without fabricating
research. Keeping every Manager as a hard gate retains the required two-sided
and risk review. The remaining fixes address observed live reliability and
audit defects without changing prompts, evaluation rules, or safety checks.

---

## ADR-0024

Date

2026-08-08

Decision

`live_agent_benchmark_v1` is a separate measurement system from the offline
`research_benchmark_v1`. It never fetches market data during a run. A detached
SHA-256 locks one retained US:AAPL SEC/Alpaca snapshot, and six scenario
projections reuse the existing `ResearchCoordinator`, `ReportAssembler`,
`LLMGateway`, and `ReportEvaluationService`.

A run is valid only with `provider_real=true` and `judge_real=true`; the live
composition creates only a configured OpenAI or Qwen Provider and
`LLMReportJudge`. Each run records model, supported inference parameters,
Prompt versions, rules version and per-case input fingerprints, then saves
complete Agent results, reports and evaluations. A/B comparison requires the
same dataset, snapshot, case set and rules and reports neutral score deltas.
It does not choose or promote a candidate.

The first version covers US only. CN/HK cases remain in the offline synthetic
Benchmark and are not presented as live evidence until legally retained fixed
real snapshots exist.

Reason

Prompt and model comparisons require identical evidence; refetching SEC or
market data would confound changes in Agent behavior with data drift. Keeping
the live instrument separate also prevents real-provider semantics from
weakening the deterministic, network-free responsibilities of the existing
offline Benchmark.

---

## ADR-0025

Date

2026-08-09

Decision

The first Phase 3 Main integration adopts two complementary canonical input
bundles rather than creating a third aggregate schema. `ResearchDataBundle`
owns normalized structured availability, freshness, quality, missing-data and
field-level lineage. `ResearchContextBundle` owns point-in-time L0–L4 Memory,
retrieval metadata, explicit empty context and vector snapshot identity.
`ResearchTaskRequest` carries both or neither and rejects asset, market,
report-window or `as_of` disagreement.

`ResearchWorkflowService` is the only composition boundary that constructs
the pair. It supplies a timezone-aware UTC end-of-report-day `as_of`, the
canonical asset, explicit data window, dataset version, current report ID and
Memory namespaces. Data and Memory reject future items independently, and the
Agent projector repeats the temporal check. DuckDB `TIMESTAMP` remains
UTC-naive only inside Repository encoding/decoding; cross-module contracts are
timezone-aware. Existing legacy Memory rows are not rewritten automatically;
an old snapshot of uncertain timezone provenance must be audited or rebuilt
before use in a point-in-time baseline.

The fixed eight-Agent topology consumes least-privilege `agent_input_v1`
projections. The current Prompt text and output schemas remain unchanged, so
the versioned contract is supplied alongside the legacy Prompt-compatible
context during migration. Managers receive four explicit Analyst slots,
including failed slots. No Agent receives a Provider, Repository, DuckDB,
FAISS, SDK or Provider-specific response field.

`DataSourceReference` remains normalized provenance metadata and
`SourceReference` remains the claim citation shape; they are not duplicate
schemas. `ResearchEvidenceItem.to_source_reference()` is the single approved
conversion, using the normalized record key plus stable `ev_*` identity.
Agent numeric validation and Report citation validation accept that existing
citation shape without weakening grounding. Data `MissingData` and Memory
`MissingContext` remain separate because they represent different absence
causes; `AgentCoverageManifestV1` is their single aggregation point.

`LLMRunMetadata` moves from the Gateway implementation module to the shared
LLM Schema. Agents pass Prompt version, `agent_output_v1`, and their Pydantic
response model through the unified Gateway; token/cache audit fields are
written to existing Agent run records and the complete metadata remains on the
execution result. Evaluation passes its ruleset Prompt version and
`judge_response_v1`; complete real-Gateway metadata is persisted in the
Evaluation JSON. Judge provider-compatibility normalization remains local and
precedes its existing strict `JudgeResponse` validation. OpenAI, Qwen and Fake
continue through one Gateway.

The bundles remain internal application contracts; no new FastAPI route is
introduced. Legacy pair-free `ResearchTaskRequest` construction remains only
as a compatibility path for focused tests and fixed Benchmark infrastructure.
Production Worker, offline API composition and live report composition inject
the canonical Data bundle builder. No Prompt, scoring rule, Agent count,
trading, factor, Regime, MoE, backtest or training behavior is added.

Reason

The four Phase 3 windows produced independently valid components but left the
production chain split between generic JSON features, raw Memory results and
document-only citations. Constructing one aligned bundle pair at the
orchestration boundary preserves module ownership, avoids cycles and prevents
Provider leakage. A single citation conversion and two deliberately distinct
absence types remove identity ambiguity without erasing the difference
between missing market data and an empty historical retrieval. Versioned LLM
metadata makes Agent and Judge runs reproducible while retaining the existing
replaceable Gateway and fully offline default tests.

---

## ADR-0026

Date

2026-08-13

Decision

Strict Agent Evidence validation remains unchanged. Real structured Agent
generation may perform at most one repair after a syntactically valid response
fails schema or Evidence validation. The repair receives the same input and
Evidence plus only a credential-safe contract violation; it may remove an
unsupported claim but may not add facts, Evidence, aliases, calculations, or
external data. Fake/default inference never repairs.

Gateway schema failures retain schema name/version, validation paths and a
bounded Expected/Actual/Missing/Extra/Type-mismatch diff without retaining
rejected values, Prompt content, or credentials. Invalid JSON, schema,
Provider, timeout, and cache errors remain separate safe categories.

Where live evidence showed recurring drift between prose lists and a separate
binding list, Technical, Sentiment, News/Event, Bull, and Bear now generate one
authoritative collection of Claim objects. Python deterministically assembles
the unchanged public response shape from those validated objects. No fuzzy ID
matching, alias repair, automatic ID correction, unsupported numeric tolerance,
or Fake fallback is introduced.

Reason

The former two-output representation let a model produce a valid prose item
and an empty or missing binding independently. One authoritative Claim object
makes the producer contract structurally consistent while leaving the strict
consumer validator intact. A bounded repair recognizes normal structured-model
variance without turning repeated sampling into an acceptance strategy. The
latest live result remains blocked, proving the gate still fails closed when a
repair cannot satisfy the contract.

---

## ADR-0027

Date

2026-08-13

Decision

Phase 3 uses one authoritative accepted Claim collection and one shared,
deterministic claim-intent compliance policy. `claim_type` continues to
describe factual/analytical role semantics. The orthogonal `claim_intent`
distinguishes fact, attributed third-party opinion, analytical inference,
system recommendation, and execution instruction.

Attributed third-party ratings and target prices are allowed only when the
claim names an external analyst or institution and retains exact Evidence and
numeric grounding. DeepInsight recommendations, DeepInsight target prices,
imperative trades, portfolio allocations, positions, orders, and stop-loss
instructions remain prohibited. Agent, Report, and Evaluation call the same
policy instead of maintaining independent keyword lists. Report rendering may
label third-party opinion but cannot change its accepted claim text or create a
new factual claim. Rejected claims remain diagnostic metadata and are never
rendered.

`AGENTS.md` is reduced from a Phase 1-era process manual to current repository
boundaries, five non-negotiable research rules, stable engineering standards,
credential safety, and the three Phase 3 gates: Engineering, Contract, and Live
Acceptance. Temporary five-window ownership rules and repeated phase history
are removed; durable module status and architecture history remain in their
dedicated documents.

Reason

Three separate natural-language keyword detectors had drifted. In particular,
Report and Evaluation treated a cited statement that an external analyst
lowered a price target as if DeepInsight had issued that target. Intent and
attribution are the relevant safety boundary, not the isolated words “buy” or
“price target”. A shared deterministic policy removes redundant blockers while
retaining fail-closed rejection of genuine system advice and executable
instructions. The shorter agent guide avoids duplicating rules already enforced
by schemas and tests and makes the five safety invariants easier to audit.
## ADR-0028

Date

2026-08-14

Decision

Freeze Research Completeness v1 on the credential-free fresh acceptance
`20260813T163645Z`. The accepted baseline uses dataset
`live_aapl_phase3_final_20260813_v1`, an as-of date of 2026-08-13, and a
2026-05-14 through 2026-08-13 market-data window. Sparse SEC filings use a
separate bounded 740-day lookback in smoke, explicit ingestion, and workflow
orchestration; denser data retains its frequency-aware window.

Fundamental availability requires at least two strictly validated Claims.
This is not a validation relaxation: canonical Evidence identity,
exact/deterministic numeric grounding, point-in-time safety, intent compliance,
and quarantine remain unchanged. One valid Claim is insufficient. Analyst
provenance type is assigned deterministically during Claim promotion and is
not self-reported in the Draft LLM contract.

The production Qwen fixed-bundle Contract Gate completed eight of eight roles.
Fresh Acceptance completed real SEC, Alpaca, FRED, Stocktwits, Qwen, Memory,
eight Agents, report assembly, and real Evaluation without Fake fallback.
Report `rep_70fb903a3bc74aaebe2e391771fd3816` has 19 traceable citations and
21 fully grounded numeric Claims. Evaluation
`eval_34ed61df67b54ed09f08d369f4b63da8` passed every Final Gate threshold
with an overall score of 0.95. The Judge used the existing configurable Qwen
timeout at 240 seconds; no Prompt, model, rule, or retry-count change was made.

Reason

The former acceptance reused a short EOD window for sparse SEC filings,
causing a false Provider-unavailable result. A later run used a 2025 as-of
date with records observed in 2026; the point-in-time gate correctly rejected
them. Frequency-aware windows and an explicit current live dataset preserve
temporal safety. The completed baseline proves that every required capability
reaches the formal runtime, Agent chain, report, and Evaluation, so Phase 3 can
be frozen without new Providers or architecture.

---

## ADR-0029

Date

2026-08-14

Decision

Complete Report v1 with deterministic projections over existing Providers,
not new data sources. SEC Company Facts remains the fundamental authority;
growth and accounting ratios are computed with same-form fiscal alignment and
accepted/filing-time cutoffs. Valuation combines point-in-time SEC EPS, equity,
and shares with Alpaca close and never estimates a missing input. An older
annual EPS is not labeled current TTM after a newer quarter; four discrete
quarters are required in that case. Alpaca
historical OHLC explicitly retains its requested adjustment mode in coverage
metadata. FRED is projected as a latest-value `macro_snapshot_v1`; raw vintages
remain in DuckDB. Community posts remain Evidence, while report presentation
prefers deterministic Stocktwits aggregates.

Report missing-data rendering is role-scoped: Analyst sections disclose their
own gaps, while Bull/Bear/Risk do not repeat unrelated global field lists.
Macro and news facts still require accepted Agent Claims; ReportAssembler does
not promote raw bundle values into new facts. Alpha Vantage is deferred as an
optional P1 enrichment and is not implemented or required.

Reason

The successful Phase 3 acceptance already contained 1,473 FRED observations,
153 Alpaca News records, 63 AAPL bars plus three benchmarks, and sufficient SEC
Company Facts. The report gaps were therefore mostly projection, deterministic
operator, Agent consumption, and presentation defects rather than Provider
absence. Keeping computation deterministic preserves numeric grounding and
point-in-time safety without adding a parallel factual channel.

---

## ADR-0030

Date

2026-08-14

Decision

Use Financial Modeling Prep Stable API as the primary standardized US
Fundamental/TTM/ratio source. SEC EDGAR remains primary for filings, raw XBRL
facts and corporate events; Alpaca remains primary for prices. FMP is disabled
by default, requires `FMP_API_KEY`, and enters the existing controlled HTTP,
normalization, Repository and `ResearchDataBundle` path. No Agent calls FMP.

The implemented endpoint set is `ratios-ttm`, `key-metrics-ttm`,
`income-statement-growth`, plus a bounded quarterly `income-statement` request
for reporting/accepted timestamps. Provider-priority selection never averages
FMP and SEC-derived ratios. A secondary SEC value is retained as an auditable
cross-check with an explicit tolerance and `CONFLICT` quality state.

Provider-standardized metric facts and the existing FRED MacroSnapshot are
promoted into deterministic Validated Claims before Analyst quarantine. This
does not bypass Claim validation: canonical Evidence IDs, exact numeric
literals, point-in-time timestamps and source lineage remain mandatory. The
LLM supplies interpretation but is not responsible for copying or
reformatting already-standardized numeric facts. Versioned contracts derive
missing-data presentation from the final Bundle rather than legacy global
feature flags.

Reason

Repeated live runs proved that the Providers and Bundle contained complete
FMP/FRED data while model formatting variance could turn exact values or
reporting dates into rejected Claims, leaving Fundamental or Macro sections
empty. Standardized facts are deterministic data projection, not model
reasoning. Keeping that projection inside the authoritative Claim path makes
live output reliable without relaxing Evidence, numeric or point-in-time
rules.

Fresh acceptance `20260814T100747Z` completed all real Providers, eight Agents,
Report and real Judge. Report `rep_27ce48e18b5443f297c485405792c535`
contains all 15 required FMP metrics, the full Technical research categories,
five FRED macro categories and attributable Alpaca News. It traced `56/56`
citations, retained accepted grounding for `42/42` numeric Claims, and scored
`0.9674999999999999`. Research Completeness v1 is frozen on this baseline.

---

## ADR-0031

Date

2026-08-14

Decision

Publish and freeze Phase 3 Research Completeness v1 against the credential-free
acceptance manifest `20260814T100747Z`. The release identity is report
`rep_27ce48e18b5443f297c485405792c535`, Evaluation
`eval_041e4ae3647d43c6a8dacc498102d2ca`, dataset
`live_aapl_fmp_completeness_v1`, and evaluation rules `report_quality_v2`.
Generated acceptance databases, source payloads, OAuth state, and reports stay
outside Git under ignored runtime directories. Public documentation records
aggregate validation evidence and reproducible commands without publishing
credentials or presenting research-quality scores as investment performance.

The Phase 3 public surface is an evidence-grounded AI Research Report. Phase 4
and later Factor, Regime, MoE, backtesting, post-training, strategy, portfolio,
and execution concepts remain roadmap items rather than current capabilities.
The suggested immutable release tag is `phase3-research-completeness-v1`.

Reason

The final baseline completed real SEC, FMP, Alpaca, FRED, Stocktwits, Qwen,
Memory, all eight Agents, Report, and Evaluation with every release threshold
passing. Freezing one named manifest prevents later documentation or roadmap
work from silently redefining the Phase 3 evidence. Keeping generated live
artifacts out of source control avoids publishing bulky licensed/runtime data
or local authentication state while retaining an auditable local acceptance.

---

## ADR-0032

Date

2026-08-30

Decision

Adopt `SectorOntology v1` as exactly 18 stable first-level research Sectors
identified by `S01` through `S18`. Industry Chains remain dynamic, versioned
research objects associated with one Sector. Asset `SectorMembership` records
carry chain roles, source, confidence, weight, and half-open
`[valid_from, valid_to)` intervals; a new revision appends rather than replacing
historical classification.

Add a unified research-scope hierarchy with GLOBAL, MACRO, SECTOR,
INDUSTRY_CHAIN, ASSET, and RESEARCH_EPISODE types. This hierarchy is separate
from the existing Memory L0–L4 levels and from the Phase 3 per-request Agent
scope. It requires one root, type-valid parent links, contained validity
intervals, and deterministic cycle rejection.

Persist the minimal foundation in DuckDB tables `sector_nodes`, `sector_edges`,
`sector_memberships`, and `research_scopes`. The supported edge vocabulary is
BELONGS_TO, SUPPLIES, CUSTOMER_OF, COMPETES_WITH, BENEFITS_FROM, EXPOSED_TO,
and DRIVES. No Neo4j, graph algorithm, Sector Agent, Radar, Factor, Backtest,
or trading capability is introduced. The five-asset seed is non-exhaustive and
exists only to validate contracts and temporal behavior.

Reason

The legacy fields on `instruments` can describe only a current classification
snapshot and would destroy history if overwritten. Independent temporal
memberships preserve point-in-time research safety. A narrow DuckDB graph and
scope tree establish Macro-to-Asset research identity without duplicating the
existing Data, Memory, or Agent architectures and leave later Phase 4 services
free to consume stable contracts.

---

## ADR-0033

Date

2026-08-30

Decision

Build `SectorUniverseSnapshot` as an immutable point-in-time projection over
the existing temporal `SectorMembership` records. Store snapshots and
benchmark mappings in the existing DuckDB Sector Repository. A snapshot
records its `as_of`, sorted canonical asset IDs, membership version, source,
coverage diagnostics, quality, and optional benchmark IDs. New membership
states create new snapshots and never update historical rows.

Maintain an optional benchmark candidate for each of the 18 Sectors, but do
not treat a configured ticker as verified. Promote a candidate into a temporal
`SectorBenchmarkMapping` only after the existing Alpaca Adapter returns a real
daily bar in the requested window. Broad proxies such as SOXX for Memory &
Storage and XLK for Consumer Electronics remain explicitly PARTIAL rather than
being represented as exact constituent benchmarks.

Use the current versioned five-asset research universe for Day31 v1 because
the checked-in FMP Adapter does not implement profile, screener,
classification, or constituents, while Alpaca supplies prices/news but not
classification. Promote the approved Day30 mapping into the distinct
`sector_universe_membership_v1` revision with an explicit internal-curation
source so a live snapshot never claims a test fixture as its classification
source. Do not infer a complete universe from SEC SIC or introduce a new
Provider. This is sufficient for the scoped S01/S02/S03 live smoke, but
automatic exhaustive constituents across all 18 Sectors remain a documented
coverage limitation.

Reason

The task explicitly permits the current research universe when FMP constituent
access is unavailable. Separating candidate configuration from live-validated
mapping prevents nonexistent or unavailable ETFs from entering research.
Append-only snapshots preserve point-in-time safety and allow later universe
expansion without rewriting Day31 history.

---

## ADR-0034

Date

2026-08-30

Decision

Define `SectorResearchSnapshot v1` as an immutable deterministic projection of
one point-in-time `SectorUniverseSnapshot`. Reuse the existing
`TechnicalFeatureOperator` for each constituent and benchmark, then compute
Sector market state, breadth, fundamental breadth, and valuation state in one
`SectorStateOperator`. No LLM participates in feature calculation.

Use constituent medians for Sector returns, volatility, drawdown,
fundamentals, and valuation; do not average market capitalization. Define
`excess_return_vs_market` and `excess_return_vs_sector_benchmark` on a
20-session horizon. Define leaders and laggards as constituents whose 20-day
return is respectively above or below the validated Sector benchmark return.
FMP standardized records have priority for canonical ratios when both FMP and
SEC rows exist.

Represent every aggregate with a value, coverage count, universe count, and
AVAILABLE/PARTIAL/MISSING status. Require at least two valid constituents for
a Sector aggregate. A smaller sample remains PARTIAL with a null aggregate,
even when its single issuer observation is available. Persist the result in
the append-only `sector_research_snapshots` table.

Treat DuckDB `TIMESTAMP` round trips as UTC when the existing Repository
returns a naive datetime; DataNormalizer writes normalized UTC and the schema
stores it without timezone metadata. This restoration occurs only for cutoff
comparison, and observations after the `as_of` end-of-day remain rejected.

Reason

Sector features must be reproducible, order-independent, and safe for later
structured research without delegating arithmetic to a model. Explicit sample
coverage prevents the small Day31 universe from creating apparently precise
but misleading Sector aggregates. Append-only state and strict time cutoffs
preserve historical reproducibility.

---

## ADR-0035

Date

2026-08-30

Decision

Connect the existing FRED Macro Pack to deterministic Sector research through
two versioned outputs: `SectorCycleState v1` and `MacroSensitivity v1`. The
cycle state is a five-dimensional descriptive summary of rates, inflation,
labor, growth, and financial stress. It compares the latest transformed
observation with available three- and twelve-month references and reports
RISING, FALLING, STABLE, MIXED, or UNKNOWN. It is explicitly not a Regime
classifier, trained model, or investment signal.

Estimate Sector macro sensitivity using the first validated Sector benchmark,
monthly benchmark returns, and monthly FRED changes. Use a rolling 36-month
window, require at least 24 aligned observations, and report one univariate OLS
beta plus Pearson correlation per series. CPI, core PCE, payrolls, industrial
production, and GDP use year-over-year changes; rates, spreads, unemployment,
and stress series use level changes. Do not introduce multivariate regression,
imputation, extrapolation, or LLM calculation.

Persist each combined result as an immutable `sector_macro_snapshots` row with
source Sector snapshot identity, feature version, status, coverage, and source
IDs. Reject prices, observations, vintages, and ingestion timestamps later
than the Sector `as_of`. Batch persistence of long FRED histories uses one
Repository transaction per table while preserving the existing vintage keys
and read semantics.

Reason

Day33 needs reproducible Macro-to-Sector context before any later Regime work.
Simple descriptive comparisons and independently auditable sensitivity
statistics expose direction and historical association without pretending to
identify causal effects. Explicit sample counts keep quarterly GDP and other
sparse series PARTIAL rather than manufacturing precision. FRED real-time
metadata makes a current acceptance snapshot point-in-time safe; recreating
historical release-by-release backtests would require a separately versioned
vintage dataset and is intentionally out of scope.

---

## ADR-0036

Date

2026-08-30

Decision

Implement `SectorAnomalyRadar v1` as an independent deterministic event
detector over the existing Day30 ontology, Day32 Sector state, Day33 macro
state, normalized OHLCV, corporate events, and news. Support six event types:
price/volume, breadth, earnings, news/company event, macro shock, and
supply-chain propagation candidate. Do not add an Agent, LLM detector,
Regime, Factor, trading action, or new data Provider.

Use transparent rules rather than ML anomaly detection. Price events use a
trailing return z-score and median-volume ratio; breadth uses short/long
participation divergence and cross-sectional dispersion; earnings requires
structured actual and expected values; material news uses an auditable narrow
term set; macro shocks require both a material three-month relative move and a
Day33 sensitivity with sufficient observations. These thresholds are ruleset
v1 configuration constants, not learned parameters or causal claims.

Allow propagation only when effective Industry Chain membership or graph edges
connect the source event to candidate assets. Propagation remains
`PROPAGATION_CANDIDATE`, uses UNKNOWN direction, preserves the original
Evidence IDs, and explicitly defers impact interpretation to later research.

Persist one immutable `SectorAnomalyEvent` body and separate scope links in
DuckDB. Project the exact same summary into the existing L1/L2 Memory service
for effective SECTOR, CHAIN, and source-ASSET namespaces. This reuses the
current hierarchical scope and FAISS infrastructure rather than creating a
Radar Memory hierarchy. Every event and query is bounded by `available_at`,
`ingested_at`, and `as_of`.

Reason

Day35 needs a small, auditable set of noteworthy Sector events rather than a
second narrative system. Deterministic rules make detection reproducible and
allow false positives to be inspected. Separating canonical event storage from
scope links avoids divergent duplicate bodies while preserving both Sector
and asset research retrieval. Knowledge-graph propagation identifies where to
look; it deliberately does not assert who benefits or recommend a trade.

---

## ADR-0037

Date

2026-08-30

Decision

Implement `SectorResearchAgent v1` as an independent research component above
the frozen eight-Agent asset chain. Do not add it to `AgentName`, the Phase 3
role registry, or the asset coordinator. Day36 may later project its accepted
Claims into a separate `SectorContextBundle`; Day35 does not alter that chain.

Compose `SectorResearchInput v1` from one aligned `SectorUniverseSnapshot`,
`SectorResearchSnapshot`, `SectorMacroSnapshot`, optional benchmark mapping,
PIT-safe `SectorAnomalyEvent` rows, effective Industry Chain/membership/graph
context, and the existing `ResearchContextBundle`. The Agent receives these
typed objects from its composition boundary and never receives a Repository,
Provider, DuckDB, or FAISS implementation.

Project those direct upstream objects into a compact invocation-local Evidence
manifest. `SectorResearchOutput v1` contains an authoritative collection of
existing `ValidatedClaim` objects enriched only by a Sector category, an
interpretive `SectorCycleAssessment`, explicit uncertainties/missing data, and
quarantined Claim diagnostics. Narrative is not a second factual channel.
Every accepted Claim must cite exact manifest IDs, bind every Python-extracted
numeric literal exactly, and use `direct_evidence` provenance. A minimum of
three valid Claims and coverage of every HIGH/CRITICAL Radar event are required.

Treat Macro beta/correlation only as historical association, propagation as a
candidate hypothesis, and PARTIAL/proxy/MISSING state as degraded Evidence.
Reject causal upgrades, unsupported numeric transformations, graph mutations,
invented catalysts, and system-generated trading intent. Selected accepted
research Claims may be persisted through the current Memory service as L3
SECTOR/CHAIN trace items with a deterministic lineage header; do not persist a
free-form full narrative or create L4 Regime Memory.

Reason

Day35 needs interpretation over already reproducible Sector intelligence, not
a second metric engine or a ninth asset role. Reusing the Phase 3 Evidence and
Validated Claim architecture preserves strict citation/numeric behavior and
makes later Day36 consumption possible without giving downstream Agents raw
LLM prose. Keeping the interpretive Sector cycle separate from Day33 macro
directions and from a future Regime model prevents a research assessment from
becoming a hidden signal.

---

## ADR-0038

Date

2026-08-30

Decision

Integrate Day35 Sector Intelligence into the frozen eight-Agent asset chain
through one optional, point-in-time `SectorContextBundle v1`. Resolve the
asset's primary Sector and active Industry Chains only from effective temporal
`SectorMembership` rows. Preserve multiple-membership, seed/proxy, PARTIAL,
missing-chain, missing-event, and unavailable-Sector-Agent uncertainty; never
infer membership from a ticker or prompt text.

Project the bundle separately for all eight roles. Analysts receive compact
conditional presentation context but retain their existing role-local raw
asset Evidence validation. Managers receive only relevant accepted Sector
Claims through the existing `validated_claims` route. Their Claims reference
Sector Claim IDs as direct upstream, so provenance reaches Sector state/Radar
Evidence and canonical Provider sources recursively without a second numeric
or citation pass. Radar detail is limited to News/Event, Research, and Risk
projections and is linked to the accepted Sector Claim carrying the event.

Make Sector resolution an optional orchestration dependency of
`ResearchWorkflowService`. An absent or invalid Sector context degrades to the
unchanged Phase 3 workflow; it never triggers Fake data or a Fake model. Add
only minimal usage diagnostics containing provided/used Claim/Event IDs and
context size. Do not introduce a new database table, Agent hierarchy, Memory
layer, trajectory, reward, Factor, Regime, backtest, or trading behavior.

Reason

Day36 must prove Macro-to-Sector-to-Chain-to-Asset is a running information
path, not merely related schemas. A compact optional context preserves the
stable Phase 3 Agent contract and makes failures non-blocking. Direct-upstream
Claim composition keeps each layer responsible for validating only its own
producer while maintaining complete provenance. Role projections prevent the
full Sector report or duplicate Radar prose from entering every prompt, and
ID-only diagnostics prove actual use without creating a learning system before
Phase 4B.

Day36 live closure also makes Sector Claim intent a deterministic Draft-schema
default rather than a model-authored Prompt field. This removes a Prompt/schema
enum drift without weakening Claim intent, Evidence, numeric-grounding, PIT, or
quarantine policy. The smoke runner persists successful credential-free
`SectorResearchOutput` objects so the exact real Sector output can be supplied
to the downstream asset contract and audited independently from its summary.

---

## ADR-0039

Date

2026-08-31

Decision

Adopt `Unified Temporal Contract v1` as the single point-in-time eligibility
rule for Data, Sector, Event, accepted Sector Claim, Memory, and research
context inputs. Preserve existing Provider/domain field names and map them into
nullable `TemporalMetadata` rather than performing a repository-wide rename.
Use one UTC-aware `validate_temporal_access()` entry point and half-open
effective intervals.

Treat event and period time as descriptive only. A record is research-usable
only when every present canonical availability, ingestion, snapshot, and
effective-bound constraint permits it at `research_as_of`. Filing fiscal end
does not replace acceptance/publication time; FRED observation date does not
replace its vintage; a news publication does not replace ingestion; and a
Memory effective time does not replace creation/availability time.

Persist the Memory service clock's `created_at` and reject later-created
Memory during replay even if `effective_ts` is older. Decode legacy DuckDB
naive `TIMESTAMP` values only through an explicitly named UTC storage
compatibility function. Do not interpret naive values using the host timezone
and do not rewrite legacy rows automatically.

Reason

Phase 4B needs replayable future ResearchState and Episode data, but building
those objects before agreeing on visibility would encode leakage into every
later dataset. Existing modules already implemented mostly correct local PIT
checks, yet their rules differed and Memory could be backfilled after the
requested cutoff. A shared contract removes drift while preserving Phase 3
and Phase 4A schemas. Explicit storage compatibility makes legacy behavior
auditable without pretending uncertain historical timestamp provenance is
known.

---

## ADR-0040

Date

2026-08-31

Decision

Establish `ResearchStateSnapshot v1` as the immutable machine-facing research
artifact at one `research_as_of`. Build it only from frozen
`ResearchDataBundle`, compact Sector/Memory context projections, accepted
Claims, and centrally recorded run/version references. The builder cannot call
an LLM or Provider and has no Report input; report prose is never parsed back
into factual state.

Represent features as deterministic numeric, versioned normalized research
state, or semantic/categorical. Available features reference Claim, Evidence,
or artifact IDs without embedding their upstream payload. Normalized features
must name a deterministic transform and version. Accepted Manager Claims stay
machine-state facts by Claim ID and retain recursive lineage through Analyst or
Sector Claims to canonical Evidence.

Keep the Snapshot frozen and identify it with a SHA-256 fingerprint of all
typed inputs. Centralize source run, dataset/data snapshot, Sector/Memory
context, Agent run, Prompt, and model versions in snapshot lineage. Reuse
Unified Temporal Contract v1 for every feature and reject mismatched cutoffs,
future values, unknown upstream Claims, Claim cycles, and direct Claims without
source references.

For historical compatibility, missing frozen artifacts remain
`NOT_AVAILABLE_AT_SOURCE_RUN`. The Phase 3 AAPL Golden Run therefore does not
receive newer Sector/Chain context. The Day36 AAPL State uses its own
SectorContextBundle and retains PARTIAL macro semantics when macro Claims are
available through Sector research but the asset Bundle did not persist direct
FRED observations.

Reason

Reports are presentation artifacts and cannot be a safe dataset or training
source. A small claim/evidence-referenced State preserves the already validated
fact chain while making replay and future dataset construction possible. A
pure builder prevents hidden inference and network drift; explicit historical
missingness prevents later Phase 4 information from contaminating Phase 3
baselines. No Factor, Regime, Episode, reward, backtest, trading, or RL contract
is introduced.

---

## ADR-0041

Date

2026-08-31

Decision

Establish `ResearchEpisode v1` as the immutable, reference-only audit record
of one research process performed under a `ResearchStateSnapshot`. Keep State
and Episode separate: State records what was knowable at `research_as_of`,
while Episode records frozen input identities, minimal Agent execution
metadata, structured Claim identities and counts, existing Sector usage
diagnostics, version references, and optional report identity.

Do not persist private model reasoning, chain-of-thought, raw prompts, or
report prose in an Episode. Reuse the Day36
`SectorContextUsageDiagnostic` contract from a neutral schema module. A
complete Episode requires exact accepted/rejected Claim identity closure; a
historical source that retained only counts materializes as explicitly
`PARTIAL` with named missing metadata and no invented Claim IDs.

Identify an Episode by a deterministic SHA-256 fingerprint of its typed frozen
inputs. Episode construction is offline and cannot call an LLM, Provider, or
live data source. Future Outcomes may reference `episode_id`, but must not
overwrite the original Episode.

Reason

Replay and future training need an auditable record of what the system did,
not hidden model thought. Separating process identity from machine research
state avoids mixing facts with execution metadata, while exact/partial trace
semantics preserve old runs without fabricating precision. Reusing Day36
usage diagnostics prevents a second Sector-observation channel and keeps the
artifact small enough to remain a provenance index rather than a trajectory
platform.

---

## ADR-0042

Date

2026-08-31

Decision

Establish `LearningMemoryMetadata v1` as an optional, structured extension of
the existing L0–L4 Memory records. L0–L4 continue to describe Memory level;
GLOBAL, MACRO, SECTOR, INDUSTRY_CHAIN, ASSET, and RESEARCH_EPISODE continue to
describe the independent Day30 research scope. DuckDB remains authoritative
for metadata and FAISS remains a private similarity index.

Persist the metadata in one additive `memory_items.metadata_json` column with
an idempotent migration. Legacy rows and Day35 JSON-header summaries remain
readable with null structured metadata; they are not guessed, rewritten, or
silently promoted. New records may declare EPISODIC, SEMANTIC, or PERFORMANCE
usage. Day40 operationalizes EPISODIC for selected validated Claims, thesis,
risks, catalysts, important Events, State references, and Episode references.
It does not define an undifferentiated report content type.

EPISODIC records require `episode_id`, `research_state_id`, versioned Scope,
canonical source references, structured temporal metadata, and Claim/Event
lineage appropriate to their content kind. SEMANTIC records require an
explicit CANDIDATE, VALIDATED, or RETIRED lifecycle; a record tied to one
Episode cannot be marked VALIDATED. PERFORMANCE records reserve only Episode,
Outcome, Factor, and research references and compute no performance value.

Both legacy semantic search and `ResearchContextBundle` retrieval use the
Day37 Unified Temporal Contract. Effective time, persisted creation time, and
structured availability are all gates; the strict latest availability must
be no later than `research_as_of`. Retrieval may filter structured Scope,
usage class, and Episode identity and retains query filters, score, reason,
source, Episode/State linkage, and Memory version. A zero-result retrieval is
explicitly `empty_valid`; similarity never creates a historical analog or
promotes Semantic Truth.

Reason

Learning workflows need replayable links between Scope, time, State, Episode,
and retrieval without replacing the proven DuckDB/FAISS implementation or
turning reports into training data. An additive JSON sidecar avoids a risky
table rewrite while giving new writes a strict typed contract. Reusing Day37
prevents a second future-leakage policy, and explicit lifecycle/reference-only
rules keep Day40 from inventing Outcome, Factor, performance, or durable
knowledge before their own approved contracts exist.

---

## ADR-0043

Date

2026-08-31

Decision

Establish `ResearchEpisodeAttribution v1` as an immutable companion artifact
that records which Memory, Sector Claim, and Radar Event context was provided,
selected, and used by each Agent run in a ResearchEpisode. Do not mutate the
Day39 Episode, duplicate the Day36 collection path, or store private reasoning.
Reuse `SectorContextUsageDiagnostic` through an adapter and require an explicit
accepted Claim reference before new-run context may be marked used.

Establish `MemoryRetrievalRecord v1` for every observed Memory retrieval,
including an explicit `empty_valid` record when no relevant Memory is selected.
Record query/purpose, role/run/Episode/cutoff, eligible candidates, selected
IDs, rank, score, reason, Scope filters, snapshot identity, source lineage, and
future exclusion count. Candidate recording occurs after authoritative DuckDB
metadata filtering and Day37 temporal validation; FAISS remains a private
similarity implementation.

Preserve truthful historical degradation. If a PARTIAL source Episode retained
Day36 used IDs but omitted accepted asset Claim IDs, record
`NOT_AVAILABLE_AT_SOURCE_RUN` and an empty `used_by_claim_ids`; never infer the
missing Claim. If the source run did not persist a Memory retrieval, do not
manufacture an empty RetrievalRecord. All future Outcome/usefulness fields are
status-only and their score remains null until an approved later contract.

Reason

Learning and replay need exact observation lineage without confusing prompt
presence with evidentiary use. One composable contract avoids incompatible
Memory/Sector/Event trackers, while accepted Claim linkage preserves the
authoritative Evidence-to-Claim chain. Explicit historical absence prevents
retroactive precision and Day37 reuse prevents a second time-safety policy.

---

## ADR-0044

Date

2026-09-01

Decision

Establish `ResearchDatasetSample v1` as a reference-only, immutable,
point-in-time sample linking one Asset and cutoff to its frozen
ResearchState, ResearchEpisode, data snapshot, optional Sector/Memory context,
optional ResearchEpisodeAttribution, Agent runs, and centralized version
lineage. Do not copy State, Claims, Evidence, Memory, Report, or SectorContext
payloads into the Sample.

Build Sample identity from canonical sorted JSON containing the State,
Episode, and optional Attribution identities/fingerprints plus the dataset
schema/build version. Materialization time is not identity-bearing. Reuse the
Day37 temporal validator for every upstream artifact and reject mismatched
State/Episode/Attribution identities or cutoffs.

Persist validated Samples in the existing DuckDB through the immutable
`research_dataset_samples` Repository and write a small credential-free
artifact manifest. Duplicate audit columns are verified against Sample JSON
on read. Historical absence is explicit: Phase 3 receives no later Sector
backfill, PARTIAL Day36 trace quality remains PARTIAL, and empty-valid Memory
does not invalidate a Sample.

Day42 computes no Outcome or future return. `label_ids` remains empty and
`label_status` remains `PENDING` or `NOT_AVAILABLE`. Factor, Reward, Regime,
Backtest, SFT, DPO, Offline RL, and model training remain out of scope.

Reason

Future replay and evaluation need a stable row-level unit without duplicating
large upstream artifacts or creating a second provenance graph. Referencing
the already frozen State, Episode, and Attribution keeps the fact chain
auditable, while one shared temporal policy prevents Dataset-specific future
leakage. DuckDB plus JSON manifests meets current scale and operational needs
without introducing a feature store or data lake.

---

## ADR-0045

Date

2026-09-01

Decision

Close Phase 4B with `GoldenReplayManifest v1`, a credential-free audit result
that deterministically rebuilds ResearchState, ResearchEpisode, optional
Research Attribution, and ResearchDatasetSample from frozen artifacts. Replay
is explicitly not a new research run: its service has no Provider, LLM,
Gateway, or live ingestion dependency and records literal zero call counts.

Require exact equality with the previously materialized State, Episode, and
Attribution, and exact Dataset Sample equality excluding audit `created_at`.
Stable Replay identity is computed from canonical source artifact and rebuilt
artifact identities. Repeated builds must preserve State, Episode, Dataset
Sample, and Replay identities.

Use Unified Temporal Contract v1 for the Golden leakage challenge. Future
News, Radar Event, Memory, Sector Membership, and Filing fixtures must be
rejected before a Replay can pass. Preserve historical absence rather than
enriching it: Phase 3 receives no later Sector/Chain/Memory context; Day36
retains its original empty-valid Memory and partial downstream Claim identity.
Trace samples may be PARTIAL only when they name the exact metadata omitted by
the source run. Missing historical identities are never inferred.

Reason

Phase 4B needs a single executable proof that its temporal, State, Episode,
Memory, Attribution, and Dataset contracts compose without network access or
future leakage. Exact identity reproduction is stronger and more auditable
than rerunning Agents for a merely similar output. Truthful partial traces
preserve the evidence boundary while exposing what older instrumentation did
not retain.

---

## ADR-0046

Date

2026-09-14

Decision

Reset Phase 4C ownership around a hard Research/Quant repository boundary.
The long-term system has three layers: Research Intelligence, Quant Alpha /
Strategy, and Portfolio / Execution. The current `deepinsight` repository owns
only Research Intelligence and Opportunity Discovery. A future independent
`deepinsight-quant` repository owns Quant Alpha, selection, timing, holdings,
Regime/MoE routing, backtest, portfolio, risk transformation, and execution.

Define Planetary Alpha（行星阿尔法）as low-cost, repeatable traditional
quantitative Alpha/Factor over a broad PIT Market Universe. Define Satellite
Alpha（卫星阿尔法）as proprietary, attributable Research-produced descriptors
derived from Evidence, Claims, ResearchState, Sector/Industry-Chain research,
events, debate, risk, and Memory. Satellite Alpha inside `deepinsight` is raw
research output, not a validated Factor exposure, rank, signal, or position.

Freeze the handoff direction as Evidence → Validated Claim → Research State
Feature → Satellite Alpha Observation → ResearchQuantHandoffBundle. Quant may
later transform that bundle into processed Factor exposures, Alpha signals,
strategies, and portfolios. `deepinsight` may not emit z-scores, neutralized
Factors, IC metrics, buy/sell scores, trade signals, position scores/weights,
or orders. Satellite intent is `SELECTION`, `TIMING`, or `BOTH`, but all
ranking and decision semantics remain Quant-owned.

Require a selection-bias safeguard: the Research Candidate Universe cannot
replace the independent Base Quant PIT Market Universe. Planetary Factor
research and validation must always use the full Quant universe; DeepInsight
Opportunity Discovery only helps form the expensive Research Candidate and
Coverage pools.

Supersede the ownership implied by older Phase-Two reserved Factor Miner,
router, strategy, training, backtest, portfolio, and execution interfaces and
`p2_*` columns. Retain them as non-operational historical compatibility
artifacts and 501 boundaries until a later migration removes or relocates
them; do not activate them in this repository. ResearchState features remain
Research Features. Legacy factor/regime/router/reward names in nullable fields
do not authorize computation.

Day44 changes governance documentation only. It introduces no Satellite Alpha
schema, Opportunity Candidate schema, handoff runtime, Quant repository,
Factor, Regime, strategy, portfolio, or execution code. Phase 3, Phase 4A, and
Phase 4B contracts—including ValidatedClaim grounding, temporal rules,
ResearchState/ResearchEpisode identity, and Golden Replay—remain frozen.

Reason

Research interpretation and large-universe Quant processing have different
cost, validation, and operational requirements. Keeping them in one repository
would encourage opaque AI scores, selection-biased Factor research, and hidden
trading semantics in research artifacts. A reference-only handoff preserves
DeepInsight's evidence and PIT advantages while allowing a future Quant system
to maintain a complete universe and independently validate incremental Alpha.

---

## ADR-0047

Date

2026-09-15

Decision

Adopt Satellite Alpha Ontology v1 as versioned, attributable raw Research
descriptors. Separate stable `SatelliteAlphaDefinition` meaning from PIT
`SatelliteAlphaObservation` values. Selection/Timing/Both are intended research
usage only and do not authorize ranks, Quant Factors, signals, or decisions.

Require explicit comparison and coverage semantics. Missing inputs must never
be numeric zero. Complex families remain decomposed components with unit,
scale, transform version, section-qualified State feature references, and
Claim/Evidence/artifact lineage. Observation identity uses canonical semantic
content and excludes `created_at`; `available_at` remains an independent PIT
consumption boundary.

Implement only deterministic Evidence Strength inventory and truthful partial
State projections on Day45. History-dependent Timing families remain
`REQUIRES_HISTORY`; `PEER_GROUP` remains unsupported without a formal PIT
contract. The mapper consumes frozen ResearchState and optional Episode, calls
Unified Temporal Contract v1, and makes zero LLM/Provider calls. It does not
parse report prose.

Do not expand ResearchState v1. Its current accepted structured content can
support several partial descriptors, but logic stage, expectation direction,
risk component type, catalyst/invalidator identity, debate disposition,
canonical Sector ID, and event identity/time are not retained as formal fields.
Future State versions may preserve those semantics only from already accepted
upstream structure; they must not request another LLM score.

Reason

A small definition/observation split provides stable, interpretable research
semantics while preserving historical truth, provenance, and the Research/
Quant repository boundary. Explicit partial and history-required states are
safer than opaque synthetic scores or inferred backfill.

---

## ADR-0048

Date

2026-09-15

Decision

Produce Day46 Selection Satellite observations only from frozen structured
State features, existing accepted Claim paths, and a compact PIT projection of
SectorContext event identities. Exact versioned feature names may carry
alignment, expectation direction/subtype, logic stage, and decomposed chain
semantics. Claim prose is never parsed to infer a missing category.

Map existing Bull/Bear paths deterministically to disagreement and preserve
the existing Risk Agent sections as separate coarse components. Sector context
presence alone remains UNCERTAIN rather than positive. Detailed risk and chain
components remain PARTIAL when State lacks their accepted structured source.
ResearchState v1 and ResearchEpisode identity remain unchanged.

Adopt `OpportunityCandidate v1` as a Research qualification artifact over
Selection Observations. Eligibility is an auditable union of structured
Sector/Chain alignment, expectation change, material event/logic stage,
accepted Research Manager thesis, structured debate, or structured Risk
review. Evidence Strength or State presence alone cannot qualify an asset.
There is no weighted score or minimum-score threshold.

Candidate identity is deterministic over research semantics and reference-only
lineage and excludes `created_at`. Candidate availability is the latest source
Observation availability. Qualified candidates may be PARTIAL, while
insufficient inputs remain explicit. No rank, Top-K, Factor exposure, target
price, trade action, position, or portfolio field is permitted.

Reason

Exact structured mappings increase currently supported Selection coverage
without inventing facts or another LLM scoring pass. A transparent eligibility
artifact provides a safe Research-to-future-Quant consideration boundary while
leaving all comparison, ranking, and decision logic to `deepinsight-quant`.

---

## ADR-0049

Date

2026-09-15

Decision

Adopt `ResearchStateTransition v1` as a deterministic, reference-only derived
research artifact. Select the nearest strictly earlier same-Asset
ResearchState; require both States to remain independently PIT-valid; reject
same-time and future predecessors. Prefer explicit lineage when a future State
contract supplies it, but do not infer lineage using embeddings or prose.

Project Day47 Timing semantics through the existing
`SatelliteAlphaObservation`. Add only optional previous-State and transition
references to that contract. Two grounded expectation points may describe
direction, delta, and rate; at least three are required for acceleration or
deceleration. Event and catalyst windows use versioned calendar thresholds and
separate schedule availability from later outcome availability.

Keep existing Memory L0–L4 and DuckDB/FAISS boundaries unchanged. Retrieved
Memory is reference-only lineage and must pass Unified Temporal Contract v1.
Do not add a Timing Memory database, an L5 layer, model calls, Quant timing,
ranking, signals, positions, or execution semantics.

Reason

Immutable ordered State comparison provides auditable historical continuity
without rewriting frozen research or crossing the Research/Quant boundary.
Explicit missing coverage is safer than fabricated predecessors, neutral
values, prose-derived categories, or leaked later outcomes.

---

## ADR-0050

Date

2026-09-15

Decision

Adopt `ResearchQuantHandoffBundle v1` as the only formal, versioned export from
DeepInsight Research to future `deepinsight-quant`. Export canonical Asset and
cutoff, ResearchState/ResearchEpisode IDs, optional OpportunityCandidate and
ResearchStateTransition IDs, compact Selection/Timing Satellite references,
explicit coverage/quality, source run/data snapshot, version manifest, and
reference-only provenance. Do not copy internal Research payloads.

Candidate and Transition linkage is optional. Qualified, insufficient,
negative, partial, source-run-unavailable, and history-required Research must
remain exportable so the future Quant system does not receive a
selection-biased positive-only feed. Missing remains categorical and never
becomes zero or a score.

Derive `bundle_id` from canonical semantic content and sorted Observation
references; exclude `created_at`. Require exact Asset/cutoff/State/Episode
alignment, Candidate Observation closure, Transition termination at the
current State, source feature/provenance references, and Unified Temporal
Contract-compatible materialization. Export sorted-key JSON or ordered JSONL
with a credential-free deterministic batch manifest.

The handoff ends Research ownership. It must not contain Planetary Alpha,
Factor exposure/normalization/rank, IC, expected return, Top-K, signals,
selection/timing decisions, Holdings, Regime/MoE, portfolio, orders, or
execution. Its Builder and exporter make zero LLM and Provider calls.

Reason

A small reference-only wire contract decouples future Quant implementation
from Research internals while preserving historical truth, negative examples,
semantic versions, PIT safety, and recursive provenance. JSON/JSONL provides a
stable artifact boundary without prematurely introducing transport or storage
infrastructure.

---

## ADR-0051

### Freeze Phase 4 as Research Intelligence v1 after Day49 Golden Acceptance

Status: Accepted

Decision

Freeze the current `deepinsight` repository at the versioned
`ResearchQuantHandoffBundle v1` boundary. Day49 accepts Phase3 AAPL and the
Day36 sector-aware real-Qwen AAPL run through deterministic frozen-artifact
replay, plus explicitly labelled Selection and Timing contract fixtures. The
acceptance makes zero Provider and LLM calls, preserves source-run missingness,
uses the unified temporal validator, and keeps `(asset_id, research_as_of)`
unique in every Handoff batch.

Treat Satellite Alpha as Research descriptors only. OpportunityCandidate is a
research opportunity object, not ranking or advice. Timing observations are
State evolution, not entry/exit. Quant validation, universe, Factor
processing, IC/RankIC, Top-K, strategy, portfolio, and execution remain outside
this repository.

Do not create the proposed release tag while the accepted Phase 4 tree remains
uncommitted. Tag only a reviewed commit containing the exact accepted files.

Reason

The Golden Acceptance proves deterministic identity, PIT exclusion,
provenance, negative/partial coverage, and external-consumer readability while
preserving the Research/Quant ownership boundary. It does not prove predictive
Alpha, Memory usefulness, or trading performance.

---

## ADR-0052

### Use one explicit PIT Sector artifact at the live report composition root

Status: Accepted

Decision

Allow `scripts.live_report` to accept one prebuilt `SectorContextBundle` via
`--sector-context`. Validate its canonical Asset identity and exact
`research_as_of` before any network request, wrap it with the existing
`AssetSectorContextResolver` contract, and inject that resolver into the same
`ResearchWorkflowService` used by the standard live report path. Preserve the
legacy Phase 3 degradation path when no artifact is supplied. Do not duplicate
Day36 Sector construction, rerun a Sector Agent inside Report assembly, or let
the Report create Sector facts.

Move record-to-temporal compatibility mapping out of the eager Services export
package into neutral `src.temporal_mapping`, retaining
`src.services.temporal` as a compatibility export. Lazily expose Memory runtime
services so importing Memory contracts from Sector schemas does not initialize
retrieval, Services, Golden Replay, and Sector schemas recursively.

Reason

The Phase 4 runtime capability already existed below the composition root; the
live entry had simply omitted the resolver dependency. Explicit artifact
injection preserves PIT alignment and avoids a second Sector pipeline. Neutral
temporal mapping and lazy runtime exports remove the two concrete package
initialization cycles without weakening the Unified Temporal Contract or
renaming frozen schemas.

---

## ADR-0053

### Adopt Numeric Grounding Equivalence v1 without weakening Claim quarantine

Status: Accepted

Decision

Validate Analyst and Sector Claim numerals through one shared semantic
grounder. Digits embedded in an exact canonical identifier are presentation
components only when that complete identifier occurs in the Claim's bound
Evidence. A separate human-readable duration such as `10-year` still requires
explicit `window_value`/`window_unit` or equivalent formal window metadata;
opaque keys such as `change_5d` do not provide it.

Treat decimal spellings with equal `Decimal` value as the same fact. Permit a
shorter decimal rendering only when it is the exact deterministic rounding of
a specifically bound Evidence numeric token and retains at least six
significant digits. Do not introduce epsilon matching, percentage/ratio,
basis-point, currency, unit, or annualization conversions. Preserve the
Evidence ID and source token for every successful match.

Partial/candidate disclosure, mandatory HIGH-event accepted-Claim coverage,
Claim lineage, PIT validation, and the minimum of three accepted Sector Claims
remain unchanged.

Reason

Exact string matching incorrectly quarantined high-precision values rendered
with safe decimal precision, while the old tokenizer did not formally
distinguish identifier digits from facts. The versioned semantic policy removes
that false positive without allowing ungrounded duration language or material
numeric changes.

---
# ADR: Phase 4 live FMP precheck is configuration-only

**Status:** Accepted — 2026-09-15

Phase 4 release acceptance must not execute `scripts.smoke_fmp` before
`scripts.live_report`. That smoke is a complete data acquisition rather than a
configuration check and can consume the Provider rate limit immediately before
the authoritative run. Operators use
`scripts.live_report --configuration-preflight`, which performs zero Provider
data requests. The subsequent full invocation owns one run-scoped FMP
acquisition, validates its `FMPProviderSnapshot`, and reuses the same snapshot
for formal ingestion and downstream consumers.

The invariant is: **PRECHECK != ACQUISITION; ACQUIRE ONCE; VALIDATE ON
SNAPSHOT; REUSE DOWNSTREAM**. Persistent HTTP 429 remains fail-closed; no old
snapshot, Fake Provider, or unbounded retry is allowed.

---

## ADR-0054

### Scope live reruns and frozen materialization to one report execution

Status: Accepted

An authorized live repair may reuse one exact run-scoped acquisition only when
Asset, canonical `research_as_of`, request window, and snapshot identity match.
`--resume-acquired-run --rerun-research` skips Provider acquisition and
ingestion, but reruns the Agent/Report layer when a versioned Prompt changes.
Live manifests and downstream State/Episode materializers select Agent runs by
the resulting `report_id`; two research executions in one DuckDB must never be
merged into one ResearchState or ResearchEpisode.

At the Qwen Judge boundary, compatibility normalization remains an exact
allowlist. The observed `known_missing_data` evidence label maps to the existing
`diagnostic` category; arbitrary evidence kinds remain invalid. Complete ISO
timestamps are structured metadata in acceptance diagnostics, so their
components are not independently reclassified as financial numeric facts.
Numbers outside the timestamp remain subject to Numeric Grounding v2.
