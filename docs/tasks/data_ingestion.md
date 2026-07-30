# Data Ingestion 任务规格

## 目标

建立可替换的多市场 Provider Adapter、canonical `asset_id` 标准化和最小数据摄取链路，将结构化行情、财务数据及文本元数据可靠写入 DuckDB，为后续 Memory 和报告生成提供输入。

## 范围

- 实现 MASTER_SPEC 中的 `BaseProviderAdapter`。
- 创建 Wind、CNINFO、HKEXnews、SEC EDGAR、FRED、Alpaca 和 X 的 Provider Adapter 占位实现。
- 商业 Reuters/LSEG 和 Bloomberg 仅保留持牌连接器边界，不进行抓取。
- 规范化 CN、HK、US 的 `asset_id`。
- 支持 instruments、EOD bars 和 documents 的最小摄取路径。
- 根据 MASTER_SPEC Schema 写入 DuckDB。
- 记录 `ingestion_jobs` 状态、写入行数和错误。
- 支持 full、incremental、repair 任务类型的契约。
- 保存原始数据或原始文本引用。
- 实现最小文档切块能力，为 Embedding 和 FAISS 提供 `document_chunks`。
- 使用测试 Fixture 打通离线摄取集成测试。

## 非目标

- 不绕过授权抓取 Wind、Reuters/LSEG 或 Bloomberg。
- 不承诺本任务接通所有真实 Provider 凭据。
- 不生成 Embedding 或更新 FAISS。
- 不实现 Memory。
- 不调用 LLM。
- 不生成 Agent 分析或研究报告。
- 不实现实时交易行情、交易执行或策略。
- 不自行加入新的第三方数据平台。

## 输入

- Provider 配置和凭据环境变量
- 市场范围
- 标的列表
- 目标日期或开始、结束日期
- Provider 原始结构化记录和文本
- 领域模型及 DuckDB Repository

## 输出

- 规范化 instruments。
- 规范化 EOD bars。
- 财务、宏观、公司事件和文本记录；其中未被 Base Adapter 覆盖的方法需先确认接口。
- `text_documents` 和 `document_chunks`。
- `ingestion_jobs` 运行记录。
- 可追溯到 Provider 的来源字段。

## 允许修改的目录

- `src/adapters/`
- `src/services/`，仅限摄取、标准化和文档处理服务
- `src/repositories/`，仅限摄取所需 Repository
- `scripts/`，仅限 source registry 初始化相关脚本
- `config/providers.yaml`
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- `pyproject.toml`，仅限已确认 Provider 所需依赖

## 禁止修改的目录

- `src/agents/`
- `src/api/`
- `src/memory/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/services/llm_gateway.py`
- `src/phase2_reserved/`
- `apps/web/`
- `infra/k8s_reserved/`
- `data/faiss/`

## 核心接口

依据 MASTER_SPEC：

```text
BaseProviderAdapter.healthcheck() -> dict
BaseProviderAdapter.fetch_instruments() -> iterable[dict]
BaseProviderAdapter.fetch_eod_bars(
    asset_ids: list[str],
    target_date: date,
) -> iterable[dict]
BaseProviderAdapter.fetch_documents(
    asset_ids: list[str],
    start_date: date,
    end_date: date,
) -> iterable[dict]
```

以下接口或规则未完整定义：

- fundamentals、macro_series、corporate_events 的 Adapter 方法：**待确认**
- Provider 原始记录到标准记录的正式 Normalizer 接口：**待确认**
- 文档切块大小、重叠量和 Token 计算方式：**待确认**
- 多 Provider 冲突时的来源优先级：**待确认**
- 财务重述、行情修订和幂等键策略：**待确认**
- 原始文本文件的命名、编码和保留周期：**待确认**

## 验收标准

- Provider 细节不会泄漏到 API、Memory 或 Agent。
- canonical `asset_id` 与 MASTER_SPEC 示例一致。
- 相同摄取任务重复运行不会产生重复主记录。
- 每条规范化数据保留 `source_id` 和摄取时间。
- 商业 Provider 占位实现不会尝试未授权网络访问。
- 测试 Fixture 可以完成 Adapter → 标准化 → DuckDB 的离线闭环。
- 文档切块结果具有稳定 `chunk_index` 和可追溯 `document_id`。
- 失败任务能够记录状态和错误，不留下部分状态不明的任务。

## 测试要求

- 单元测试 Base Adapter 契约和资产代码规范化。
- 单元测试文档切块的空文本、短文本和多块文本。
- 集成测试 instruments、EOD bars、documents 写入。
- 测试重复摄取的幂等性。
- 测试非法市场、错误 Provider 数据和部分失败。
- 所有默认测试必须离线，不依赖商业凭据。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`

## 完成后需要更新的文档

- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 如果确定来源优先级、修订或切块策略，更新 `docs/DECISIONS.md`
