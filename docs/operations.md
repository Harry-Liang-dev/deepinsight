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
the responsibility of the later Agent execution layer.

Tests must inject `FakeLLMProvider`, an in-process client stub, or an
`httpx.MockTransport`. The default test suite must never use a real API key,
make a real OpenAI request, or consume API quota.
