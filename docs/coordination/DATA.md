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
