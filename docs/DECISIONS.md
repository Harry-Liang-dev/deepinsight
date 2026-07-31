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
