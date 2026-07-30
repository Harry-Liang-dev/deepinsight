# Report Pipeline 任务规格

## 目标

按照 MASTER_SPEC 固定的研究链路编排数值特征、文档、Memory、四个 Analyst、Research Manager、Bull/Bear、Risk Manager 和 ReportAssembler，生成可追踪、可持久化的标准化研究报告。

## 范围

- 实现 `ResearchReportPipeline`。
- 构建报告所需的结构化特征和文档上下文。
- 按固定顺序调用四个 Analyst。
- 调用 Research Manager。
- 在 Research Manager 之后调用 Bull 和 Bear。
- 使用 Bull、Bear 和 Research Manager 结果调用 Risk Manager。
- 实现 ReportAssembler。
- 生成 Markdown 和 JSON 报告。
- 写入 `reports` 和 `report_sections`。
- 写入完整的 Agent Run 和来源追踪。
- 将最终报告摘要写入 L3 Memory。
- 支持单资产报告的最小闭环。
- 确保同一报告请求的幂等边界可被上层任务控制。

## 非目标

- 不实现 Provider 网络访问。
- 不实现 Agent 内部推理逻辑。
- 不直接调用 OpenAI SDK。
- 不实现 HTTP 路由。
- 不实现 Scheduler、Worker 或 Redis 队列。
- 不实现多轮自主辩论。
- 不实现交易建议、策略、回测、组合或执行。
- 不实现 Phase Two 业务。

## 输入

- 报告生成请求
- 结构化数值特征
- 文档及 Chunk 引用
- Memory 检索结果
- Agent Registry
- Report Repository
- Agent Run Logger
- Memory Service

## 输出

- 标准化报告对象。
- Markdown 报告。
- JSON 报告。
- 报告章节和引用。
- `reports`、`report_sections` 和相关 `agent_runs` 记录。
- L3 报告追踪 Memory。

## 允许修改的目录

- `src/orchestration/`
- `src/reports/`
- `src/services/`，仅限 Report Service、Context Service
- `src/repositories/`，仅限报告持久化
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`

## 禁止修改的目录

- `src/adapters/`
- `src/agents/` 的内部实现
- `src/api/`
- `src/memory/` 的内部实现
- `src/operators/` 的内部实现
- `apps/`
- `infra/`
- `src/phase2_reserved/`
- 数据库 DDL，除非先更新 database 任务和相关决策

## 核心接口

依据 MASTER_SPEC：

```text
ResearchReportPipeline(
    feature_service,
    doc_service,
    agent_registry,
    report_service,
    memory_service,
    run_logger,
)

ResearchReportPipeline.execute(
    report_request: dict,
) -> dict
```

固定编排顺序：

1. `feature_service.build_context`
2. `doc_service.collect_documents`
3. 四个 Analyst
4. Research Manager
5. Bull Manager 和 Bear Manager
6. Risk Manager
7. `report_service.assemble`
8. 报告持久化
9. 写入报告 Memory

以下内容未完整定义：

- `ReportAssembler` 的正式类签名：**待确认**
- 完整 `report_json` Schema 和章节必填规则：**待确认**
- `final_recommendation` 的允许值及与交易信号的边界：**待确认**
- 多资产、市场日报、watchlist 和 macro weekly 的组装方式：**待确认**
- Pipeline 失败后的断点恢复协议：**待确认**
- 报告幂等键和 `force_refresh` 的正式规则：**待确认**

最小闭环只实现单资产报告；其他报告类型在接口确认前不得自行设计复杂聚合。

## 验收标准

- 单资产请求可以完整执行固定 Agent 顺序。
- 四个 Analyst 的结果全部进入 Research Manager。
- Bull 和 Bear 均基于 Research Manager 结果。
- Risk 同时接收 Bull 和 Bear。
- 最终报告包含来源追踪、Bull、Bear、风险和综合结论。
- 报告不包含交易指令、订单或仓位。
- Markdown 与 JSON 表达同一份报告内容。
- 报告和章节成功持久化。
- Agent 运行记录可按 `report_id` 查询。
- 最终报告摘要可写入 L3 Memory。
- 任一阶段失败时报告不会被标记为 completed。

## 测试要求

- 使用 Fake Agent、Memory 和 Repository 测试准确调用顺序。
- 测试 Bull 和 Bear 都执行后才调用 Risk。
- 测试 Agent 失败、报告装配失败和持久化失败。
- 测试引用和 `source_trace_json`。
- 测试 Markdown/JSON 一致性。
- 测试报告状态转换。
- 至少提供一次使用临时 DuckDB 和本地临时 FAISS 的集成测试。
- 默认测试不得调用真实 Provider 或 OpenAI。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`
- `llm_gateway.md`
- `data_ingestion.md`
- `memory.md`
- `agents.md`

## 完成后需要更新的文档

- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 如果确认报告 Schema、状态、幂等或多资产行为，更新 `docs/DECISIONS.md`
