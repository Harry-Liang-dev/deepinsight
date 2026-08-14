# DeepInsight

> **Institutional-grade AI research, grounded in evidence.**

DeepInsight is an evidence-grounded multi-agent AI investment research system
designed to turn fragmented market, fundamental, macro, news, and sentiment
data into auditable institutional-style research.

It is not a stock-picking chatbot, and it does not ask an LLM to guess financial
numbers. DeepInsight builds a canonical research dataset first, validates every
accepted factual claim against Evidence, and then uses specialized Agents for
interpretation, debate, risk reasoning, and report synthesis.

- Multi-source financial intelligence
- Eight-agent research organization
- Evidence-grounded and numerically validated claims
- Point-in-time-safe data and Memory boundaries
- Auditable Markdown and JSON research reports

The current Phase 3 product output is an **AI Research Report**. Trading,
portfolio allocation, backtesting, model training, Factor, Regime, and MoE
capabilities are not part of the current release.

## How it works

```mermaid
flowchart TD
    S[SEC EDGAR] --> D[Data Ingestion]
    F[FMP] --> D
    A[Alpaca] --> D
    R[FRED] --> D
    T[Stocktwits] --> D
    D --> B[ResearchDataBundle]
    B --> E[Evidence + Memory]
    E --> FA[Fundamental Analyst]
    E --> TA[Technical Analyst]
    E --> SA[Sentiment Analyst]
    E --> NA[News / Event Analyst]
    FA --> RM[Research Manager]
    TA --> RM
    SA --> RM
    NA --> RM
    RM --> BU[Bull Manager]
    RM --> BE[Bear Manager]
    BU --> RI[Risk Manager]
    BE --> RI
    RI --> RP[Auditable Research Report]
    RP --> EV[Evaluation]
```

The deterministic layer computes and normalizes financial values before model
inference. LLMs are responsible for interpretation, synthesis, debate, and risk
reasoning—not raw financial arithmetic.

The authoritative fact flow is:

```text
Multi-source Data
→ Canonical Research Data
→ Evidence
→ Analyst Validated Claims
→ Manager Claims
→ Research Report
```

## Research capabilities

### Fundamental intelligence

- Revenue and net-income growth
- Gross, operating, and net margins
- ROE and ROA
- Liquidity and leverage
- EPS TTM and book value per share
- Market capitalization, P/E, P/B, and earnings yield

### Technical intelligence

- Multi-window returns and simple moving averages
- RSI, MACD, and ATR
- Realized volatility and maximum drawdown
- Volume ratio
- Relative strength versus SPY, QQQ, and XLK

### Macro intelligence

- Rates and yield-curve context
- Inflation
- Labor conditions
- Growth and industrial production
- Financial stress

### Sentiment intelligence

- Community sentiment and bullish/bearish distribution
- Attention and message volume
- Sentiment change
- Raw community messages retained as supporting Evidence, not verified facts

### News and events

- SEC filings and corporate events
- Alpaca financial news
- Point-in-time event lineage and source references

## Data sources

| Provider | Capability | Current role |
|---|---|---|
| SEC EDGAR | Filings, XBRL facts, corporate events | Authoritative filing and disclosure source |
| Financial Modeling Prep | Standardized US fundamentals, TTM ratios, valuation | Primary standardized-metric source; disabled unless configured |
| Alpaca Market Data | OHLCV, benchmarks, financial news | Primary price, market/sector context, and news source |
| FRED / ALFRED | Macroeconomic observations and vintages | Point-in-time macro source |
| Stocktwits MCP | Community sentiment and attention | Sentiment Evidence; not treated as verified company fact |
| Qwen | Structured LLM inference and evaluation | Current production live LLM through the shared `LLMGateway` |

Several live Providers require credentials from the user's own accounts. No
credential value belongs in the repository.

## The eight-agent research organization

1. **Fundamental Analyst** — growth, profitability, balance sheet, and valuation
2. **Technical Analyst** — trend, momentum, volatility, volume, and relative strength
3. **Sentiment Analyst** — community positioning, attention, and disagreement
4. **News/Event Analyst** — filings, corporate events, and financial news
5. **Research Manager** — integrates the four Analyst claim sets
6. **Bull Manager** — constructs the evidence-supported upside thesis
7. **Bear Manager** — constructs the evidence-supported downside thesis
8. **Risk Manager** — reviews macro, event, market, and thesis risks

Managers consume validated upstream claims; they do not reconnect to Providers
or independently fetch facts. Agents never depend directly on DuckDB, FAISS, or
a Provider SDK.

## Evidence grounding

Every accepted factual claim retains provenance to canonical Evidence. Numeric
claims require either an exact source literal or a deterministic feature
calculation. Unknown citations, unsupported numbers, and prohibited claim
intents are quarantined and cannot enter managers or reports.

DeepInsight deliberately prefers an explicit gap over an invented completion:
if a fact cannot be validated, it is rejected or disclosed as missing.

