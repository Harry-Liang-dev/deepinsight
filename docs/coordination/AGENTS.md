# Current Status

Window 3 已完成 Phase 3 Final Agent Contract Simplification。Fundamental 与 Bear
已收敛为 Claim-first 输出，并加入 producer-side claim quarantine；strict citation、
exact numeric grounding、unknown Evidence rejection、cross-role isolation 均保持。

固定 ResearchDataBundle 的 live Qwen 7-Agent contract：`7/7 PASS`。
Risk smoke：`PASS`。离线 benchmark：`7/7 PASS`。

# Current Task

只处理两个 Final Gate blocker：

- Fundamental：`FundamentalAnalystOutput = claims[] + normalized_scores + uncertainties + metadata`；
  factual content 只从已验证 Claim objects 组装。
- Bear：`claims[] + confidence + metadata`；downside/invalidator 内容只从已验证
  Claim objects 组装，presentation prose 不得成为事实来源。

每个最终 Claim 包含 `claim_id`、`claim_type`、`claim_text`、Python 提取的
`numeric_literals`、canonical `evidence_ids`、`derivation_type`、`confidence`。

# API Changes

- 新增 Fundamental strict/draft Claim response models 与 Bear draft response model；
  Draft 层仅为逐 Claim quarantine 保留必要的结构承载，最终输出仍经 strict
  `ClaimEvidenceBinding` 校验。
- 新增 `RejectedClaim` 与 `claim_policy_v1`，角色阈值配置为：Fundamental 至少
  `3` 个有效 Claim，Bear 至少 `2` 个有效 Claim。
- `BaseAgent` 在 producer side 逐 Claim 检查：missing/empty binding、unknown 或
  cross-role Evidence、exact numeric grounding、非法 Claim schema；非法 Claim
  只记录到 `rejected_claims` 并丢弃，不修正、不 fuzzy match、不替换 ID。
- 达到角色 minimum 的保留 Claim 才能 `status=ok`。rejected diagnostics 在
  `_parse_analyst_output` 中剥离，不进入 Research Manager、下游 Manager 或报告。
- Fundamental normalized scores 保留为非事实性 score，并携带
  `score_metadata`（assessment 或 deterministic calculation）。
- live contract harness 增加 `valid_claims`、`rejected_claims` 指标及 `--include-risk`
  Risk smoke；不保存原始 LLM 输出。

# Prompt Changes

- `config/prompts/fundamental_analyst.yaml`：`v7 -> v8`，Claims-first、至少 3 个
  有效 Claim、score 与事实 Claim 分离。旧版保留在
  `config/prompts/archive/agent_contract_v7_pre_simplification/`。
- `config/prompts/bear_manager.yaml`：`v7 -> v8`，Claims-first、至少 2 个有效
  downside/invalidator Claim、presentation 不产生新数字。旧版同目录保留。
- Technical、Sentiment、News、Research、Bull、Risk Prompt 未改变。

# Files Changed

- `src/schemas/agents.py`
- `src/schemas/__init__.py`
- `src/agents/base.py`
- `src/agents/analysts.py`
- `src/agents/managers.py`
- `src/agents/claim_policy.py`
- `src/agents/__init__.py`
- `src/agents/coordinator.py`
- `config/prompts/fundamental_analyst.yaml`
- `config/prompts/bear_manager.yaml`
- `config/prompts/archive/agent_contract_v7_pre_simplification/`
- `tests/unit/agents/test_evidence_contract.py`
- `tests/unit/agents/test_agents.py`
- `tests/integration/agents/test_research_coordinator.py`
- `scripts/live_agent_contract.py`
- `docs/coordination/AGENTS.md`

未修改 Data、Memory、LLM Gateway、Report、Factor、Regime、Trading、
`docs/MODULE_STATUS.md` 或 `docs/DECISIONS.md`。

# Tests

