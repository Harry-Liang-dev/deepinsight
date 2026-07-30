UV ?= uv
CONDA_PYTHON := $(CONDA_PREFIX)/bin/python

.PHONY: check-conda install test lint typecheck format-check check

check-conda:
	@test -n "$(CONDA_PREFIX)" || (echo "请先激活 Conda 环境 deepinsight"; exit 1)
	@test -x "$(CONDA_PYTHON)" || (echo "找不到解释器：$(CONDA_PYTHON)"; exit 1)

install: check-conda
	$(UV) pip install --python "$(CONDA_PYTHON)" -e ".[dev]"

test: check-conda
	"$(CONDA_PYTHON)" -m pytest

lint: check-conda
	"$(CONDA_PYTHON)" -m ruff check .

typecheck: check-conda
	"$(CONDA_PYTHON)" -m mypy

format-check: check-conda
	"$(CONDA_PYTHON)" -m black --check .

check: lint typecheck format-check test
