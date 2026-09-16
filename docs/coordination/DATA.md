# Current Status

Sprint ID: `P3-STOCKTWITS-MCP-RUNTIME-CLOSURE-01`

Selected Gap: Stocktwits Python runtime MCP transport (`P0`)

Status: COMPLETE. The sole remaining Research Completeness v1 Data P0 is
closed at the Data layer. Python now connects directly to the official
Stocktwits remote MCP using the official MCP Python SDK and Streamable HTTP.
No Codex/ChatGPT subprocess, web scraping, private API, X fallback, fake
sentiment, Agent Prompt, Memory, LLM Gateway, report semantics, Factor,
Regime, backtest, or trading change was introduced.

Runtime data path:

```text
StocktwitsSentimentProvider
  -> MCPTransport Protocol
  -> StreamableHTTPMCPTransport
  -> official mcp Python SDK ClientSession + OAuthClientProvider
  -> Streamable HTTP https://mcp.stocktwits.com/mcp
  -> canonical ProviderRecord mapping
  -> DataNormalizer
  -> MarketDataRepository / DuckDB
  -> ResearchDataBundle.sentiment_evidence
```

Root cause: the canonical Provider/Repository/Bundle path existed, but its
runtime transport slot had no concrete Python MCP client. The previous smoke
therefore required host injection and correctly returned `NOT_CONFIGURED`.

Current Data gap state:

- Remaining P0: none.
- Remaining P1: operational replay of FRED, Alpaca News, benchmark context,
  and refreshed SEC Company Facts into the next complete live-acceptance DB;
  CN/HK equivalent breadth and adjusted-price/corporate-action coverage remain
  outside this US:AAPL runtime-closure scope.

## Current Task

Implemented:

- Replaced the old five-method synchronous Stocktwits transport shape with a
  reusable async `MCPTransport` Protocol: `initialize`, `list_tools`,
  `call_tool`, and `close`.
- Added `StreamableHTTPMCPTransport` over official `mcp` SDK
  `OAuthClientProvider`, `streamable_http_client`, and `ClientSession`.
- Kept `StocktwitsSentimentProvider` SDK-independent through dependency
  injection. Its synchronous BaseProvider interface safely runs one complete
  async session even when called from the async live-report runtime.
- Runtime discovers tools with `list_tools()` and fails before calls if any of
  the approved tools are absent. The Provider only calls:
  `get_sentiment`, `get_sentiment_history`, `get_message_volume`,
  `get_message_volume_history`, and `get_symbol_messages`.
- Added bounded recent-message pagination. Invalid or looping cursors fail;
  reaching the explicit page cap ends the configured recent-evidence sample.
- Preserved the existing canonical models and community-only classification.
  Raw MCP payloads never enter repositories, Bundles, or Agent inputs.
- Added direct production composition in `python -m scripts.live_report` when
  `STOCKTWITS_MCP_ENABLED=true`. Missing OAuth state fails preflight as
  `ProviderStatus.NOT_CONFIGURED` with `authorization required`; no Fake
  transport is substituted.
- Injected `DocumentRepository` into the production Bundle composition while
  touching the Data live-acceptance orchestration.

OAuth and token storage:

- No Stocktwits username, password, custom client ID, or client secret setting
  is required.
- The official SDK performs OAuth discovery, dynamic client registration,
  authorization-code flow, and PKCE against the Stocktwits account flow.
- Added `MCPTokenStorage` and `LocalFileMCPTokenStorage`.
- Default store: `data/auth/stocktwits/oauth_state.json`, configurable by
  `STOCKTWITS_MCP_TOKEN_STORE`.
- Store directory/file modes were verified as `0700`/`0600`; `data/auth/` is
  Git-ignored. Token values are not logged, persisted to DuckDB, included in
  reports/manifests, or present in fixtures.
- The controlled HTTP client ignores ambient proxy variables by default
  (`STOCKTWITS_MCP_TRUST_ENV=false`). This avoids an invalid ambient SOCKS
  proxy configuration observed in the host; proxy use can be explicitly
  enabled when an operator has a compatible environment.

Official SDK:

- dependency constraint: `mcp>=1.28,<2`;
- live-verified installed version: `mcp==1.29.0`.

## API Changes

New reusable Data-layer interfaces/types:

```text
MCPTransport
MCPTokenStorage
MCPToolResult
StreamableHTTPMCPTransport
LocalFileMCPTokenStorage
FakeMCPTransport
```

New composition helpers:

```text
build_stocktwits_mcp_transport(settings, ...)
build_stocktwits_provider(settings)
stocktwits_authorization_configured(settings)
```

New Settings/environment variables:

```text
STOCKTWITS_MCP_ENABLED              default false
STOCKTWITS_MCP_URL                  default https://mcp.stocktwits.com/mcp
STOCKTWITS_MCP_TOKEN_STORE          default data/auth/stocktwits
STOCKTWITS_MCP_REDIRECT_URI         default http://127.0.0.1:8765/callback
STOCKTWITS_MCP_TRUST_ENV            default false
```

Existing history/message limits and timeout remain under `ProviderSettings`.

Operator commands:

```text
python -m scripts.auth_stocktwits_mcp
STOCKTWITS_MCP_ENABLED=true python -m scripts.smoke_stocktwits
```

## Files Changed

Runtime/Data:

- `.gitignore`
- `pyproject.toml`
- `config/providers.yaml`
- `src/core/settings.py`
- `src/adapters/__init__.py`
- `src/adapters/mcp.py`
- `src/adapters/stocktwits.py`
- `src/adapters/stocktwits_runtime.py`
- `scripts/live_report.py`

Authorization/smoke:

- `scripts/auth_stocktwits_mcp.py`
- `scripts/smoke_stocktwits.py`

Tests:

- `tests/conftest.py`
- `tests/unit/core/test_settings.py`
- `tests/unit/adapters/test_stocktwits_adapter.py`
- `tests/integration/services/test_stocktwits_mcp_ingestion.py`
- `tests/unit/test_live_report.py`

Coordination:

- `docs/coordination/DATA.md`

## Tests

Offline quality gates (no default network access):

- default pytest: PASS, `346 passed, 5 deselected`;
- focused Stocktwits/settings/live-report tests: PASS, `36 passed`;
- Ruff: PASS;
- mypy: PASS, `251 source files`;
- Black check: PASS, `251 files`;
- `git diff --check`: PASS.

Offline coverage includes:

- exact approved tool calls and canonical mapping;
- SDK-independent Provider dependency injection;
- required-tool missing;
- OAuth missing and expired-token failure simulation;
- malformed local OAuth state without credential leakage;
- network/MCP initialization/tool-call failures;
- invalid Provider response and wrong symbol;
- empty current signal and empty message behavior;
- bounded recent-message pagination;
- calls from an already-running asyncio runtime;
- idempotent DataIngestionService -> DuckDB persistence;
- point-in-time Repository reads;
- ResearchDataBundle projection, community-only retention, and source lineage;
- live-report preflight `NOT_CONFIGURED` behavior.