- Agent focused pytest：`53 passed`。
- Fixed Bundle Fake contract：`7/7 PASS`。
- Offline benchmark：`7/7 PASS`，`research_benchmark_v1`。
- Full pytest：`404 passed, 1 failed, 5 deselected`；唯一失败为 Main-owned
  offline API fixture 仍期望 8 个 cache、当前 v2 流程实际为 7 个，记录为
  `EXPECTED_CROSS_MODULE_FAILURE = 1`，本窗口不越权修改。
- `ruff check .`：PASS。
- `mypy .`：PASS（256 source files）。
- `black --check .`：PASS。
- `git diff --check`：PASS。

# Live 7-Agent Gate

固定 bundle：`phase3_research_completeness_final_v1`；Provider/model：
`qwen/qwen3.7-flash`；timeout `90`、max retries `0`、thinking disabled、remote
storage disabled；执行顺序保持固定。

最终运行 `agent_contract_20260813T110830Z_6395dfd4`：前置七角色 `7/7 PASS`。

- Fundamental：valid `3`，rejected `3`，numeric `3/3 grounded`。
- Technical：valid `3`，rejected `0`，numeric `3/3 grounded`。
- Sentiment：valid `6`，rejected `0`，numeric `6/6 grounded`。
- News/Event：valid `4`，rejected `0`，numeric `4/4 grounded`。
- Research Manager：valid `5`，rejected `0`，numeric `5/5 grounded`。
- Bull：valid `7`，rejected `0`，numeric `7/7 grounded`。
- Bear：valid `3`，rejected `2`，numeric `3/3 grounded`。

所有 accepted Claims：`invalid_citations=0`、`ungrounded_numeric=0`、
`unknown_evidence=0`、`schema_errors=0`。

# Risk Smoke

同一运行 `agent_contract_20260813T110830Z_6395dfd4`：`8/8 PASS`（含前置七角色与
Risk）。Risk valid claims `6`，numeric `6/6 grounded`，invalid citations、schema
errors、unknown Evidence 均为 `0`。

# Blockers

- Agent Contract Closure：NONE。
- Main-owned offline API fixture 尚需迁移到 v2 Fake response（不属于 Window 3）。
- Fundamental / Technical 的 Gateway schema-validation 历史问题不再是本轮
  Contract blocker；本窗口未修改 Gateway。

# Required Changes From Other Modules

## Required Changes From MAIN

- 迁移 Main-owned `apps/api/offline.py` 与其 e2e fixture 的 cache 计数/Claim-first
  Fake response，使全量 pytest 的单个预期失败消失。
- 不要把 `rejected_claims` 作为下游事实输入；只消费 validated Claim objects。

## Required Changes From DATA / MEMORY / LLM_GATEWAY

NONE。

# Ready For Integration

YES

# Phase 4C Day44 — Agent Research Boundary

## Current Status

Agents remain Research Intelligence producers. Existing Claim, grounding,
quarantine, direct-upstream provenance, and trading boundaries are unchanged.

## Current Task

Future Agent outputs may support Opportunity Candidates and Selection/Timing
Satellite Alpha as structured Research descriptors. They must not become
Quant ranks or trading decisions.

## API Changes

None. No Prompt or structured-output schema changed on Day44.

## Files Changed

`docs/coordination/AGENTS.md` only for Window synchronization.

## Tests

Full offline Gate A passed: `565 passed, 5 deselected`; Ruff, mypy, Black, and
`git diff --check` pass. Existing Phase 3/4A Agent contracts did not change.

## Blockers

None. Future descriptor vocabulary and minimum provenance will require a
separate approved schema task.

## Required Changes From Other Modules

Agents may later produce decomposed Selection Satellite Alpha and state-change
Timing Satellite Alpha. They must not implement cross-sectional ranking,
Top-K, one opaque AI stock score, Quant timing, position sizing, or holdings
decay.

## Ready For Integration

YES — Day44 ownership is frozen; no Day45 implementation has begun.

