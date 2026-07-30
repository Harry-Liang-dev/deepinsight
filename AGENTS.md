# AGENTS.md

# DeepInsight Development Guide

This document defines the engineering rules for all AI coding agents working on the DeepInsight repository.

Every Codex session MUST read this file before making any changes.

---

# 1. Project Overview

DeepInsight is an AI-native investment research platform.

The goal of Phase One (MVP) is to generate high-quality, standardized investment research reports using LLMs and structured financial data.

DeepInsight is NOT a trading platform.

DeepInsight is NOT a quantitative strategy engine.

DeepInsight is NOT an execution system.

The only product delivered in Phase One is a research report.

---

# 2. Single Source of Truth

Always read these documents before implementing any feature.

1. docs/MASTER_SPEC.md

Complete system specification.

2. docs/CODING_GUIDE.md

Coding conventions.

3. docs/MODULE_STATUS.md

Current implementation progress.

4. docs/tasks/

Current module task specification.

When conflicts exist:

MASTER_SPEC.md always has the highest priority.

---

# 3. MVP Scope

Current Phase:

Phase One.

Allowed capabilities:

- Multi-market financial data ingestion
- Data normalization
- DuckDB storage
- FAISS semantic retrieval
- GPT-based reasoning
- Multi-agent collaboration
- Research report generation
- FastAPI backend
- Docker deployment

Not allowed in Phase One:

- Reinforcement Learning
- Local model training
- Trading
- Order execution
- Portfolio optimization
- Backtesting
- Strategy generation
- High-frequency trading
- Autonomous investing

If a feature belongs to Phase Two or later,
DO NOT implement it.

---

# 4. Engineering Philosophy

DeepInsight is designed as a long-term AI investment research operating system.

Always prioritize:

- clarity over cleverness
- maintainability over short-term optimization
- modularity over monolithic implementation
- deterministic behavior over hidden magic
- explicit configuration over hard coding
- simplicity before optimization

Every module should be replaceable.

Every dependency should be isolated.

---

# 5. Architecture Principles

The system is organized into layers.

Data Layer

↓

Memory Layer

↓

LLM Gateway

↓

Analyst Agents

↓

Manager Agent

↓

Research Report Generator

↓

FastAPI Service

Modules should communicate through well-defined interfaces.

Avoid unnecessary coupling.

---

# 6. Coding Standards

Language

Python 3.12

Backend

FastAPI

Database

DuckDB

Vector Store

FAISS

Validation

Pydantic v2

ORM

SQLAlchemy 2.x

Testing

pytest

Formatting

black

ruff

Documentation

Google Style Docstring

Every public function must include type hints.

---

# 7. Repository Rules

Do not modify unrelated modules.

Keep commits focused.

One feature per commit.

Run tests before completion.

Do not introduce unnecessary dependencies.

Do not leave TODO placeholders unless explicitly requested.

---

# 8. Task Workflow

Every implementation follows the same workflow.

1. Read MASTER_SPEC.

2. Read the corresponding task document.

3. Explain the implementation plan.

4. Implement only the requested module.

5. Run tests.

6. Update MODULE_STATUS.md.

7. If an architectural decision changes,
update DECISIONS.md.

---

# 9. Decision Making

When requirements are ambiguous:

Never guess.

Follow MASTER_SPEC.

If uncertainty still exists:

Stop implementation.

Explain the ambiguity.

Request clarification.

---

# 10. Code Quality

Avoid:

- duplicated code
- global mutable state
- circular imports
- hidden side effects
- hard-coded configuration
- premature optimization

Prefer:

- dependency injection
- repository pattern
- composition over inheritance
- explicit interfaces
- small reusable modules

---

# 11. Documentation

Every new module should include:

- module description
- public API documentation
- unit tests
- integration tests (when applicable)

Documentation is part of the implementation.

---

# 12. Long-Term Vision

DeepInsight is expected to evolve through multiple phases.

Phase One

AI Investment Research Platform

↓

Phase Two

Collaborative Multi-Agent Investment Analyst

↓

Phase Three

AI Portfolio Intelligence

↓

Phase Four

Enterprise Investment Operating System

Current repository ONLY implements Phase One.

Do not implement future architecture in advance.

---

# 13. Final Principle

When making engineering decisions:

Choose the solution that makes the repository easier to understand six months from now.

Code is written once.

It will be maintained for years.

---

## DeepInsight Principles

DeepInsight should behave like a disciplined investment research team.

Every component should have a clear responsibility.

Every decision should be explainable.

Every output should be reproducible.

The system should favor transparency over unnecessary complexity.

Long-term maintainability is more important than short-term implementation speed.