Live authentication result:

```text
authentication = PASS
mcp_initialize = PASS
tool_count = 13
required_tools_available = true
```

Available MCP tools observed (names only):

```text
get_following_feed
get_message_volume
get_message_volume_history
get_sentiment
get_sentiment_history
get_symbol
get_symbol_messages
get_symbol_pulse
get_trending_symbols
get_user_messages
get_watchlist_feed
get_widget_registry
whoami
```

Final live US:AAPL Data Layer Diagnostic:

```text
status = PASS
sentiment_status = AVAILABLE
sentiment_score = 70.0
sentiment_label = BULLISH
bullish_pct = 75.48
bearish_pct = 24.52
message_volume_score = 46.0
snapshot_count = 22
sentiment_history_count = 21
message_volume_history_count = 21
message_count = 149
earliest_message_timestamp = 2026-08-11T01:06:11
latest_message_timestamp = 2026-08-11T07:15:14
ResearchDataBundle.sentiment_evidence.status = present
bundle_evidence_count = 239
source_lineage_complete = true
```

No post text or token was printed. `python -m scripts.live_report` production
wiring is checked in and offline-tested; Window 1 Final Data Gate was not run,
as required by the task boundary.

## Blockers

No remaining Data-layer P0 blocker.

The complete Window 1 live report/final acceptance remains NOT_RUN by design;
that is Main Agent ownership, not evidence of a Stocktwits runtime failure.

## Required Changes From Other Modules

MAIN:

- Enable `STOCKTWITS_MCP_ENABLED=true` in the prepared parent shell for the
  final acceptance runtime. Do not copy or commit the local OAuth store.
- Run the Window 1 Final Data Gate/new US:AAPL acceptance and confirm the
  persisted acceptance DB contains Stocktwits ingestion job IDs,
  `sentiment_snapshots`, and `sentiment_evidence` counts.
- Main alone may update `docs/MODULE_STATUS.md` and `docs/DECISIONS.md`.

AGENTS:

- No Prompt or input-schema change is requested. The existing contract already
  declares `ResearchDataBundle.sentiment_evidence` for Sentiment Analyst and
  managers. Verify its consumption in the Main-owned final acceptance.
- Continue treating Stocktwits Evidence as community sentiment/attention, not
  verified fundamental or event facts.

MEMORY:

- No change required for this P0 closure. Do not manufacture historical
  Memory from Stocktwits posts.

LLM_GATEWAY:

- No Data-layer API change required. The checked-in live-report wrapper passes
  current offline schema/quality tests; no Gateway internal change was made.

## Ready For Integration

YES

---

# Phase 4C Day44 — Data Ownership Boundary

## Current Status

Data ownership is synchronized with the Research/Quant split. This repository
continues to produce canonical, attributable, PIT-safe Research data.

## Current Task

Future Research-to-Quant handoff data integrity must preserve canonical
`asset_id`, market, `research_as_of`, event/calendar availability, source
lineage, quality, and versions. No Day45 contract is implemented today.

## API Changes

None. `ResearchQuantHandoffBundle` is a reserved design boundary only.

## Files Changed

`docs/coordination/DATA.md` only for Window synchronization.

## Tests

Full offline Gate A passed: `565 passed, 5 deselected`; Ruff, mypy, Black, and
`git diff --check` pass. Existing Data and Temporal contracts did not change.

## Blockers

None. A future cross-repository transport/storage choice is intentionally
undecided.

## Required Changes From Other Modules

Main must define the shared handoff schema before Data implements projection.
Data must not implement a broad Quant universe, traditional Factor library,
winsorization, neutralization, z-scores, IC metrics, or ranking.

## Ready For Integration

YES — Day44 ownership is frozen; no Day45 implementation has begun.

---

# Phase 4C Day45 — Satellite Alpha Data Contract Audit

## Current Status

Data contract audit is complete. Day45 Satellite Alpha must be a
ResearchState-derived, reference-only Research descriptor. It must not carry
Provider payloads, Quant Factor semantics, rankings, or trading fields. No
Data Provider, normalization, Repository, Temporal Contract, ResearchState,
ResearchEpisode, Dataset, or Golden Replay implementation was changed.

## Current Task

Reviewed the proposed `SatelliteAlphaDefinition` and
`SatelliteAlphaObservation` boundary against canonical Asset identity,
Unified Temporal Contract v1, ResearchState/ResearchEpisode lineage, PIT
Dataset identity, and Phase 3/Phase 4A historical replay behavior.

### Canonical asset join recommendation

- `SatelliteAlphaObservation.asset_id` MUST reuse
  `src.models.identifiers.AssetId`. Its serialized canonical values are
  `CN:600519.SH`, `HK:0700.HK`, and `US:AAPL`.
- The stable future cross-repository security join key is the serialized
  canonical `asset_id`. For one Satellite observation the semantic composite
  key is `asset_id + research_as_of + definition_id + definition_version`;
  `observation_id` should be the deterministic identity of that tuple plus
  canonical component/provenance input.
- `AAPL` is a Provider/raw ticker and is accepted only at the Data
  normalization boundary when market is explicit. `US:AAPL` is the canonical
  Asset ID. `NASDAQ:AAPL` is not an `AssetId`; `NASDAQ` remains instrument
  metadata. `ASSET:US:AAPL` is a research-scope ID, not another Asset ID.
  Typed domain contracts therefore do not admit three interchangeable Asset
  identities.
- `Market` (`CN`, `HK`, `US`) is the per-asset market semantic and is already
  encoded by `asset_id.market`. If Observation duplicates `market` for search
  or transport convenience, validation MUST require
  `market == asset_id.market`. `MarketScope` values `GLOBAL` and `MIXED` are
  context/report scopes and are not valid substitutes for an Asset market.
- `exchange_code` is canonical instrument metadata but currently remains a
  validated string rather than a closed exchange enum. It must not join or
  identify Satellite observations. Future ticker-change/permanent-issuer
  mapping is not solved by inventing a second Day45 asset master.

### Sector and Industry-Chain join semantics

- `sector_id` reuses the closed `SectorId` values `S01` through `S18`.
  `chain_ids` reuse uppercase canonical IDs backed by versioned
  `IndustryChainDefinition` objects.
- Asset-to-Sector/Chain membership already has PIT semantics through
  `SectorMembership(asset_id, sector_id, chain_ids, role, valid_from,
  valid_to, version)` and Repository reads enforce
  `valid_from <= as_of < valid_to`.
- Observation construction MUST inherit the resolved Sector/Chain hierarchy
  and `sector_context_id`/membership snapshot or version from its frozen
  `ResearchStateSnapshot`. It must not query the latest membership during
  export. Each chain ID must resolve to a definition effective at the same
  cutoff and belonging to the same Sector.
- When the source run predates Sector/Chain capture, the result remains
  `NOT_AVAILABLE_AT_SOURCE_RUN`; it is not populated from the current
  ontology. Empty `chain_ids` means no chain was resolved in that source
  context, not an implicit peer group.