`AGENT_FINAL_CLOSURE = PASS`。可以进入 fresh Phase 3 acceptance；本窗口不开始
Phase 4 / Day30。

---

# Report Completeness Inputs — 2026-08-14

## Current Status

Analyst input projection can now consume richer deterministic Evidence without
any Provider SDK dependency.

## API Changes

- Fundamental: growth, margin, quality/leverage/liquidity and valuation
  Evidence are available when canonical inputs exist.
- Technical: the complete deterministic price/volume indicator set and
  SPY/QQQ/XLK relative strength are available; their presence counts as real
  price history.
- Sentiment: aggregate score/share/change/attention/topic/dispersion Evidence
  is preferred over individual community posts.
- News/Event: attributed Alpaca News and FRED MacroSnapshot Evidence are
  explicitly covered when present. Prompt versions for Technical, Sentiment,
  and News/Event are `v8`.

## Required Changes From Other Modules

NONE. Managers continue to consume validated upstream Claims rather than raw
Provider fields.

## Ready For Integration

YES

# Phase 4C Day45 — Satellite Alpha Ontology v1

## Current Status

Window 3 implemented the versioned definition/observation ontology and a pure
ResearchState mapper. Satellite Alpha remains an attributable Research
descriptor, not a Quant Factor, rank, signal, or portfolio instruction.

## Current Task

Day45 contract closure only. Day46 OpportunityCandidate and Day47 historical
Timing builders were not started.

## API Changes

- Added usage `SELECTION/TIMING/BOTH`, five comparison scopes, explicit
  coverage/maturity enums, 14 family definitions, typed components,
  deterministic Observation identity, and the State support audit.
- Added `SatelliteAlphaMapper`: frozen State plus optional matching Episode to
  14 truthful observations; zero LLM/Provider/report calls.
- ResearchState v1 is unchanged. Missing formal semantics remain PARTIAL,
  MISSING_INPUT, NOT_AVAILABLE_AT_SOURCE_RUN, or REQUIRES_HISTORY.

## Files Changed

- `src/schemas/satellite_alpha.py`
- `src/services/satellite_alpha.py`
- `src/schemas/__init__.py`
- `src/services/__init__.py`
- `tests/unit/services/test_satellite_alpha.py`
- `docs/SATELLITE_ALPHA.md`
- `docs/schema.md`
- `docs/DECISIONS.md`
- `docs/MODULE_STATUS.md`
- `docs/coordination/AGENTS.md`

## Tests

Focused Day45 contract tests: `15 passed`, covering ontology usage/value
shapes, grounded components, semantic identity, PIT, provenance,
Phase3/Phase4A compatibility, missing statuses, history requirements, and
prohibited Quant/trading fields. Full pytest: `580 passed, 5 deselected`.
Leakage gate: `3 passed, 582 deselected`. Ruff, mypy (319 files), Black, and
`git diff --check`: PASS.

## Blockers

None in the Day45 Agent-owned implementation.

## Required Changes From Other Modules

Future State version only: preserve already-accepted logic stage, expectation
direction/subtype, risk component type, catalyst/invalidator identities,
structured debate disposition, canonical Sector ID, and event identity/time.
Do not add another LLM score. Day47 owns ordered State history.

## Ready For Integration

YES

---

# Final Projection Closure — 2026-08-14

## Current Status

Eight real Qwen Agent runs completed in acceptance `20260814T100747Z`.

## API Changes

- Fundamental receives deterministic canonical Claims for Growth, Margins,
  Profitability, Balance/Liquidity and Valuation when FMP Evidence is present.
- News/Event receives deterministic FRED Claims for Rates, Inflation, Labor,
  Growth and Financial Stress. Both paths retain strict local Claim validation.
- Versioned role contracts no longer add legacy global document/memory missing
  flags; Bundle/Memory coverage remains authoritative.

## Tests

All eight live Agent records are `ok`; accepted Claim lineage reaches FMP,
SEC, Alpaca, FRED and Stocktwits Evidence.

