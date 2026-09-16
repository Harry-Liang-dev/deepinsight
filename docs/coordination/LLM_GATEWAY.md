# Current Status

Phase 3 Final Gate blocking fix `LLM CACHE RELIABILITY` is implemented and
verified with offline tests. A transient DuckDB cache-read failure is now a
bounded, observable degraded cache miss and no longer prevents Provider
invocation. Permanent schema, integrity, corruption, and programming errors
remain explicit failures before Provider invocation.

The failed acceptance artifact
`data/live_acceptance/20260812T170421Z/phase3_completeness_summary.json`
contains only the former Gateway-level error. It has no `run_manifest.json` or
related log retaining the original DuckDB exception. The database is currently
readable and its six cache payloads are valid JSON, so the exact historical
DuckDB exception subtype cannot be recovered.

# Current Task

Completed the LLM cache runtime reliability pass:

- classified DuckDB repository errors into narrowly defined transient and
  permanent failures without exposing raw database messages;
- added bounded cache-read/write retry with injected sleep for deterministic
  tests;
- changed exhausted transient cache reads to an explicit degraded miss;
- kept permanent cache read failures fail-closed;
- kept successful Provider responses usable when cache persistence degrades;
- added per-request-fingerprint single-flight coordination;
- verified operation-scoped DuckDB connections and concurrent cache access
  with eight workers;
- preserved request fingerprint, Provider retry/rate-limit behavior, and safe
  logging.

# API Changes

- Added `TransientRepositoryError`, carrying only a safe
  `database_error_type`; existing `RepositoryError(message)` construction
  remains compatible.
- Added `LLMCacheReliabilityPolicy` with cache read retries `0..2`, cache write
  retries `0..2`, and deterministic bounded exponential backoff.
- Added injectable `LLMSingleFlight` and `sleeper` dependencies to
  `LLMGateway`.
- Extended `LLMRunMetadata` with `cache_read_status`, `cache_write_status`,
  `cache_retry_count`, `cache_read_error_type`, and
  `cache_write_error_type`.
- `retry_count` continues to mean Provider retry count. Cache retries are
  separately reported and do not bypass the Provider rate-limit/retry policy.

# Files Changed

- `src/repositories/base.py`
- `src/repositories/__init__.py`
- `src/schemas/llm.py`
- `src/services/llm_gateway.py`
- `src/services/__init__.py`
- `tests/unit/repositories/test_database.py`
- `tests/unit/services/test_llm_gateway.py`
- `tests/integration/services/test_llm_cache_reliability.py` (new)
- `docs/coordination/LLM_GATEWAY.md`

# Tests

Added coverage for normal hit/miss, transient read recovery, exhausted read
fallback, permanent read failure, Provider failure after degraded read,
transient/permanent cache write failure, fingerprint stability, safe logging,
connection isolation, eight concurrent reads/writes, eight concurrent Agent
requests, corrupt cached JSON, and exactly-once Provider invocation for eight
identical concurrent requests.

Final quality-gate results:

- full default offline pytest: `369 passed, 5 deselected`;
- dedicated cache concurrency regression: `4 passed`;
- Ruff: passed;
- Black: passed (`252 files would be left unchanged`);
- `git diff --check`: passed;
- focused strict mypy for all eight Gateway/cache Python files: passed;
- full-repository mypy: failed with 28 errors only in the Agent-window file
  `tests/unit/agents/test_agents.py:491-499`;
- default tests are offline and use `FakeLLMProvider`; no external API was
  called.

# Blockers

- The historical underlying DuckDB exception cannot be identified exactly
  because the old code discarded exception type/message and the failed
  acceptance directory has no log or run manifest. New failures retain a safe
  exception class in metadata/logs without retaining sensitive/raw content.
- Full-repository mypy currently reports errors in the Agent-window file
  `tests/unit/agents/test_agents.py`. This LLM Gateway window must not modify
  Agent code or tests; focused mypy for all Gateway/cache changes passes.

# Required Changes From Other Modules

