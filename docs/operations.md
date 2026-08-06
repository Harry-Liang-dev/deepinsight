# Operations

## Python development environment

DeepInsight targets Ubuntu and Python 3.12. Conda provides the interpreter;
`uv` resolves and installs all project dependencies declared in
`pyproject.toml`.

Do not run `uv init` in this repository. Do not create a project-local
`.venv`.

### Create the Conda environment

For a new environment:

```bash
conda env create --file environment.yml
conda activate deepinsight
```

For an existing `deepinsight` environment:

```bash
conda env update --name deepinsight --file environment.yml
conda activate deepinsight
```

Verify the interpreter before installing:

```bash
test -n "$CONDA_PREFIX"
test -x "$CONDA_PREFIX/bin/python"
"$CONDA_PREFIX/bin/python" --version
```

The version must satisfy `>=3.12,<3.13`.

### Install project dependencies

Install the editable project and development dependency group into the active
Conda interpreter:

```bash
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

`pyproject.toml` is the only Python dependency declaration source.
`requirements.txt` is not used.

### Run checks

```bash
"$CONDA_PREFIX/bin/python" -m pytest
"$CONDA_PREFIX/bin/python" -m ruff check .
"$CONDA_PREFIX/bin/python" -m mypy
"$CONDA_PREFIX/bin/python" -m black --check .
```

The equivalent Make targets are:

```bash
make install
make check
```

### Dependency boundary

The Phase One environment does not install PyTorch, torchvision, torchaudio,
CUDA Toolkit, reinforcement-learning frameworks, backtesting engines, or
execution-system dependencies.

## Application configuration

`src.core.AppSettings` is the single application configuration entry point.
Configuration precedence is:

1. Explicit values supplied while constructing a settings object
2. Process environment variables
3. A local `.env` file
4. Typed defaults

Create a local file from the committed example:

```bash
cp .env.example .env
```

Never put a real key in `.env.example`. The local `.env` file is ignored by
Git.

Important environment variables:

| Variable | Purpose |
|---|---|
| `DEEPINSIGHT_ENV` | `development`, `test`, or `production` |
| `DEEPINSIGHT_TIMEZONE` | Application timezone |
| `DEEPINSIGHT_DUCKDB_PATH` | DuckDB file path |
| `DEEPINSIGHT_FAISS_ROOT` | FAISS index root |
| `DEEPINSIGHT_SNAPSHOT_ROOT` | Snapshot root |
| `DEEPINSIGHT_BACKUP_ROOT` | Backup root |
| `DEEPINSIGHT_LOG_LEVEL` | Validated stdlib/structlog level |
| `OPENAI_API_KEY` | OpenAI secret; may be empty before LLM work starts |
| `OPENAI_MODEL_DEFAULT` | Default reasoning model |
| `OPENAI_MODEL_FAST` | Faster model |
| `OPENAI_EMBEDDING_MODEL` | Embedding model |
| `OPENAI_TIMEOUT_SECONDS` | Per-request OpenAI timeout in seconds |
| `OPENAI_MAX_RETRIES` | Additional retries performed by the official SDK |
| `OPENAI_STORE_REMOTE` | Whether OpenAI may retain Responses API output |

Application processes must call `load_settings()` and receive the resulting
object through dependency injection. Business modules must not read
`os.environ` directly.

Logging initialization is explicit:

```python
from src.core import configure_logging, load_settings

settings = load_settings()
configure_logging(settings.logging)
```

## DuckDB initialization

The DuckDB file path is read from `StorageSettings.duckdb_path`. Initialize all
Phase One tables and indexes from the active Conda environment:

```bash
"$CONDA_PREFIX/bin/python" scripts/bootstrap_duckdb.py
```

To target a non-default database, inject the path through configuration:

```bash
DEEPINSIGHT_DUCKDB_PATH="data/duckdb/platform.duckdb" \
  "$CONDA_PREFIX/bin/python" scripts/bootstrap_duckdb.py