## Point-in-time safety

Research data, source timestamps, and Memory retrieval share an explicit
`as_of` cutoff. Records observed after that cutoff are not eligible for the
run. This prevents future leakage and establishes the foundation for future
point-in-time research datasets, factor research, regime representation, and
backtesting—none of which are claimed as implemented here.

## Phase 3 validation snapshot

Research Completeness v1 was frozen on the real US:AAPL acceptance run
`20260814T100747Z`:

| Check | Result |
|---|---:|
| Default pytest | 447 passed, 5 live tests deselected |
| Eight Agents | 8/8 completed |
| Accepted Agent claims | 54 |
| Rejected claims | 2, quarantined |
| Unique citations traced | 56/56 |
| Citation coverage | 1.00 |
| Citation traceability | 1.00 |
| Numeric grounding | 1.00 |
| Factual correctness | 0.97 |
| Trading-instruction compliance | 1.00 |
| Overall report evaluation | 0.9675 |

This is one live **research-quality acceptance** using real SEC, FMP, Alpaca,
FRED, Stocktwits, and Qwen services. It is not an investment-return result,
trading benchmark, or statement of future performance.

## Example output

The accepted AAPL report combines:

- a standardized growth, margin, profitability, liquidity, and valuation snapshot;
- rates, inflation, labor, growth, and financial-stress context;
- trend, momentum, volatility, volume, drawdown, and benchmark-relative strength;
- aggregate community sentiment and attributable financial news;
- separate Bull, Bear, Risk, and final synthesis sections.

Local live artifacts are written to a timestamped, Git-ignored directory:

```text
data/live_acceptance/20260814T100747Z/
├── run_manifest.json
├── research_data_bundle.json
├── research_data_bundle_summary.json
├── duckdb/platform.duckdb
└── reports/
    ├── rep_27ce48e18b5443f297c485405792c535.md
    ├── rep_27ce48e18b5443f297c485405792c535.json
    └── rep_27ce48e18b5443f297c485405792c535.evaluation.json
```

Generated acceptance data is evidence for a local run and is not intended for
source control.

## Installation

DeepInsight targets Ubuntu and Python 3.12. Conda provides the interpreter;
`uv` resolves and installs dependencies from the sole dependency declaration,
`pyproject.toml`. The project does not create an in-repository `.venv`.

```bash
conda env create --file environment.yml
conda activate deepinsight
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

To create the environment without `environment.yml`:

```bash
conda create -n deepinsight python=3.12 pip -y
conda activate deepinsight
python -m pip install uv
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

## Configuration

[`src/core/settings.py`](src/core/settings.py) is the typed configuration source.
The application reads environment variables only; it does not load `.env`
files. [`.env.example`](.env.example) is a name-and-default reference, not a
credential store.

Prepare a private shell script outside the repository:

```bash
chmod 600 ~/.local/bin/load_deepinsight_keys.sh
source ~/.local/bin/load_deepinsight_keys.sh
```

Core live variables:

| Variable | Required for |
|---|---|
| `DEEPINSIGHT_LLM_PROVIDER=qwen` | Selecting the production Qwen path |
| `QWEN_API_KEY` | Qwen inference and evaluation |
| `QWEN_MODEL_NAME` | Qwen model selection; current default is `qwen3.7-flash` |
| `DEEPINSIGHT_PROVIDER_SEC_USER_AGENT` | SEC Fair Access identity |
| `DEEPINSIGHT_PROVIDER_SEC_CIK_MAP` | Canonical asset-to-CIK mapping |
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Alpaca data and news |
| `FRED_API_KEY` | FRED/ALFRED macro data |
| `STOCKTWITS_MCP_ENABLED=true` | Explicit Stocktwits MCP enablement |
| `FMP_ENABLED=true`, `FMP_API_KEY` | FMP standardized metrics |
| `DEEPINSIGHT_LIVE_*` | Versioned live dataset, cutoff, window, and output root |

Stocktwits authorization state is stored under the configured local
`STOCKTWITS_MCP_TOKEN_STORE`, which is ignored by Git. Never display, attach,
or commit the private loader, OAuth state, or any secret.

## Quick start

### Offline API demo

The deterministic offline path requires no external credentials:

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn apps.api.offline_main:app \
  --host 127.0.0.1 --port 8001
```

Health check:

```bash
curl --fail http://127.0.0.1:8001/health
```

Submit the fixed offline single-asset workflow through the same public API
contract used by production composition:

```bash
curl --fail \
  -H "Content-Type: application/json" \
  -d '{
    "report_date": "2026-08-14",
    "market_scope": "US",
    "report_type": "single_asset",
    "asset_ids": ["US:AAPL"],
    "language": "en",
    "include_sections": [
      "executive_view", "macro_context", "fundamentals",
      "technical_text", "sentiment", "news_events",
      "bull_case", "bear_case", "risk_review", "final_synthesis"
    ],
    "force_refresh": false
  }' \
  http://127.0.0.1:8001/v1/reports/generate