Required observation identity and lineage:

- canonical `AssetId`; an explicit market, if stored, must equal
  `asset_id.market`;
- one timezone-aware UTC `research_as_of` equal to the source
  `ResearchStateSnapshot.research_as_of`;
- `research_state_id`, definition ID/version, observation schema/build
  version, and the source State feature version;
- unambiguous State feature references. Since `ResearchStateFeature` has no
  standalone ID, use canonical section-qualified feature paths rather than a
  bare `feature_name`;
- compact `source_claim_ids`, `source_evidence_ids`, and source artifact/data
  snapshot references inherited from the frozen State; never copy Evidence or
  Provider payloads;
- deterministic observation identity from canonical normalized semantic
  input. Audit-only materialization time must not affect identity.

Required temporal behavior:

- reuse `validate_temporal_access()` and `TemporalMetadata`; do not implement
  a Satellite-specific future-time checker;
- `research_as_of` is the immutable knowledge/decision cutoff and MUST equal
  the source `ResearchStateSnapshot.research_as_of`. Every referenced feature,
  Claim, Evidence, Sector membership, and source artifact must pass the shared
  validator at this cutoff;
- Observation MUST also retain its own UTC-aware `available_at`: the earliest
  time the completed descriptor itself could be consumed. This is not
  automatically equal to `research_as_of`. A later offline materialization
  may describe an older State, but future Quant may consume it only at a
  consumer cutoff where `available_at <= consumer_as_of`; it must never be
  represented as if it existed in the historical source run;
- `event_time`, `published_at`, period time, and membership
  `effective_from/effective_to` already remain reachable through the
  section-qualified State feature and Claim/Evidence/artifact references.
  They SHOULD NOT be copied into the generic Observation because one
  descriptor can aggregate heterogeneous upstream clocks. If a future
  definition describes one focal event, that event remains a referenced
  canonical artifact rather than a second temporal truth;
- definition validity, if versioned by an effective interval, follows the
  existing inclusive-start/exclusive-end convention;
- Phase 3 Golden artifacts cannot receive later Sector, Chain, Memory, Event,
  feature, or definition-derived values. A source-run absence remains
  `NOT_AVAILABLE_AT_SOURCE_RUN`;
- a Timing definition that requires prior State history remains
  `REQUIRES_HISTORY` when only one snapshot exists. Day45 must not synthesize
  a transition or read later State.

### `comparison_scope` support matrix

| Scope | Day45 support | Stable mapping | Required constraint |
| --- | --- | --- | --- |
| `MARKET` | SUPPORTED as descriptive identity | `asset_id.market` / `Market` | Does not imply a complete market universe, market rank, or cross-sectional calculation |
| `SECTOR` | SUPPORTED, PIT | frozen `SectorId` plus effective `SectorMembership`/Sector snapshot | Use membership effective at `research_as_of`; never latest-state backfill |
| `INDUSTRY_CHAIN` | SUPPORTED, PIT | effective `IndustryChainDefinition` plus membership `chain_ids` and version | Validate chain/Sector consistency and source-run presence |
| `PEER_GROUP` | `UNSUPPORTED / FUTURE` | none | No formal peer-group definition, membership, version, or PIT universe exists; do not infer peers |
| `ASSET_TIME_SERIES` | CONDITIONALLY SUPPORTED | same canonical `asset_id` across frozen State snapshots | Requires prior PIT State history; otherwise `REQUIRES_HISTORY`, never a synthetic delta |

`comparison_scope` declares the intended frame of interpretation only. It
does not authorize Data or Agents to calculate ranks, percentiles,
normalizations, Top-K, or a Base Quant Universe.

Required availability semantics:

- `AVAILABLE`, `PARTIAL`, `MISSING`, `NOT_AVAILABLE_AT_SOURCE_RUN`,
  `REQUIRES_HISTORY`, and `UNSUPPORTED` must remain distinguishable, either as
  the closed Day45 coverage vocabulary or an exactly mapped typed component;
- `MISSING` is never represented by numeric zero, an empty score, or a neutral
  categorical value;
- an available numeric component must originate from a deterministic grounded
  ResearchState feature and retain its unit where applicable;
- semantic/categorical observations must retain the accepted Claim/State
  feature reference that produced them;
- structured observations may have components without a scalar aggregate.

### Numeric component grounding constraints

- Every numeric component must carry a semantic component name, value, unit
  or explicit unitless scale, component/transform version, and direct State
  feature plus Claim/Evidence/artifact references. IDs must resolve through
  the frozen `ResearchStateLineage`; copied Provider values are prohibited.
- A deterministic numeric `ResearchStateFeature` is acceptable only when its
  canonical Evidence parents support the value. A
  `NORMALIZED_RESEARCH_STATE` numeric is acceptable only with its existing
  deterministic `transform_name` and `transform_version`. A numeric literal
  originating only in LLM prose is never acceptable.
- `revenue_exposure` may be numeric only when its numerator, denominator,
  currency/unit, period, formula, and Evidence parents are available. An LLM
  estimate of geographic/customer/chain revenue exposure is categorical or
  `MISSING`, not a number.
- `earnings_increment_potential` may be numeric only when all grounded input
  assumptions and a deterministic versioned formula exist. Otherwise retain
  a Claim-referenced categorical descriptor or explicit missing status; do
  not convert narrative upside into a `0..1` score.
- `expectation_delta` requires two comparable, PIT-safe expectation
  observations/State snapshots with matching units and an explicit transform
  version. One snapshot produces `REQUIRES_HISTORY`; a later expectation may
  not be read backward.
- Existing exact-numeric Claim grounding remains authoritative. Missing is
  not zero, neutral, an empty scalar, or an absent component silently ignored
  by an aggregate.

Research/Quant join safeguards:

- `usage` is limited to `SELECTION`, `TIMING`, or `BOTH` and describes intended
  downstream research use, not a selection or timing decision;
- `comparison_scope` is explicit descriptive metadata. It must not embed a
  rank, percentile, z-score, peer-normalized value, or an inferred Base Quant
  Universe;
- Provider names and source locators remain reachable through Evidence and
  artifact references, not duplicated as Provider-specific observation
  fields;
- State/data snapshot/version references support the future handoff join, but
  Day45 does not implement `ResearchQuantHandoffBundle` or a cross-repository
  transport.

## API Changes

None from Window 2. Main/Window 3 shared-schema integration MUST enforce:

```text
SatelliteAlphaDefinition
  definition_id
  definition_version
  usage
  comparison_scope
  observation/value shape
  required source feature semantics

SatelliteAlphaObservation
  observation_id
  definition_id + definition_version
  asset_id (+ validated market only if explicitly stored)
  research_as_of
  available_at
  research_state_id
  source feature paths
  source Claim/Evidence/artifact references
  coverage status + explicit missing reason
  observation/schema/build versions
  an adapter to shared TemporalMetadata / validate_temporal_access
```

