# Phase 3 Data Completeness Task

## 目标

以真实运行 `20260808T082315Z` 为审计基线，建立从 Provider 原始记录到
Agent 可消费证据包的完整数据契约，使每个 Agent 明确知道数据是否存在、来自
哪里、截至何时、经过何种转换以及缺失会产生什么影响。

Phase 3 的本任务只建设 Structured Financial Intelligence 输入层，不实现因子、
Regime、MoE、策略池、回测、交易、组合优化或模型训练。

## 审计基线

- 标的：`US:AAPL`
- 数据集：`live_aapl_multisource_baseline_v1`
- 数据窗口：`2026-05-08` 至 `2026-08-07`
- 报告：`rep_6732964e3eb2453e9a3b8d88940570ea`
- 真实 Provider：SEC EDGAR、Alpaca Market Data、Qwen
- 入库数据：1 份 SEC 10-Q、9 个文档 chunk、63 根 EOD bar
- 空表：`fundamentals`、`macro_series`、`corporate_events`
- Memory：运行前检索结果为 0；报告完成后仅写入 1 条 L3 report trace
- Agent：8 次运行，其中 Technical 与 Sentiment 降级失败
- 报告引用：75 条陈述只使用 2 个 SEC chunk；Alpaca 价格未形成报告引用
- Evaluation：总分 `0.7758536585`，确定性分 `0.9985652798`，LLM Judge
  分 `0.4846153846`

该基线只能说明 US 单标的一次真实运行，不代表 CN、HK 或跨周期覆盖。

## 范围

- 定义统一、可归因的结构化证据项和数据可用性清单。
- 为 Fundamental、Technical、Sentiment、News/Event 定义角色化输入视图。
- 为 Research、Bull、Bear、Risk Manager 定义只读全局研究上下文。
- 补齐 US 第一版的财务、价格技术、宏观、市场/行业、事件和 Memory 输入。
- 为每个字段记录 Provider、原始定位、时间边界、单位、币种、转换和版本。
- 将缺失、过期、部分失败和不适用作为一等状态传递给 Agent 与 Report。
- 保持 Provider → Normalization → Repository → Memory/Evidence → Agent 的单一链路。
- 通过固定 snapshot 和真实 live baseline 分别验证确定性与时效性。

## 非目标

- 不增加新的 Agent。
- 不让 Agent 或 Report Pipeline 直接访问 Provider、DuckDB 或向量索引。
- 不在 LLM 中计算可确定性计算的财务或技术指标。
- 不以降低 numeric grounding、Schema 或引用校验来换取 Agent 成功。
- 不将推断写成事实，不生成证据中不存在的百分比、单位转换或财务数字。
- 不接入来源授权、留存政策尚未明确的新闻、社交媒体或一致预期数据。
- 不实现因子、Regime、MoE、策略池、回测、交易、组合优化或训练。

## 输入

- Canonical asset、报告 `as_of`、数据窗口和市场日历。
- Provider 原始记录及稳定原始定位。
- 标准化财务、行情、宏观、事件和文档记录。
- L0–L4 Memory 检索结果及 snapshot/version。
- Prompt version、数据转换 version 和指标计算 version。

## 输出

- `ResearchEvidenceBundle`：按能力域组织的可归因证据集合。
- `DataAvailabilityManifest`：requested/present/missing/stale/not_applicable、原因和
  最新时间。
- Fundamental、Technical、Sentiment、Event 四种 Analyst 输入视图。
- `ManagerResearchContext`：已验证 Analyst 输出、覆盖率、冲突、缺失和证据索引。
- 可被 Report 和 Evaluation 追踪的结构化数值引用。
- Provider/字段/市场/时效覆盖清单和机器可读审计结果。

## A. Eight-Agent Data Requirement Matrix

表中的“最大时效”是 Phase 3 建议 SLA，不表示当前系统已经满足。

