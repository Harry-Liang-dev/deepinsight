# API 任务规格

## 目标

通过 FastAPI 暴露 Phase One 的报告生成、报告查询和 Memory 服务接口，使最小投研报告闭环可以被外部调用，同时明确 Phase Two 路由不可用。

## 范围

- 创建 FastAPI 应用入口。
- 实现报告生成路由。
- 实现报告查询路由。
- 实现 Memory 写入、搜索和快照查询路由。
- 使用 Pydantic v2 请求和响应 Schema。
- 通过 FastAPI Dependency Injection 注入 Service。
- 提供健康检查。
- 将业务错误映射为明确 HTTP 状态。
- 注册 MASTER_SPEC 指定的 Phase Two 路由，并统一返回 `501 Not Implemented`。
- 为异步报告任务保留 `job_id` 和 queued 状态契约。

## 非目标

- API 不直接执行 SQL 或操作 FAISS。
- API 不直接调用 OpenAI。
- 不在路由中实现报告 Pipeline。
- 不实现交易、回测、训练、路由或执行逻辑。
- 不引入新的 API 框架或网关。
- 身份认证、租户系统、计费和复杂权限不在本任务范围，因为 MASTER_SPEC 未明确。
- 不实现 Web UI。

## 输入

- `GenerateReportRequest`
- Memory Write Request
- Memory Search Request
- Report Service
- Memory Service
- 任务提交服务
- Report Repository 查询服务

## 输出

- JSON HTTP 响应。
- 报告生成任务的 `job_id` 和状态。
- 已完成报告。
- Memory 写入和检索结果。
- Phase Two 路由的 501 响应。
- 健康检查结果。

## 允许修改的目录

- `apps/api/`
- `src/api/`
- `src/schemas/`，仅限 API 层缺失且已经确认的 Schema
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/api.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- `pyproject.toml`，仅限增加 MASTER_SPEC 指定的 FastAPI、Uvicorn 依赖

## 禁止修改的目录

- `src/adapters/`
- `src/agents/`
- `src/memory/` 的内部实现
- `src/operators/`
- `src/orchestration/` 的内部实现
- `src/reports/` 的内部实现
- `src/repositories/` 的内部实现
- `src/services/llm_gateway.py`
- `data/`
- `infra/k8s_reserved/`
- Phase Two 业务实现

## 核心接口

依据 MASTER_SPEC：

- `POST /v1/reports/generate`
- `GET /v1/reports/{report_id}`
- `POST /v1/memory/write`
- `POST /v1/memory/search`
- `GET /v1/memory/snapshot/{snapshot_date}`

Phase Two 固定返回 501：

- `POST /v1/phase2/factors/mine`
- `POST /v1/phase2/router/select`
- `POST /v1/phase2/training/run`
- `POST /v1/phase2/backtest/run`
- `POST /v1/phase2/execution/paper`
- `POST /v1/phase2/execution/live`

以下内容未完整定义：

- 报告任务状态查询路由：**待确认**
- `job_id` 到 `report_id` 的映射和返回时机：**待确认**
- API 错误响应的统一 Schema：**待确认**
- Memory Snapshot 是查询现有快照还是触发创建：**待确认**
- 认证、授权、CORS 和速率限制：**待确认**

## 验收标准

- FastAPI 应用可以启动。
- OpenAPI 文档包含 Phase One 路由和 Phase Two 占位路由。
- 请求和响应由 Pydantic v2 校验。
- 报告生成接口不在路由函数中执行业务编排。
- 报告查询能够区分不存在、处理中、失败和完成状态；具体查询接口若未确认，需要在实现前澄清。
- Memory 路由仅调用 Memory Service。
- 所有 Phase Two 路由稳定返回 501，且无副作用。
- API 不返回密钥、内部绝对路径或完整敏感日志。
- API 测试不需要真实 OpenAI 或 Provider。

## 测试要求

- 使用 FastAPI TestClient 或等价官方测试方式。
- 测试所有 Phase One 路由的成功和校验失败。
- 测试报告不存在和服务失败。
- 测试 Memory 写入、搜索和空结果。
- 逐一测试六个 Phase Two 路由返回 501。
- 测试 Service 通过依赖覆盖注入 Fake。
- 至少提供一项 API 到临时持久化层的集成测试。
- 默认测试不得访问真实网络。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`
- `memory.md`
- `report_pipeline.md`

## 完成后需要更新的文档

- `docs/api.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 如果确认任务查询、错误模型或安全策略，更新 `docs/DECISIONS.md`
