# Current Status

Phase 3 Final Gate blocker integration was executed on 2026-08-13. Main-owned
offline fixtures now use `agent_output_v2`; full offline E2E, strict Evidence
validation, cache reliability, type checking, formatting, and the offline
Benchmark are green. Gateway schema failures now retain credential-safe schema
identity, validation paths, and Expected/Actual/Missing/Extra/Type-mismatch
diagnostics instead of collapsing into `agent_execution`.

The live seven-Agent hard gate is still blocked. Latest candidate
`agent_contract_20260812T193505Z_785547ec` passed 5/7. Fundamental failed
claim/binding cardinality after its single repair attempt; Bear failed exact
numeric grounding after its single repair attempt. Risk, eight-Agent gate,
fresh acceptance, report, and Evaluation were therefore not run.

Phase 3 coordination is established. Window 1 owns architecture, shared
interfaces, integration, and quality gates. Windows 2–5 report through their
own files and do not directly change another window's module.

Day 22 completed a read-only reverse audit of live run `20260808T082315Z`.
The result is specified in `docs/tasks/phase3_data_completeness.md`. No
production code, Prompt, Evaluation rule, or live artifact was changed.

The current runtime has eight Agents and one shared `AgentContext`. The four
Analysts consume structured features, retrieved documents, and Memory. The
four Managers consume validated Analyst outputs plus shared context; they must
not fetch Provider data.

## Current Task

Close producer/consumer drift without weakening Evidence validation. Technical,
Sentiment, News/Event, Bull, and Bear now generate one authoritative Claim
object collection and deterministically assemble their public prose/binding
shape. Fundamental and Research retain their current public generation shape;
the remaining blocker proves Fundamental still needs the same producer-side
single-source treatment. Bear additionally needs a producer-side way to omit
an unsupported numeric claim within its one allowed repair, not validator
relaxation or ID correction.

Define the Phase 3 Agent data contract before adding more Providers. The live
audit establishes the following integration order:

1. attributable structured Evidence and one availability manifest;
2. SEC structured fundamentals and multi-period history;
3. attributable adjusted market/technical data;
4. macro and market/industry context;
5. licensed event, news, sentiment and consensus coverage.

### Canonical capability layers

```text
Provider records
  -> normalized facts/events/bars/documents
  -> attributable Evidence Package
  -> role-specific Agent input view
  -> Analyst outputs
  -> Manager global context + Analyst outputs
  -> report + Evaluation
```

Every role input must answer four questions:

1. What data is present?
2. What required or optional data is absent?
3. What time window and as-of boundary apply?
4. Which source reference grounds every fact and numeric value?

### Eight-Agent data matrix

| Agent | Direct inputs | Must-have data | Optional context | Must not do | Missing-data behavior |
|---|---|---|---|---|---|
| Fundamental Analyst | Fundamental role view | Asset identity; report/as-of date; normalized income, balance-sheet and cash-flow facts when available; filing evidence; fiscal period/unit/currency; source lineage | Valuation inputs, issuer L2 Memory, industry comparison, corporate actions | Fetch data; calculate undisclosed metrics; use unattributable structured numbers | Name each absent statement/metric/period and lower certainty |
| Technical Text Analyst | Technical role view | Attributable OHLCV window; adjustment/feed/calendar metadata; deterministic indicators; price evidence references | Corporate actions, volatility regime, market/industry relative series, L0/L4 Memory | Fetch prices; calculate indicators in the LLM; cite filing text as price evidence | State insufficient history, stale bars, missing adjustment or benchmark series |
| Sentiment Analyst | Sentiment role view | Timestamped attributable text sample; source class; sample window/count; language; issuer/entity match | L1/L2 Memory, source-quality and coverage metadata | Treat one filing as broad investor sentiment; infer unsampled social sentiment | Disclose sample, channel, recency and market-coverage limits |
| News Event Analyst | Event role view | Timestamped events/documents; event type; issuer/entity mapping; original locator; publication/effective time | Materiality metadata, prior related events, market/macro context | Fetch news; invent event impact or merge unrelated entities | Separate confirmed event, possible impact and unresolved facts |
| Research Manager | Validated Analyst outputs + global context | Analyst coverage manifest; evidence links; contradictions; missing-data manifest; as-of boundary | Macro, market/industry and relevant Memory summaries | Re-read Providers; add new facts; hide failed Analyst coverage | Preserve disagreements and missing roles explicitly |
| Bull Manager | Research summary + validated Analyst outputs | Constructive evidence, required conditions, counterevidence, coverage manifest | Macro/industry context and historical analog Memory | Add facts, targets, trades or Provider calls | Reduce confidence and state which constructive premise lacks evidence |
| Bear Manager | Research summary + validated Analyst outputs | Adverse evidence, required conditions, invalidators, coverage manifest | Risk/event/macro context and historical analog Memory | Add facts, targets, trades or Provider calls | Reduce confidence and distinguish confirmed weakness from scenario |
| Risk Manager | Bull/Bear outputs + research summary + validated evidence | Confirmed risks, scenario risks, missing data, conflicting evidence, time validity | Liquidity, regulatory, macro and event Memory | Add unsupported facts, execute trades or call Providers | Treat missing coverage as risk and keep scenarios conditional |