## Blockers

NONE.

## Ready For Integration

YES — integrated and frozen.

---

# Phase 4A Day35 — Sector Research Agent

## Current Status

Day35 Agent implementation is complete. `SectorResearchAgent` is an
independent upstream component over Day31-Day34 state and the existing PIT
Memory bundle; it is not added to the frozen eight-Agent asset chain.

## Current Task

Deliver claim-first, evidence-grounded Sector interpretation for trend,
breadth, fundamentals, valuation, Macro environment/sensitivity, Industry
Chains, Radar anomalies, leaders/laggards, catalysts, risks, and an
interpretive Sector cycle. Day36 integration is intentionally not started.

## API Changes

- Added versioned `SectorResearchInput v1` and `SectorResearchOutput v1`.
- Reused `RoleEvidenceManifestEntry`, `ValidatedClaim`, `RejectedClaim`,
  `SourceReference`, and `ResearchContextBundle`; no second Claim/Evidence
  architecture was introduced.
- Added compact `SectorResearchEvidence` projection and invocation-local exact
  citation namespace.
- Added `SectorCycleAssessment` with accepted supporting Claim IDs, confidence,
  and uncertainty. It is not Day33 `MacroCycleDirection` or a Regime.
- Added strict local rejection for unknown Evidence, ungrounded numeric
  literals, correlation/beta causality, candidate certainty, undisclosed
  PARTIAL/proxy inputs, invented catalysts, and prohibited trading intent.
- Selected accepted anomaly/catalyst/risk/chain/cycle Claims may be written
  through the existing Memory Protocol as SECTOR/CHAIN L3 trace items.

## Prompt Changes

- Added `config/prompts/sector_research_agent.yaml`, version
  `sector_research_prompt_v1`.
- Prompt is compact, role-specific, Claim-first, and explicitly forbids metric
  calculation, new graph relationships, candidate-to-fact promotion,
  correlation-to-causality promotion, hidden proxy precision, external
  networking, and trade/position/order/target-price output.
- No Phase 3 Agent Prompt changed.

## Files Changed

- `src/schemas/sector_research.py`
- `src/agents/sector_research.py`
- `src/agents/__init__.py`
- `config/prompts/sector_research_agent.yaml`
- `scripts/smoke_sector_research.py`
- `tests/unit/agents/test_sector_research_agent.py`
- `docs/schema.md`
- `docs/DECISIONS.md`
- `docs/MODULE_STATUS.md`
- `docs/coordination/AGENTS.md`

## Tests

- Agent-focused: `16 passed`.
- Full offline pytest: `496 passed, 5 deselected`.
- Real Day32-Day34 fixed-snapshot Fake smoke: S01/S02/S03 `3/3 PASS`;
  invalid citations `0`; all accepted numeric Claims grounded; HIGH Radar
  events cited `3/3`; S02/S03 remained PARTIAL/proxy.
- Optional real Qwen smoke: visible `configuration_error` during Provider
  client initialization; no Fake fallback and no accepted live result.
- Ruff, mypy, Black, and `git diff --check`: PASS.

## Blockers

- Agent contract/offline closure: NONE.
- Optional live Qwen rerun requires the host's current Provider client
  configuration issue to be resolved. The same real fixed data remains
  available and no Agent/Gateway workaround was added.
- `MASTER_SPEC.md` remains Phase One-oriented and does not describe Day35;
  current Phase 4 operational truth is the runnable Day30-Day35 code plus
  ADR-0032 through ADR-0037 and `MODULE_STATUS.md`.
- Existing coordination `MAIN.md` and this file previously stopped at Phase 3;
  this Day35 entry closes the Agent-side drift without rewriting Main-owned
  coordination history.

## Required Changes From Other Modules

NONE for Day35. Day36 Main integration may consume accepted Claims through a
new `SectorContextBundle`, but must not consume rejected Claims or raw LLM
text.

