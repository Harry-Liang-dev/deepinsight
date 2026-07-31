# API

## Application

The Phase One ASGI application is created by `src.api.create_app`. The factory
accepts typed settings and an `ApiServices` container, so tests and deployment
composition can replace report, task, Memory, and snapshot services without
changing route code.

The default `apps.api.main:app` is safe to start without infrastructure. Its
health endpoint works, while unconfigured report generation and Memory
operations fail explicitly rather than opening DuckDB, FAISS, or an LLM
Provider during import.

`apps.api.offline_main:app` is a separate deterministic demonstration entry.
It injects the complete local application workflow with fixed provider data,
Fake LLM responses, Fake Embedding, temporary DuckDB, and temporary FAISS.
It supports the same public report routes without an API key or network call.
The temporary artifacts are removed when that demo process exits.

## Phase One endpoints

| Method | Path | Success | Contract |
|---|---|---:|---|
| GET | `/health` | 200 | application liveness and environment |
| POST | `/v1/reports/generate` | 202 | `GenerateReportRequest` → `TaskStatusResponse` |
| GET | `/v1/reports/jobs/{job_id}` | 200 | `TaskStatusResponse` |
| GET | `/v1/reports/{report_id}` | 200 | `ResearchReport` |
| POST | `/v1/memory/write` | 201 | `MemoryWriteRequest` → `MemoryWriteResult` |
| POST | `/v1/memory/search` | 200 | `MemorySearchRequest` → `MemorySearchResponse` |
| GET | `/v1/memory/snapshot/{snapshot_date}` | 200 | safe snapshot metadata |

The task-status path resolves the API task specification's previously
unconfirmed status-query requirement. A report request is accepted in
`queued` state. The instance-local task service then records `running` and
either `completed` with `report_id`, or `failed` with safe `ErrorInfo`.

This Phase One implementation uses FastAPI background tasks and in-process
state. It has no distributed queue: jobs are not durable across process
restarts, and a deployment must run one API worker if it relies on this task
status implementation. A later durable task service can replace the injected
protocol without changing routes.

The injected report generator is `ResearchWorkflowService`. It owns only
application sequencing: ingestion, normalized context reads, document
indexing, deterministic feature calculation, one Memory search, fixed Agent
coordination, and report finalization. Routes remain unaware of all storage,
vector, provider, LLM, and Agent implementations.

Snapshot GET only queries metadata for an existing snapshot; it never creates
one. Responses contain logical artifact names only and reject absolute or
nested filesystem paths.

## Memory service boundary

`MemoryService.write(MemoryWriteRequest) -> MemoryWriteResult` accepts one
validated L0–L4 item. A source reference and creator are mandatory. The result
contains the stable Memory ID plus opaque namespace/vector identifiers for
operational traceability; no FAISS object is returned.

`MemoryService.search(MemorySearchRequest) -> MemorySearchResponse` performs
semantic retrieval across requested levels and then applies exact namespace,
optional asset, minimum-importance, expiry, and `top_k` filters. Each result
contains:

- Memory ID, level, namespace key, optional asset, type, and text
- cosine similarity score and effective timestamp
- importance score and creator
- the stored `SourceReference`

`time_decay_days` is accepted and validated, but it does not alter ranking
until MASTER_SPEC defines a decay formula. The service never generates a
source or excerpt reference.

## Error response

All errors use one envelope:

```json
{
  "error": {
    "code": "report_not_found",
    "message": "Research report 'report-1' was not found.",
    "retryable": false,
    "details": null
  }
}
```

Stable mappings are:

| HTTP status | Error code |
|---:|---|
| 404 | `job_not_found`, `report_not_found`, `snapshot_not_found`, or `http_not_found` |
| 422 | `validation_error` |
| 500 | `internal_error` |
| 501 | `phase_two_not_implemented` |
| 503 | `service_unavailable` |

Unexpected exception messages are not returned to callers. Validation details
contain field location, safe validation message, and validation type.

## Phase Two placeholders

The following routes always return HTTP 501 with no business side effect:

- `POST /v1/phase2/factors/mine`
- `POST /v1/phase2/router/select`
- `POST /v1/phase2/training/run`
- `POST /v1/phase2/backtest/run`
- `POST /v1/phase2/execution/paper`
- `POST /v1/phase2/execution/live`

Authentication, authorization, CORS, rate limiting, user accounts, payment,
and frontend behavior remain unimplemented because Phase One does not define
them.
