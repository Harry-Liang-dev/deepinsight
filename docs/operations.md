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
3. Typed defaults

Credentials are loaded into the parent shell from a private file outside the
repository before starting DeepInsight or Codex:

```bash
chmod 600 ~/.local/bin/load_deepinsight_keys.sh
source ~/.local/bin/load_deepinsight_keys.sh
```

Never display, commit, attach, or copy that private file into the repository.
Application Settings do not load `.env` files.

Important environment variables:

| Variable | Purpose |
|---|---|
| `DEEPINSIGHT_ENV` | `development`, `test`, or `production` |
| `DEEPINSIGHT_TIMEZONE` | Application timezone |
| `DEEPINSIGHT_LLM_PROVIDER` | Live selection: `openai` or `qwen` |
| `DEEPINSIGHT_DUCKDB_PATH` | DuckDB file path |
| `DEEPINSIGHT_FAISS_ROOT` | FAISS index root |
| `DEEPINSIGHT_RAW_ROOT` | Original source-document root |
| `DEEPINSIGHT_SNAPSHOT_ROOT` | Snapshot root |
| `DEEPINSIGHT_BACKUP_ROOT` | Backup root |
| `DEEPINSIGHT_REDIS_URL` | Durable report job ID queue |
| `DEEPINSIGHT_PROVIDER_SEC_USER_AGENT` | SEC Fair Access identity |
| `DEEPINSIGHT_PROVIDER_SEC_CIK_MAP` | Canonical asset-to-CIK JSON mapping |
| `DEEPINSIGHT_PROVIDER_SEC_REQUEST_TIMEOUT_SECONDS` | SEC request timeout |
| `DEEPINSIGHT_PROVIDER_SEC_MAX_RETRIES` | Additional transient SEC attempts |
| `DEEPINSIGHT_PROVIDER_SEC_REQUESTS_PER_SECOND` | SEC per-process request ceiling, maximum 10 |
| `DEEPINSIGHT_PROVIDER_SEC_BACKOFF_BASE_SECONDS` | Initial SEC retry delay |
| `DEEPINSIGHT_PROVIDER_SEC_MAX_BACKOFF_SECONDS` | Maximum SEC retry delay |
| `DEEPINSIGHT_PROVIDER_SEC_MAX_DOCUMENTS` | Filing limit per ingestion request |
| `APCA_API_KEY_ID` | Alpaca Market Data key ID; environment-only secret |
| `APCA_API_SECRET_KEY` | Alpaca Market Data secret; environment-only secret |
| `APCA_API_BASE_URL` | Alpaca Market Data API origin |
| `FMP_API_KEY` | Optional Financial Modeling Prep secret; environment-only |
| `FMP_ENABLED` | Explicitly enable the optional FMP standardized-metrics Provider |
| `DEEPINSIGHT_PROVIDER_ALPACA_REQUEST_TIMEOUT_SECONDS` | Alpaca request timeout |
| `DEEPINSIGHT_PROVIDER_ALPACA_MAX_RETRIES` | Additional transient Alpaca attempts |
| `DEEPINSIGHT_PROVIDER_ALPACA_REQUESTS_PER_MINUTE` | Alpaca request ceiling, maximum 200 |
| `DEEPINSIGHT_PROVIDER_ALPACA_FEED` | Historical stock feed: `iex` or `sip` |
| `DEEPINSIGHT_PROVIDER_ALPACA_ADJUSTMENT` | Official historical-bar adjustment |
| `DEEPINSIGHT_SCHEDULER_ENABLED` | Explicit daily Scheduler switch |
| `DEEPINSIGHT_WEB_API_BASE_URL` | FastAPI address used by Scheduler/Web |
| `DEEPINSIGHT_LOG_LEVEL` | Validated stdlib/structlog level |
| `OPENAI_API_KEY` | Required only when OpenAI is selected |
| `QWEN_API_KEY` | Required only when Qwen is selected |
| `QWEN_MODEL_NAME` | Qwen inference model |
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
- Every Repository connection acquires a path-specific Linux advisory lock,
  shared with snapshot and backup scripts. This serializes API reads and
  Worker writes across local processes.
- Deployment designates one report Worker. API writes only durable job
  metadata; the Scheduler and Web do not open DuckDB.
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

The safe default and offline demo retain their deterministic process-local task
service. The production factory
`apps.api.production:create_production_application` instead persists the full
request and lifecycle in `report_jobs`, then sends only `job_id` through Redis.
The separate single Worker atomically claims `queued` jobs and writes a safe
terminal state. On restart it requeues interrupted `running` jobs; duplicate
Redis messages cannot claim an already terminal job.

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

