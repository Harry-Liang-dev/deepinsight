# Live Agent Benchmark Task

## 目标

建立独立于 `research_benchmark_v1` 的 `live_agent_benchmark_v1`，使用真实
LLM、固定且可校验的数据快照、现有八 Agent 流水线、报告组装器和真实 LLM
Judge，形成可重复、可审计的 Prompt/模型测量工具。

## 范围

- 首版使用一个允许保存的 US:AAPL 固定 SEC/Alpaca 证据快照。
- 提供普通基本面、数据缺失、证据冲突、重大事件、高波动和 Memory 不完整六个
  固定场景。
- 复用 `ResearchCoordinator`、`ReportAssembler`、`LLMGateway` 和
  `ReportEvaluationService`。
- 记录 Provider、模型、推理参数、Prompt 版本、输入指纹、Agent 输出、报告和
  Evaluation。
- 每次运行使用独立 `run_id` 和输出目录。
- 支持同一快照上 candidate 与 baseline 的结构化差异比较。

## 非目标

- 不优化或修改 Agent、Prompt、报告生成器或评估规则。
- 不修改现有离线 `research_benchmark_v1` 的职责、案例或通过门。
- 不在 Benchmark 运行时重新抓取市场数据。
- 不使用 Fake LLM、Fake Judge 或自动 Fake fallback。
- 不评价收益，不实现交易、回测、训练、强化学习或自动 Prompt 选择。
- 不把 US 固定样本宣称为 CN/HK 市场覆盖。

## 输入

- 版本化 snapshot manifest 与内容 SHA-256。
- 六个固定 `LiveAgentScenario`。
- 显式 Provider、model、推理参数、Prompt 根目录和 Evaluation rules 版本。
- 通过父 shell 注入的真实 Provider credential。
- 可选 baseline run manifest，用于 A/B 比较。

## 输出

- `run_manifest.json`：运行身份、真实 Provider/Judge 标志、模型、推理参数、
  snapshot hash、Prompt 版本和案例输入指纹。
- `summary.json`：案例状态、Agent 成功率、Evaluation 分数和失败原因。
- 每案例 `input.json`、`agents.json`、`report.json`、`report.md` 和
  `evaluation.json`。
- 可选 `comparison.json`：candidate 相对 baseline 的分数差，不输出“改善”结论。

## 数据结构

- `LiveBenchmarkSnapshot`：数据集版本、市场覆盖、来源和场景。
- `LiveSnapshotSource`：Provider、原始定位、采集/发布时间和固定原文。
- `LiveAgentScenario`：固定来源选择、结构化特征、Memory 输入和已知缺失项。
- `LiveBenchmarkConfig`：真实运行门、Provider、模型、推理参数和 Prompt 版本。
- `LiveCaseResult` / `LiveBenchmarkRunResult`：案例及运行机器结果。
- `LiveBenchmarkComparison`：同输入 baseline/candidate 分数差。

## 核心接口

```text
LiveSnapshotLoader.load() -> LoadedLiveSnapshot
LiveAgentBenchmarkRunner.run(snapshot, config) -> LiveBenchmarkRunResult
LiveBenchmarkWriter.write(result, artifacts, output_root) -> Path
LiveBenchmarkComparator.compare(baseline, candidate) -> LiveBenchmarkComparison
```

## 固定场景

| case_id | 目的 |
|---|---|
| `us_normal_fundamentals` | 完整 SEC 基本面和价格证据 |
| `us_missing_data` | 固定缺失估值/长期价格字段 |
| `us_conflicting_evidence` | 增长事实与承诺/不确定性并存 |
| `us_material_event` | 固定申报中的承诺与或有事项 |
| `us_high_volatility` | 固定 Alpaca 价格窗口的高低区间 |
| `us_incomplete_memory` | 明确空 Memory，不允许补造 |

首版 `market_coverage` 只能为 `US`。CN/HK 没有满足固定、合法、真实 Agent
输入要求的快照，因此不得伪装为 live 案例。

## 评分与 A/B 规则

- 每个成功报告使用现有十二维 Evaluation。
- `provider_real=true` 且 `judge_real=true` 才允许 Evaluation。
- Agent 或报告失败作为可测结果保存，不自动重试成 Fake 结果。
- A/B 必须具有相同 dataset version、snapshot hash、案例 ID 集合和规则版本。
- 比较输出每维、总分、Agent 成功率和报告完成率差值；不自动判定 candidate 更好。

## 验收标准

- snapshot hash 不匹配时在任何 LLM 请求前失败。
- 六个场景输入均从同一固定 snapshot 物化。
- 运行过程不调用 SEC、Alpaca 或其他数据 Provider。
- Fake LLM、Fake Judge 或 `provider_real/judge_real=false` 时拒绝运行和评分。
- Prompt 版本、模型和支持的推理参数进入 manifest 与输入指纹。
- 每个 Agent 输出、最终报告和 Evaluation 分文件保存。
- A/B 输入不一致时拒绝比较。
- 默认 pytest 不读取 live credential，不发起网络请求。

## 测试要求

- snapshot Schema、来源引用、市场覆盖和 hash 漂移测试。
- 六场景闭集及输入物化测试。
- Provider/Judge 真实硬门测试。
- 输入 fingerprint 对字段顺序稳定、对 Prompt/model/参数变化敏感。
- 原子产物写入及 secret 字段拒绝测试。
- A/B 可比性和差值测试。
- live pytest 使用 `live` marker，缺 credential 时 skip，默认测试不执行。
- 全量 pytest、Ruff、mypy、Black 和 `git diff --check`。

## 允许修改的目录

- `docs/tasks/live_agent_benchmark.md`
- `benchmarks/live_agent/`
- `src/live_benchmark/`
- `src/schemas/live_benchmark.py`
- `src/schemas/__init__.py`
- `scripts/live_agent_benchmark.py`
- `tests/unit/live_benchmark/`
- `tests/live/test_live_agent_benchmark.py`
- `docs/MODULE_STATUS.md`
- `docs/DECISIONS.md`
- `benchmarks/README.md`
- `README.md`
- `.gitignore`

## 禁止修改的目录

- `benchmarks/cases/v1/`、`benchmarks/results/default_v1.json`
- `src/benchmark/`
- `src/agents/`
- `config/prompts/`
- `src/reports/`
- `src/evaluation/`
- `src/memory/`
- `src/adapters/`
- `src/api/`
- `data/live_acceptance/`

## 依赖的前置任务

- `report_evaluation.md`
- `research_benchmark.md`
- `agents.md`
- `report_pipeline.md`
- `integration.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`
- `docs/DECISIONS.md`
- `benchmarks/README.md`
