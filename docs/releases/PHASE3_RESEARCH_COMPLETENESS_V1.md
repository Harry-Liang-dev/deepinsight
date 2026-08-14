# DeepInsight Phase 3 — Research Completeness v1

Release status: **FROZEN**  
Freeze baseline: `20260814T100747Z`  
Suggested tag: `phase3-research-completeness-v1`

## Release summary

Phase 3 closes the Research Completeness milestone. DeepInsight can now ingest
real multi-source US research data, project it into one point-in-time canonical
bundle, validate factual and numeric claims, coordinate eight research Agents,
assemble a ten-section report, and evaluate the result through deterministic
checks plus a real LLM Judge.

The release output is research. It does not implement trading, portfolio
construction, backtesting, model training, Factor, Regime, or MoE behavior.

## Goals completed

- Replace document-only context with a typed `ResearchDataBundle`.
- Make Evidence lineage and point-in-time eligibility explicit.
- Supply all eight Agents with role-appropriate, auditable inputs.
- Separate deterministic financial computation from LLM interpretation.
- Close fundamental, technical, macro, news, and sentiment coverage gaps.
- Produce a versioned report evaluation with twelve dimensions.
- Validate the checked-in pipeline against real Providers without Fake fallback.

## Architecture delivered

```text
SEC / FMP / Alpaca / FRED / Stocktwits
                    ↓
        Normalization and DuckDB
                    ↓
          ResearchDataBundle
                    ↓
        Evidence + Point-in-Time Memory
                    ↓
     Four Analysts → Research Manager
                         ↓
                    Bull / Bear
                         ↓
                    Risk Manager
                         ↓
              Markdown / JSON Report
                         ↓
         Deterministic + LLM Evaluation
```

`Validated Claim Collection` is the authoritative factual representation.
Analysts ground new facts in canonical Evidence. Managers consume accepted
upstream claims and preserve recursive provenance. Rejected claims are
quarantined and cannot enter the report.

## Provider matrix

| Provider | Phase 3 responsibility | Runtime status in freeze baseline |
|---|---|---|
| SEC EDGAR | Filing text, XBRL facts, disclosure events | Real / success |
| Financial Modeling Prep | Standardized fundamentals, TTM ratios, valuation | Real / success |
| Alpaca Market Data | AAPL OHLCV, SPY/QQQ/XLK context, financial news | Real / success |
| FRED / ALFRED | Vintage-aware US macro pack | Real / success |
| Stocktwits MCP | Community sentiment, history, attention, messages | Real / success |
| Qwen | Structured Agent inference and report Judge | Real / success |

OpenAI remains a replaceable Provider implementation but was not the
production Provider for this release acceptance.

## Canonical research coverage

### Fundamentals and valuation

The final bundle exposed revenue and net-income growth; gross, operating, and
net margins; ROE and ROA; debt-to-equity and current ratio; EPS TTM; book value
per share; market capitalization; P/E; P/B; and earnings yield. FMP is primary
for standardized metrics. SEC remains authoritative for filings and raw XBRL.
Overlapping values are retained as primary/secondary observations and are not
silently averaged.

### Technical and market context

Deterministic operators produce returns, SMA, distance to moving averages,
realized volatility, drawdown, RSI, ATR, MACD, volume ratio, and relative
strength against SPY, QQQ, and XLK. LLMs interpret these features; they do not
calculate them.

### Macro

The FRED projection covers rates, inflation, labor, growth, and financial
stress. Source observations retain their vintage and cutoff semantics.

### News and sentiment

Alpaca News and SEC disclosures enter the News/Event evidence set. Stocktwits
aggregate sentiment, bullish/bearish distribution, attention, and message
volume enter the Sentiment path. Individual posts remain noisy community
Evidence and are not promoted to verified company facts.

## Eight-agent system

The live baseline completed:

1. Fundamental Analyst
2. Technical Analyst
3. Sentiment Analyst
4. News/Event Analyst
5. Research Manager
6. Bull Manager
7. Bear Manager
8. Risk Manager

Agent inputs are typed and Provider-neutral. Agents do not receive Provider
SDKs, DuckDB, or FAISS handles. Agent and Judge calls share the replaceable
`LLMGateway` boundary.

## Validation snapshot

The freeze evidence is the fresh US:AAPL run under
`data/live_acceptance/20260814T100747Z/`.

| Measure | Result |
|---|---:|
| Default tests | 447 passed, 5 live tests deselected |
| Agents | 8/8 completed |
| Accepted Agent claims | 54 |
| Rejected claims | 2 |
| Traceable citations | 56/56 |
| Numeric accepted claims grounded | 42/42 |
| Citation coverage | 1.00 |
| Citation traceability | 1.00 |
| Factual correctness | 0.97 |
| Trading-instruction compliance | 1.00 |
| Missing-data disclosure | 1.00 |
| Overall evaluation | 0.9675 |

The 2 rejected claims remained quarantined. The scores describe research
quality for one live acceptance; they do not measure investment returns.

Artifacts:

- Report: `rep_27ce48e18b5443f297c485405792c535`
- Evaluation: `eval_041e4ae3647d43c6a8dacc498102d2ca`
- Dataset: `live_aapl_fmp_completeness_v1`
- Evaluation rules: `report_quality_v2`
- LLM/Judge: Qwen `qwen3.7-flash`, real

## Safety properties

- Every accepted factual claim traces to canonical Evidence.
- Numeric claims require exact or deterministic grounding.
- Source and observation times are checked against the run cutoff.
- Report assembly cannot create a new factual claim.
- DeepInsight-generated trades, positions, orders, and target prices are
  prohibited.
- Credentials are environment-only and absent from manifests and artifacts.

## Known limitations

- The formal live acceptance currently covers one US single-asset case,
  US:AAPL; it does not establish broad-market or cross-market quality.
- Alpaca raw bars do not supply every adjusted-close and turnover field in the
  accepted configuration. The limitation is disclosed without estimation.
- Historical research, prior-risk, analog, and regime Memory may be
  `EMPTY_VALID` until the system accumulates its own dated research history.
- Analyst consensus, forecasts, earnings transcripts, and insider transactions
  remain optional future enrichment.
- Qwen is the currently validated production live Provider. The retained
  OpenAI path still requires an independent funded-account acceptance.
- The system evaluates research quality, not portfolio performance or alpha.

## Compatibility and operation

- Python: `>=3.12,<3.13`
- Dependency source: `pyproject.toml`
- Environment: Conda interpreter plus `uv`
- Default tests: offline and deterministic
- Live runs: explicit, fail-closed, and credential-free in their persisted
  manifest

See [README](../../README.md), [operations](../operations.md),
[module status](../MODULE_STATUS.md), and [decisions](../DECISIONS.md).

## Next phase

Phase 4 is **Structured Research Intelligence**, not an extension of this
release's report tuning. Planned work includes `ResearchStateSnapshot`,
point-in-time research datasets, factor infrastructure, and regime
representation. Factor mining, MoE, backtesting, post-training, and strategy
development remain future work and are not part of this release.