SHOULD retain `data_snapshot_id` as a compact lineage reference when present
in `ResearchStateLineage`; it must remain null/absent when unavailable in the
source run rather than being inferred from a later artifact. SHOULD keep
definition metadata separate from per-asset values so changing descriptive
text does not silently rewrite historical observations.

Forbidden fields or semantics include:

```text
FactorDefinition / FactorValue / FactorExposure
quant_factor_zscore / neutralized_factor
rank / percentile / Top-K / IC / RankIC / ICIR
AI_STOCK_SCORE / BUY_SCORE / SELL_SCORE
trade_signal / position_score / position_weight / order
Provider response payloads or Provider-specific field names
arbitrary LLM-generated 0..1 alpha, logic, benefit, or timing scores
future labels, returns, outcomes, entry/exit, or sizing decisions
```

## Files Changed

- `docs/coordination/DATA.md`

No production or test file was modified by Window 2.

## Tests

Documentation-only contract audit; Window 2 changed no production schema.
Existing identity/temporal/ontology/dataset contract regression:
`39 passed`. `git diff --check`: PASS.

Minimum shared-schema tests for Main/Window 3 should prove:

- canonical Asset/market consistency and rejection of `AAPL` /
  `NASDAQ:AAPL` as Observation `asset_id` values;
- `exchange_code` does not participate in observation identity;
- PIT Sector/Chain membership is inherited from frozen State and an older
  run is never backfilled;
- UTC/PIT rejection for a future State or feature;
- Observation `available_at` is distinct from source `research_as_of` and is
  honored at the downstream consumer cutoff;
- stable semantic identity independent of materialization time and mapping
  order;
- missing is distinct from zero;
- `PEER_GROUP` is explicitly unsupported and one-snapshot
  `ASSET_TIME_SERIES` is `REQUIRES_HISTORY`;
- every numeric component resolves to grounded parents, unit/scale, and a
  deterministic transform where derived;
- Phase 3 Golden absence is not backfilled;
- Phase 4A observations use only source-run State/sector artifacts;
- construction performs zero Provider and zero LLM calls;
- no forbidden Quant/trading field exists in the public schema.

## Blockers

`BLOCKING_ISSUES = NONE` in existing Data/identity/temporal infrastructure.

Pre-integration rejection criteria for the Window 3/Main schema are:

- missing Observation-level `available_at` or silently equating it with
  `research_as_of`;
- accepting bare ticker/exchange-ticker as canonical `asset_id`;
- declaring `PEER_GROUP` supported without a versioned PIT membership model;
- numeric components without grounded parent references, units/scales, and a
  deterministic transform where applicable.

These are contract requirements, not reasons to alter the frozen Temporal,
ResearchState, Dataset, or Golden Replay schemas today.

## Required Changes From Other Modules

MAIN:

- Reject any shared schema that stores bare, ambiguous feature names without
  their ResearchState section or stable feature reference.
- Validate definition/observation versions and semantic identity centrally;
  do not modify ResearchState or Golden Replay identity.
- Validate Observation availability separately from source-State cutoff, both
  through the existing Unified Temporal Contract.

AGENTS:

- Build observations only from the frozen ResearchState and accepted
  provenance references. Do not request a new LLM score or map prose to a
  scalar.
- Treat Timing concepts without prior snapshots as `REQUIRES_HISTORY`, not as
  zero, neutral, or an inferred direction.

MEMORY:

- May audit historical continuity references, but Day45 must not query Memory
  to backfill a frozen State or create a transition builder.

LLM_GATEWAY:

- No Provider/Gateway call is required for frozen-artifact observation
  reconstruction. Do not add an independent factor-scoring request.

Nonblocking future Quant considerations:

- `AssetId` is the current stable cross-repository join, but permanent issuer
  identity across ticker changes/corporate actions is not yet modeled. Future
  `deepinsight-quant` may own a separately versioned security-master mapping;
  Day45 must not guess one.
- The Research Sector universe is intentionally scoped and cannot substitute
  for Quant's complete Base PIT Market Universe.
- Cross-repository wire/storage format, corporate-action alignment, and Quant
  peer-universe construction remain future handoff concerns. None authorizes
  implementation in `deepinsight` today.

## Ready For Integration

YES — the Data/Temporal contract is ready for Window 1 shared-schema review.

---

# Report Completeness Polish — 2026-08-14

## Current Status

Existing-provider projection closure is complete. No Provider was added.

## API Changes

- SEC Company Facts canonical inputs add `current_assets`,
  `current_liabilities`, and consolidated `total_debt`; absent concepts remain
  MISSING.
- Fundamental deterministic outputs add fiscal-aligned YoY growth, margins,
  ROE/ROA, debt-to-equity, and current ratio with raw-parent lineage.
- Valuation v1 now exposes `eps_ttm`, `book_value_per_share`, `market_cap`,
  `pe_ttm`, `pb`, and `earnings_yield`, selecting each latest canonical input
  independently.
- Technical v2 exposes 1/5/20/60-session returns, SMA distances, 20/60-session
  volatility, 60-session drawdown, RSI14, ATR14, MACD, volume ratio, and
  SPY/QQQ/XLK relative strength.
- FRED projection adds `macro_snapshot_v1` friendly fields while retaining raw
  series lineage. Stocktwits adds deterministic change, attention, dispersion,
  and topic presentation fields.
- Alpaca already supported `adjustment=all`; normalized coverage metadata now
  records the requested adjustment so raw and adjusted OHLC series are not
  semantically conflated.

## Tests

Default pytest: `438 passed, 5 deselected`. Ruff, mypy, Black, and
`git diff --check`: PASS. A copy of acceptance `20260813T163645Z` produced
17 fundamental fields, 3 of 6 valuation fields, all 20 technical fields, 12
MacroSnapshot fields, 574 news evidence items, and 11 sentiment fields without
network access or mutation of the baseline DB.

## Blockers

No P0. Existing acceptance lacks the newly mapped SEC current/debt concepts;
current ratio and debt-to-equity correctly remain MISSING until a later normal
SEC refresh contains those concepts. Current EPS TTM, PE TTM, and earnings
yield also remain MISSING because the snapshot lacks four discrete recent
quarters; stale annual EPS is not mislabeled as current TTM.

## Ready For Integration

YES

---

# FMP Standardized Metrics Closure — 2026-08-14

## Current Status

FMP live AAPL mapping and the fresh acceptance `20260814T100747Z` are PASS.
SEC remains authoritative for filings/XBRL/events; FMP is the primary
standardized ratio/TTM source and is disabled by default.

## API Changes

- New optional `FinancialModelingPrepAdapter` and `FMP_API_KEY` setting.
- Canonical standardized fields: revenue/net-income YoY, three margins,
  ROE/ROA, debt-to-equity/current ratio, EPS TTM, book value/share, market cap,
  PE/PB and earnings yield.