```

Bootstrap is idempotent and can be run repeatedly without deleting existing
records. It does not enable DuckDB FTS and does not initialize FAISS.

Database tests always create a separate file below pytest's temporary
directory. They never read or write the configured development database.

### Connection and writer boundary

- Application code accesses DuckDB only through `src.repositories`.
- Connections are opened for one scoped operation and then closed.
- Writes use explicit commit-or-rollback transactions.
- Writes made through one `DuckDBDatabase` instance are serialized in-process.
- Deployment must designate one writer process for the DuckDB file. The
  in-process lock is not a cross-process or distributed lock.
- Readers must not open the file with incompatible DuckDB configuration while
  the writer is active.

Schema changes currently use idempotent bootstrap DDL only. No migration
framework is installed; a formal migration strategy remains a later decision.

## Research report pipeline

`ResearchCoordinator` owns the fixed Agent execution sequence and Agent Run
audit. `ReportAssembler` begins from its structured `ResearchTaskResult`; it
does not repeat inference or retrieval.

The report lifecycle is:

1. Validate the single-asset request, all standard sections, all eight Agent
   outputs, and every citation.
2. Build Markdown and JSON from one in-memory standard section representation.
3. Persist the report and sections with `running` status.
4. Write an attributable `report_trace` item to L3 Memory under
   `REPORT:<report_id>`.
5. Persist the same report with `completed` status.

Report persistence and Memory are injected through narrow interfaces. The
report package does not import DuckDB or FAISS implementations and never calls
an external Provider or LLM. If persistence or Memory fails, the completed
state is not written.

## FastAPI service

Start the safe default application from the active Conda environment:

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn apps.api.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Verify liveness:

```bash
curl --fail http://127.0.0.1:8000/health
```

OpenAPI is available at `/openapi.json`; the interactive development
documentation is available at `/docs`.

`apps.api.main:app` intentionally does not construct DuckDB, FAISS, Memory, or
LLM dependencies. A deployment composition must inject configured application
services before report and Memory endpoints are usable. Until then, those
operations return an explicit service failure or a failed report task rather
than silently touching local storage or an external network.

Report work uses a process-local FastAPI background task. Task status is held
in memory, is lost on restart, and is not shared between workers. Run one
worker for this MVP implementation. Do not use it as a durable production job
queue.

API-focused checks are:

```bash
"$CONDA_PREFIX/bin/python" -m pytest tests/unit/api tests/integration/api
```

## Offline end-to-end workflow

Run a complete no-credential demonstration API:

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn apps.api.offline_main:app \
  --host 127.0.0.1 \
  --port 8001
```

The offline composition uses fixed US single-asset data, Fake LLM responses,
Fake Embedding, and an ephemeral temporary storage root. It exercises:

1. FastAPI report submission and task state
2. provider ingestion, normalization, raw text, and DuckDB writes
3. document embedding and persistent FAISS sidecars
4. attributable Memory retrieval
5. four Analysts and four Managers with Agent Run audit
6. ten-section report assembly, report persistence, and L3 trace Memory
7. report query through the public API

It never instantiates an OpenAI client. An `OPENAI_API_KEY` is neither required
nor used by this entry point, and LLM logs contain request fingerprints rather
than prompts, payloads, or credentials.

