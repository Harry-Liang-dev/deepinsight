# Integration 任务规格

## 目标

将 Phase One 已完成的模块组装为最小可运行投研报告闭环，并验证本地进程、持久化、API、Worker、Scheduler、Web 和 Docker Compose 之间的边界正确。

## 范围

- 组装配置、DuckDB、FAISS、Embedding、Memory、LLM Gateway、Agent Registry、Report Pipeline 和 FastAPI。
- 建立 API、Worker、Scheduler 和 Web 的应用入口。
- 使用 MASTER_SPEC 的单 Scheduler、单 Worker 拓扑。
- 建立报告生成任务的提交和执行链路。
- 使用 Redis 作为 MASTER_SPEC Compose 中声明的基础任务协调组件；具体队列协议必须先确认。
- 提供最小 Web 报告浏览页面。
- 建立 Dockerfile 和 Docker Compose 服务。
- 验证 DuckDB、FAISS、日志、快照和备份卷。
- 实现本地快照和备份的最小可验证路径。
- 使用测试 Fixture、Fake Provider 和 Fake LLM 完成默认端到端测试。
- 提供可选的真实 OpenAI 冒烟测试，但默认不运行。

## 非目标

- 不要求第一轮集成接通全部商业 Provider。
- 不执行真实交易、回测、组合优化或模型训练。
- 不实现 Kubernetes 部署。
- 不引入 Celery、RQ、Arq 等队列框架，除非另行确认。
- 不建设复杂前端框架；MASTER_SPEC 当前仅要求报告浏览 Web UI。
- 不建设完整监控平台。
- 不进行多节点或高可用部署。
- 不实现 Phase Two 路由背后的业务。

## 输入

- 已完成的所有 Phase One 模块
- 测试数据 Fixture
- Fake Provider
- Fake LLM/Embedding
- 应用配置
- Docker Compose 配置
- 报告生成请求

## 输出

- 可启动的 API、Worker、Scheduler 和 Web 应用。
- 可由 Docker Compose 启动的本地环境。
- 一次完整的报告生成结果。
- DuckDB 报告、章节、运行日志和 Memory 记录。
- FAISS 本地索引。
- 最小报告浏览页面。
- 快照和备份产物。
- 端到端测试和运行文档。

## 允许修改的目录

- `apps/`
- `infra/docker/`
- `infra/compose/`
- `scripts/`，仅限 bootstrap、FAISS rebuild、registry seed 和 backup
- `tests/integration/`
- `tests/fixtures/`
- `docker-compose.yml`
- `Makefile`
- `.env.example`
- `README.md`
- `docs/api.md`
- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 已实现模块中仅限依赖装配所必需的最小改动
- `pyproject.toml`，仅限 MASTER_SPEC 已指定组件所需依赖

## 禁止修改的目录

- `infra/k8s_reserved/`，除非只保留 MASTER_SPEC 已明确的非运行模板
- `src/phase2_reserved/` 中的业务逻辑
- 任何交易、回测、组合优化、策略生成或训练模块
- 未经确认的第三方队列、编排、监控或前端组件
- 生产数据和真实密钥

## 核心接口

端到端主链路：

```text
Report API
  -> Report Job
  -> Worker
  -> ResearchReportPipeline
  -> DuckDB + FAISS
  -> Report Query API
  -> Web Report View
```

定时链路依据 MASTER_SPEC：

```text
Scheduler
  -> Data Ingestion
  -> Document Embedding
  -> Memory Refresh
  -> Report Generation
  -> Snapshot and Backup
```

Compose 服务依据 MASTER_SPEC：

- `api`
- `worker`
- `scheduler`
- `web`
- `redis`

以下内容未完整定义：

- Redis 上采用何种任务消息格式和消费协议：**待确认**
- 是否引入现成队列库：**待确认**；未确认前不得增加
- 报告 Job 状态表及查询接口：**待确认**
- DuckDB 多进程单写入者和锁策略：**待确认**
- Web UI 的正式页面和交互验收：**待确认**
- 快照一致性、保留周期和恢复流程：**待确认**
- Scheduler 在各市场交易日和时区下的最终时间表：**待确认**

## 验收标准

- 本地命令可以启动 API。
- Docker Compose 可以启动规格内的服务。
- 使用 Fake Provider 和 Fake LLM 时，可以从报告请求生成一份单资产报告。
- 报告可以通过 API 查询并在 Web 中浏览。
- 报告、章节、Agent Runs 和 L3 Memory 可在持久化层找到。
- 重启服务后 DuckDB 和 FAISS 数据仍存在。
- 任一外部依赖失败时任务状态可见，不静默丢失。
- Phase Two 路由始终返回 501。
- 默认端到端测试无需商业凭据和真实 OpenAI 调用。
- Docker 和本地运行使用同一配置模型。
- 不出现交易、回测、训练或执行路径。

## 测试要求

- 端到端测试覆盖 Fixture 摄取到报告查询。
- 覆盖 API → Job → Pipeline → Persistence。
- 覆盖服务重启后的报告和向量加载。
- 覆盖 LLM、Embedding、Provider 和 Memory 任一环节失败。
- 覆盖重复提交和幂等行为；正式规则若未确认，先阻止实现并澄清。
- 提供 Docker Compose 健康检查或等价冒烟测试。
- 测试备份产物可以被识别；完整恢复验收规则待确认。
- 真实网络测试必须显式标记并默认跳过。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`
- `llm_gateway.md`
- `data_ingestion.md`
- `memory.md`
- `agents.md`
- `report_pipeline.md`
- `api.md`

## 完成后需要更新的文档

- `README.md`
- `docs/api.md`
- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 如果确定队列、并发、快照、Scheduler 或 Web 方案，更新 `docs/DECISIONS.md`
