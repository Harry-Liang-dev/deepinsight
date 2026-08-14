# Report Evaluation Task

## 目标

建立可重复、可审计、规则版本化的投研报告质量评估系统。系统必须优先以
确定性代码检查可客观验证的质量属性，并将必须依赖语义判断的部分委托给通过
现有 `LLMGateway` 调用的 LLM Judge。

评估结果必须能够回答：

- 使用了哪个规则版本和 Judge 模型；
- 每个维度为何获得该分数；
- 分数依据了哪些报告路径、引用或原始证据；
- 哪些检查由代码计算，哪些由 LLM Judge 判断；
- 同一输入和规则是否具有稳定的输入指纹和可复查结果。

## 范围

- 定义评估输入、检查结果、维度结果和最终结果的 Pydantic v2 模型。
- 实现十二个首版评估维度。
- 实现版本化规则加载和严格校验。
- 实现确定性检查器。
- 实现通过现有 `LLMGateway` 的语义 Judge 适配器。
- 提供显式、离线、可注入的 Fake Judge。
- 聚合确定性和 Judge 检查，生成结构化 `EvaluationResult`。
- 将完整评估结果和审计元数据保存到 DuckDB。
- 为模型、规则、检查器、Judge、聚合和 Repository 编写测试。

## 非目标

- 不修改 Agent、Manager 或报告生成逻辑以提高测试分数。
- 不增加新的研究 Agent 或多轮 Judge 辩论。
- 不自动重写、修复或重新生成低质量报告。
- 不使用收益率、Alpha、回测或交易结果评价报告。
- 不实现强化学习、奖励模型训练、微调或自动偏好学习。
- 不实现交易、订单、仓位、组合优化或策略执行。
- 不增加新的 LLM Provider、向量数据库或任务队列。
- 不把真实网络 Judge 纳入默认 pytest。

## 输入与输出

### 输入

`EvaluationInput` 至少包含：

- 待评估的 `ResearchReport`；
- 可按 `SourceReference` 定位的证据原文；
- 证据发布时间或生效时间（如已知）；
- 上游已经识别的缺失数据项；
- 明确的评估规则版本。

报告本身不足以证明事实正确性或引用可追溯性，因此证据原文是评估输入的一部分，
不得由评估器自行访问外部数据源补齐。

### 输出

`EvaluationResult` 至少包含：

- `evaluation_id`、`report_id`；
- `ruleset_version`、`judge_model`；
- 稳定的 `input_fingerprint`；
- 确定性检查结果和 Judge 检查结果；
- 十二个维度的聚合分数；
- `deterministic_score`、`judge_score`、`overall_score`；
- 每个检查和维度的理由与证据；
- UTC 评估时间。

所有分数使用闭区间 `[0.0, 1.0]`。

## 评估维度

1. `structure_completeness`：标准章节、顺序和结构化内容是否完整。
2. `factual_correctness`：数字是否逐字落证，语义事实是否被证据支持。
3. `citation_coverage`：需要引用的报告陈述是否具有引用。
4. `citation_traceability`：引用能否匹配本次输入中的原始证据。
5. `conclusion_evidence_consistency`：最终结论是否与证据和正文一致。
6. `bull_bear_balance`：看多与看空论证是否均有实质内容且公平处理反方。
7. `risk_identification_quality`：风险是否具体、相关、区分已确认与情景风险。
8. `uncertainty_expression`：是否显式且恰当地表达未知、条件和证据限制。
9. `temporal_validity`：证据是否不晚于报告日且满足规则规定的新鲜度。
10. `trading_instruction_compliance`：是否不存在交易、订单、目标价或仓位指令。
11. `missing_data_disclosure`：上游已知缺失项是否在报告中披露。
12. `readability`：报告是否清晰、专业、连贯且避免不必要重复。

## 评分规则

- 规则由版本化 `EvaluationRuleSet` 定义，不在评估代码中散落魔法数字。
- 首版规则版本为 `report_quality_v1`。
- 每个确定性检查只根据输入报告、证据和规则计算。
- 每个 Judge 检查只接受规则指定的语义维度。
- `factual_correctness` 是混合维度：
  - 数字逐字落证检查；
  - Judge 语义事实性检查。
- `uncertainty_expression` 是混合维度：
  - 不确定性显式存在检查；
  - Judge 不确定性质量检查。
- 其余维度由规则映射到一个确定性检查或一个 Judge 检查。
- 维度分数按规则中的组件权重归一化聚合。
- 总分按规则中的维度权重归一化聚合。
- 确定性总分和 Judge 总分分别按各自检查权重聚合，不得相互隐藏。
- `passed` 由版本化通过阈值计算。
- 无可评估项目时必须使用规则定义的明确行为，并在理由中说明，不能除零或静默
  假定失败。