Run the deterministic success and failure checks:

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/integration/test_research_workflow_e2e.py -q
```

The test rebuilds DuckDB and FAISS Repository objects after generation to
verify persisted reports, document vectors, L1 Memory, and L3 report Memory
remain readable. A Fake LLM timeout case verifies that the API job becomes
`failed` and no report is silently created.

The offline app is not the unresolved Worker/Redis architecture. Report job
state remains process-local and one worker is required. Redis message shape,
durable job storage, multi-process DuckDB locking, Scheduler timing, Web UI,
snapshot consistency, and recovery policy remain pending and are not inferred
by this integration.

## Data ingestion

Provider source metadata lives in `config/providers.yaml`; it contains no
credentials. All production credential values remain environment-owned.
Wind, CNINFO, HKEXnews, SEC EDGAR, FRED, Alpaca, X, LSEG, and Bloomberg are
explicit connector boundaries in the first release. They do not make network
requests until a separately authorized implementation and credentials are
configured.

Offline development and tests use `FakeProviderAdapter`. Construct the
ingestion service by injecting the DuckDB Repositories, `DataNormalizer`, a
configured `RawTextStore`, and a configured `DocumentChunker`. No business
module reads environment variables or opens a Provider connection during
import.

Raw document text is stored verbatim as UTF-8 below the injected raw-data root.
The source directory and file name are deterministic hashes, and
`text_documents.raw_text_path` retains the resulting reference. Source ID,
source URL, publish timestamp, checksum, and ingestion/creation timestamp are
stored in canonical records where the MASTER_SPEC schema provides them.

The ingestion request supports `full`, `incremental`, and `repair` job types.
Supplying `target_date` enables EOD ingestion; document start and end dates
must be supplied together. Every run transitions from `running` to either
`completed` or `failed`. On failure, inspect `ingestion_jobs.error_message` and
`rows_written`; already committed normalized rows are attributable and may be
replayed idempotently with a repair job.

Document chunks are prepared for, but not written to, FAISS. Their metadata
explicitly says `embedding_status: pending`. The Embedding/FAISS module must
generate the vector before changing that state.

Default ingestion tests are fully offline:

```bash
python -m pytest \
  tests/unit/adapters \
  tests/unit/services/test_data_normalization.py \
  tests/unit/services/test_document_processing.py \
  tests/integration/services/test_data_ingestion.py
```

## Memory and FAISS

Construct `FaissVectorRepository` from `StorageSettings.faiss_root`, the same
model name exposed by the injected Embedding service, and its explicit vector
dimension. Construct `MemoryService` with `MemoryItemRepository`, the vector
Repository, and the Embedding service. Agents and other upper modules must
depend on `MemoryService`; they must not import or retain FAISS indexes.

Each namespace is persisted below the configured FAISS root:

```text
memory_L2_v1/
├── index.faiss
├── vector_meta.parquet
└── manifest.json
```

Files are written to same-directory temporary paths and replaced individually.
The manifest, index dimension, vector count, and vector-ID metadata are
validated on reload. A partial or incompatible namespace raises a persistence
error instead of being treated as an empty index.

Memory writes persist the vector first and then the DuckDB sidecar. If DuckDB
rejects the record, the service removes the new vector. A failed compensation
raises `MemoryConsistencyError` and the namespace must be rebuilt from
authoritative `memory_items`. `MemoryService.rebuild_level(level)` performs
that rebuild. Writes are serialized within each Repository instance; the
deployment must retain the existing single-writer process rule.

Document ingestion leaves chunks pending. Run
`DocumentEmbeddingService.index_document(document_id)` to embed those chunks,
persist them in their configured document namespace, and update their
Repository-managed status. Source documents and URLs remain in DuckDB and are
not synthesized from vector metadata.

Production OpenAI embedding calls require an explicitly injected output
dimension matching the index contract. Unit and integration tests use
`FakeEmbeddingService` and never call an external API:

```bash
python -m pytest \
  tests/unit/repositories/test_vector.py \
  tests/integration/memory \
  tests/integration/services/test_document_embedding.py
```

Runtime FAISS artifacts remain ignored by Git. Only `data/faiss/.gitkeep` may
be committed.

## LLM Gateway

`src.services.LLMGateway` is the only Phase One text-inference entry point. It
uses the official OpenAI Python SDK and the Responses API. Model names,
credentials, timeout, retry count, and remote-storage behavior come from
`OpenAISettings`; no service reads environment variables directly.

Create the production provider through the Gateway default and inject the
DuckDB cache Repository:

```python
from src.core import load_settings
from src.repositories import DuckDBDatabase, LLMCacheRepository
from src.services import LLMGateway