- MAIN should review and integrate the additional cache reliability fields in
  `LLMRunMetadata` wherever the full metadata envelope is persisted or
  displayed.
- MAIN should resolve or delegate the unrelated full-mypy failures in
  `tests/unit/agents/test_agents.py` so the repository-wide quality gate can
  become green.
- The live coordinator currently creates separate Gateway instances. If
  cross-Gateway deduplication for identical fingerprints is required, MAIN can
  inject one shared `LLMSingleFlight` (or one shared Gateway) into those
  instances. This fix does not modify Agent/live-report orchestration.

# Ready For Integration

NO — the LLM cache fix and focused gates are ready, but repository-wide mypy
must be cleared by the owning Agent/MAIN window before the strict Final Gate
can be declared PASS.

---

# Phase 4C Day44 — Gateway Ownership Boundary

## Current Status

The historical full-mypy blocker above was closed by Main during Phase 3 and
is retained only as history. Current Gateway/cache behavior is stable.

## Current Task

Future Satellite Alpha or handoff work may reuse the unified Gateway only when
a Research structured-output contract actually requires inference. Day44 adds
no call and changes no Gateway code.

## API Changes

None. Provider/model/Prompt lineage remains part of Research provenance.

## Files Changed

`docs/coordination/LLM_GATEWAY.md` only for Window synchronization.

## Tests

Existing offline Fake, cache reliability, structured-output, and safe logging
tests remain authoritative; default pytest remains network-free. Full Gate A:
`565 passed, 5 deselected`; Ruff, mypy, Black, and `git diff --check` pass.

## Blockers

None for Day44.

## Required Changes From Other Modules

Do not create an independent factor-scoring LLM call, hidden Provider path,
opaque AI stock score, or Fake fallback. Prompt/schema compatibility and model
lineage remain the Gateway contribution.

## Ready For Integration

YES — Day44 ownership is frozen; no Day45 implementation has begun.

# Phase 4C Day45 — Satellite Alpha Prompt / Gateway Contract Audit

## Current Status

Day45 Satellite Alpha is a deterministic projection from frozen,
PIT-validated ResearchState artifacts. It does not require a new LLM request,
Provider path, structured-output response, cache entry, or repair attempt.
The existing unified `LLMGateway` and active eight-Agent / Sector-Agent Prompt
contracts remain unchanged.

Existing Agent-side `normalized_scores`, manager `confidence`, Sector cycle
confidence, and `narrative_risk_score` are presentation or research-process
metadata. They are not authoritative Satellite Alpha values and must not be
promoted into observations as arbitrary LLM-generated 0–1 scores.

## Current Task

Audited the active Agent Prompts, ResearchState contracts, provider-independent
structured-output path, and credential-free `LLMRunMetadata` against the
Day44 Research / Quant boundary.

## Structured Output Support Matrix

