# Coding Guide

## Language

Python 3.12

## Package Management

uv

## API

FastAPI

## ORM

SQLAlchemy 2.x

## Validation

Pydantic v2

## Vector Database

FAISS

## Structured Database

DuckDB

## Logging

structlog

## Testing

pytest

pytest-asyncio

## Formatting

black

ruff

## Type Checking

mypy

## Typing

All public functions must include type hints.

## Docstring

Google Style Docstring.

## General Rules

- No hard-coded paths.
- No global mutable state.
- Configuration must come from environment variables.
- Every module should be independently testable.
- Prefer dependency injection.
- Avoid circular imports.
- Keep functions short and focused.

## Folder Layout

- `apps/`: deployable API, scheduler, worker, and web applications
- `config/`: application, provider, and prompt configuration
- `data/`: local DuckDB, FAISS, raw data, snapshots, and backups
- `docs/`: specifications, task definitions, and operations documentation
- `infra/`: Docker, Compose, and reserved infrastructure
- `scripts/`: bootstrap, maintenance, and operational scripts
- `src/`: backend application packages
- `tests/`: unit, integration, and fixture packages

## Forbidden

Do not introduce features outside the MVP scope.

Do not add experimental code.

Do not commit temporary scripts.
