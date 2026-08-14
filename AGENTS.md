# DeepInsight Engineering Guide

All coding agents must read this file before changing the repository.

## Project boundary

DeepInsight is an evidence-grounded investment research system. The current
deliverable is research, not trading, execution, portfolio construction,
backtesting, model training, Factor, Regime, or MoE functionality. Do not add
those capabilities unless a later approved specification explicitly requires
them.

`docs/MASTER_SPEC.md` is the product and architecture source of truth. Also
read `docs/CODING_GUIDE.md`, `docs/MODULE_STATUS.md`, `docs/DECISIONS.md`, and
the relevant file under `docs/tasks/`. When they conflict, `MASTER_SPEC.md`
wins.

## Five non-negotiable research rules

1. Never fabricate a financial fact.
2. Every accepted factual claim must trace to canonical Evidence.
3. Every numeric claim requires exact literal or deterministic grounding.
4. Point-in-time safety must never be violated.
5. DeepInsight must not issue system-generated trades, positions, orders, or
   target prices in the current phase.

Attributed third-party ratings or target prices are research Evidence, not
DeepInsight recommendations. They are allowed only with explicit third-party
attribution, a valid citation, and exact numeric grounding. Rejected claims
must never enter managers, reports, or evaluation as accepted facts.

## Architecture

The production dependency direction is:

```text
Data → Memory → LLM Gateway → Agents → Report → API
                         └──────────────→ Evaluation
```

- Modules communicate through typed Pydantic v2 contracts and narrow
  Protocols.
- Agents do not depend on Provider SDKs, DuckDB, or FAISS.
- Routes do not contain research workflow logic.
- Reports do not fetch data or create new factual claims.
- `Validated Claim Collection` is the authoritative factual representation:
  `Evidence → Validated Claim → Narrative → Report`.
- Preserve replaceability through dependency injection; avoid circular
  imports, global mutable state, hidden fallbacks, and duplicated schemas.

## Engineering standards

- Python 3.12, FastAPI, DuckDB, FAISS, Pydantic v2, pytest, Ruff, mypy, Black.
- Public functions require type hints and concise Google-style docstrings.
- Prefer clarity, deterministic behavior, explicit configuration, and small
  composable modules.
- Do not modify unrelated modules or add unused dependencies.
- Do not leave `pass`, `NotImplementedError`, TODO, FIXME, or empty adapters in
  a completed path.
- Preserve user changes in a dirty worktree.
- Update `docs/MODULE_STATUS.md` after completed implementation work and
  `docs/DECISIONS.md` when architecture or policy changes.

## Quality gates

Phase 3 has three gates only.

### Gate A — Engineering

```bash
pytest -q
ruff check .
mypy .
black --check .
git diff --check
```

### Gate B — Contract

Validate schema, citation lineage, numeric grounding, point-in-time safety,
and claim intent. Default contract tests are deterministic and offline.

### Gate C — Live Acceptance

Use real configured Providers, all eight Agents, Report, and Evaluation.
Live runs must be explicit, must never fall back to Fake, and must record a
credential-free manifest with provider, model, Prompt version, dataset
version, real/Fake flags, timestamp, and run ID.

## External services and credentials

Default pytest must never access the network. Real Qwen/OpenAI, SEC, Alpaca,
FRED, Stocktwits, or other external services are allowed only through explicit
live commands.

Credentials come exclusively from environment variables. Never put credential
values in source, fixtures, configuration, logs, exceptions, stdout, CI,
prompts, or Git. Missing live credentials must produce SKIPPED,
NOT CONFIGURED, or an explicit exit code—never a Fake fallback.

Public variable names currently include:

- `DEEPINSIGHT_LLM_PROVIDER`
- `QWEN_API_KEY`
- `QWEN_MODEL_NAME`
- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`
- `APCA_API_BASE_URL`
- `DEEPINSIGHT_PROVIDER_SEC_USER_AGENT`
- `DEEPINSIGHT_PROVIDER_SEC_CIK_MAP`
- `FRED_API_KEY`
- `FMP_ENABLED`
- `FMP_API_KEY`
- `STOCKTWITS_MCP_ENABLED`
- `STOCKTWITS_MCP_TOKEN_STORE`
- `DEEPINSIGHT_LIVE_DATASET_VERSION`
- `DEEPINSIGHT_LIVE_AS_OF_DATE`
- `DEEPINSIGHT_LIVE_DATA_START`
- `DEEPINSIGHT_LIVE_DATA_END`

The repository owner may maintain the private file
`~/.local/bin/load_deepinsight_keys.sh` outside the repository. It contains
export statements only and must not be committed, copied into a prompt, or
displayed by an agent. Prepare the parent shell before starting Codex:

```bash
chmod 600 ~/.local/bin/load_deepinsight_keys.sh
source ~/.local/bin/load_deepinsight_keys.sh
codex
```

An already-running process does not inherit variables exported later.

## Working method

Before implementation, inspect the repository and explain the plan and files
in scope. Implement the smallest change that satisfies the approved task.
Run tests proportional to risk, then all required gates. When requirements
remain ambiguous after consulting the specification, stop and request
clarification rather than inventing architecture.
