# DeepInsight

DeepInsight is an AI-native, multi-market investment research platform.

Phase One is limited to generating standardized investment research reports.
Trading, order execution, portfolio optimization, backtesting, strategy
generation, and model training are outside the MVP scope.

## Repository layout

- `apps/`: deployable API, scheduler, worker, and web applications
- `config/`: application and provider configuration
- `data/`: local runtime data, indexes, snapshots, and backups
- `docs/`: specifications, engineering documentation, and task definitions
- `infra/`: Docker, Compose, and reserved infrastructure definitions
- `scripts/`: repository maintenance and operational scripts
- `src/`: backend application packages
- `tests/`: unit, integration, and test fixture packages

The repository currently contains scaffold files only. No business logic has
been implemented.

## Python environment

DeepInsight uses Conda only to provide the Python 3.12 interpreter. Project
dependencies are declared exclusively in `pyproject.toml` and installed by
`uv` into the active Conda environment. The project does not use a local
`.venv`.

```bash
conda activate deepinsight
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

Run the Foundation checks with the same interpreter:

```bash
"$CONDA_PREFIX/bin/python" -m pytest
"$CONDA_PREFIX/bin/python" -m ruff check .
"$CONDA_PREFIX/bin/python" -m mypy
"$CONDA_PREFIX/bin/python" -m black --check .
```

See `docs/operations.md` for environment creation and verification details.
