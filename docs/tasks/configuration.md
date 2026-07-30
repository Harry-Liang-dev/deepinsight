# Configuration 任务规格

## 目标

实现集中、显式、可测试的应用配置层，为 DuckDB、FAISS、OpenAI、数据源和应用运行参数提供统一入口，消除业务代码中的硬编码路径和密钥。

## 范围

- 按 MASTER_SPEC 定义 `OpenAISettings`、`StorageSettings` 和 `AppSettings`。
- 支持从环境变量读取敏感配置。
- 读取或映射 `config/settings.yaml` 和 `config/providers.yaml` 中的非敏感配置。
- 提供开发、测试和容器环境可覆盖的存储路径。
- 配置应用环境、时区、模型名称、超时、重试和远程存储开关。
- 配置 structlog 的基础行为，但不实现业务日志。
- 为测试提供无全局可变状态的配置构造方式。

## 非目标

- 不连接 OpenAI。
- 不打开 DuckDB 文件。
- 不加载或操作 FAISS 索引。
- 不验证外部 Provider 凭据是否真实有效。
- 不实现数据摄取、Memory、Agent、报告或 API。
- 不在代码或 YAML 中写入真实密钥。

## 输入

- 环境变量
- `config/settings.yaml`
- `config/providers.yaml`
- `.env.example`
- MASTER_SPEC 中的 `OpenAISettings`、`StorageSettings`、`AppSettings` 示例

## 输出

- 类型明确的应用配置对象。
- OpenAI、存储和 Provider 配置。
- 可供依赖注入使用的配置加载入口。
- 不包含真实密钥的环境变量示例。

## 允许修改的目录

- `src/core/`
- `config/`
- `.env.example`
- `tests/unit/`
- `tests/fixtures/`
- `docs/`
- `pyproject.toml`，仅限增加本任务必需且已由规格要求的依赖

## 禁止修改的目录

- `data/`
- `src/adapters/`
- `src/agents/`
- `src/api/`
- `src/memory/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/repositories/`
- `src/phase2_reserved/`
- `apps/`
- `infra/`

## 核心接口

依据 MASTER_SPEC：

- `OpenAISettings`
  - `api_key_env`
  - `model_default`
  - `model_fast`
  - `embedding_model`
  - `timeout_seconds`
  - `max_retries`
  - `store_remote`
- `StorageSettings`
  - `duckdb_path`
  - `faiss_root`
  - `snapshot_root`
  - `backup_root`
- `AppSettings`
  - `env`
  - `timezone`
  - `openai`
  - `storage`

以下细节 MASTER_SPEC 未明确：

- YAML、环境变量和默认值的覆盖优先级：**待确认**
- 配置加载函数或工厂的正式名称：**待确认**
- Provider 配置的正式 Pydantic Schema：**待确认**

## 验收标准

- 所有配置对象使用 Pydantic v2，并具有完整类型标注。
- 不存在硬编码的开发机绝对路径。
- 测试可以把 DuckDB、FAISS、快照和备份路径指向临时目录。
- OpenAI 和 Provider 密钥只从环境变量获取。
- 配置错误能够在应用启动阶段明确报告。
- 配置加载不会创建数据库、索引或网络连接。
- 模块不存在全局可变配置实例。

## 测试要求

- 测试默认值。
- 测试环境变量覆盖。
- 测试非法超时、重试次数和空路径等错误输入。
- 测试配置对象之间互不污染。
- 测试 `.env.example` 不包含真实密钥。
- 测试不得访问网络。

## 依赖的前置任务

- `foundation.md`

## 完成后需要更新的文档

- `README.md`
- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- 如果确定配置优先级或改变 MASTER_SPEC 示例，更新 `docs/DECISIONS.md`