## Ready For Integration

YES

`DAY35_SECTOR_AGENT = PASS`

---

# Phase 4B Day38 — Accepted Claim State Projection

## Current Status

Accepted Analyst/Manager Claims can be projected into ResearchState by stable
Claim ID. Recursive provenance is validated once and closes at direct
Evidence; rejected Claims and report prose are not State inputs.

## API Changes

- No Agent Prompt or Agent output contract changed.
- `ResearchStateClaimInput` adds only producer role and run identity around the
  existing `ClaimEvidenceBinding`.

## Blockers

NONE. A source run that did not persist full accepted Claims remains explicitly
`NOT_AVAILABLE_AT_SOURCE_RUN` for debate/risk/thesis State.

## Ready For Integration

YES

---

# Phase 4B Day39 — Agent Execution References

## Current Status

ResearchEpisode references existing Agent runs and structured Claim results;
it does not change any Agent Prompt or output contract.

## API Changes

- `AgentExecutionTrace` records role/run identity, context and Claim IDs,
  accepted/rejected counts, status, optional latency, and Provider/model/Prompt
  versions.
- Existing Day36 Sector usage diagnostics are referenced directly.
- Private reasoning, chain-of-thought, raw prompts, and report prose are not
  Episode fields.

## Blockers

NONE. Historical runs that omitted exact Claim identities remain explicitly
PARTIAL and must not be backfilled with synthetic IDs.

## Ready For Integration

YES

---

# Phase 4C Day46 — Selection Satellite and OpportunityCandidate v1

## Current Status

Window 3 implemented deterministic Selection production and research-only
Opportunity qualification. ResearchState v1 and ResearchEpisode identity are
unchanged; Day47 was not started.

## Current Task

Day46 contract and engineering gates are complete. The implementation is ready
for independent Main acceptance.

## API Changes

- `SelectionSatelliteBuildInput` adds only a compact canonical Sector/Radar
  projection around frozen State/Episode inputs.
- Exact State feature names support alignment, expectation, logic, and chain
  components. Existing Bull/Bear/Risk Claim paths support conservative partial
  debate and coarse risk components. Claim prose is never parsed.
- `OpportunityCandidate v1` records rule-based qualification, deterministic
  identity, PIT availability, Selection Observation IDs, and compact source
  lineage. It has no weighted score or Quant/trading fields.

## Files Changed

- `src/schemas/satellite_alpha.py`
- `src/services/satellite_alpha.py`
- `src/schemas/opportunity.py`
- `src/services/opportunity.py`
- shared schema/service exports
- `tests/unit/services/test_selection_opportunity.py`
- `docs/SATELLITE_ALPHA.md`
- `docs/OPPORTUNITY_CANDIDATE.md`
- shared schema/status/decision documentation
- `docs/coordination/AGENTS.md`

## Tests

- Focused Day45+Day46: `31 passed` (`16` new Day46 tests).
- Full pytest: `596 passed, 5 deselected`.
- Leakage: `3 passed, 598 deselected`.
- Ruff, mypy (322 source files), Black, and `git diff --check`: PASS.

## Blockers

No implementation blocker. Missing State semantics remain explicit rather
than inferred from prose.

## Required Changes From Other Modules

None for Day46. Main should independently validate qualification and the
Research/Quant boundary. Day47 history work requires separate authorization.

## Ready For Integration

YES

---

# Phase 4 Day49 — Agent Contract Freeze Sync

## Current Status

Phase3 Claim contracts, Day36 Sector usage, Day45 Satellite projection, and
Day46 OpportunityCandidate remain accepted without Prompt or Agent changes.

## Current Task

Freeze sync only; Day49 added no Agent capability and made no LLM calls.

## API Changes

None. OpportunityCandidate remains Research qualification, never Top-K,
advice, or a portfolio decision.

## Files Changed

This coordination status only.

## Tests