### Shared data capabilities

| Capability | Minimum attributable content | Primary consumers |
|---|---|---|
| Fundamental | Period, report type, unit, currency, statement facts, derived-feature provenance | Fundamental, Research, Bull/Bear, Risk |
| Technical | Raw/adjusted flag, feed, trading dates, OHLCV, computed-feature window/version | Technical, Research, Bull/Bear, Risk |
| Sentiment | Channel, sample count/window, language, source quality, texts | Sentiment, Research, Risk |
| News/Event | Entity, event type, publish/effective time, source locator, text | News, Research, Bull/Bear, Risk |
| Macro | Series/event identity, geography, effective time, release vintage, source | All Analysts when relevant; all Managers |
| Market/Industry | Benchmark identity, constituent/industry mapping, relative window, source | Fundamental, Technical, Managers |
| Memory | Level, namespace, effective time, retrieval score, source reference, snapshot/version | All roles through role-filtered retrieval |
| Evidence | Stable evidence ID, source/provider, locator, observed/published/effective time, content hash, unit and transformation lineage | Every claim-producing component |

### Current gaps to resolve before Provider expansion

- `structured_features` is a generic JSON object rather than typed role views.
- Structured numeric features do not carry first-class `SourceReference` links;
  report citations currently favor documents/Memory.
- Data availability and freshness are inferred from nulls instead of one
  canonical manifest.
- All four Analysts receive the same context rather than least-privilege role
  projections.
- Fundamental structured extraction from filings is incomplete; current SEC
  strength is attributable filing text.
- Real sentiment, general news, macro, market benchmark, and industry datasets
  are not yet complete across CN/HK/US.
- Manager inputs need an explicit global-context/evidence package contract,
  even though Managers already avoid direct Provider calls.

### Day 22 live evidence

- DuckDB contains 63 real Alpaca bars and one SEC filing, but zero rows in
  `fundamentals`, `macro_series`, and `corporate_events`.
- All fundamental structured metrics were null. Only close, SMA20/SMA60,
  20-day return, and trend label were populated.
- Technical failed because a structured numeric claim lacked attributable
  evidence; Sentiment failed because no proper sentiment dataset existed.
- All eight Agents retrieved two SEC chunks and zero Memory items. The only
  L3 Memory item was written after report completion.
- The final report contains two unique SEC citations and no Alpaca citation,
  despite the real bar ingestion.
- Saved Evaluation scores include evidence consistency 0.3, Bull/Bear balance
  0.2, and factual correctness 0.6302. The saved single numeric failure was a
  known punctuation-scanner false positive; the deeper gap is pre-report
  structured numeric lineage.

## API Changes

- `LLMSchemaValidationError` now carries safe schema name/version, field paths,
  error types, and contract diff without rejected values, Prompt, or credential.
- Invalid provider JSON is classified as `LLMInvalidJSONError`.
- Real Gateway Agent calls allow at most one structured-output repair with
  unchanged Evidence/input; Fake Gateway never repairs.
- Agent/LLM metadata records structured-output attempt count and repair state.
- Technical, Sentiment, News/Event, Bull, and Bear use Claim-object generation
  schemas; public response schemas remain unchanged after deterministic
  assembly.

Proposed for Main Agent review; not yet approved or implemented:

