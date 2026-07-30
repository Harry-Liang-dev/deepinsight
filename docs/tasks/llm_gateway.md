# LLM Gateway 任务规格

## 目标

实现 Phase One 唯一的 GPT 推理入口，使所有 Agent 通过可缓存、可记录、可替换、可测试的统一服务调用 OpenAI Responses API。

## 范围

- 实现 MASTER_SPEC 中的 `LLMGateway`。
- 仅使用 OpenAI Responses API，不使用 Assistants API。
- 支持模型、系统 Prompt 和输入载荷。
- 支持结构化 JSON 返回。
- 根据模型、Prompt 和输入载荷生成确定性缓存键。
- 读写 DuckDB 中的 `llm_cache`。
- 应用配置中的超时、重试和 `store_remote`。
- 记录调用状态、延迟、Token 使用和错误所需的基础信息。
- 支持注入测试替身，单元测试不得依赖真实 OpenAI 请求。

## 非目标

- 不实现任何 Analyst 或 Manager Agent。
- 不编写角色 Prompt。
- 不实现 Memory 检索。
- 不计算财务或技术指标。
- 不实现本地模型、微调、训练或多模型路由。
- 不引入 Assistants API、LangGraph 或其他 LLM 编排框架。
- 不负责报告编排。

## 输入

- `OpenAISettings`
- `llm_cache` Repository
- 模型名称
- 系统 Prompt
- JSON 可序列化输入载荷
- OpenAI API Key 环境变量

## 输出

- JSON 对象形式的模型响应。
- 缓存记录。
- 可记录的调用元数据或错误。
- 可供 Agent 依赖注入的 Gateway 实例。

## 允许修改的目录

- `src/services/`
- `src/repositories/`，仅限 LLM Cache 和调用日志所需接口
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- `pyproject.toml`，仅限增加官方 OpenAI SDK

## 禁止修改的目录

- `src/agents/`
- `src/memory/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/api/`
- `src/adapters/`
- `apps/`
- `infra/`
- `config/prompts/`
- `src/phase2_reserved/`

## 核心接口

依据 MASTER_SPEC：

```text
LLMGateway(cache_repo, settings)
LLMGateway.invoke_json(
    model: str,
    system_prompt: str,
    input_payload: dict[str, object],
) -> dict[str, object]
```

缓存键必须覆盖：

- `model`
- `system_prompt`
- `input_payload`

以下细节未被 MASTER_SPEC 完整定义：

- OpenAI Responses API 结构化输出参数的正式封装：**待确认**
- 温度、最大输出 Token 等推理参数是否开放：**待确认**
- Cache Repository 的正式方法名和签名：**待确认**
- 缓存过期策略和 `force_refresh` 如何穿透 Gateway：**待确认**
- Agent Run Logger 与 Gateway 的责任边界：**待确认**

## 验收标准

- 所有 Phase One 文本推理只能通过 `LLMGateway`。
- 使用官方 OpenAI Responses API。
- API Key 不进入日志、缓存键或持久化输入。
- 相同模型、Prompt 和规范化输入产生相同缓存键。
- 命中缓存时不调用远程 API。
- 无效 JSON、超时和远程错误能够转换成明确错误。
- 重试次数和超时来自配置。
- 模块可以使用测试替身完全离线测试。
- 未实现任何 Agent 或角色业务。

## 测试要求

- Mock OpenAI 客户端测试成功响应。
- 测试缓存命中和缓存未命中。
- 测试缓存键稳定性及输入变化。
- 测试超时、限流、无效 JSON 和重试上限。
- 测试 `store_remote` 配置传递。
- 测试日志或错误中不泄漏 API Key。
- 集成测试使用临时 DuckDB 的 `llm_cache`，不得调用真实网络。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- 如果确定推理参数、缓存策略或日志边界，更新 `docs/DECISIONS.md`