- Source priority and FMP-versus-SEC cross-check metadata are explicit; values
  are never averaged.

## Tests

FMP smoke: 15/15 required AAPL metrics available. Full Gate A: `447 passed, 5
deselected`; Ruff, mypy, Black and diff checks pass.

## Blockers

NONE for Phase 3. Adjusted-close/turnover coverage remains an explicit raw
Alpaca limitation rather than a Fundamental blocker.

## Ready For Integration

YES — integrated and frozen.

---

# Phase 4B Day38 — Data to ResearchState Projection

## Current Status

ResearchState consumes frozen `ResearchDataBundle` Evidence and selects the
latest attributable value per canonical field at the source cutoff. It does
not query a Provider or recalculate financial/technical features.

## API Changes

- No Provider, normalization, Repository, or deterministic operator changed.
- State features retain Evidence IDs and bundle/data-snapshot lineage.

## Blockers

NONE. Missing capability sections stay explicit and are never converted to
zero or neutral values.

## Ready For Integration

YES

---

# Phase 4C Day48 — Research → Quant Handoff Independent Acceptance

## Current Status

`DAY48_RESEARCH_QUANT_HANDOFF = FAIL`。Window 2 以未来
`deepinsight-quant` 外部消费者视角完成独立验收；现有 Builder 的内部
identity/PIT/coverage 检查大部分成立，但公开 JSON/JSONL wire contract
存在两个阻断问题，尚不能判定为稳定、无歧义、可独立消费。

## Current Task

仅验收 `ResearchQuantHandoffBundle v1`，未修改 Handoff 生产 schema、
Builder、Exporter，未执行 Day49，也未实现任何 Quant/Trading 能力。

验收矩阵：

| Gate | Result | Evidence / finding |
|---|---|---|
| Schema/version/extra control | PASS | Bundle 与 manifest 均有 v1 literal；Pydantic `extra="forbid"`；Candidate/Transition 可选；Selection/Timing 分支显式。 |
| Canonical Asset identity | PASS | 复用 `AssetId` 和 `Market`；AAPL artifact 为 `US:AAPL`，没有引入 `AAPL`/`NASDAQ:AAPL` 映射。Sector/Chain 复用现有 canonical IDs。 |
| PIT cutoff | PASS | `research_as_of` 为唯一 Research cutoff；`created_at`/`generated_at` 不进入研究信息集合或 Bundle semantic ID；State/Episode/Observation/Candidate/Transition alignment 与可用时间已有拒绝测试。 |
| Selection payload | FAIL | `HandoffSatelliteReference` 只输出 ID/family/usage/coverage/version/available_at；缺少 `comparison_scope`、`value`、`value_components`。单独 JSON artifact 无法让 Quant 读取实际 descriptor。 |
| Timing payload | FAIL | 同一 compact reference 丢失 Timing observation 的实际 value/components；Quant 只能知道 family 与 coverage，无法区分有效 transition 描述内容。`REQUIRES_HISTORY` 本身仍正确保留且未变成 0。 |
| Negative/partial support | PASS | 已覆盖 qualified、`INSUFFICIENT_RESEARCH`、Candidate absent、PARTIAL、`MISSING_INPUT`、`NOT_AVAILABLE_AT_SOURCE_RUN`、`REQUIRES_HISTORY`；不是正样本专用导出。 |
| Single serialization | FAIL | JSON/version/round-trip 字面结构稳定，但外部 stdlib-only consumer 无法从 artifact 读取 Satellite scope/value/components，因此不满足独立可理解性。 |
| Batch serialization | FAIL | JSONL/manifest 有版本且 Bundle-ID 排序稳定，但 exporter 允许同一 `(asset_id, research_as_of)` 出现多个不同 Bundle；该最小 Quant join key 在一个 batch 内不唯一。 |
| Determinism | PASS | `bundle_id` 排除 `created_at`，Observation 输入顺序不影响 ID；batch `export_id` 由规范排序后的 semantic content 产生。 |
| Provenance | PARTIAL | aggregate Claim/Evidence/Event/artifact indexes 与 primary object closure 存在；但 compact Satellite ref 不带 per-observation descriptor/component lineage，且 export 没有 Observation sidecar/resolver contract，单独 artifact 无法完成逐 Observation 追溯。 |
| Frozen Phase3/Phase4A | PASS | Phase3 不出现后来的 Sector/Chain backfill；无 predecessor 时 Timing 保留 `REQUIRES_HISTORY`；Phase4A 使用冻结 source-run State。 |
| Internal leakage | PASS | 未发现 Prompt、raw LLM、CoT、FAISS ID、DuckDB row ID、embedding 或 Memory storage pointer。 |
| Quant scope leakage | PASS | 未发现 Factor exposure、rank/zscore、IC/RankIC、expected return、Top-K、BUY/SELL、position、portfolio、MoE 或 execution 字段。 |
| External-consumer readability | FAIL | 新增的黑盒 consumer test 只用 `json` 读取生产导出的 artifact，稳定复现 Satellite payload 不完整。 |
| Engineering gate | FAIL | 既有 Day48 focused tests 通过；新增两项 acceptance contract tests 按预期失败，故 full pytest 不能通过。Ruff/mypy/Black/diff 结果见 Tests。 |

## API Changes

无生产 API 变更。新增独立验收测试明确冻结以下外部 contract 期望：

- 每条 Selection/Timing Satellite wire item 可读到 `comparison_scope`、
  `value`、`value_components`，并继续保留 observation ID、usage、coverage、
  definition/transform version 与 availability；
- 一个 batch 内 `(asset_id, research_as_of)` 不得对应多个无选择规则的
  Bundle。若 Window 1 采用不同的无歧义版本/variant key 方案，必须同时
  更新公开 schema、manifest 和 consumer contract，而不是依赖内部约定。

## Files Changed

- `tests/integration/services/test_research_quant_handoff_external_consumer.py`
- `docs/coordination/DATA.md`

未修改 Window 1 的 Handoff 生产实现或共享状态/决策文件。

## Tests

- Day48 implementation focused suite：`18 passed`。
- Day45–48 Satellite/Opportunity/Transition/Handoff focused regression：
  `72 passed`。
- Cross-phase ResearchState/Episode/Attribution/Dataset/Golden/Satellite/
  Opportunity/Transition/Handoff regression：`107 passed, 2 failed`；两项
  failure 均为本次新增 acceptance blocker。
- Full pytest：`637 passed, 5 deselected, 2 failed`。
- Leakage selection：`8 passed, 636 deselected`。
- Ruff：PASS。
- mypy：PASS（`329 source files`）。
- Black：PASS（`329 files`）。
- `git diff --check`：PASS。

## Blockers

1. `HandoffSatelliteReference` 没有导出 Satellite 的 comparison scope 与
   grounded value/components。仅靠 observation ID 不足以构成独立 artifact
   contract；当前也没有随 JSON/JSONL 交付的 versioned Observation sidecar
   或公开 resolver contract。