```

The production application factory is available separately and requires its
configured DuckDB/FAISS/Redis and live Provider environment:

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn \
  apps.api.production:create_production_application --factory \
  --host 127.0.0.1 --port 8000
```

Routes delegate to injected application services; they do not call databases,
vector indexes, or LLM Providers directly. See [API documentation](docs/api.md)
for the complete contract.

### Live provider smokes

After sourcing the private shell environment, each smoke remains explicit and
outside default pytest:

```bash
"$CONDA_PREFIX/bin/python" -m scripts.smoke_sec_edgar
"$CONDA_PREFIX/bin/python" -m scripts.smoke_alpaca
"$CONDA_PREFIX/bin/python" -m scripts.smoke_fred
STOCKTWITS_MCP_ENABLED=true \
  "$CONDA_PREFIX/bin/python" -m scripts.smoke_stocktwits
FMP_ENABLED=true \
  "$CONDA_PREFIX/bin/python" -m scripts.smoke_fmp
DEEPINSIGHT_LLM_PROVIDER=qwen \
  "$CONDA_PREFIX/bin/python" -m scripts.smoke_qwen --diagnostic
```

### Reproducible live report

`scripts.live_report` is fail-closed: every required Provider, Qwen Judge, and
dataset field must be configured, and no Fake fallback is allowed.

```bash
source ~/.local/bin/load_deepinsight_keys.sh
env -u ALL_PROXY -u all_proxy \
  DEEPINSIGHT_LLM_PROVIDER=qwen \
  FMP_ENABLED=true \
  STOCKTWITS_MCP_ENABLED=true \
  DEEPINSIGHT_LIVE_DATASET_VERSION=live_aapl_release_v1 \
  DEEPINSIGHT_LIVE_AS_OF_DATE=YYYY-MM-DD \
  DEEPINSIGHT_LIVE_DATA_START=YYYY-MM-DD \
  DEEPINSIGHT_LIVE_DATA_END=YYYY-MM-DD \
  "$CONDA_PREFIX/bin/python" -m scripts.live_report
```

Choose a closed, internally consistent window where
`data_start <= data_end <= as_of_date`. The command creates a new timestamped
directory unless `DEEPINSIGHT_LIVE_ROOT` explicitly selects a new empty root.

## Quality gates

Default tests are deterministic, offline, and exclude the `live` marker:

```bash
"$CONDA_PREFIX/bin/python" -m pytest -q
"$CONDA_PREFIX/bin/python" -m ruff check .
"$CONDA_PREFIX/bin/python" -m mypy .
"$CONDA_PREFIX/bin/python" -m black --check .
git diff --check
```

The offline research benchmark is also deterministic:

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/integration/benchmark -q
```

## Repository structure

```text
apps/                    API, Worker, Scheduler, and Web composition roots
config/                  Provider metadata, prompts, and evaluation rules
src/
├── adapters/            External Provider boundaries
├── agents/              Eight-agent contracts and coordination
├── benchmark/           Offline benchmark runner
├── evaluation/          Deterministic and LLM-Judge evaluation
├── memory/              Point-in-time research Memory
├── operators/           Deterministic financial feature calculations
├── repositories/        DuckDB and FAISS persistence boundaries
├── reports/             Report contracts and assembly
├── schemas/             Shared Pydantic v2 domain contracts
└── services/            Ingestion, Gateway, and Bundle services
scripts/                 Explicit operations and live-smoke entry points
tests/                   Offline unit/integration tests and isolated live tests
docs/                    Specifications, decisions, tasks, releases, and operations
```

## Roadmap

- **Phase 1 — Research Operating System Foundation:** done
- **Phase 2 — Evaluation, Benchmark, and Real Data Validation:** done
- **Phase 3 — Research Completeness v1:** done and frozen
- **Phase 4 — Structured Research Intelligence:** planned
  - `ResearchStateSnapshot`
  - point-in-time research datasets
  - factor infrastructure
  - regime representation
- **Future research:** factor mining, regime-aware routing, MoE, backtesting,
  model post-training, and a strategy layer

The long-term direction is an end-to-end research and quantitative-development
system, but the implementation sequence starts with trustworthy research data
and auditable claims—not trading.

## Documentation

- [Master specification](docs/MASTER_SPEC.md)
- [Coding guide](docs/CODING_GUIDE.md)
- [Module status](docs/MODULE_STATUS.md)
- [Architecture decisions](docs/DECISIONS.md)
- [Schema reference](docs/schema.md)
- [Operations guide](docs/operations.md)
- [Phase 3 release notes](docs/releases/PHASE3_RESEARCH_COMPLETENESS_V1.md)
- [Phase 3 founder roadshow (Chinese)](docs/roadshow/DEEPINSIGHT_PHASE3_ROADSHOW_CN.md)

## Disclaimer

DeepInsight is currently a research system. It does not provide investment
advice, portfolio allocation, or trade execution.
