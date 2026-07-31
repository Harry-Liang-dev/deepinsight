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