| Semantic | Current Agent / artifact | Current field | Support status | Change needed |
|---|---|---|---|---|
| Logic stage | Fundamental, News/Event, Research Manager; canonical Event/Radar Evidence | accepted `ValidatedClaim.claim_text`, `claim_type`, `evidence_ids`; `SectorAnomalyEvent.event_type/status` | DERIVABLE | Window 3 may apply a versioned closed mapping from an exact accepted Claim or canonical Event type, for example an attributable “order confirmed” Claim to `ORDER_CONFIRMED`. Unmatched language must remain `UNKNOWN`; do not ask an LLM for certainty or a score. |
| Expectation direction | Technical, News/Event, Sector Research, ResearchState | deterministic `trend_label`; `MacroCycleDirection`; `SectorAnomalyEvent.direction`; accepted Claim/Feature references | DERIVABLE | Prefer an explicit upstream direction. A versioned deterministic mapping may consume accepted Claim semantics only when the rule is exact; otherwise emit `UNKNOWN`. No new Agent field is required for v1. |
| Risk taxonomy | Fundamental/Technical/Sentiment/News risk Claims, Bear, Risk, Sector Research | `analysis.risk_points[*]`; `confirmed_risks[*]`; `scenario_risks[*]`; `watch_items[*]`; Bear `claim_type=downside/invalidator`; Sector `category=risks` | SUPPORTED | Reuse these existing structured classes as the v1 taxonomy source. Do not create a parallel LLM-authored risk taxonomy or promote `narrative_risk_score`. |
| Catalyst | News/Event, Bull, Sector Research, Radar | accepted Event Claims; `conditions_required[*]`; Sector `category=catalysts`; Radar `event_type`, `status`, and Evidence IDs | DERIVABLE | Sector catalysts are directly structured. Asset catalysts may be projected only from accepted Event/condition Claims with canonical event lineage. If no Radar/Event support exists, emit `NOT_OBSERVED`; never invent a catalyst. |
| Invalidator | Bull and Bear | `invalidators[*]`; accepted Claim `claim_path`; defaulted `claim_type=invalidator` | SUPPORTED | Consume accepted invalidator Claims directly and retain their upstream Claim lineage. |
| Sector / Industry-Chain relationship | Sector Research and deterministic Sector contracts | `SectorMembership.role/chain_ids`; `SectorEdge.edge_type`; `SectorContextBundle.active_chain_ids`; Sector `category=industry_chains` | SUPPORTED | Reuse the temporal graph vocabulary (`belongs_to`, `supplies`, `customer_of`, `competes_with`, `benefits_from`, `exposed_to`, `drives`). A propagation candidate must not be upgraded to confirmed benefit. |
| Bull/Bear/Risk disagreement | Research Manager, Bull, Bear, Risk, ResearchState/Episode | `analysis.conflicts[*]`; distinct accepted Bull/Bear/Risk Claim collections; `debate_state`, `risk_state`; Episode role Claim IDs | SUPPORTED | Compare structured accepted Claim identities/paths and explicit conflict Claims only. Never save or parse chain-of-thought, scratchpads, hidden reasoning, or raw responses. |
| Event timing, when applicable | News/Event plus canonical Event/Radar/ResearchState artifacts | Claim Evidence lineage; `event_time`, `published_at`, `available_at`, `ingested_at`, `as_of`, `impact_window_days`; Feature `available_at/as_of` | SUPPORTED | Use canonical temporal metadata under Unified Temporal Contract v1. Do not infer a date/window from prose or backfill a later event into an earlier cutoff. |
| Model lineage | All eight Agents, Sector Research, ResearchState and Episode | `LLMRunMetadata.provider/model/prompt_version`; `ResearchStateLineage.versions`; `AgentExecutionTrace.provider/model/prompt_version` | SUPPORTED | Reference existing State/Episode lineage once at artifact level. Satellite observations need no Prompt copy, raw response, Provider payload, or LLM-internal field. |

`DERIVABLE` means a pure, versioned, fail-closed projection over accepted
structured artifacts. It does not authorize fuzzy text classification. A rule
that cannot prove its input pattern must produce an explicit unknown/missing
state rather than a guessed ontology value.

## Required Prompt Changes

None for Satellite Alpha Ontology v1. The existing Claim-first contracts
already expose the attributable semantic units needed for deterministic
projection. Adding `logic_certainty_score`, `chain_benefit_score`,
`alpha_score`, `buy_score`, or another model-authored 0-to-1 Satellite field
would violate the Day44 boundary.

## Changes Actually Made

Only this Window 5 coordination audit. No Agent Prompt, Pydantic schema,
Gateway, Provider Adapter, cache, ResearchState, Episode, or production runtime
file changed.

## Why Deterministic Derivation Is Preferred

The accepted Claim and canonical Event/Sector fields already carry Evidence,
numeric grounding, PIT time, role/path semantics, and stable identities. A
deterministic projection preserves that lineage and produces replayable output.
A second LLM pass would add model variance, another cache/Provider lineage,
and an unsupported scoring surface without creating new Evidence.

## No-secondary-scoring-call Confirmation

- Satellite materialization LLM calls: `0`.
- Secondary factor-scoring calls: `0`.
- New Provider invocations or hidden routing paths: `0`.
- Existing Agent structured-output repair behavior is unchanged and is not a
  Satellite scoring path.

