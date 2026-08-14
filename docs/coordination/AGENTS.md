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
