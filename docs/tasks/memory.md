# Memory 任务规格

## 目标

基于 DuckDB、FAISS 和本地 Embedding 实现 Phase One 五级全局记忆的最小写入与检索闭环，为 Analyst、Manager 和报告追踪提供可归因的语义上下文。

## 范围

- 实现 L0–L4 的名称和语义约束。
- 实现 MASTER_SPEC 中的 `MemoryWriteRequest` 和 `MemoryService`。
- 实现文档和 Memory 的 Embedding Service。
- 实现 FAISS Repository、namespace 目录和 manifest 处理。
- 在 DuckDB 中维护向量 ID 与 `chunk_id`、`memory_id` 的映射。
- 支持 Memory 写入。
- 支持跨 Memory Level、namespace 和 `top_k` 的语义搜索。
- 支持 `min_importance_score` 和时间衰减参数的契约。
- 提供索引保存、加载和重建能力。
- 确保 Memory 写入可归因于 system、operator 或 agent。

## 非目标

- 不引入 Milvus、Weaviate、Mem0 或 LangGraph 运行依赖。
- 不实现分布式向量数据库。
- 不实现 Agent。
- 不生成 L0–L4 的业务摘要；本任务只提供存储和检索能力。
- 不实现 Web UI。
- 不实现 Phase Two reward、router 或训练逻辑。
- 不在本任务实现 HTTP 路由。
- 完整快照和备份编排可在 Integration 任务中完成。

## 输入

- `MemoryWriteRequest`
- 文档 Chunk 或 Memory 摘要文本
- Memory Level
- namespace key
- importance score
- 来源引用
- Embedding 配置
- DuckDB Repository
- FAISS 存储路径

## 输出

- `memory_items` 记录。
- FAISS 向量。
- namespace manifest 和向量元数据。
- Memory 写入结果。
- 按相似度和过滤条件返回的 Memory 搜索结果。

## 允许修改的目录

- `src/memory/`
- `src/repositories/`，仅限 FAISS、Memory 和向量元数据
- `src/services/`，仅限 Embedding Service
- `scripts/`，仅限 FAISS rebuild
- `data/faiss/`，仅保留占位或测试忽略规则，不提交运行索引
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`
- `docs/schema.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- `pyproject.toml`，仅限增加 FAISS 和官方 Embedding 调用所需依赖

## 禁止修改的目录

- `src/agents/`
- `src/api/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/adapters/`
- `apps/`
- `infra/k8s_reserved/`
- `src/phase2_reserved/`

## 核心接口

依据 MASTER_SPEC：

```text
MemoryService(duckdb_repo, vector_repo, embedder)
MemoryService.write(req: MemoryWriteRequest) -> dict
MemoryService.search(
    levels: list[str],
    namespace_keys: list[str],
    query_text: str,
    top_k: int = 8,
) -> list[dict]
```

Namespace：

- `memory_L0_v1`
- `memory_L1_v1`
- `memory_L2_v1`
- `memory_L3_v1`
- `memory_L4_v1`

FAISS manifest 至少包含：

- namespace
- embedder model
- embedding dimension
- distance metric
- source table
- FAISS index type
- created time

以下规则未完整定义：

- DuckDB 与 FAISS 双写的原子性和失败补偿：**待确认**
- FAISS vector ID 的分配和并发策略：**待确认**
- 时间衰减和 importance 的最终重排公式：**待确认**
- Memory 去重、更新、删除和过期策略：**待确认**
- L0 与 L4 内容的具体生成规则：**待确认**
- Embedding 请求是否通过 `LLMGateway` 或独立官方客户端：**待确认**

## 验收标准

- L0–L4 均能使用独立 namespace 写入和读取。
- DuckDB 记录能够定位对应 FAISS vector ID。
- FAISS 重启加载后检索结果仍可用。
- namespace 和 asset 过滤有效。
- 无效 Memory Level、空文本和维度不一致会被拒绝。
- 每条 Memory 都有来源引用和 `created_by`。
- 索引文件不会进入 Git。
- Phase One 服务不读取 `p2_reward_hint_json` 或 `p2_router_hint_json`。
- 双写失败不会静默产生不可发现的不一致。

## 测试要求

- 使用临时目录测试 FAISS 保存和重新加载。
- 测试每个 Memory Level。
- 测试 namespace、importance 和 top_k 过滤。
- 测试空索引和无结果。
- 测试向量维度不一致。
- 测试 DuckDB 与 FAISS 映射。
- 模拟其中一个存储写入失败，验证错误可见且可恢复。
- 默认测试不调用真实 Embedding 网络服务。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`
- `domain_models.md`
- `database.md`
- `data_ingestion.md`

## 完成后需要更新的文档

- `docs/schema.md`
- `docs/api.md`
- `docs/operations.md`
- `docs/MODULE_STATUS.md`
- 如果确定一致性、排序或生命周期策略，更新 `docs/DECISIONS.md`