2. `export_batch()` 只拒绝重复 `bundle_id`，不拒绝重复
   `(asset_id, research_as_of)`。现有 mixed-coverage 测试实际导出两个相同
   AAPL/cutoff 的 Bundle，未来 Quant 用规定的二元 key join 会得到一对多。

Known limitations 保持不变：Satellite Alpha 尚未 Quant-validated；Selection
family 部分仍 PARTIAL；真实 Timing history coverage 较少；PEER_GROUP
unsupported；真实 non-empty Memory historical replay 仍
`NOT_YET_AVAILABLE`。Handoff readiness 不代表 `deepinsight-quant` 已实现。

## Required Changes From Other Modules

MAIN / Window 1：

- 修复 public Satellite handoff payload，使 external consumer 能读取
  definition/version、usage、comparison scope、coverage 和 grounded
  value/components；保留 per-observation lineage，或提供同批、versioned、
  manifest-declared 的 Observation sidecar/resolver contract。不得让 Quant
  导入 Research service internals 才能解释值。
- 为 batch 定义并强制唯一 join semantics。首选拒绝重复
  `(asset_id, research_as_of)`；若允许 variant，必须把稳定 variant/version
  key 纳入公开 join contract 与 manifest。
- 修复后重新运行本文件新增的两个 acceptance tests 和完整 Gate A，再交
  Window 2 复验。

DATA、AGENTS、MEMORY、LLM_GATEWAY：本轮无生产改动要求。以上问题必须由
Day48 Handoff Owner 修复，不应由 Data Layer 绕过。

## Ready For Integration

NO — `READY_FOR_DAY49 = NO`。返回 Window 1 修复 Day48；Window 2 不执行
Day49。

---

# Phase 4C Day48 — Research → Quant Handoff Re-Acceptance

## Current Status

`DAY48_RESEARCH_QUANT_HANDOFF = PASS`。Window 1 对
`SATELLITE_WIRE_PAYLOAD_INCOMPLETE` 和 `BATCH_JOIN_KEY_AMBIGUOUS` 的定点
修复均通过 Window 2 独立复验；`READY_FOR_DAY49 = YES`。本轮未执行 Day49。

## Current Task

只复验 Day48 repaired contract。未修改 Handoff schema、Builder、Exporter
或任何其他生产实现；未创建 `deepinsight-quant`。

复验矩阵：

| Gate | Result | Independent finding |
|---|---|---|
| Schema/version | PASS | Bundle/manifest 均使用受控 v1 literal 和 `extra="forbid"`；version manifest 完整保留 State/Episode/Satellite/Candidate/Transition/Handoff 解释版本。 |
| Canonical asset identity | PASS | 继续复用 `AssetId`/`Market`，标准 AAPL join identity 为 `US:AAPL`；Sector/Chain 未另建临时映射。 |
| PIT | PASS | `research_as_of` 仍为唯一 Research cutoff；更晚 materialization/export 不改变信息集合或 semantic identity；State/Episode/Observation/Candidate/Transition 对齐保持。 |
| Selection payload | PASS | 每条 wire item 可独立读取 alpha identity、ID、versions、usage、scope、coverage、value/components、quality/confidence、missing reasons、availability。 |
| Timing payload | PASS | Timing wire 使用同一忠实 projection；有效描述值与 `REQUIRES_HISTORY` 均可直接从 artifact 区分。 |
| Faithful projection | PASS | 对 Phase3 AAPL 全部 Selection 与 Timing observations 逐项比较，wire 与源 Observation 的 versions、usage、scope、coverage、value/components、quality/confidence、availability 一致；missing reasons 仅作无损 canonical sorting。 |
| Missing semantics | PASS | `PARTIAL`、`MISSING_INPUT`、`NOT_AVAILABLE_AT_SOURCE_RUN`、`NOT_APPLICABLE`、`UNSUPPORTED`、`REQUIRES_HISTORY` 可经 JSON roundtrip 保留；unavailable value 为 null、components 为空、原因显式，未补零或生成 neutral score。 |
| External-consumer readability | PASS | 黑盒 consumer 只以 stdlib `json` 读取 exported artifact；无需 Observation service、Research DB、Agent 或 Memory internals。 |
| Batch joinability | PASS | 单 batch 中 `(asset_id, research_as_of)` 唯一；重复 key 在创建目录/文件前 hard fail，错误稳定包含 asset 与 cutoff；不同资产同 cutoff、同资产不同 cutoff 均允许。 |
| Serialization | PASS | Single JSON 与 JSONL/manifest contract versioned；single/multi-cutoff manifest semantics 明确。 |
| Determinism | PASS | 输入顺序不改变 export ID、Bundle-ID 排序后的 JSONL 内容或顺序；`created_at` 不改变 Bundle semantic identity。 |
| Provenance | PASS | wire 保留 Observation ID，components 保留直接 provenance refs，aggregate provenance 保留 State/Episode/Claim/Evidence/Event/artifact closure；可沿正式 Research path 解析且无需内联 Evidence graph。 |
| Candidate/Transition | PASS | Candidate/Transition 仍可选且版本/identity closure 未漂移；Transition current State mismatch 继续 hard fail。 |
| Frozen history | PASS | Phase3 无 Sector/Chain/Timing backfill；Phase4A 仅使用 source-run 信息；无真实 predecessor 时维持 `REQUIRES_HISTORY`。 |
| Negative/partial samples | PASS | `QUALIFIED`、`INSUFFICIENT_RESEARCH`、Candidate absent、`PARTIAL`、`MISSING_INPUT`、`REQUIRES_HISTORY` 均可导出。 |
| Internal leakage | PASS | wire 未暴露 Prompt、raw LLM、CoT、FAISS/DuckDB internal IDs、Memory embedding 或 object pointer。 |
| Quant scope leakage | PASS | 未发现 Planetary/Factor exposure、z-score、IC/RankIC、forecast/return、rank/Top-K、BUY/SELL、position/MoE/order/execution semantics。 |
| Engineering gates | PASS | 独立测试、focused/cross-phase/full pytest、leakage、Ruff、mypy、Black 与 diff check 全部通过。 |

## API Changes

无生产 API 变更。Window 2 仅扩展既有外部 consumer acceptance test：

- 校验全部必需 wire 字段；
- 对全部 Phase3 Selection/Timing source observations 做忠实 projection 对比；
- 覆盖 unavailable coverage 状态的 JSON roundtrip 与禁止 numeric fill；
- 校验 duplicate join-key 错误内容及 pre-write failure。

## Files Changed

- `tests/integration/services/test_research_quant_handoff_external_consumer.py`
- `docs/coordination/DATA.md`

## Tests

- Window 2 external-consumer tests：`8 passed`。
- Day48 implementation focused tests：`23 passed`。
- Day45–48 focused regression：`85 passed`。
- Cross-phase State/Episode/Attribution/Dataset/Golden/Satellite/Opportunity/
  Transition/Handoff regression：`120 passed`。