Phase regressions and full Gate PASS.

## Blockers

None. Phase4A historical Asset Claim identities remain partially unavailable
and were not inferred or backfilled.

## Required Changes From Other Modules

None.

## Ready For Integration

YES — Agent-side Research Intelligence v1 contracts are frozen.

---

# Phase 4 Pre-Freeze — S03 Sector Research Validation Diagnostics

## Current Status

Sector Research validation now emits a stable stage, field path, error code,
expected semantics, observed summary, and related Sector/Claim/Event/Chain IDs.
Failed structured responses that reach the Agent are retained as a
credential-free validation artifact for deterministic replay.

The historical `20260914T205638Z` S03 run cannot be replayed exactly: that run
persisted neither its structured response nor `ErrorInfo.message`; its manifest
contains only `sector_research_validation` with null details. The same S03
State/Macro/Radar databases pass the fixed offline path with APPLE_CHAIN and the
HIGH Radar event intact.

## Current Task

Validation observability and strict lineage diagnostics are complete. The one
authorized S03-only Qwen smoke stopped at Gateway `configuration_error` before
Sector validation, so no retry was attempted.

## API Changes

- `SectorResearchValidationStage` defines the approved failure taxonomy.
- Local promotion failures return non-null safe `ErrorInfo.details`.
- Cycle support paths must reference submitted and accepted Claims.
- The smoke command accepts `--sector S03` and persists failed structured
  response artifacts when the response reaches the Agent validator.

## Files Changed

- `src/schemas/sector_research.py`
- `src/agents/sector_research.py`
- `scripts/smoke_sector_research.py`
- `tests/unit/agents/test_sector_research_agent.py`
- `docs/coordination/AGENTS.md`

## Tests

- Sector Agent focused: `21 passed`.
- Historical DB fixed smoke: S01/S02/S03 `3/3 PASS`; S03 has 4 valid Claims,
  4/4 grounded numeric Claims, 0 invalid citations, and 1/1 HIGH event cited.
- Full pytest: `674 passed, 5 deselected`.
- Leakage: `8 passed, 671 deselected`.
- Ruff, mypy (332 source files), Black: PASS.

## Blockers

- Exact historical RCA is unavailable because the failed structured response
  was not persisted by the old run.
- The single live S03 smoke failed at Gateway configuration before the Agent
  validator; this Window must not diagnose or change the Provider path.

## Required Changes From Other Modules

Window 5 / Main should resolve the Qwen `configuration_error`, then run a new
explicit S03-only smoke. If Sector validation fails, the new artifact will
contain precise non-null diagnostics and a replayable structured response.

## Ready For Integration

NO — observability is ready, but live S03 contract acceptance is not proven.

---

# Phase 4 Pre-Freeze — S03 Dependent Claim Lineage Repair

## Current Status

The saved `20260915T052024Z` S03 structured response proved that `claims[4]`
was correctly quarantined because it cited PARTIAL GDP/INDPRO Evidence without
the required degradation language. It had no numeric, event, PIT, Sector, or
Chain violation. The cycle still had two accepted declared supports, so the
former unconditional failure was a dependent-lineage resolution defect.

Cycle promotion now resolves only after the final accepted Claim set. When at
least one declared accepted support remains, rejected support paths are removed
and the cycle is explicitly PARTIAL with `REJECTED_SUPPORT_CLAIM` provenance.
Zero accepted support still fails closed with exact accepted/rejected/required
counts. Rejected Claims never become downstream support.

## Current Task

The original S03 artifact replays offline as PASS/PARTIAL, and a new exact-cutoff
Qwen S03-only smoke passes the Sector contract.

## API Changes

- `SectorCycleAssessment` adds status, dropped support paths, and degradation
  reasons using existing Sector capability semantics.
- Successful diagnostics include the candidate Claim status map, effective
  supporting Claim IDs, and dropped support paths.
- Insufficient support reports `INSUFFICIENT_ACCEPTED_CYCLE_SUPPORT` with exact
  lineage counts.