settings = load_settings()
database = DuckDBDatabase(settings.storage.duckdb_path)
database.bootstrap()
gateway = LLMGateway(LLMCacheRepository(database), settings.openai)
```

`invoke_json(model, system_prompt, input_payload)` sends the system prompt as
Responses API instructions and sends a deterministic JSON serialization of the
input payload as the user input. Responses must decode to a JSON object.
Identical model, prompt, and canonical payload values reuse the local
`llm_cache` entry without contacting OpenAI.

`OPENAI_MAX_RETRIES` is passed to the official SDK and means additional
attempts after the initial request. Timeout, rate-limit, authentication,
invalid-request, connection, remote-service, and invalid-response failures are
mapped to stable service exceptions. Public exception messages and structured
logs never include API keys, prompts, user payloads, or raw provider errors.

Gateway logs contain only provider name, model name, status, cache-hit flag,
latency, token usage when available, response ID when available, a truncated
request fingerprint, and a stable error code. Agent-run persistence remains
the responsibility of the Agent execution layer.

Tests must inject `FakeLLMProvider`, an in-process client stub, or an
`httpx.MockTransport`. The default test suite must never use a real API key,
make a real OpenAI request, or consume API quota.

### Manual live LLM smoke check

The live check is an independent opt-in script and is never collected by
pytest. Run it from the repository root after installing the project:

```bash
export OPENAI_API_KEY="inject-from-a-secure-source"
OPENAI_MAX_RETRIES=0 OPENAI_STORE_REMOTE=false \
  "$CONDA_PREFIX/bin/python" -m scripts.smoke_llm
```

Required configuration:

- `OPENAI_API_KEY`: required and read through `OpenAISettings`.
- `OPENAI_MODEL_FAST`: optional; defaults to the configured fast model.
- `OPENAI_TIMEOUT_SECONDS`: optional positive timeout.
- `OPENAI_MAX_RETRIES`: must be `0` for this check.
- `OPENAI_STORE_REMOTE`: must be `false` for this check.

The script performs one `LLMGateway.invoke_json` call with a compact request,
validates the returned object with the existing `RiskManagerResponse` schema,
verifies temporary DuckDB cache persistence, and inspects captured Gateway
metadata for API key, prompt, or payload leakage. It prints metadata only,
never the full model response. The temporary database is deleted on exit.

Token use is bounded operationally by selecting `OPENAI_MODEL_FAST`, requesting
only four compact fields, and making one call. The current Gateway contract
does not expose a separate output-token limit. Timeout, authentication, and
invalid-JSON mappings, plus failure-log redaction, remain deterministic offline
checks:

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/unit/services/test_llm_provider.py \
  tests/unit/services/test_llm_gateway.py -q
```

Exit code `0` means the live response passed schema, cache, and safe-metadata
checks. Exit code `1` means a mapped provider/cache or validation failure.
Exit code `2` means the required safe live configuration was not supplied.

### Temporary DashScope Qwen compatibility smoke check

When OpenAI account quota is unavailable, an independent manual script can
verify the OpenAI SDK's Responses-compatible transport against DashScope:

```bash
export DASHSCOPE_API_KEY="inject-from-a-secure-source"
DASHSCOPE_MODEL=qwen3.8-max \
  "$CONDA_PREFIX/bin/python" -m scripts.smoke_qwen --diagnostic
```

The script makes exactly one request with SDK retries disabled, enables Qwen
thinking through `extra_body`, validates the final JSON with the existing
`RiskManagerResponse`, and prints only bounded reasoning summaries in
diagnostic mode. The API key and full final answer are never printed.

`DASHSCOPE_BASE_URL` may override the default legacy compatible endpoint when
the account has a workspace-specific endpoint. `DASHSCOPE_MODEL` must identify
a Responses-compatible model enabled for that account. This is an operational
compatibility check only: it does not add Qwen to the production Gateway and
does not prove the OpenAI production provider itself is available.

Default pytest remains offline. Its Qwen smoke tests inject a client stub and
never read credentials or access the network.

