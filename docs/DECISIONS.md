# Architecture Decisions

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