- Full pytest：`650 passed, 5 deselected`。
- Leakage selection：`8 passed, 647 deselected`。
- Ruff：PASS。
- mypy：PASS（`329 source files`）。
- Black：PASS（`329 files`）。
- `git diff --check`：PASS。

## Blockers

NONE。上次两个 Day48 blockers 均已关闭。

保留非阻断限制：Satellite Alpha 尚未 Quant-validated；Selection family
部分仍 PARTIAL；真实 Timing history coverage 较少；PEER_GROUP unsupported；
真实 non-empty Memory historical replay 仍 `NOT_YET_AVAILABLE`。Day48 Handoff
通过不代表 `deepinsight-quant` 已实现。

## Required Changes From Other Modules

None for Day48 re-acceptance。

## Ready For Integration

YES — `DAY48_RESEARCH_QUANT_HANDOFF = PASS`；`READY_FOR_DAY49 = YES`。
Window 2 未执行 Day49。

---

# Phase 4 Day49 — Data Contract Freeze Sync

## Current Status

Day49 accepted the existing canonical Asset, Evidence, Sector/Chain, temporal,
and Handoff join contracts without changing Data production.

## Current Task

Freeze sync only. Default acceptance used frozen artifacts and made zero live
Provider calls.

## API Changes

None. Canonical Quant join key remains unique `(asset_id, research_as_of)`.

## Files Changed

This coordination status only.

## Tests

Full Gate PASS: `650 passed, 5 deselected`; leakage `8 passed`.

## Blockers

None. Quant universe and Planetary Alpha remain outside this repository.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — Data contracts are frozen for Research Intelligence v1.

---

# Phase 4 Pre-Freeze — Alpaca News Range Validation Repair

## Current Status

`ALPACA_NEWS_ADAPTER_REPAIR = PASS`。指定 AAPL failure 已复现并确认为
provider query overfetch，而非 true PIT leakage。修复限定在 Alpaca News
adapter normalization/boundary 层，没有修改 Unified Temporal Contract。

## Current Task

只调查并修复 `ALPACA_NEWS_RANGE_VALIDATION`。未处理 Sector、Report、LLM、
Stocktwits、Quant 或 Day49。

原始 failure reconstruction：

- `REQUEST_WINDOW = [2026-08-31T00:00:00Z,
  2026-09-14T23:59:59.999999Z]`，UTC closed interval；
- `RESEARCH_AS_OF = 2026-09-14T23:59:59.999999Z`；
- real diagnostic：`142` raw records，`3` pages，`2` pagination tokens；
- 唯一 out-of-range item：Alpaca news `61485240`，
  `created_at=2026-08-28T03:32:06Z`，
  `updated_at=2026-08-31T03:05:27Z`，分类 `BEFORE_START`；
- `AFTER_END=0`、`AFTER_RESEARCH_AS_OF=0`、
  `TIMESTAMP_AMBIGUOUS=0`。

Root cause：Alpaca News endpoint 的 interval 为 inclusive，结果按
`updated_at` 排序。Provider 因窗口内更新返回了 publication time 早于
start 的旧文章；旧 adapter 直接把任何 publication-date range mismatch
升级为整批 Provider failure，没有区分安全 overfetch 与 future revision。

Versioned semantics：

- `alpaca_news_created_at_utc_closed_day_v1`；
- date-only `start` 转为 UTC 当日 `00:00:00`，inclusive；
- date-only `end` 转为 UTC 当日 `23:59:59.999999`，inclusive，同时作为
  adapter fetch 的 Research cutoff；因此 end calendar day 内的任意时间
  都是 inside-range，不存在独立的“after request end but <= cutoff”区间；
- `created_at < start` 且 creation/update 均不晚于 cutoff：确定性过滤，
  reason=`before_start`；
- 重复 news ID：确定性过滤，reason=`duplicate_news_id`；
- `created_at` 或 `updated_at > cutoff`：true PIT violation，hard fail；
- timestamp 缺失、无 timezone、不可解析或 update 早于 creation：
  ambiguous/malformed，fail closed；
- 请求参数改为显式 RFC3339 UTC timestamp，避免 date-only 和本地 timezone
  解释差异。

## API Changes

- `AlpacaAdapter.news_fetch_diagnostics()` 返回 credential-free latest-fetch
  diagnostics：window semantics、request bounds、research cutoff、raw/
  accepted/filtered/rejected counts、filter reasons 和 page count。
- `scripts.smoke_alpaca_news` 输出
  `ALPACA_NEWS_RANGE_VALIDATION`、raw/accepted/filtered counts、filter reasons
  与 latest accepted timestamp；不输出正文或 credentials。

## Files Changed

- `src/adapters/providers.py`
- `scripts/smoke_alpaca_news.py`
- `tests/unit/adapters/test_alpaca_news_range.py`
- `docs/coordination/DATA.md`

## Tests

- Focused adapter/normalization/persistence tests：`10 passed`。
- Related legacy regression：`12 passed`。
- Full pytest final successful run：`669 passed, 5 deselected`。
- Leakage：`8 passed, 666 deselected`。
- Ruff：PASS。
- mypy：PASS（`332 source files`）。
- Black：PASS（`332 files`）。
- `git diff --check`：PASS。

Live AAPL News smoke：

- `ALPACA_NEWS_RANGE_VALIDATION=PASS`；
- raw=`147`、accepted=`146`、filtered=`1`；
- filter reasons=`before_start:1`；
- latest accepted timestamp=`2026-09-14T19:49:07Z`；
- all source locators present；
- future/PIT rejection 未触发。

## Blockers

NONE for Alpaca News range validation。

## Required Changes From Other Modules

None。Pre-Freeze AAPL 完整 rerun 由其 Owner 决定；Data Agent 不运行完整
Research Run。

## Ready For Integration

YES — `READY_FOR_AAPL_LIVE_RERUN = YES`。

---

# Phase 4 Final Live — FMP Same-Run Acquisition Repair

## Current Status

`WINDOW2_DATA_REPAIR = PASS`，但真实 integrated smoke 仍被 Provider 当前
rate-limit window 阻塞，不能声明 live PASS。失败 run
`phase4_prefreeze_20260915T125425Z_aapl` 的根因是
`LIVE_PREFLIGHT_DUPLICATES_FORMAL_INGESTION`：外部 independent smoke 已完成
一次完整 15-metric acquisition，`scripts.live_report` 随即重新执行同一
smoke；若第二次成功，后续 `DataIngestionService` 还会再次 fetch。

## Current Task

只消除 FMP same-run acquisition duplication，并保留现有 bounded 429 retry。
未修改 metric mapping、Agent、Sector、Temporal Contract、ResearchState、
Satellite 或 Quant。

Run-scoped contract：

- key=`provider + canonical asset_ids + research_as_of + start/end +
  fmp_standardized_fundamentals_v1`；
- 首次调用获取四个现有 Stable endpoints 并生成 credential-free typed
  `FMPProviderSnapshot`；