### Live SEC-to-Qwen report acceptance

Run the complete opt-in acceptance from the repository root:

```bash
export SEC_USER_AGENT="DeepInsight monitored-contact@example.com"
export DASHSCOPE_API_KEY="inject-from-a-secure-source"
env -u ALL_PROXY -u all_proxy \
  DASHSCOPE_MODEL=qwen3.6-flash \
  DASHSCOPE_ENABLE_THINKING=false \
  "$CONDA_PREFIX/bin/python" -m scripts.live_report
```

The SEC adapter reads official submissions metadata and at most one recent
10-Q/10-K primary document for `US:AAPL`. It declares the configured
`SEC_USER_AGENT`, performs no scraping of commercial feeds, and makes no price
request. The full extracted filing text is retained in the raw store and fully
chunked/indexed; at most two deterministically distributed chunks per document
enter the Agent context to bound live LLM cost without selecting only filing
headers. Missing prices, deterministic technical history,
structured fundamentals, macro Memory, and broad sentiment samples remain
explicit report uncertainties.

The Qwen Responses client is injected behind the existing
`LLMGateway → OpenAIProvider` interface. The embedding client is injected into
the existing `OpenAIEmbeddingService`, using `text-embedding-v4`, 256
dimensions, and provider batches of at most ten inputs. Qwen requests use the
standard compatible base URL. The live default is `qwen3.6-flash` with
`enable_thinking=false`, because the eight schema-bound evidence tasks do not
require long-form reasoning. SDK retries are zero. The fixed eight-Agent
topology therefore makes exactly eight LLM requests.

The script submits through FastAPI and fails unless every report citation can
join to a persisted document chunk whose document has a source URL, raw-text
path, and source metadata. Exit code 2 means required configuration is absent;
exit code 1 means live ingestion, inference, assembly, or traceability failed.
It never falls back to Fake data or Fake models.
On failure it also reports DuckDB stage counts, ingestion/Agent state, and
credential-redacted provider status, type, parameter, message, endpoint, and
request ID when available.

## Phase One Agents

Agent prompts are YAML files under `config/prompts/`. Every file contains the
closed `AgentName`, a version, and the full system prompt. Runtime code loads
them through an injected `PromptLoader`; role instructions must not be embedded
in Agent classes. Changing prompt text requires changing its version so
`agent_runs.prompt_template_ver` remains reproducible.

Construct each Agent with the public `LLMGateway`, `MemoryService`,
`PromptLoader`, and `AgentRunRepository` boundaries. The model is supplied in
`ResearchTaskRequest` from typed application settings rather than hard-coded by
an Agent:

```python
from pathlib import Path

from src.agents import FundamentalAnalystAgent, PromptLoader
from src.repositories import AgentRunRepository

fundamental_agent = FundamentalAnalystAgent(
    llm_gateway=gateway,
    memory_service=memory_service,
    prompt_loader=PromptLoader(Path("config/prompts")),
    run_logger=AgentRunRepository(database),
)
```

`ResearchCoordinator` requires exactly the eight Phase One roles. It runs the
four Analysts, Research Manager, Bull Manager, Bear Manager, and Risk Manager
in the fixed MASTER_SPEC order. It returns Agent artifacts only; report
assembly and API work remain separate modules.

Memory search failure is recorded as uncertainty and may degrade to supplied
document evidence. Invalid JSON, invalid role values, unsupported scores,
fabricated citations, unattributed conclusions, and trading instructions fail
the individual Agent run. One Analyst failure remains explicit and the chain
may continue with coverage warnings. Research Manager failure stops both thesis
reviews; either thesis failure stops Risk Manager.

Deterministic feature operators accept normalized pandas frames. Missing or
short history returns null values plus `missing_data`; the operators never ask
an LLM to calculate a numeric feature.

Run the Agent checks fully offline:

```bash
python -m pytest \
  tests/unit/operators \
  tests/unit/agents \
  tests/integration/agents
```