| Agent | 所需数据 | 当前存在/Provider/表 | 频率与最大时效 | 真实性 | 当前缺口与报告影响 | 优先级 |
|---|---|---|---|---|---|---|
| Fundamental Analyst | 三表、财务周期、单位/币种、同比与盈利能力 | SEC 10-Q 文本存在；`text_documents`/`document_chunks`；`fundamentals` 为空 | 季/年；申报后 24h | 文本真实，结构化缺失 | 只能从长文本叙述，无法稳定计算增长、利润率、现金流和资产负债质量 | P0 |
| Fundamental Analyst | 估值：价格、股本、市值、EPS、P/E、P/B | Alpaca 收盘价存在；股本、标准化 EPS 与估值不存在 | 日；1 个交易日 | 价格真实，估值缺失 | 无法判断价格是否已反映基本面，Bull/Bear 缺少估值锚 | P0 |
| Fundamental Analyst | 8–12 季盈利历史、盈利 surprise 和一致预期 | 当前不存在；无已批准共识 Provider | 季度/修订事件；1 日 | 否 | 无法区分单季异常与趋势，也无法衡量预期差 | P1；共识 P2 |
| Technical Text Analyst | 可引用 OHLCV、feed/calendar 和窗口 | Alpaca 63 根 bar；`eod_bars` | 日；收盘后 1 日 | 是 | 原始数据入库但未进入一等 Evidence；真实运行被 numeric grounding 拒绝 | P0 |
| Technical Text Analyst | 复权价格、公司行为、成交额 | `adj_close`、`turnover` 全空；公司行为未结构化 | 日/事件；1 日 | 否 | 长周期收益、跳空、回撤和成交分析可能失真 | P0 |
| Technical Text Analyst | 波动率、量能、动量、均线、回撤 | 当前仅 close、SMA20/60、20 日收益、trend label | 日；1 日 | 基础价格真实，覆盖不全 | Technical section 降级；没有波动、量价和回撤证据 | P0 |
| Technical Text Analyst | 指数/行业相对表现、宽度、波动 Regime | 不存在；无表/Provider | 日；1 日 | 否 | 无法判断个股走势来自 alpha、行业还是市场 beta | P1 |
| Sentiment Analyst | 专业财经媒体文本、发布时间、实体匹配、来源质量 | 不存在；专业新闻 Adapter 为空边界 | 小时/日；最长 4h | 否 | 真实运行只有 filing，Sentiment 降级，不能代表投资者情绪 | P1 |
| Sentiment Analyst | 允许范围内的 X 定向帖子、关注量、样本量和语言 | 不存在；X Adapter 为空边界 | 小时；最长 2h | 否 | 无法衡量注意力和社交情绪；必须明确渠道缺失 | P2 |
| Sentiment Analyst | 分析师/媒体倾向、覆盖量与可靠性 | 不存在 | 日；1 日 | 否 | 无法区分单一来源叙述与跨来源共识 | P1/P2 |
| News Event Analyst | SEC filing、earnings、M&A、管理层变更、诉讼、监管、制裁、产品事件 | 仅 1 份 SEC filing；`corporate_events` 为空 | 事件驱动；1–4h | filing 真实，其余缺失 | News section 实际是 filing 摘要，无法覆盖报告窗口内的独立事件 | P0 |
| News Event Analyst | 地缘暴露和事件关联 | filing 中可能出现文本，未结构化；无独立来源 | 事件驱动；4h | 部分 | 无法区分公司披露风险与已发生外部事件 | P1 |
| Research Manager | 四 Analyst 输出、覆盖/冲突/缺失清单、宏观与市场上下文 | 四输出接口存在；本次仅 2/4 Analyst 成功；无宏观/市场/历史 Memory | 每次报告；继承底层 SLA | 部分真实 | 汇总基于单一 filing，重复内容多，结论与证据一致性仅 0.3 | P0 |
| Bull Manager | 建设性证据、成立条件、反证、估值/行业/宏观 | Analyst 输出存在；估值、行业、宏观缺失 | 每次报告；继承底层 SLA | 部分真实 | Bull case 条件化严重，无法判断上行是否已定价 | P0/P1 |
| Bear Manager | 负面证据、触发条件、invalidators、事件/波动/宏观 | Analyst 输出存在；技术/情绪/宏观缺失 | 每次报告；继承底层 SLA | 部分真实 | 正面事实被放入 Risk Warnings，Bear/Bull balance 得分 0.2 | P0 |
| Risk Manager | 已确认/情景风险、流动性、监管、事件、宏观、冲突和时效 | 主要来自同一 SEC filing | 每次报告；继承底层 SLA | 部分真实 | 风险识别尚可但缺少价格、宏观、行业及历史类比，得分 0.7 | P1 |

## B. Existing Data Coverage Matrix

