# Agents 任务规格

## 目标

实现 Phase One 的确定性数值特征和角色化 GPT Agent，使结构化数据、检索证据和 Memory 可以被转换为可追踪、结构化、非交易性质的研究观点。

## 范围

- 实现 Fundamental 和 Technical 确定性数值算子。
- 实现 `BaseAgent`。
- 实现四个 Analyst：
  - Fundamental Analyst
  - Technical Text Analyst
  - Sentiment Analyst
  - News Event Analyst
- 实现四个 Manager：
  - Research Manager
  - Bull Manager
  - Bear Manager
  - Risk Manager
- 所有 Agent 通过 `LLMGateway` 调用 GPT。
- Agent 通过 `MemoryService` 获取语义上下文。
- Prompt 存放于 `config/prompts/` 并具有版本。
- Agent 输出必须是结构化 JSON。
- 记录 `agent_runs` 所需的输入、检索上下文、输出、Prompt 版本、模型和执行指标。
- 区分事实、推断、不确定性和引用。

## 非目标

- Agent 不直接操作 OpenAI SDK。
- Agent 不直接连接 DuckDB 或 FAISS。
- 不让 LLM 计算财务或技术指标。
- 不实现多轮自主对话、LangGraph 或动态 Agent 路由。
- 不实现交易建议、价格目标、仓位、订单或策略。
- 不实现 ReportAssembler 或 FastAPI。
- 不实现 Phase Two Factor Miner、MoE Router 或训练能力。

## 输入

- 报告日期、市场和 `asset_id`
- 确定性结构化特征
- 检索文档及引用
- L0–L4 Memory
- Prompt 模板和版本
- LLM Gateway

## 输出

- 四个 Analyst 的结构化分析结果。
- Research Manager 结构化总结。
- Bull 和 Bear 结构化论点。
- Risk Manager 结构化风险结果。
- `agent_runs` 追踪记录。
- 可供 Report Pipeline 使用的 Agent 输出集合。

## 允许修改的目录

- `src/agents/`
- `src/operators/`
- `config/prompts/`
- `src/repositories/`，仅限 Agent Run Logger
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/MODULE_STATUS.md`
- `docs/operations.md`

## 禁止修改的目录

- `src/api/`
- `src/adapters/`
- `src/memory/` 的实现
- `src/orchestration/`
- `src/reports/`
- `apps/`
- `infra/`
- `src/phase2_reserved/`
- DuckDB DDL，除非先更新 database 任务和相关决策

## 核心接口

依据 MASTER_SPEC：

```text
BaseAgent(llm_gateway, memory_service, prompt_loader)
BaseAgent.run(payload: dict) -> dict
```

必须具备的 Agent 名称：

- `fundamental_analyst`
- `technical_text_analyst`
- `sentiment_analyst`
- `news_event_analyst`
- `research_manager`
- `bull_manager`
- `bear_manager`
- `risk_manager`

已明确的输出：

- Fundamental Analyst Response
- Bull Manager Response
- Bear Manager Response
- Risk Manager Response

待确认：

- Technical Text Analyst 的完整输出字段：**待确认**
- Sentiment Analyst 的完整输出字段：**待确认**
- News Event Analyst 的完整输出字段：**待确认**
- Research Manager 的完整输出字段：**待确认**
- Agent 模型选择是否全部使用 `model_default`：**待确认**
- Bull/Bear 是并列单轮论证还是需要多轮辩论：**待确认**；最小闭环不得自行增加多轮机制

## 验收标准

- 所有 Agent 使用公共 BaseAgent 和依赖注入。
- 所有 GPT 调用经过 LLM Gateway。
- 所有数值指标由 `src/operators/` 产生且结果确定。
- Agent 输出通过 Pydantic Schema 验证。
- Agent 不输出交易指令、价格目标或订单建议。
- 引用只能指向输入中存在的 document/chunk。
- Agent Run 能追踪模型、Prompt 版本、输入、检索上下文和输出。
- 任一 Agent 可以用测试 Gateway 独立运行。
- Prompt 不硬编码在 Agent 类中。

## 测试要求

- 每个数值算子具有正常、缺失、空数据和历史不足测试。
- 每个 Agent 使用 Fake Gateway 进行单元测试。
- 测试输出 Schema 校验失败。
- 测试引用不存在的文档或 Chunk 时被发现。
- 测试 Agent 不直接访问网络或数据库。
- 集成测试使用 Memory Stub/Fake 和 LLM Fake。
- 至少验证一次四 Analyst → Research Manager → Bull/Bear → Risk 的数据契约兼容性，但完整编排属于下一任务。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`
- `llm_gateway.md`
- `data_ingestion.md`
- `memory.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- `docs/schema.md`
- 如果确认缺失的 Agent Schema、模型选择或辩论方式，更新 `docs/DECISIONS.md`