- No Prompt, Gateway, Data, Memory, Radar, or Temporal contract changed.

## Files Changed

- `src/schemas/sector_research.py`
- `src/agents/sector_research.py`
- `scripts/smoke_sector_research.py`
- `tests/unit/agents/test_sector_research_agent.py`
- `docs/coordination/AGENTS.md`

## Tests

- Sector Agent focused: `24 passed`.
- Phase4A Sector focused: `53 passed`.
- Original S03 structured artifact: PASS with 6 accepted, 6 quarantined,
  cycle PARTIAL, 2 effective supports, and dropped `claims[4]`.
- Historical S01/S02 output compatibility: PASS.
- Full pytest: `707 passed, 5 deselected`.
- Leakage: `8 passed, 704 deselected`.
- Ruff, mypy (341 source files), Black, and `git diff --check`: PASS.
- Live Qwen S03 `20260915T053121Z`: PASS; 10 accepted, 3 quarantined,
  7/7 grounded numeric Claims, 0 invalid citations, HIGH event 1/1 cited,
  retry count 0, and no rejected cycle dependency.

## Blockers

NONE for the S03 Sector Research claim-lineage contract.

## Required Changes From Other Modules

None. Main may run the full AAPL live acceptance using the same unified cutoff.

## Ready For Integration

YES — ready for the full AAPL live rerun.

---

# Phase 4 Final AAPL — S02 Mandatory HIGH Event Coverage

## Current Status

The saved S02 artifact was replayed against its exact State/Macro/Radar cutoff.
Its only HIGH-event Claim (`claims[2]`) was correctly quarantined with
`numeric_literal_not_grounded:3`: Qwen converted the upstream `change_3m`
dimension label into a new numeric literal, `3-month`. The two rounded values
in the same Claim were grounded by the Radar Event, and its Event ID, scope,
and PIT lineage were valid.

No other candidate Claim carried the HIGH Event ID, so final accepted coverage
is genuinely empty. The strict `HIGH_EVENT_NOT_CITED` failure remains correct.

## Current Task

Window 3 added a deterministic mandatory-event coverage matrix over the final
accepted Claim set and expanded failure diagnostics. It did not change Prompt,
numeric grounding, Radar severity, or the mandatory coverage invariant.

## API Changes

- Successful Sector diagnostics now include a per-event `COVERED`/`UNCOVERED`
  matrix derived after Claim validation.
- `HIGH_EVENT_NOT_CITED` now records severity, all candidate Claim paths and
  final statuses, rejection codes, accepted covering Claim IDs, mandatory and
  covered counts, and all uncovered Event IDs.
- Duplicate Claim references never inflate the mandatory Event count.

## Files Changed

- `src/agents/sector_research.py`
- `scripts/smoke_sector_research.py`
- `tests/unit/agents/test_sector_research_agent.py`
- `docs/coordination/AGENTS.md`

## Tests

- Sector/Phase4A focused: `57 passed`.
- Original S02 artifact replay: expected strict FAIL; mandatory=1, covered=0,
  candidate `claims[2]` quarantined, no accepted covering Claim.
- S01/S03 saved output compatibility: PASS.
- Full pytest: `711 passed, 5 deselected`.
- Leakage: `8 passed, 708 deselected`.
- Ruff, mypy (341 source files), Black, and `git diff --check`: PASS.

## Blockers

The current Prompt/Qwen output does not guarantee one valid accepted Claim for
every mandatory HIGH Event. There is no local Agent validator bug to repair.

## Required Changes From Other Modules

Window 5 should version the Sector structured-output Prompt so that Event
Claims copy only exact numeric literals supplied by Event Evidence and avoid
turning dimension names such as `change_3m` into `3-month`. Mandatory HIGH
Event coverage must remain explicit.

## Ready For Integration

NO — a Prompt contract change and new S02-only live validation are required.