## API Changes

None.

- Prompt changes: none.
- Gateway changes: none.
- Provider changes: none.
- Additional factor/scoring calls: zero.
- Frozen-artifact Satellite Alpha materialization must report zero additional
  LLM calls and zero Provider calls.

## Files Changed

- `docs/coordination/LLM_GATEWAY.md` only.

## Tests

No Window 5 production or Prompt code changed. Existing structured-output,
cache, Provider-selection, safe-metadata, and Prompt/schema compatibility tests
remain the authoritative Gateway regression suite. This audit runs
`git diff --check` only, as required for a coordination-only change. Main owns
the final Day45 repository-wide Gate.

## Blockers

None from LLM Gateway.

## Required Changes From Other Modules

- `SatelliteAlphaDefinition` and `SatelliteAlphaObservation` must be ordinary
  typed Research contracts, not LLM response schemas.
- Deterministic observation identity must reference the frozen
  `ResearchStateSnapshot` and its source feature/Claim/Evidence lineage.
- Provider/model/Prompt versions already retained in ResearchState lineage
  should be referenced or carried once at the artifact level; do not invent a
  second model-lineage channel or duplicate full prompts.
- Never map Agent presentation scores or confidence fields directly to a
  Satellite Alpha scalar. Numeric components require deterministic or already
  grounded ResearchState provenance.
- Timing ontology may be declared, but observations that require unavailable
  state history must remain `REQUIRES_HISTORY`; no LLM may infer a synthetic
  historical transition.
- Do not add a factor-scoring Prompt, hidden Provider invocation, Fake
  fallback, Quant score, Signal, ranking, or trading semantic.

## Ready For Integration

YES — the Day45 Gateway boundary is compatible with deterministic Satellite
Alpha ontology/materialization and requires zero Prompt or production Gateway
changes.

---

# Phase 4 Day49 — Gateway Contract Freeze Sync

## Current Status

Existing Gateway/Prompt/model lineage remains unchanged. Day49 Golden replay,
Satellite, Transition, Candidate, and Handoff construction made zero LLM calls.

## Current Task

Freeze sync only; no Provider path, scoring call, cache behavior, or fallback
was added.

## API Changes

None.

## Files Changed

This coordination status only.

## Tests

Full offline Gate PASS; five explicit live tests remain deselected by default.

## Blockers

None for the frozen offline Research contract.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — LLM Gateway boundary is unchanged and frozen for Research Intelligence
v1.

---

# Phase 4 Pre-Freeze — Qwen Sector Gateway Configuration Repair

## Current Status

`QWEN_SECTOR_SMOKE_CONFIGURATION_ERROR` is resolved. The only authorized
S03-only real-Qwen smoke passed both Gateway initialization and Sector
validation under the previously failing ambient proxy environment. No shell
proxy variables were removed for the successful rerun.

## Current Task

Compared the Phase 3, Day36, provider-preflight, live-report, benchmark, and
Sector-smoke construction paths. Every production entry already calls
`build_configured_llm_provider`; there was no duplicate Gateway factory. The
runtime difference was external: the known-working live-report command removed
`ALL_PROXY/all_proxy`, while `smoke_sector_research` inherited a generic SOCKS
proxy alongside usable protocol-specific HTTP proxy variables.

The exact credential-free failure recovered from lazy SDK initialization was
`Qwen client initialization requires HTTPX SOCKS support`, at configuration
stage `client_initialization`. Removing only `ALL_PROXY/all_proxy` reproduced
the known-working initialization; removing only the four HTTP(S) proxy names
did not.

## API Changes

- `LLMProviderError` now carries an allowlisted optional
  `configuration_stage`; missing credentials report `credential_resolution`,
  and SDK construction failures report `client_initialization`.
- `LLMGateway` accepts an optional `LLMFailureMetadataSink` and emits immutable
  `LLMFailureMetadata` containing only provider, model, safe code, safe message,
  configuration stage, and timestamp.