| 能力域 | 当前真实覆盖 | Provider | 数据库/Memory | 频率/窗口 | 结论 |
|---|---|---|---|---|---|
| 标的身份 | US:AAPL instrument | SEC/内部映射 | `instruments` 1 行 | 运行时 | 可用 |
| SEC filing | 1 份 2026-07-31 10-Q，含 URL、checksum 和 accession locator | SEC EDGAR | `text_documents` 1、`document_chunks` 9 | 单次快照 | 可用但单一 |
| EOD OHLCV | 2026-05-08 至 2026-08-07 共 63 根，含 VWAP | Alpaca/IEX | `eod_bars` 63 | 日频 | 原始可用 |
| 调整价/成交额 | 全部为空 | Alpaca 当前归一化结果 | `eod_bars` | 日频 | 不可用 |
| 财务结构化数据 | 0 行 | 无完成链路 | `fundamentals` | 季/年 | 缺失 |
| 宏观 | 0 行 | FRED Adapter 尚为空边界 | `macro_series` | 多频率 | 缺失 |
| 公司事件 | 0 行 | 仅 filing 文档，无事件提取 | `corporate_events` | 事件驱动 | 缺失 |
| 专业新闻/情绪 | 0 | 无已启用真实 Adapter | 无专用结构化覆盖 | 小时/日 | 缺失 |
| 技术特征 | close、SMA20/60、20 日收益、趋势 | 确定性 operator + Alpaca | Agent `structured_features` JSON | 每次报告 | 有值但无一等引用 |
| Fundamental 特征 | 所有第一版指标为 null | operator 无输入 | Agent `structured_features` JSON | 每次报告 | 缺失 |
| Memory | 运行前 0；运行后 1 条 L3 report trace | 内部 | `memory_items` 1 | 每份报告 | 不能服务本次推理 |
| Report citations | 2 个唯一 SEC chunk，75 条陈述引用 | SEC | report JSON/sections | 每份报告 | 可追溯但来源高度集中 |

## C. Missing Data Matrix

| 缺失数据 | 显式/隐式 | 直接影响 | 优先级 |
|---|---|---|---|
| 结构化三表及多期历史 | 报告未逐字段完整披露，属于隐式核心缺口 | Fundamental、估值、趋势和 Risk 缺乏确定性基础 | P0 |
| 价格特征的 Evidence/SourceReference | 隐式；bar 已入库但报告无引用 | Technical 因 numeric grounding 失败并整节降级 | P0 |
| 复权价、公司行为、turnover | 隐式 | 收益、回撤和量价分析可能偏差 | P0 |
| 真实情绪样本及覆盖元数据 | 显式：Sentiment unavailable | 情绪整节降级，Manager 缺少市场注意力 | P1 |
| 独立新闻和结构化事件 | 隐式；News 看似成功但只读 filing | 事件覆盖被高估，重大事件可能漏报 | P0 |
| 宏观与 Regime Memory | 显式：无 L1/L4 证据 | Macro section 为空，Risk 缺少外生环境 | P1 |
| 指数、行业、宽度和相对强弱 | 隐式 | 无法形成市场/行业归因 | P1 |
| 估值、股本与标准化 EPS | 隐式 | Bull/Bear 无定价锚，机构可用性低 | P0 |
| 发行人历史事件、既往 thesis/risk/report | 隐式 | 无法比较历史承诺、风险演化和观点变化 | P1 |
| 一致预期与分析师修订 | 隐式 | 无法评估预期差；无合法来源前必须披露 | P2 |
| 数据可用性/新鲜度统一 manifest | 隐式 | null、失败、过期和不适用无法可靠区分 | P0 |
| 来源可靠性、授权和留存元数据 | 隐式 | Sentiment/News 即使接入也无法审计样本质量 | P1 |

## D. Provider Gap Matrix