- `EvidenceItem`: stable evidence identity plus provider, locator, timestamps,
  content hash, unit, currency and transformation lineage.
- `DataAvailabilityManifest`: requested/present/missing/stale fields, reason,
  as-of time and source coverage.
- `ResearchEvidenceBundle`: fundamental, technical, sentiment, event,
  macro, market/industry, Memory and evidence collections.
- Four role-specific Analyst input views derived from the bundle.
- `ManagerResearchContext`: validated Analyst outputs, coverage, conflicts,
  global context and evidence index; no Provider clients.

These names describe required boundaries, not final accepted schemas. Main
must reconcile them with `AgentContext`, ingestion records and Memory APIs.

The full required fields, SLA proposals, Provider order, ownership split, and
acceptance criteria are now recorded in
`docs/tasks/phase3_data_completeness.md`. Final schema names remain pending an
interface review; no parallel schema family is approved yet.

## Files Changed

Main blocker-integration files include `apps/api/offline.py`, the shared Agent
base/contracts and role implementations, Agent/LLM schemas, LLM Gateway and
Provider boundaries, `scripts/live_agent_contract.py`, affected Prompts, and
their regression tests.

- `AGENTS.md`
- `docs/coordination/MAIN.md`
- `docs/coordination/DATA.md`
- `docs/coordination/AGENTS.md`
- `docs/coordination/MEMORY.md`
- `docs/coordination/LLM_GATEWAY.md`
- `docs/tasks/phase3_data_completeness.md`

## Tests

Final offline evidence:

- pytest: `395 passed, 5 deselected`
- fixed-bundle Fake contract: `7/7 PASS`
- offline `research_benchmark_v1`: `7/7 PASS`
- Ruff: PASS
- mypy: `0 errors / 255 source files`
- Black: PASS
- `git diff --check`: PASS

Latest live candidate used `qwen/qwen3.7-flash` and
`phase3_research_completeness_final_v1`: `5/7 PASS`. Fundamental failed after
one repair with an unbound business claim; Bear failed after one repair with
an unsupported exact numeric literal. No fuzzy matching, ID correction, or
Fake fallback occurred.

First Main integration quality gates on 2026-08-09:

- pytest: `314 passed, 5 deselected`
- offline `research_benchmark_v1`: `7/7 passed`
- Ruff: PASS
- mypy: PASS (`230 source files`)
- Black: PASS (`230 files unchanged`)
- `git diff --check`: PASS

## Blockers

- P0: Fundamental producer still independently emits prose and bindings; one
  real run produced a cardinality mismatch after the only allowed repair.
- P0: Bear Claim schema is synchronized, but one real run still emitted a
  numeric thesis whose bound Evidence lacked that exact literal after repair.
- Gate consequence: Risk and Fresh Acceptance are prohibited until one live
  candidate reaches 7/7 with zero invalid citations, schema errors, unbound
  claims, and ungrounded numeric claims.

- Shared interface blockers are resolved under ADR-0025.
- Historical resolved blockers: canonical Evidence conversion, role-specific
  contracts, Workflow bundle pairing, Memory schema version, Gateway metadata
  call-site wiring, and full mypy.
- Real CN/HK fixed-source coverage remains incomplete.
- Real sentiment/news licensing and retention policy is not settled.
- Macro and market/industry context Providers are not implemented end to end.
- Current Alpaca-derived technical features still need Data-owned field-level
  Evidence before they can be cited as first-class research facts.
- Real data coverage remains incomplete; this is the next Phase 3 task, not a
  cross-module integration blocker.

## Required Changes From Other Modules

- AGENTS: converge Fundamental generation to one authoritative Claim
  collection while retaining its normalized scores and public schema.
- LLM_GATEWAY: no cache redesign is required. Preserve the one-repair maximum
  and new safe diagnostics.
- DATA / MEMORY: no blocker or change request.

- Resolved: the four child interfaces are accepted and wired by Main.
- DATA should next extend the accepted Bundle rather than create a new input.
- AGENTS, MEMORY and LLM_GATEWAY have no cross-module change request pending.
- Any future shared Schema change still requires Main review.

## Ready For Integration

NO — offline integration is green, but the live seven-Agent hard gate is 5/7;
Risk and Fresh Acceptance remain correctly blocked.
