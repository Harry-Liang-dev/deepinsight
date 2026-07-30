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