| 能力 | 当前 Provider 状态 | 最小候选路径 | 合规/架构约束 | 优先级 |
|---|---|---|---|---|
| US filing 文本 | SEC EDGAR 已真实可用 | 保留现有 Adapter | User-Agent、速率限制、稳定 locator | 已有 |
| US 结构化财务 | 未完成 | 同一 SEC 官方 XBRL/company facts 能力 | 不写死 issuer；保留 taxonomy、period、unit、filing lineage | P0 |
| US EOD price | Alpaca 已真实可用 | 扩展现有正规化与 Evidence 包装 | 不建立平行价格链路；校验 feed、日历和窗口 | P0 |
| 调整价/公司行为 | 当前缺失 | 先验证现有 Alpaca 合同能力，不能满足再决策 | 不自行猜复权因子 | P0 |
| 指数/行业市场上下文 | 缺失 | 先用获准行情 Provider 的明确 benchmark/sector 标的；市场宽度另行确认 | ETF 代理必须标记为 proxy，不冒充行业全样本 | P1 |
| US 宏观 | FRED Adapter 为空边界 | FRED 与相应官方发布源 | 保留 vintage/realtime_start/realtime_end，防止前视 | P1 |
| 事件 | filing 有原文，无结构化事件 | SEC filing/event normalization；其他官方源按事件类型补充 | confirmed event 与 scenario 分离 | P0/P1 |
| 专业财经新闻 | LSEG/Bloomberg 仅边界 | 完成授权后接入一个已许可来源 | 禁止无授权抓取和长期留存 | P1 |
| X 定向帖子 | 仅边界 | 获得 API/留存许可后接入 | 样本偏差、删除与引用政策必须显式 | P2 |
| 分析师一致预期 | 无来源 | 仅接受有授权、可追溯的商业来源 | 缺失时披露，不从媒体文本拼造 | P2 |
| CN/HK | MASTER_SPEC 有 Wind/SSE/CNINFO/HKEX 路径，当前未完成 | US 契约稳定后按市场接入 | 不以固定 Fake 样本宣称 live 覆盖 | P1/P2 |

## E. Top-10 Phase 3 Data Gaps

1. 结构化数值没有统一 Evidence lineage，真实价格存在却不能被 Agent 安全引用。
2. SEC 财务报表没有进入 `fundamentals`，所有核心 Fundamental 指标为空。
3. 缺少估值输入（标准化 EPS、股本、市值、P/E、P/B）。
4. 缺少复权、公司行为、波动率、回撤、成交额和完整量价技术数据。
5. 缺少 benchmark、sector、breadth、relative strength 和 volatility context。
6. 缺少 rates、inflation、employment、PMI、GDP、liquidity 与央行时间点数据。
7. News/Event 只有单一 filing，缺少 earnings、M&A、管理层、诉讼、监管等事件覆盖。
8. 缺少可合法保存的专业媒体、分析师/媒体情绪、关注量及来源可靠性。
9. L0/L1/L2/L4 和历史 L3 Memory 在运行前为空，无法做历史类比或观点演化。
10. 缺少可授权的一致预期与 earnings revision；在接入前必须作为已知缺失披露。

## F. 推荐 Provider 接入顺序

1. 不新增 Provider：先让现有 Alpaca bar 和确定性特征生成可引用 Evidence，并建立
   `DataAvailabilityManifest`。
2. 扩展现有 SEC 官方链路，接入结构化 XBRL 财务、多期历史和 filing lineage。
3. 完成现有 Alpaca 链路的复权/公司行为能力验证，并加入 benchmark/sector 的
   明确代理数据；代理身份必须披露。
4. 完成 FRED/官方宏观发布链路，保留 vintage，先覆盖利率、通胀、就业和 GDP。
5. 从 SEC 与官方来源生成结构化 earnings、管理层、诉讼和监管事件。
6. 授权明确后接入一个专业财经新闻 Provider，再做跨来源事件去重。
7. 授权和保留政策明确后接入 X/其他情绪渠道。
8. 最后接入商业一致预期；US 输入契约稳定后再扩展 CN/HK。

## G. 属于 Data 的问题

- Provider 获取、asset identifier 映射、标准化、单位/币种和 point-in-time 时间语义。
- 三表、复权行情、公司行为、宏观、事件、市场/行业与新闻/情绪覆盖。
- 确定性指标计算及其原始字段、公式、窗口和版本 lineage。
- 稳定 Evidence ID、原始 locator、hash、freshness 和 availability 状态。
- 不负责修改 Agent Prompt 或放宽 numeric grounding。

## H. 属于 Memory 的问题

- L0 实时/市场快照、L1 宏观事件、L2 发行人事件、L3 thesis/risk/report trace、
  L4 regime archive 的 point-in-time 写入与检索。
- 运行前没有历史 Memory，当前唯一 L3 是报告完成后的回写，不能反向作为本次证据。
- Memory 必须保留 source reference、effective time、snapshot/version 和检索原因。
- 空结果必须作为显式 coverage 状态，不得由 LLM 补造历史。

## I. 属于 Agent 的问题