- The shared Provider runtime now resolves the specific conflict “generic
  SOCKS proxy plus protocol HTTP proxy” by constructing the official HTTPX
  client with the protocol HTTP proxy and `trust_env=false`. It does not mutate
  process environment, hardcode a proxy, or expose proxy values.
- Sector smoke manifests now retain `error_message_safe`,
  `configuration_stage`, `provider`, and `model`, and separate
  `gateway_initialization` from `sector_validation`.

## Files Changed

- `src/services/llm_provider.py`
- `src/services/llm_gateway.py`
- `src/services/__init__.py`
- `scripts/smoke_sector_research.py`
- `tests/unit/services/test_llm_provider.py`
- `tests/unit/services/test_llm_provider_selection.py`
- `tests/unit/services/test_llm_gateway.py`
- `tests/unit/test_smoke_sector_research.py` (new)
- `docs/coordination/LLM_GATEWAY.md`

No Sector Prompt, Sector validator, Agent contract, PIT, numeric-grounding,
Sector ontology, ResearchState, or Quant file was changed by Window 5.

## Tests

- Focused Gateway/Provider/Sector-smoke tests: `49 passed`.
- Offline S03 replay over the accepted State/Macro/Radar DuckDB inputs: Gateway
  `PASS`, Sector validation `PASS`, valid Claims `4`, numeric grounding `4/4`,
  HIGH event lineage `1/1`, invalid citations `0`.
- Full default offline pytest: `678 passed, 5 deselected`.
- Leakage selection: `8 passed, 675 deselected`.
- Ruff: PASS.
- mypy: PASS (`333 source files`).
- Black: PASS (`333 files would be left unchanged`).
- `git diff --check`: PASS.
- Current ambient-environment SDK initialization without network: PASS for
  `qwen/qwen3.7-flash`.
- One real S03-only Qwen smoke: PASS at
  `data/live_acceptance/phase4_prefreeze/20260914T204751Z_aapl/sector_research_s03_repair/20260915T035156Z/manifest.json`.
  It made one Provider call, retry count `0`, remote storage disabled; S03 had
  valid Claims `5`, grounded numeric Claims `2/2`, HIGH event lineage `1/1`,
  invalid citations `0`, and retained `APPLE_CHAIN`.
- Credential scan of the live manifest and structured output: PASS; no
  configured Qwen/OpenAI credential value was present.

## Blockers

None in the Qwen Gateway runtime/configuration path.

## Required Changes From Other Modules

- MAIN may integrate the successful S03 artifact and schedule the separately
  governed AAPL live rerun. Window 5 did not run the full AAPL workflow.
- No changes are required from Window 3; the live response passed the unchanged
  Sector validator and no Prompt repair is authorized by this result.

## Ready For Integration

YES — `QWEN_SECTOR_GATEWAY_REPAIR=PASS`,
`S03_LIVE_SECTOR_RESEARCH=PASS`, and `READY_FOR_AAPL_LIVE_RERUN=YES`.

---

# Phase 4 Pre-Freeze — Qwen Embedding Transport Repair

## Current Status

The Qwen embedding client proxy blocker is resolved. Generation and embedding
now share one OpenAI-compatible transport policy while retaining separate
models and API resources. The embedding-only live smoke and exact-cutoff
Radar→Memory persistence passed. The subsequent S03-only live run reached the
unchanged Sector validator and failed a new, precise Claim-lineage condition;
therefore the full AAPL live rerun is not ready.

## Current Task

Root cause was transport-policy drift. `QwenProvider` already selected an
explicit protocol HTTP proxy with `trust_env=false` when a conflicting generic
SOCKS proxy was present. `QwenEmbeddingService` independently constructed
`OpenAI(...)`, inherited all ambient proxy variables, and failed before payload
submission with an underlying `ValueError` for the selected SOCKS proxy
scheme/transport.

`resolve_provider_transport_config` now owns the common policy. It does not
mutate environment variables, expose proxy URLs, or provide direct fallback.
When both a valid HTTP(S) proxy and generic SOCKS proxy exist it returns
`protocol_http_over_conflicting_socks` /
`explicit_httpx_trust_env_false`. A SOCKS-only environment continues through
the SDK path and unsupported SOCKS fails explicitly.

