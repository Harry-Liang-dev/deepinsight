# Domain Models 任务规格

## 目标

建立 Phase One 最小闭环所需的领域模型和 Pydantic v2 数据契约，使数据摄取、Memory、Agent、报告和 API 通过明确类型协作。

## 范围

- 定义跨市场 canonical `asset_id` 的格式和验证规则。
- 定义市场、Memory Level、任务状态、报告类型等有限值。
- 定义数据源标准化后的结构化记录契约。
- 定义 Memory 写入和搜索请求/响应契约。
- 定义通用 Agent 请求、输出状态和引用契约。
- 定义报告生成请求、报告结果和报告章节契约。
- 保留 MASTER_SPEC 中的 Phase Two nullable 字段，但 Phase One 代码不得读取或依赖其内容。
- 明确时间、日期、语言、JSON 元数据和可空字段的表示方式。

## 非目标

- 不创建 SQL 表或 SQLAlchemy 映射。
- 不实现 Repository。
- 不实现资产代码转换算法。
- 不实现 Memory 检索、Agent 调用或报告生成。
- 不设计交易信号、订单、组合、回测或训练模型。
- 不扩展 MASTER_SPEC 未定义的复杂领域层次。

## 输入

- MASTER_SPEC 的 canonical `asset_id` 示例
- MASTER_SPEC 的 SQL DDL
- Memory API 请求/响应示例
- Agent 输入/输出示例
- Report API 请求/响应示例

## 输出

- `src/models/` 中的领域枚举和值对象。
- `src/schemas/` 中的 Pydantic v2 请求、响应和内部传输模型。
- 供后续模块复用的稳定字段定义。

## 允许修改的目录

- `src/models/`
- `src/schemas/`
- `tests/unit/`
- `tests/fixtures/`
- `docs/schema.md`
- `docs/MODULE_STATUS.md`
- `docs/DECISIONS.md`，仅在确有架构决定时

## 禁止修改的目录

- `src/repositories/`
- `src/adapters/`
- `src/memory/`
- `src/agents/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/api/`
- `src/services/`
- `apps/`
- `data/`
- `infra/`

## 核心接口

规格已明确的核心契约：

- canonical `asset_id`
  - `CN:600519.SH`
  - `CN:000001.SZ`
  - `HK:0700.HK`
  - `US:AAPL`
- `MemoryWriteRequest`
- Memory Search Request / Response
- Common Agent Request
- Fundamental Analyst Response
- Bull Manager Response
- Bear Manager Response
- Risk Manager Response
- `GenerateReportRequest`
- Report Response

以下契约不完整，必须标记而不能自行复杂化：

- Technical Text、Sentiment、News Event 和 Research Manager 的完整输出 Schema：**待确认**
- 最终 `report_json` 的完整标准 Schema：**待确认**
- `final_recommendation` 和 `confidence_band` 的允许值：**待确认**
- 多个 `asset_ids` 如何映射到一份或多份报告：**待确认**
- JSON 元数据使用 Pydantic 对象还是保持通用映射：**待确认**

## 验收标准

- 所有公共模型使用 Pydantic v2 或明确的不可变值类型。
- 所有公共成员和方法具有类型标注。
- canonical `asset_id` 可以区分 CN、HK、US 示例。
- 非法市场、Memory Level、报告类型和日期会被拒绝。
- Phase One 模型不包含交易方向、订单、仓位或回测结果。
- 后续模块无需复制相同请求/响应结构。
- 未明确的报告和 Agent 字段以“待确认”约束记录，不擅自扩展。

## 测试要求

- 对每个核心 Schema 提供有效和无效输入测试。
- 覆盖 canonical `asset_id` 的三个市场示例。
- 覆盖时间、日期、可空字段和 JSON 序列化。
- 验证 Phase Two 字段默认保持空值且不会被业务模型解释。
- 测试不得访问数据库、文件系统或网络。

## 依赖的前置任务

- `foundation.md`
- `configuration.md`

## 完成后需要更新的文档

- `docs/schema.md`
- `docs/MODULE_STATUS.md`
- 如果确定待确认的领域契约，更新 `docs/DECISIONS.md`