- 四个 Analyst 共用通用 JSON context，缺少角色化 required/optional/forbidden 契约。
- Fundamental 在结构化指标全空时仍可基于 filing 工作，但必须明确其能力边界。
- Sentiment 不得把单一 filing 当作市场情绪样本。
- Manager 必须保留失败角色、冲突和缺失，不能用流畅叙述掩盖覆盖不足。
- Bear 的 invalidator/condition 语义不稳定，出现正面事实被表达成风险的情况。
- 这些问题应在数据契约稳定后修复，不能通过 Prompt 让模型猜缺失数据。

## J. 属于 LLM Gateway 的问题

- 保持 Provider 可替换、结构化 Schema、调用元数据、错误映射和真实/Fake 隔离。
- 记录 provider/model/inference 参数、Prompt version、request fingerprint 和延迟。
- 本次 Qwen 调用成功；Technical/Sentiment 失败来自输出数值无证据，而非 Gateway 故障。
- Gateway 不负责补数据、计算指标、决定数据可靠性或弱化验证规则。

## K. 属于 Report Pipeline 的问题

- 将结构化 Evidence 与文档/Memory 一样纳入 citation index 和来源追踪。
- 当前 75 条引用陈述仅落到两个 SEC chunk，价格证据未出现在报告来源中。
- Executive 与 Final Synthesis、各 Manager section 大量重复同一事实和风险。
- 107 条不确定性陈述大量来自跨章节重复的相同缺失项，需要集中披露并保留章节引用。
- `bear.invalidators` 被统一映射为 `risk_warnings`，导致正面反证显示为风险警告。
- “Evidence source reviewed”不应代替 executive fact；事实、推断、条件、反证和风险
  应保持语义标签。
- Report 不得重新抓数据或为补齐章节自行调用 LLM/Provider。

## 真实报告专项审计

### 明确 missing data 与被降级 section

- Technical Text：整节降级，明确记录 Agent output unavailable。
- Sentiment：整节降级，明确记录 Agent output unavailable。
- Macro Context：仅有“无可归因 L1/L4 Macro Memory”的不确定性。
- Executive/Final：明确列出 Technical 与 Sentiment unavailable。

### 未标 missing 但证据不足

- Fundamental：结构化三表与估值全空，成功输出完全依赖 10-Q 文本。
- News/Event：没有独立新闻或 `corporate_events`，成功输出只是 filing 摘要。
- Bull/Bear/Risk：没有价格、估值、市场、行业、宏观、情绪或历史 Memory 证据。
- Citation coverage/traceability 虽为 1.0，只说明引用格式和内部映射完整，不代表来源多样。

### 重复与纯 narrative

- 销售、经营利润、库存、回购、采购义务和供应限制在多个章节反复出现。
- “strong operational efficiency”“robust fundamental expansion”“channel stuffing or
  demand deterioration”等是模型解释；原文数字可引用，但解释没有行业、历史或其他
  结构化证据交叉验证。
- Judge 给出 factual correctness `0.6302`、evidence consistency `0.3`、Bull/Bear
  balance `0.2` 和 readability `0.6`，核心原因是语义错误、内部矛盾和重复。

### Numeric grounding failure

- 保存的 Evaluation 记录 41 个 numeric claims、40 个 grounded、1 个 ungrounded；
  被标记内容为 Bear Case 中的 `2028`。
- 使用当前修复后的 deterministic scanner 对同一报告复核为 41/41，确认原记录是
  标点分词误报，不是新的真实未落证数字。
- 真正的数据问题是 Alpaca 派生数值不能进入 citation index，导致 Technical Agent
  在报告组装前已失败；不能只看最终报告的 41/41。

## 数据结构（建议，名称待接口评审确认）

- `EvidenceItem`
  - stable evidence ID
  - provider/source ID 与原始 locator
  - observed/published/effective/as-of 时间
  - asset/series/event identity
  - value/text、unit、currency
  - transformation、formula/window/version、parent evidence IDs
  - content hash 与授权/可靠性元数据
- `DataAvailabilityManifest`
  - requested field/capability
  - status：present/missing/stale/partial/not_applicable
  - latest effective time、freshness SLA、reason、provider coverage
- `ResearchEvidenceBundle`
  - fundamental、technical、sentiment、event、macro、market/industry、Memory
  - evidence index 与 dataset/snapshot identity
- `ManagerResearchContext`
  - validated Analyst outputs、agent coverage、conflicts、missing data、global context
  - 不包含 Provider、Repository 或 SDK client