The offline app intentionally remains independent of Redis so default pytest
is deterministic. The production task path is separately covered by
Repository/Worker tests and the Compose topology below.

## Production processes and Docker Compose

Validate and start the single-node topology:

```bash
chmod 600 ~/.local/bin/load_deepinsight_keys.sh
source ~/.local/bin/load_deepinsight_keys.sh
docker compose config --quiet
docker compose up --build
```

Compose receives only variables inherited from the prepared parent shell. The
Worker fails explicitly until the selected LLM and data Provider credentials
are configured. The services are:

- `api`: request persistence, Redis dispatch, task/report/snapshot reads
- `worker`: the only full report-workflow executor
- `scheduler`: one UTC cron that submits configured single-asset reports via API
- `web`: read-only Streamlit task/report viewer via API
- `redis`: append-only delivery queue containing job IDs only

The production worker remains bound to the official OpenAI implementation
required by MASTER_SPEC. Its successful live smoke (P1-3) is deferred until
account funding is restored; Qwen compatibility acceptance must not be
reported as an official OpenAI production pass.

## Snapshot, backup, and recovery

Create local bundles:

```bash
"$CONDA_PREFIX/bin/python" -m scripts.snapshot_local
"$CONDA_PREFIX/bin/python" -m scripts.backup_local
```

Each bundle contains `platform.duckdb`, `faiss.tar.gz`, and `manifest.json`
with SHA-256 digests. Creation acquires the same DuckDB file lock used by
Repository writes, builds in a same-root temporary directory, and publishes
with atomic rename. The snapshot API reads only validated manifests and
returns logical artifact names.

Recovery procedure:

1. stop API, Worker, Scheduler, and Web;
2. verify both manifest hashes;
3. restore DuckDB and extract FAISS into the configured paths;
4. start Redis, API, then the single Worker;
5. Worker recovery returns interrupted `running` jobs to `queued`;
6. verify `/health`, job status, report retrieval, and Memory search.

Never restore over a running process. Local file locking is not a
multi-machine distributed lock.

## Data ingestion

Provider source metadata lives in `config/providers.yaml`; it contains no
credentials. All production credential values remain environment-owned.
Wind, CNINFO, HKEXnews, FRED, X, LSEG, and Bloomberg remain explicit connector
boundaries. SEC EDGAR and Alpaca have opt-in official implementations and do
not make network requests during import or default tests. Alpaca credentials
must be supplied only through `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY`.

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

The live check is an independent opt-in script. The corresponding `live`
pytest marker is excluded by default. Run it from the repository root after
installing the project:

```bash
source ~/.local/bin/load_deepinsight_keys.sh
DEEPINSIGHT_LLM_PROVIDER=openai \
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

### DashScope Qwen live smoke check

When OpenAI account quota is unavailable, select the production Qwen Provider
and run the same Gateway smoke:

```bash
source ~/.local/bin/load_deepinsight_keys.sh
"$CONDA_PREFIX/bin/python" -m scripts.smoke_qwen --diagnostic
```

`smoke_qwen` only validates the configured selection and delegates to
`smoke_llm`; it contains no SDK request implementation. The selected
`QwenProvider` enters the existing `LLMGateway`, validates final JSON with
`RiskManagerResponse`, writes only the temporary cache, and emits safe request
metadata. The API key and full final answer are never printed.

`QWEN_MODEL_NAME` must identify a Responses-compatible model enabled for that
account. This Qwen
result does not prove the OpenAI Provider itself is available.

Default pytest remains offline. Its Qwen smoke tests inject a client stub and
never read credentials or access the network.

### Live SEC-to-Qwen report acceptance

Run the complete opt-in acceptance from the repository root:

```bash
source ~/.local/bin/load_deepinsight_keys.sh
FMP_ENABLED=true STOCKTWITS_MCP_ENABLED=true \
  "$CONDA_PREFIX/bin/python" -m scripts.live_report --configuration-preflight

env -u ALL_PROXY -u all_proxy \
  FMP_ENABLED=true STOCKTWITS_MCP_ENABLED=true \
  "$CONDA_PREFIX/bin/python" -m scripts.live_report
