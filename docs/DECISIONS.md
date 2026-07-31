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