MASTER_SPEC 未明确这些类的最终字段布局和迁移兼容期，均标记为“待确认”；实现时应
优先复用现有领域模型，避免建立平行模型体系。

## 核心接口（待确认）

```text
EvidenceBuilder.build(normalized_records, transformations) -> EvidenceItem[]
AvailabilityService.assess(request, evidence, as_of) -> DataAvailabilityManifest
ResearchEvidenceService.build(asset_id, window, as_of) -> ResearchEvidenceBundle
AgentContextProjector.for_role(bundle, role) -> RoleSpecificAgentContext
ManagerContextBuilder.build(agent_results, bundle) -> ManagerResearchContext
```

## 验收标准

- 每个 Agent 输入均包含 data availability、as-of、窗口和来源覆盖。
- 每个结构化数值可以回溯到数据库记录和 Provider 原始 locator。
- Technical 可使用真实 Alpaca 数据通过 numeric grounding，不放宽校验。
- Fundamental 的财务指标来自结构化官方数据和确定性计算，不由 LLM 计算。
- 空表、Provider 部分失败和过期数据在报告中明确披露。
- Manager 不直接访问 Provider、DuckDB 或 FAISS，不新增事实。
- 同一事实在报告来源清单中去重，章节语义不混淆条件、反证与风险。
- 默认测试完全离线；live 测试与默认 pytest 隔离。
- 固定 snapshot 可复现 Agent 输入 fingerprint 和数据覆盖结果。
- US 第一版完成前不声称 CN/HK、新闻、情绪或一致预期已覆盖。

## 测试要求

- Evidence lineage：原始值、派生值、多父证据、单位/币种和 hash 测试。
- Availability：missing/stale/partial/not_applicable 与边界时间测试。
- Repository：结构化财务、行情、宏观、事件的重复初始化与临时数据库测试。
- Role projection：每个 Agent 只能看到允许字段；Manager 无 Provider/Repository。
- Numeric grounding：真实价格/财务证据可引用，无来源数字仍被拒绝。
- Point-in-time：宏观 vintage、filing 发布时间和 Memory snapshot 无前视。
- Degraded path：Provider 部分失败、空 Memory、无 sentiment/news 的明确披露。
- Report：引用去重、结构化引用追踪、Bear invalidator 语义和跨章节重复检查。
- 固定 Benchmark：离线确定性覆盖；live baseline 单独执行且禁止 Fake fallback。
- 全量 `pytest`、Ruff、mypy、Black 和 `git diff --check`。

## 允许修改的目录

- `docs/tasks/phase3_data_completeness.md`
- `docs/coordination/`（每个窗口只修改自己的文件）
- `src/schemas/`（共享接口须由 Main Agent 审批）
- `src/services/data_ingestion.py`
- `src/services/data_normalization.py`
- `src/operators/`
- `src/adapters/`
- `src/repositories/`
- `src/memory/`
- `src/agents/`（仅经 Main 集成批准的数据契约适配）
- `src/reports/`（仅经 Main 集成批准的证据/语义适配）
- 对应 `tests/`、固定 `benchmarks/` 数据与必要文档
- `docs/MODULE_STATUS.md`、`docs/DECISIONS.md`（仅 Main Agent）

## 禁止修改的目录

- 交易、订单、持仓、组合优化、回测、策略池相关目录或代码
- Factor、Regime、MoE、强化学习和模型训练实现
- 现有 Evaluation 评分规则（不得为提高当前报告分数而修改）
- 现有 Agent Prompt（本数据完整性任务阶段不得为当前样例调参）
- `data/live_acceptance/20260808T082315Z/` 原始审计产物
- 其他窗口拥有的 `docs/coordination/*.md`
- 真实 credential、用户私有 shell 文件或任何 secret 值

## 依赖的前置任务

- `data_ingestion.md`
- `domain_models.md`
- `memory.md`
- `agents.md`
- `report_pipeline.md`
- `report_evaluation.md`
- `research_benchmark.md`
- `live_agent_benchmark.md`

## 完成后需要更新的文档

- `docs/MODULE_STATUS.md`（Main Agent）
- `docs/DECISIONS.md`（仅产生正式架构决策时，由 Main Agent 更新）
- `docs/schema.md`
- `docs/operations.md`
- `benchmarks/README.md`
- 对应窗口自己的 `docs/coordination/*.md`