## API Changes

- Added credential-safe `ProviderTransportConfig` and
  `resolve_provider_transport_config()` for OpenAI-compatible transport only.
- `QwenProvider` and `QwenEmbeddingService` use the same transport resolver;
  generation schema/sampling and embedding request semantics remain separate.
- `EmbeddingConfigurationError` now includes safe error code,
  configuration stage, provider, model, proxy mode, and transport mode.
- Embedding services expose request/validated-embedding counts and safe
  transport modes for acceptance observability.
- Added an embedding-only smoke that writes a credential-free manifest.
- Sector Radar smoke writes safe embedding diagnostics on failure and
  provider/model/count/dimension/transport metadata on success. Radar and
  Memory semantics are unchanged.

## Files Changed

- `src/services/provider_transport.py` (new)
- `src/services/llm_provider.py`
- `src/services/embedding.py`
- `src/services/__init__.py`
- `scripts/smoke_qwen_embedding.py` (new)
- `scripts/smoke_sector_radar.py`
- `tests/unit/services/test_provider_transport.py` (new)
- `tests/unit/services/test_embedding_providers.py`
- `tests/unit/test_smoke_qwen_embedding.py` (new)
- `docs/coordination/LLM_GATEWAY.md`

No Memory contract, Radar detection semantics, Temporal Contract, Sector
Agent, Prompt, validator, ResearchState, or Quant boundary was modified.

## Tests

- Focused transport/Embedding/Chat/Memory/Radar suite: `61 passed`.
- Full default offline pytest: `704 passed, 5 deselected`.
- Leakage selection: `8 passed, 701 deselected`.
- Ruff: PASS.
- mypy: PASS (`341 source files`).
- Black: PASS (`341 files would be left unchanged`).
- `git diff --check`: PASS.
- Pre-request SDK initialization under the conflicting live environment:
  PASS, `request_count=0`.

Embedding-only live artifact:

- `data/live_acceptance/phase4_prefreeze/qwen_embedding_transport_repair/20260915T051734Z/manifest.json`
- provider/model: `qwen/text-embedding-v4`;
- request/embedding count: `1/1`;
- dimension: `256`; retry: `0`; remote storage: `false`;
- proxy/transport:
  `protocol_http_over_conflicting_socks` /
  `explicit_httpx_trust_env_false`;
- secrets transferred: `0`.

Exact-cutoff Radar/Memory artifact:

- `data/live_acceptance/phase4_prefreeze/20260915T045112Z_aapl/sector_radar/20260915T051850Z/manifest.json`
- canonical `research_as_of=2026-09-15T04:51:12.136876Z`;
- six Radar events, six DuckDB Memory items, nine embedding requests and nine
  validated embeddings; dimension `256`, retry `0`, future leakage `0`;
- S01/S02/S03 Memory retrieval counts: `1/1/4`.

S03-only live artifact:

- `data/live_acceptance/phase4_prefreeze/20260915T045112Z_aapl/sector_research_s03/20260915T052024Z/manifest.json`
- Gateway request PASS at the same exact cutoff with
  `qwen/qwen3.7-flash`, retry `0`;
- Sector validation FAIL: `REJECTED_CYCLE_SUPPORT_CLAIM`, stage
  `CLAIM_LINEAGE`, field `cycle_assessment.supporting_claim_paths`;
- expected: every cycle support path identifies an accepted Claim;
- observed: rejected support path `claims[4]`;
- full structured validation artifact was retained; secret scan across all
  four new artifacts passed.

## Blockers

The only remaining blocker is S03 Sector structured-output Claim lineage:
`claims[4]` was rejected but remained referenced by the cycle assessment.
This is not an embedding, transport, Memory, temporal, PIT, or leakage failure.
Window 5 did not modify the Prompt or validator after observing it.

## Required Changes From Other Modules

