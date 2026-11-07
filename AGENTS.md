# DeepInsight Engineering Guide

## Research vNext foundation (G84, opt-in)

These additive rules preserve all provenance, authorization, budget, audit,
scientific and historical protections below. The existing eight-Agent production
path remains unchanged until separately integrated; this foundation does not
certify a nine-role end-to-end implementation.

- Sector Radar is the primary opportunity discovery entry: daily scanning,
  event-driven research and manual selection. P0 is equity events, genuinely
  sourced fund flows and relative value; P1 is independently tested medium/low
  frequency trends; P2 commodity spreads remain a reserve outside the current
  equity execution path. Radar emits selectable Opportunity Cards, never trades.
  New research requires human selection or an explicitly preauthorized Mandate.
- Preserve Fundamental, Technical, Sentiment and News/Event Analysts. The vNext
  dependency order is four Analysts → Bull/Bear → Risk → Trader → Research
  Manager. Trader is a logical research role producing non-executable
  TradeProposals, not orders, positions or system target prices. Research Manager
  reviews the proposal at the end, not between Analysts and Bull/Bear. Review
  approval is not trading authorization. Coordinator owns scheduling,
  dependencies, collaboration and State, not the roles' professional judgment.
- Preserve L0 Market Snapshot; L1 Macro/Sector Event; L2 Asset Event; L3
  Research/Debate/Risk/Decision; L4 Regime/Strategy Performance. Preserve
  orthogonal GLOBAL, MACRO, SECTOR, INDUSTRY_CHAIN, ASSET and RESEARCH_EPISODE
  scopes and Episodic, Semantic and Performance Learning Memory purposes.
  Memory is continuing research infrastructure, never a new fact authority.
  Agents read and propose append-only updates through MemoryService and checked
  permissions. They cannot directly mutate Raw Evidence, another Agent's
  historical output, Quant Factors or frozen research results.
- Detect actual data changes before calculating research impact. No material
  change permits reuse only when dependencies, freshness, sources and strategy
  versions still qualify. Daily prices do not automatically rerun nine roles.
  Execute only affected specialists and their downstream dependencies. State
  updates create new Revisions; prior States and decisions remain immutable.
- Preserve DuckDB, FAISS, Evidence, PIT, Claim Validation, ResearchState,
  ResearchEpisode and ResearchQuantHandoffBundle. FAISS similarity is not fact
  verification. Distinguish Fact, Inference, Hypothesis, ResearchQuestion,
  TradeProposal and Outcome. Future outcomes cannot enter historical research.
  OHLCV cannot fabricate fund flows. Research review cannot bypass downstream
  Quant risk, cost or portfolio gates; their implementation remains outside this
  repository. Preserve G65–G83 immutable experiments and prospective services.
- G84 shared interfaces and permission/impact rules are specified in
  `docs/G84_RESEARCH_VNEXT_MEMORY.md` and `contracts/g84-memory-v1.json`.
  They are opt-in development contracts; neither Memory proposals nor Manager
  review grant new production Claim, State or Quant admission authority.

## Independent review provenance (mandatory)

Window1 may delegate coding, unit_testing, debugging, scientific_precheck and
candidate_packaging to internal subagents. All such results are INTERNAL_PRECHECK,
never W4_INDEPENDENT_PASS. Do not use W4, Window4, independent_w4 or confusingly
similar names for W1-created subagents. Do not launch a separate Codex CLI to enter
the W4 directory and issue formal independent acceptance on W1's behalf.

Formal Window4 is independently started by the user in
`/home/harry/deepinsight-rv2-w4`. Verify the separate user-directed session,
review scope, exact source/candidate/manifest, receipt bytes and chronology;
an issuer string, directory name or PASS field alone is not independent authority.
W1 must not write, replace or backdate W4 receipts. Preserve mistaken historical
records and correct their authority with an append-only provenance addendum.
An internal precheck never authorizes formal publication. When the user directs
a post-review reissue, bind the genuine receipt and deduplicate identical facts.

All coding agents must read this file before changing the repository.

## Project boundary

DeepInsight is an evidence-grounded Research Intelligence and Opportunity
Discovery system. The long-term platform has three layers:

1. Research Intelligence
2. Quant Alpha / Strategy
3. Portfolio / Execution

