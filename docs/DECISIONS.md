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