- Window 3 should inspect the retained S03 validation artifact and determine
  whether the existing Prompt contract requires a narrowly scoped repair.
- MAIN should not run the full AAPL acceptance until S03 passes at the exact
  cutoff. No transport or Memory change is required.

## Ready For Integration

Embedding transport and exact-cutoff Radar/Memory are ready. Overall live
chain integration is not ready because S03 validation failed:

- `QWEN_EMBEDDING_TRANSPORT_REPAIR=PASS`
- `RADAR_MEMORY_EMBEDDING_GATE=PASS`
- `MEMORY_PERSISTENCE_GATE=PASS`
- `S03_LIVE_SECTOR_RESEARCH=FAIL`
- `SECTOR_EXACT_AS_OF_REPAIR=FAIL`
- `READY_FOR_FULL_AAPL_LIVE_RERUN=NO`

---

# Phase 4 Final Acceptance — S02 Sector Prompt Contract Repair

## Current Status

The Window 3 RCA is confirmed and the Prompt-only blocker is closed. The old
`sector_research_prompt_v1` allowed Qwen to turn the `change_3m` schema label
into the ungrounded Claim expression `3-month`. The unchanged validator
correctly quarantined that Claim with `numeric_literal_not_grounded:3`, leaving
the mandatory HIGH Event uncovered.

The active contract is now `sector_research_prompt_v2`; the exact v1 text is
retained under `config/prompts/archive/sector_research_prompt_v1/`. Output
schema `sector_research_output_v1`, validator behavior, numeric grounding,
Radar severity, PIT, Sector ontology, ResearchState, and Quant boundaries are
unchanged.

## Current Task

Version and narrowly strengthen the Sector Research structured-output Prompt.
The new contract states that every numeric literal in `claim_text`, including
duration/window/horizon/multiplier/ordinal-like expressions, must occur exactly
in `numeric_tokens` of Evidence cited by that Claim. Digits embedded in metric
keys, schema labels, and IDs do not provide numeric grounding. In particular,
`change_3m` cannot become `3-month` without explicit grounded duration
metadata; number-free wording such as `the configured change metric` is
required instead.

The Prompt also requires exact allowed Evidence/Event/Sector/Chain identities,
the existing category and cycle enums, explicit PARTIAL/proxy/candidate
disclosure, and at least one validation-compatible accepted Claim per
HIGH/CRITICAL Event. A silent pre-return checklist checks Event path, Evidence
IDs, degradation, and numeric grounding without outputting private reasoning or
chain-of-thought. No score or trading semantic was added.

## API Changes

- Active Prompt identity changes from `sector_research_prompt_v1` to
  `sector_research_prompt_v2`.
- Sector smoke manifests obtain the active Prompt version from the production
  version constant and record candidate/accepted/quarantined Claim counts,
  accepted mandatory-Event coverage, partial-disclosure status, and future
  leakage count.
- No Pydantic schema, validator, Agent input contract, Provider, Gateway,
  Memory, Radar, or temporal API changed.

## Files Changed

- `config/prompts/sector_research_agent.yaml`
- `config/prompts/archive/sector_research_prompt_v1/sector_research_agent.yaml`
- `src/agents/sector_research.py` (Prompt version constant only)
- `scripts/smoke_sector_research.py` (Prompt/acceptance metadata only)
- `tests/unit/agents/test_sector_research_agent.py`
- `tests/unit/test_smoke_sector_research.py`
- `docs/coordination/LLM_GATEWAY.md`

## Tests

- Prompt/Sector/smoke focused: `45 passed`.
- Added regressions for ungrounded `3-month`, number-free metric wording,
  explicit grounded duration metadata, accepted HIGH Event coverage,
  missing/present PARTIAL disclosure, Prompt mandatory coverage, allowed
  vocabulary, no validator relaxation, and no S02 hard-coding.
- Exact saved S02 v1 response replay remains strict FAIL with
  `numeric_literal_not_grounded:3`, mandatory/covered `1/0`.
