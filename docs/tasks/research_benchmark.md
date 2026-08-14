# Research Benchmark Task

## 目标

建立一个小规模、可版本化、可离线执行且可审计的多市场投研报告
Benchmark。Benchmark 用固定输入和结构化预期验证报告质量边界，并复用现有
`ReportEvaluationService`，不得复制报告评估逻辑。

首版数据集版本为 `research_benchmark_v1`，用于回答：

- 当前报告或安全失败结果是否满足案例预期；
- 哪个确定性指标低于哪个阈值；
- 预期事实是否同时出现在报告和固定证据中；
- 报告是否包含禁止结论；
- 结果使用了哪个评估规则、Judge 和输入指纹；
- 默认离线结果是否可以在新环境中重复生成。

## 范围

- 定义 Benchmark 案例、来源、固定报告材料、预期、阈值和结果模型。
- 建立覆盖 CN、HK、US 的七类首版案例。
- 对当前没有真实 Provider 闭环的市场使用明确标记的合成样本。
- 从固定语义材料确定性物化现有十章节 `ResearchReport`。
- 复用现有报告评估服务执行结构、事实、引用、时间、合规和缺失披露检查。
- 独立检查预期事实覆盖率、禁止结论和预期生命周期。
- 生成机器可读的案例结果和汇总 JSON。
- 提供默认离线 CLI 和 pytest 回归。
- 为未来 live Judge 保留依赖注入边界，但不在默认测试中访问网络。

## 非目标

- 不新增 Agent、Manager、Provider、Memory 算法或报告生成业务逻辑。
- 不把 Benchmark 案例作为真实公司当前事实或投资建议。
- 不抓取实时行情、新闻、公告或财务数据。
- 不对整份报告做 snapshot 字符串全匹配。
- 不把 Fake LLM 或 Fake Judge 的固定输出当作唯一质量证明。
- 不自动修改、重写或重新生成未达标报告。
- 不实现收益评价、Alpha、回测、交易、订单、仓位或强化学习。
- 不将 live Benchmark 纳入默认 pytest。
- 不引入新的数据格式库、LLM Provider 或任务队列。

## 案例

| 案例 | 市场 | 类型 | 默认预期 |
|---|---|---|---|
| `us_complete_company` | US | 数据完整普通公司 | 生成完整可追溯报告 |
| `cn_financial_data_missing` | CN | 财务数据缺失 | 生成报告并披露缺失 |
| `hk_news_fundamental_conflict` | HK | 新闻与基本面冲突 | 同时保留正反证据 |
| `us_high_volatility_major_event` | US | 高波动或重大事件 | 突出事件和风险 |
| `cn_provider_partial_failure` | CN | Provider 部分失败 | 只基于可用证据并披露失败 |
| `hk_memory_empty` | HK | Memory 空结果 | 不伪造 Memory 并披露限制 |
| `us_analyst_failure` | US | Analyst 失败 | 不生成报告，返回安全失败码 |

## 输入与输出

### 输入

每个 YAML 案例至少包含：

- `benchmark_version`、`case_id`、`case_version`；
- 场景、市场、规范化 `asset_id`、报告日期；
- 一个或多个固定来源，含来源类型、Provider、原始定位、采集日、发布日期、
  保存依据和文本；
- 报告型案例的固定事实、推断、风险、不确定性及引用；
- 或失败型案例的故障注入描述和固定安全失败观察；
- 预期事实、允许缺失项、禁止结论；
- 每案例最低质量阈值。

### 输出

`BenchmarkRunResult` 至少包含：

- 数据集版本、运行模式、Judge、评估规则版本和运行时间；
- 总案例、通过、失败数量；
- 每个案例的状态、市场、场景和报告/失败标识；
- 生命周期、预期事实覆盖、禁止结论合规分数；
- 确定性检查、维度和总分；
- 评估输入指纹；
- 每项失败的指标、实际值、阈值和原因。

结果必须是稳定字段顺序的 JSON，不包含密钥、提示词或外部响应原文。

## 数据格式

- 案例文件：`benchmarks/cases/v1/<case_id>.yaml`。
- 汇总结果：`benchmarks/results/default_v1.json`。
- 文本使用 UTF-8。
- 日期和时间显式包含 ISO 8601 格式。
- `fixture_kind` 只能是 `synthetic`、`public_excerpt` 或 `deidentified`。
- 合成案例必须在来源元数据中明确声明，不得使用暗示真实采集的措辞。
- 报告中的每个事实、推断和风险必须引用案例中已定义的 `evidence_id`。

## 预期事实、允许缺失和禁止结论

- `required_facts` 使用短事实片段，不要求整份报告字面相等。
- 预期事实覆盖要求事实同时存在于报告文本和至少一个固定来源原文。
- `allowed_missing_items` 必须覆盖案例传给评估器的全部已知缺失项。
- 禁止结论通过大小写不敏感的规范化短语检查；至少包含交易指令或保证收益类
  结论。
- 失败案例必须定义 `expected_failure_code`，且不得携带伪造报告。

## 最低质量阈值

每个案例必须定义 `BenchmarkThresholds`：