This repository, `deepinsight`, owns only layer 1. A future separate repository,
`deepinsight-quant`, owns layers 2 and 3. Do not add quantitative factor
libraries, selection/timing models, Regime/MoE routing, backtests, portfolio
construction, position sizing, orders, execution simulation, or live trading
to this repository.

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

### Provider-native temporal boundary

Provider-native time is authoritative at the ingestion boundary. All source
timestamps must first be interpreted and validated in the provider's native
timezone, calendar, and precision, and only then normalized onto the
DeepInsight canonical UTC timeline. A provider-specific local date must never
replace the global `research_as_of`, and a UTC calendar date must never be
blindly reused as a provider-native date semantic.

For live research, `research_as_of` is one exact timezone-aware UTC information
cutoff captured by orchestration and reused end to end. It is not a market
session date or provider calendar date. Live HTTP ingestion may finish after
that cutoff, but only source information with `available_at <= research_as_of`
is eligible; `ingested_at` remains acquisition lineage. Historical replay keeps
its stricter original-observed ingestion gate.

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

## Research / Quant boundary

The authoritative handoff direction is:

```text
Raw Evidence
→ Validated Claim
→ Research State Feature
→ Satellite Alpha Observation
→ ResearchQuantHandoffBundle
→ future deepinsight-quant
→ Processed Factor Exposure
→ Alpha Signal
→ Strategy
→ Portfolio
```

`Planetary Alpha`（行星阿尔法）means traditional, low-cost, repeatable
quantitative Alpha/Factor computed across a broad point-in-time market
universe. Momentum, reversal, value, quality, growth, size, volatility,
liquidity, technical, revisions, and traditional event factors belong to
future `deepinsight-quant`, not this repository.

`Satellite Alpha`（卫星阿尔法）means proprietary structured research
descriptors produced from information mining, Macro/Sector/Industry-Chain
reasoning, events, expectation changes, debate, risk, ResearchState, and
Memory. In this repository it is not a validated Factor exposure or trading
signal. It may describe `SELECTION`, `TIMING`, or `BOTH`, but cross-sectional
ranking, normalization, neutralization, standardization, IC/RankIC/ICIR,
Top-K selection, timing decisions, and portfolio use belong to
`deepinsight-quant`.

Prefer decomposed, attributable descriptors over a single opaque score. Do
not create `AI_STOCK_SCORE`, `BUY_SCORE`, `SELL_SCORE`, `trade_signal`,
`position_score`, `position_weight`, `order`, `quant_factor_zscore`, or
`neutralized_factor` here. A Research Candidate Universe never replaces the
complete Base PIT Market Universe required by future Quant research.

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

The repository uses three gate classes only.

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

## Frozen Research Intelligence boundary

Phase 4 freezes this repository at `ResearchQuantHandoffBundle v1`. It may
produce ResearchState, ResearchEpisode, Learning Memory, Research Attribution,
Satellite Alpha research descriptors, OpportunityCandidate, temporal State
transitions, and the versioned Research-to-Quant handoff. These are research
artifacts, not validated Quant factors or decisions.

Planetary Alpha, Quant universe maintenance, Factor processing and validation,
IC/RankIC, ranking, Top-K, timing decisions, Holdings, Regime/MoE routing,
portfolio construction, orders, and execution belong to a future independent
Quant system. Do not activate reserved interfaces for those capabilities in
this repository.

## Public Main integration — 2026-11-07

This release is INTERNAL_RESEARCH_ENGINEERING only. The default development model
is qwen3.8-flash, resolved by trusted configuration; explicit model mismatch fails
closed. A code release is not a live Provider grant or scientific admission.
Current receiver/runtime changes require new scoped W4/W5 review before LIVE.
Keep private datasets, source entities, Owner/Grant installations, original HTTP,
SDK requests, model responses, independent receipts and archive refs out of public
Git history. Publish source and synthetic tests only. Never globally replace
historical model/configuration identities.

Use `python -m research_eval --help` for the offline CLI. The public demo uses
SDK MockTransport only. External W3/W5 data roots are explicit operator settings;
permissions cannot come from Prompt metadata. A fresh clone requires no historical
worker directories for the public smoke tests documented in
`docs/RESEARCH_EVAL_PLATFORM.md`. Private integration tests retain all assertions
and run only with separately licensed historical archives.