```

The first command is a zero-network `CONFIGURATION_PREFLIGHT`. Do not place
`scripts.smoke_fmp` between it and the full invocation: that smoke performs the
same complete four-endpoint acquisition. The full invocation is authoritative
for the run: **PRECHECK != ACQUISITION; ACQUIRE ONCE; VALIDATE ON SNAPSHOT;
REUSE DOWNSTREAM**. Its manifest records the high-level acquisition, physical
endpoint attempts, snapshot reuse, and retry counts.

The SEC adapter reads official submissions metadata and at most one recent
10-Q/10-K primary document for `US:AAPL`. It declares the configured
`DEEPINSIGHT_PROVIDER_SEC_USER_AGENT`, performs no scraping of commercial
feeds, and makes no price request. The full extracted filing text is retained
in the raw store and fully
chunked/indexed; at most two deterministically distributed chunks per document
enter the Agent context to bound live LLM cost without selecting only filing
headers. Missing prices, deterministic technical history,
structured fundamentals, macro Memory, and broad sentiment samples remain
explicit report uncertainties.

Qwen is selected by configuration and enters the existing
`LLMGateway → LLMProvider` interface as `QwenProvider`. Embeddings remain
behind `EmbeddingService` as `QwenEmbeddingService`, using
`text-embedding-v4`, 256 dimensions, and provider batches of at most ten
inputs. Qwen requests use the standard compatible base URL. The live default
is `qwen3.7-flash` with
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

### SEC EDGAR Provider-only live smoke

The independent Provider smoke performs no Agent, LLM, Memory, FAISS, or report
work and is excluded from default pytest by the `live` marker:

```bash
source ~/.local/bin/load_deepinsight_keys.sh
"$CONDA_PREFIX/bin/python" -m scripts.smoke_sec_edgar \
  --asset-id US:AAPL \
  --lookback-days 370
```

The command uses only official SEC submissions and archive URLs. It prints
safe source metadata, the stable accession locator, text length, and SHA-256;
it never prints filing text. Exit code `0` means one instrument and filing
were returned, `1` means the bounded Provider request failed, and `2` means
required local configuration is missing.

Production SEC access defaults to five requests per second and rejects
configuration above SEC's published ten-request-per-second Fair Access
ceiling. Every request has an explicit timeout and identified User-Agent.
Only `429`, `500`, `502`, `503`, and `504`, plus transient connection/timeout
failures, receive bounded retries. Numeric `Retry-After` is honored within the
configured maximum delay; permanent `4xx` responses are surfaced immediately.

The requested date window first checks `filings.recent`, then only historical
`filings.files` pages whose declared range overlaps the window. Accession
number remains the idempotent document locator. Submissions JSON is transient
adapter input and is cached only for the adapter lifetime; selected CIK,
accession, form, dates, and primary-document locator enter canonical metadata.
Complete extracted filing text continues through `RawTextStore`, which retains
the checksum, raw path, SEC URL, and timestamps under the existing ingestion
design.

Run the complete offline SEC Provider regression independently with:

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/unit/adapters/test_provider_adapters.py \
  tests/integration/services/test_sec_edgar_ingestion.py \
  tests/unit/test_smoke_sec_edgar.py
```

### Alpaca US EOD Provider-only live smoke

The Alpaca Adapter uses only the official historical stock-bars endpoint:

```text
GET https://data.alpaca.markets/v2/stocks/bars
```

The default configuration requests `1Day`, `feed=iex`, `adjustment=raw`, and
ascending results. `iex` is intentionally compatible with the Basic market
data plan but is not full SIP market coverage. Raw Alpaca close is stored as
`close`; unavailable `adj_close` and `turnover` remain null. Every external
symbol is mapped back to a requested canonical `US:<ticker>` identifier before
normalization.

Alpaca access is proactively limited to 180 requests per minute, below the
Basic 200-per-minute ceiling. HTTP 429 honors `X-RateLimit-Reset` when present;
otherwise the shared bounded exponential retry policy applies. Historical
pagination follows opaque `next_page_token` values and has a configured page
safety bound.

Run the independent live smoke only after injecting both credentials:

```bash
source ~/.local/bin/load_deepinsight_keys.sh
"$CONDA_PREFIX/bin/python" -m scripts.smoke_alpaca \
  --start-date 2026-05-01 \
  --end-date 2026-08-07
```

The command is fixed to `US:AAPL`, normalizes every returned bar, and prints
only `bar_count`, `first_date`, `last_date`, and `source_id`. It does not write
or print credentials, raw responses, Agents, prompts, reports, orders, or
backtests. Exit code `0` means bars were returned, `1` means the Provider or
normalization failed, and `2` means credentials or dates are not configured.

Run the complete offline Alpaca regression independently with:

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/unit/adapters/test_provider_adapters.py \
  tests/integration/services/test_alpaca_ingestion.py \
  tests/unit/test_smoke_alpaca.py
```

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