- S01/S02/S03 offline smoke over the saved exact-cutoff inputs: all PASS under
  Prompt v2; each mandatory HIGH Event has accepted coverage `1/1`, invalid
  citations `0`, future leakage `0`.
- Full default pytest: `716 passed, 5 deselected`.
- Leakage selection: `8 passed, 713 deselected`.
- Ruff: PASS.
- mypy: PASS (`341 source files`).
- Black: PASS (`341 files would be left unchanged`).
- `git diff --check`: PASS.

One authorized S02-only live Qwen artifact:

- `data/live_acceptance/phase4_prefreeze/phase4_prefreeze_20260915T054218Z_aapl/sector_research_s02_prompt_v2/20260915T062322Z/manifest.json`
- exact `research_as_of=2026-09-15T05:42:18.680743Z` using the matching fresh
  Sector State, Macro, Radar, and exact-cutoff Memory retrieval;
- provider/model/Prompt: `qwen/qwen3.7-flash/sector_research_prompt_v2`;
- Gateway and Sector validation: PASS; retry count `0`;
- candidate/accepted/quarantined Claims: `10/9/1`;
- accepted numeric Claims grounded: `5/5`; invalid citations `0`;
- mandatory/covered HIGH Events: `1/1`; accepted covering Claim IDs:
  `sector:S02:claim:0`, `sector:S02:claim:8`;
- partial Evidence disclosure: PASS; future leakage `0`; remote storage false;
- credential/raw-Prompt artifact scan: PASS.

The exact-cutoff Memory query correctly excluded six Radar Memory rows whose
runtime persistence timestamp was later than the canonical cutoff. It returned
an empty-valid Memory bundle rather than violating PIT; no temporal rule or
Memory data was modified.

The live model also drafted a separate market-window Claim using ungrounded
`5-day`/`20-day`/`60-day` expressions. The unchanged validator quarantined it
(`numeric_literal_not_grounded:5`) and it did not enter accepted Claims or HIGH
Event coverage. This is residual model variance, not a safety bypass; accepted
numeric grounding remains `5/5`.

## Blockers

None for the S02 mandatory HIGH Event blocker.

## Required Changes From Other Modules

MAIN may consume the v2 Prompt identity and successful S02 artifact for the
separately governed full AAPL rerun. Do not backfill the exact-cutoff Memory
items that were correctly excluded as future-persisted records.

## Ready For Integration

YES — `WINDOW5_SECTOR_PROMPT_REPAIR=PASS`,
`S02_LIVE_SECTOR_RESEARCH=PASS`, mandatory HIGH Event coverage `1/1`, and
`READY_FOR_FULL_AAPL_LIVE_RERUN=YES`.

---

# Phase 4 Release-Final Prompt Contract

## Active versions

The Phase 4 Research Intelligence v1 release uses exactly these active Prompt
contracts:

- Sector Research: `sector_research_prompt_v4`
- Research Manager: `v7`

Production loads the Sector Prompt only from
`config/prompts/sector_research_agent.yaml`. Sector versions v1, v2, and v3
remain immutable historical archives under `config/prompts/archive/` and are
not runtime candidates. Research Manager v6 is likewise archived; the active
Manager Prompt is `config/prompts/research_manager.yaml` version v7.

## Sector Prompt evolution

- `sector_research_prompt_v1`: initial Claim-first Sector Research contract.
- `sector_research_prompt_v2`: added strict numeric-literal discipline and
  required every mandatory HIGH/CRITICAL Event to be covered by a final
  accepted Claim.
- `sector_research_prompt_v3`: made association-versus-causality wording
  explicit and required conservative, validation-compatible HIGH-event Claims
  when Evidence supports only association, proxy, or limited inference.
- `sector_research_prompt_v4`: final Phase 4 release-candidate contract; every
  emitted Claim must independently include all six required structured fields,
  including explicit confidence, with incomplete Claim objects omitted rather
  than defaulted.

The earlier v1/v2 sections above are historical records of their respective
repair checkpoints. They are superseded for runtime selection by v4. This
version freeze changes no Evidence, validation, temporal, Memory, or
Research/Quant boundary contract.
