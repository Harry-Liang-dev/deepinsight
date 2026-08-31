# Phase 4 Sector Data Capability Matrix

This audit describes capabilities implemented by the checked-in Provider
adapters as of 2026-08-30. It does not infer capabilities from a vendor's
marketing site.

| Capability | FMP | Alpaca | SEC EDGAR | FRED | Stocktwits |
|---|---|---|---|---|---|
| Company sector | MISSING | MISSING | PARTIAL: SIC exists upstream but is not mapped to `SectorOntology` | MISSING | MISSING |
| Company industry | MISSING | MISSING | PARTIAL: SIC exists upstream but is not a canonical industry classification | MISSING | MISSING |
| ETF market data | MISSING | AVAILABLE | MISSING | MISSING | MISSING |
| Constituent asset mapping | MISSING | MISSING | MISSING | MISSING | MISSING |
| Fundamental metrics | AVAILABLE | MISSING | AVAILABLE | MISSING | MISSING |
| Price history | MISSING | AVAILABLE | MISSING | MISSING | MISSING |
| News | MISSING | AVAILABLE | PARTIAL: filings/events only | MISSING | MISSING |
| Earnings | PARTIAL: historical statements, no calendar contract | PARTIAL: attributed news only | AVAILABLE: filings and company facts | MISSING | MISSING |
| Sentiment | MISSING | MISSING | MISSING | MISSING | AVAILABLE |
| Macro | MISSING | MISSING | MISSING | AVAILABLE | MISSING |

`FinancialModelingPrepAdapter.fetch_instruments()` intentionally returns no
rows and the current adapter has no profile/screener/classification endpoint.
Consequently, FMP is not presented as a constituent or classification source.

## Day31 v1 universe boundary

Day31 uses the task-approved fallback: the current five-asset research
universe. Its `sector_universe_membership_v1` revision is deterministically
promoted from the approved Day30 mapping with an explicit internal-curation
source, so live snapshots never identify a test fixture as production
classification. It does not claim to be an exhaustive US security universe:

| Sector | Assets | Optional benchmark | Mapping quality |
|---|---|---|---|
| S01 Semiconductors & AI Compute | `US:NVDA`, `US:AMD`, `US:TSM` | `US:SOXX` | AVAILABLE |
| S02 Memory & Storage | `US:MU` | `US:SOXX` | PARTIAL: broad semiconductor proxy |
| S03 Consumer Electronics & Hardware | `US:AAPL` | `US:XLK` | PARTIAL: broad technology proxy |

All 18 Sectors have an explicit optional ETF candidate entry. A candidate is
not promoted into a `SectorBenchmarkMapping` until Alpaca returns a real daily
bar in the requested point-in-time window. A Sector may therefore have an
empty benchmark mapping with status MISSING.

Live smoke `20260830T024104Z` validated all five required assets and 17 unique
ETF candidates through Alpaca IEX daily bars for 2026-07-30 through
2026-08-29. The credential-free DuckDB artifact is stored locally at
`data/live_sector_universe/20260830T024104Z/sector_universe.duckdb` and remains
outside source control.

## Sufficiency decision

`CURRENT_DATA_SOURCES_SUFFICIENT = YES` for the explicitly scoped Day31 v1
universe: versioned internal membership supplies classification and Alpaca
supplies real asset/ETF price validation. Existing sources are not sufficient
for automatic, exhaustive constituent discovery across all 18 Sectors. That
limitation is recorded as PARTIAL coverage rather than hidden or filled with
unverified assets; it does not justify adding a Provider in Day31.