- `lifecycle_compliance_min`；
- 报告型案例的 `deterministic_score_min`；
- `expected_fact_coverage_min`；
- `forbidden_conclusion_compliance_min`；
- `check_minimums`：按确定性检查 ID 设置阈值；
- 可选 `live_dimension_minimums`：仅 live Judge 运行使用。

默认通过门不得依赖 Fake Judge 的语义分数。`overall_score` 和 Judge 分数可以记录，
但默认案例成败只由生命周期、固定预期和确定性检查决定。

## 数据结构

- `BenchmarkFixtureKind`：固定来源类型。
- `BenchmarkExpectedOutcome`：`report` 或 `expected_failure`。
- `BenchmarkSource`：来源元数据、定位和固定原文。
- `BenchmarkClaim`：文本和证据 ID。
- `BenchmarkReportFixture`：固定报告语义材料。
- `BenchmarkExpected`：预期事实、允许缺失、禁止结论和失败码。
- `BenchmarkThresholds`：默认及 live 阈值。
- `ResearchBenchmarkCase`：完整案例。
- `BenchmarkMetricFailure`：具体失败指标。
- `BenchmarkCaseResult`：单案例机器结果。
- `BenchmarkRunResult`：完整汇总。

## 运行器

```text
BenchmarkCaseLoader.load_all() -> list[ResearchBenchmarkCase]
BenchmarkReportMaterializer.build(case) -> ResearchReport
ResearchBenchmarkRunner.run(cases) -> BenchmarkRunResult
ResearchBenchmarkRunner.write(result, path) -> None
```

报告型案例调用现有：

```text
ReportEvaluationService.evaluate(EvaluationInput) -> EvaluationResult
```

运行器接受 `ReportJudge` 注入。默认 CLI 注入 `FakeReportJudge`；live 组合必须注入
`LLMReportJudge`，后者继续通过现有 `LLMGateway` 调用。

## 默认与 live 边界

### 默认 Benchmark

- 只读取 Git 内固定案例；
- 使用固定 UTC 运行时间；
- 使用显式 Fake Judge；
- 通过门不依赖 Fake Judge 语义分数；
- 不读取环境变量、API Key 或网络；
- 是默认 pytest 的一部分。

### Live Benchmark

- 必须显式选择并注入真实 Judge；
- 可启用 `live_dimension_minimums`；
- 输出到与默认结果不同的路径；
- 必须使用 `live`/`network` marker 或独立人工命令；
- 失败不能回退到 Fake Judge；
- 不属于本轮默认验收。

## 验收标准

- 至少七个案例，覆盖 CN、HK、US 和全部指定异常类型。
- 每个案例具有来源类型、Provider、定位、采集日期、发布日期和保存依据。
- 每个报告案例包含预期事实、允许缺失、禁止结论和最低阈值。
- 合成数据在文件及 README 中清晰标记。
- 未定义来源的引用使案例加载失败。
- 未披露的已知缺失项使案例失败。
- 预期事实缺失时指出 `expected_fact_coverage` 及阈值。
- 禁止结论出现时指出 `forbidden_conclusion_compliance` 及阈值。
- 任何确定性检查低于阈值时输出检查 ID、实际分和阈值。
- Analyst 失败案例不生成报告，并校验安全失败码。
- 默认运行结果可序列化为机器可读 JSON。
- 默认运行在无网络、无 API Key 环境下通过。
- 不使用整份字符串 snapshot 决定结果。

## 测试要求

- 案例 Schema、市场和来源元数据验证测试。
- 案例 ID、来源 ID和引用唯一性测试。
- 报告/失败结果互斥测试。
- CN、HK、US 覆盖和七类场景覆盖测试。
- 报告物化的十章节及引用测试。
- 预期事实、允许缺失和禁止结论失败测试。
- 阈值失败必须返回具体指标测试。
- 默认运行结果确定性测试。
- 机器 JSON 往返测试。
- 确认默认 Runner 没有网络或环境变量依赖。
- 全量 pytest、Ruff、mypy 和 Black。

## 允许修改的目录

- `docs/tasks/research_benchmark.md`
- `benchmarks/`
- `src/benchmark/`
- `src/models/enums.py`
- `src/schemas/benchmark.py`
- `src/schemas/__init__.py`
- `tests/unit/benchmark/`
- `tests/integration/benchmark/`
- `docs/MODULE_STATUS.md`
- 如产生新架构决策，`docs/DECISIONS.md`

## 禁止修改的目录

- `src/agents/`
- `src/reports/`
- `src/memory/`
- `src/operators/`
- `src/adapters/`
- `src/services/`
- `src/api/`
- `src/evaluation/`
- `src/repositories/`
- `apps/`
- `scripts/`
- `data/live_acceptance/`
- 第一阶段已有测试 fixtures

## 依赖的前置任务

- `report_evaluation.md`
- `domain_models.md`
- `agents.md`
- `report_pipeline.md`
- `integration.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`
- 如 Benchmark 版本、通过门或 live 边界改变，`docs/DECISIONS.md`
- `benchmarks/README.md`