- 每个检查和维度必须至少包含一条审计证据。

## 数据结构

- `EvaluationDimension`：十二个闭集维度。
- `EvaluatorKind`：`deterministic` 或 `llm_judge`。
- `EvaluationEvidenceItem`：证据 ID、来源定位、原文和可选时间。
- `EvaluationInput`：报告、证据、已知缺失项和规则版本。
- `EvaluationEvidenceRef`：一个评分所依据的报告路径、来源或诊断定位。
- `EvaluationCheck`：检查 ID、维度、评估器类型、分数、通过状态、理由和证据。
- `DimensionScore`：维度聚合分数、理由、证据和组件检查 ID。
- `JudgeMetric` / `JudgeResponse`：LLM Judge 的严格输出。
- `EvaluationRuleSet`：版本、阈值、时间窗口、维度权重和组件权重。
- `EvaluationResult`：完整可持久化评估结果。
- `EvaluationRecord`：Repository 层持久化映射，不泄漏到业务层。

DuckDB 新增 `report_evaluations`：

- `evaluation_id` 主键；
- `report_id`；
- `ruleset_version`；
- `judge_model`；
- `input_fingerprint`；
- `overall_score`；
- `deterministic_score`；
- `judge_score`；
- `result_json`；
- `created_at`。

## 核心接口

```text
EvaluationRuleLoader.load(version) -> EvaluationRuleSet
DeterministicReportEvaluator.evaluate(input, rules) -> list[EvaluationCheck]
ReportJudge.evaluate(input, rules) -> list[EvaluationCheck]
ReportEvaluationService.evaluate(input) -> EvaluationResult
EvaluationRepository.save(result) -> None
EvaluationRepository.get(evaluation_id) -> EvaluationResult | None
```

`LLMReportJudge` 必须复用：

```text
LLMGateway.invoke_json(model, system_prompt, input_payload)
```

不得复制 OpenAI SDK 调用、缓存或错误映射逻辑。

## 验收标准

- 输出恰好包含十二个唯一评估维度。
- 确定性检查与 Judge 检查在结构上明确分离。
- 每个检查和维度都有分数、理由和审计证据。
- 同一输入、规则版本和 Judge 模型产生相同输入指纹。
- 缺少标准章节会降低结构完整性分数。
- 未引用陈述会降低引用覆盖率。
- 无法匹配输入证据的引用会降低可追溯性。
- 数字不出现在对应证据中会降低事实正确性的确定性组件。
- 未来、过期或无时间证据按规则影响时间有效性。
- 交易指令会使合规分数失败。
- 已知缺失数据未披露会降低缺失披露分数。
- LLM Judge 缺项、重复项、未知项或越界分数必须被拒绝。
- Fake Judge 可在无 API Key、无网络条件下完成全流程。
- 评估结果可从临时 DuckDB 完整往返，重复 ID 不得静默覆盖。
- 默认测试不访问网络、不修改第一阶段真实数据。
- 不产生交易、回测、训练或强化学习能力。

## 测试要求

- Pydantic 模型边界和枚举闭集测试。
- 规则文件存在、版本匹配、权重和阈值校验测试。
- 十二个维度的确定性成功与失败测试。
- 数字、百分比、日期和引用匹配测试。
- Judge 响应严格性和 Gateway 调用参数测试。
- Fake Judge 默认离线测试。
- 聚合权重、通过阈值和输入指纹测试。
- Repository 初始化、保存、查询、重复 ID和异常测试。
- 一次由真实报告模型、固定证据和 Fake Judge 组成的离线集成测试。
- 运行全量 pytest、Ruff、mypy 和 Black。

## 允许修改的目录

- `docs/tasks/report_evaluation.md`
- `config/evaluation/`
- `src/evaluation/`
- `src/models/`
- `src/schemas/`
- `src/repositories/`
- `tests/unit/evaluation/`
- `tests/integration/evaluation/`
- 与数据库 Schema 断言直接相关的 Repository 测试
- `docs/MODULE_STATUS.md`
- `docs/DECISIONS.md`
- `docs/schema.md`

## 禁止修改的目录

- `src/agents/`
- `src/reports/`
- `src/memory/`
- `src/operators/`
- `src/adapters/`
- `src/services/` 中现有 LLM Gateway 与 Provider 实现
- `src/api/`
- `apps/`
- `scripts/`
- `data/live_acceptance/`
- `infra/`
- 第一阶段报告生成测试夹具，除非仅复制到评估测试目录使用

## 依赖的前置任务

- `domain_models.md`
- `database.md`
- `llm_gateway.md`
- `memory.md`
- `agents.md`
- `report_pipeline.md`
- `integration.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`
- `docs/DECISIONS.md`
- `docs/schema.md`