- 同 key 后续读取返回 defensive copy，不再访问网络；
- 不同 asset、cutoff 或 window 必须重新获取；
- records 保留 reporting period、accepted/provider timestamp、source locator
  和 canonical metrics；formal ingestion 继续写入 ingestion timestamp；
- live report 使用同一个 adapter 完成 smoke validation 和正式 ingestion，
  并将 snapshot artifact 写到该 run 的 `snapshots/fmp/`；
- manifest 输出 high-level acquisition、snapshot reuse、physical HTTP attempts
  和 retry counts。

FMP 的单次 high-level acquisition 当前必须 fan out 到四个既有 endpoint：
`income-statement`、`ratios-ttm`、`key-metrics-ttm`、
`income-statement-growth`。这不是重复 acquisition，但会放大低配额风险。

## API Changes

- `FMPProviderSnapshot`；
- `FinancialModelingPrepAdapter.fetch_fundamentals_range_at(...)`；
- `FinancialModelingPrepAdapter.acquisition_snapshot(...)`；
- `FinancialModelingPrepAdapter.acquisition_diagnostics()`；
- `ProviderHTTPClient.request_count/retry_count`；
- `scripts.smoke_fmp --verify-reuse`。

## Files Changed

- `src/adapters/fmp.py`
- `src/adapters/http.py`
- `src/adapters/__init__.py`
- `scripts/smoke_fmp.py`
- `scripts/live_report.py`（仅同一 FMP provider instance wiring/artifact）
- `tests/unit/adapters/test_fmp_adapter.py`
- `tests/unit/test_smoke_fmp.py`
- `tests/integration/services/test_fmp_run_scoped_ingestion.py`
- `docs/coordination/DATA.md`

## Tests

- Focused FMP/Provider/DataIngestion/Bundle/live_report：`51 passed`；
- full pytest：`735 passed, 5 deselected`；
- leakage：`8 passed, 732 deselected`；
- Ruff：PASS；mypy：PASS（`344 source files`）；Black：PASS；
  `git diff --check`：PASS。

Offline provider-shaped integration：external acquisition=`1`，snapshot
reuse=`1`，physical endpoint calls=`4`，retry=`0`，canonical DuckDB persistence
和 source lineage 均 PASS。

Live integrated smoke（仅 FMP）：FAIL_CLOSED。当前 shell 需命令级
`FMP_ENABLED=true`；credential present。两次独立尝试均在
`income-statement` 遇到 persistent HTTP 429：external acquisition attempt=`1`，
physical HTTP attempts=`3`，bounded retries=`2`，snapshot reuse=`0`（因首次
acquisition 未成功）。未使用 Fake。

## Blockers

- `FMP_PROVIDER_RATE_LIMIT_WINDOW`：当前真实 Provider 仍持续返回 429；需由
  Provider 配额窗口恢复后再运行一次 FMP-only integrated smoke。

## Required Changes From Other Modules

MAIN：正式 acceptance 不要在 `python -m scripts.live_report` 前另行运行
完整 `scripts.smoke_fmp` acquisition。配置 preflight 使用现有无网络
`scripts.live_report._preflight`；数据 readiness 由 live_report 内第一次真实
FMP snapshot 验证，随后同一 snapshot 供 ingestion/downstream 使用。

## Ready For Integration

NO — `MAIN_INTEGRATION_REQUIRED = YES`；在 Main 移除外部重复 acquisition 且
FMP-only integrated live smoke 成功前，`READY_FOR_FULL_AAPL_LIVE_RERUN = NO`。

---

# Phase 4 Pre-Freeze — FRED/ALFRED Provider-Date Boundary Repair

## Current Status

`FRED_DATE_BOUNDARY_REPAIR = PASS`。失败 run
`20260915T035642Z_aapl` 已用原始 observations 参数安全重放；官方 FRED
HTTP 400 明确指出请求的 `realtime_start=2026-09-15` 晚于 Provider 当日
`2026-09-14`。同一 global instant 在 `America/Chicago` 的日期确为
`2026-09-14`，因此确认是 UTC/provider calendar boundary bug。

## Current Task

只修复 FRED/ALFRED live adapter 的 date-only realtime vintage 投影和 HTTP
错误可观测性。全局 Research cutoff、observation start/end、Unified Temporal
Contract、历史 snapshot/cache 和其他 Provider 均未改变。

Versioned semantics：

- `fred_provider_calendar_closed_v1`；
- timezone-aware runtime `research_as_of` 使用 IANA `America/Chicago` 投影为
  date-only `realtime_start=realtime_end`；
- date-only输入继续原样解释，保持既有历史 ALFRED replay identity；
- naive datetime、超出 observation window 的响应、或不等于请求 cutoff 的
  realtime metadata 均 fail closed；
- observation period 与 realtime vintage 保持独立；FRED vintage precision
  明确为 `date`，不伪造秒级 availability。

## API Changes

- `FREDAdapter.provider_realtime_cutoff(date | datetime) -> date`；
- `FREDProviderRequestError` 暴露 credential-safe structured diagnostics：
  provider、HTTP status、FRED error code/message、参数名和 realtime bounds；
- `ProviderHTTPClient.get_text(..., status_error_factory=...)` 允许 adapter
  消费非成功响应并生成安全错误，不把 raw body/URL/credentials 写入消息；
- Macro ingestion cutoff 接受 date 或 timezone-aware datetime；
- `scripts.smoke_fred` 支持显式 `--research-as-of`、observation window，并输出
  Provider cutoff、12-series coverage、latest observations/vintage 和 leakage。

## Files Changed

- `src/adapters/http.py`
- `src/adapters/providers.py`
- `src/adapters/__init__.py`
- `src/services/data_ingestion.py`
- `scripts/smoke_fred.py`
- `scripts/live_report.py`（仅 FRED exact-instant wiring）
- `tests/unit/adapters/test_fred_adapter.py`
- `docs/coordination/DATA.md`

## Tests

- FRED/provider HTTP focused：`16 passed, 17 deselected`；
- Macro/Radar/Temporal/Golden Replay focused：`37 passed`；
- full pytest：`687 passed, 5 deselected`；
- leakage：`8 passed, 684 deselected`；
- Ruff：PASS；
- mypy：PASS（`333 source files`）；
- Black：PASS（`333 files`）；
- `git diff --check`：PASS。

FRED-only live replay at exact failed-run instant `2026-09-15T03:56:42Z`：

- Provider cutoff=`2026-09-14`；
- series=`12/12`，observations=`1468`；
- realtime metadata=`2026-09-14..2026-09-14`；
- future leakage=`0`；HTTP error=`none`；
- `FRED_ALFRED_PREFLIGHT=PASS`。

## Blockers

None for FRED/ALFRED provider-date projection。

## Required Changes From Other Modules

None。完整 AAPL live rerun 仍由 acceptance Owner 执行。

## Ready For Integration

YES — `READY_FOR_AAPL_LIVE_RERUN = YES`。
