# Database 任务规格

## 目标

依据 MASTER_SPEC 建立 Phase One 的 DuckDB Schema、幂等 bootstrap 和清晰的 Repository 边界，为数据摄取、Memory、Agent 运行记录和报告持久化提供单一结构化事实来源。

## 范围

- 使用单个可配置 DuckDB 文件。
- 实现 MASTER_SPEC 列出的核心表和索引。
- 提供幂等数据库初始化入口。
- 建立连接生命周期和 Repository 基础接口。
- 支持测试使用临时 DuckDB 文件。
- 保留 MASTER_SPEC 指定的 Phase Two nullable 字段和 `phase2_registry`，但不实现 Phase Two 业务。
- 明确 DuckDB 文件的单写入者或并发访问约束。

核心表包括：

- `instruments`
- `source_registry`
- `eod_bars`
- `fundamentals`
- `macro_series`
- `corporate_events`
- `text_documents`
- `document_chunks`
- `memory_items`
- `agent_runs`
- `reports`
- `report_sections`
- `llm_cache`
- `ingestion_jobs`
- `phase2_registry`

## 非目标

- 不实现 FAISS。
- 不实现 Provider 网络请求或数据清洗。
- 不实现 Memory 排序和语义检索。
- 不实现 LLM、Agent、报告编排或 API。
- 不启用 DuckDB FTS，除非另有明确任务确认。
- 不实现分布式数据库、多节点写入或数据库服务化。
- 不解析或依赖任何 `p2_*` 字段。

## 输入

- 应用存储配置
- MASTER_SPEC 的 DuckDB DDL 和索引
- `src/models/` 与 `src/schemas/` 的领域契约

## 输出

- 可重复执行的 DuckDB bootstrap。
- 持久化 DuckDB 文件或测试用临时数据库。
- 基础 Repository 接口和连接管理。
- Schema 初始化测试。
- `docs/schema.md` 中的实际 Schema 说明。

## 允许修改的目录

- `src/repositories/`
- `scripts/`，仅限 DuckDB bootstrap 相关脚本
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/schema.md`
- `docs/MODULE_STATUS.md`
- `pyproject.toml`，仅限增加 MASTER_SPEC 指定的 DuckDB、SQLAlchemy 依赖
- `data/duckdb/`，仅允许保留目录占位，不提交运行数据库

## 禁止修改的目录

- `src/adapters/`
- `src/agents/`
- `src/api/`
- `src/memory/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/services/llm_gateway.py`
- `apps/`
- `infra/`
- `data/faiss/`
- `src/phase2_reserved/`

## 核心接口

规格明确：

- 数据库路径来自 `StorageSettings.duckdb_path`
- bootstrap 必须使用 MASTER_SPEC 的 DDL 和索引
- DuckDB 是 Phase One 唯一结构化数据库

规格未明确：

- Repository 类名和每个方法的正式签名：**待确认**
- SQLAlchemy 2.x 与 DuckDB 原生连接各自负责的范围：**待确认**
- Schema 迁移和版本表的正式方案：**待确认**
- API、Worker、Scheduler 共享文件时的单写入者机制：**待确认**
- 多 Provider 数据修订和冲突保存方式：**待确认**

在上述事项确认前，只能实现最小、显式、可替换的连接和 Repository 边界，不得引入迁移框架或数据库服务。

## 验收标准

- 新建空数据库时可以一次性创建全部表和索引。
- 重复执行 bootstrap 不报错且不重复破坏数据。
- 表名、字段和 Phase Two 保留列与 MASTER_SPEC 一致。
- 测试数据库路径不依赖 `/app` 或开发机绝对路径。
- 连接生命周期明确，不存在导入时自动打开的全局连接。
- 运行数据库、临时文件和锁文件不会进入 Git。
- Repository 不包含 Memory、Agent 或报告编排逻辑。

## 测试要求

- 测试首次 bootstrap。
- 测试重复 bootstrap。
- 验证全部核心表和索引存在。
- 验证关键主键、非空字段和默认值。
- 验证测试可使用临时目录并在结束后释放连接。
- 至少提供一项基础插入和读取集成测试。
- 测试不得访问网络或生产数据目录。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`

## 完成后需要更新的文档

- `docs/schema.md`
- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- 如果确定 ORM、迁移或并发策略，更新 `docs/DECISIONS.md`
