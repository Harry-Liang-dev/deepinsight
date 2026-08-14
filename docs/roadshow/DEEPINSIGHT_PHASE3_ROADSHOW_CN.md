# DeepInsight Phase 3 技术路演演讲稿

建议时长：12–15 分钟  
演讲身份：CEO / Founder / CTO  
版本：Research Completeness v1

## 开场：聪明，还远远不够

各位好。

今天，金融市场从来不缺数据。我们有财报、价格、宏观指标、新闻、社交情绪，
也有越来越强的通用大模型。但投研工作的核心矛盾并没有因此消失：数据越来越
丰富，研究流程却依然高度碎片化。

传统研究通常从数据收集开始，经过分析师建模、团队讨论、多空辩论、风险复核，
最后形成报告。这个流程专业，但成本高、延迟长，而且很多关键判断散落在表格、
聊天记录和个人经验里。几个月后，我们往往很难回答三个简单的问题：当时究竟
看到了什么？结论依据是什么？如果站在当时那个时间点，这个判断是否仍然成立？

大模型给了我们新的可能性，但在金融行业，“聪明”还远远不够。一个语言流畅的
模型，仍然可能引用错误、数字不一致、混淆时间，甚至把不确定性写成确定事实。
金融研究必须做到四件事：有依据、可审计、时间安全、可以重复。

这就是 DeepInsight 的起点。

## 问题：两种能力长期彼此割裂

传统量化系统擅长结构化数据、确定性计算和严格回测，但对新闻、管理层表述、
风险叙事和跨来源语义理解并不天然擅长。

通用金融大模型擅长语言理解和归纳，却经常缺少稳定的数据契约、事实来源链和
时间边界。很多所谓多 Agent 系统，最后只是几个模型轮流聊天：它们会形成观点，
但很难证明观点来自哪里，也很难保证每个数字都真实存在于输入中。

这不是模型参数量的问题，而是系统架构的问题。

我们需要把结构化金融工程与模型推理组织在同一条可信链路上。我们需要的不是
一个“会炒股的 Chatbot”，而是一套 AI-native Investment Research
Infrastructure——AI 原生的投资研究基础设施。

## 产品：从碎片数据到可审计研究

DeepInsight 当前连接五类真实研究来源。

SEC EDGAR 提供权威的公司申报、XBRL 财务事实和公司事件；Financial Modeling
Prep 提供标准化的基本面、TTM 与估值指标；Alpaca 提供股票与基准行情，以及
金融新闻；FRED 提供带时间语义的宏观数据；Stocktwits 提供社区情绪和关注度。

这些数据不会直接丢给大模型。它们先经过受控接入、标准化和持久化，形成统一的
`ResearchDataBundle`。价格收益、均线、RSI、波动率、估值比率等可确定计算的
内容，优先由 Python 算子完成。模型不负责猜财务数字，也不负责在 Prompt 里
临时做金融计算。

在这之上，是 DeepInsight 的八 Agent 研究组织。

四个专业分析师分别负责基本面、技术面、情绪和新闻事件。Research Manager
负责整合四类经过验证的研究结论；Bull Manager 和 Bear Manager 分别构建看多
与看空论证；Risk Manager 最后检查宏观、市场、事件和论点风险。

后四个角色不会重新联网，也不会绕过上游自己发明事实。它们消费的是已经验证的
Claim。最终，我们得到一份十章节的 Markdown 和 JSON 研究报告，同时保留每条
结论的来源与验证状态。

## 技术护城河一：Evidence Grounding

DeepInsight 最重要的设计，不是 Agent 数量，而是 Evidence Grounding。

系统的事实链是：原始数据进入 Canonical Data，形成 Evidence；专业 Analyst
只能基于这些 Evidence 产生事实或分析 Claim；Manager 再引用上游 Claim；最终
Report 只展示被接受的内容。

每个 accepted factual claim 都可以一路追溯回原始来源。每个数字必须在 Evidence
中精确出现，或者来自版本化的确定性算子。不存在的 Evidence ID、无法落证的
数字、违反规则的内容都会进入 quarantine，不会流入下游。

这意味着系统宁愿删掉一句无法证明的话，也不会为了让报告显得完整而补造数字。
对金融系统而言，这种克制比语言上的自信更重要。

## 技术护城河二：Canonical Financial Data

同一个金融概念，在不同 Provider 中可能使用不同字段、单位、报告期和时间戳。
如果把这些差异交给模型临场理解，结果就无法稳定复现。

DeepInsight 先把多来源数据转换成统一金融语言。以基本面为例，标准化增长、利润
率、ROE、ROA、流动性、杠杆和估值指标进入相同的 typed contract；SEC 继续作为
申报与原始事实权威来源，标准化 Provider 负责常见终端指标。两个来源有差异时，
系统不会简单平均，而是记录主值、副值和数据质量状态。

这样，大模型看到的不是五套互相冲突的 API JSON，而是一份带来源、期间、单位、
时间与质量标记的研究数据包。

## 技术护城河三：Point-in-Time Safety

金融研究不仅要问“这个数据是真的吗”，还要问“在当时能看到吗”。

DeepInsight 的每次任务都有明确的 `as_of` 截止时间。数据观测、发布、申报接收和
Memory 检索都要遵守这个边界。晚于截止时间的信息不能进入当次研究。

这项能力现在看起来像工程细节，但它决定了未来的 Research Dataset、Factor、
Regime 和 Backtesting 是否可信。没有 point-in-time safety，历史回看很容易把
未来信息偷偷带回过去，任何漂亮的评估结果都可能失去意义。

所以，我们没有把防泄漏留到以后补，而是从研究系统底层开始建立。

## 技术护城河四：Structured Agent Organization

DeepInsight 不是自由聊天式的 Agent swarm，而是一套职责明确的 Research
Organization。

每个 Agent 有自己的输入范围、输出 Schema、最低有效 Claim 数和降级语义。
Analyst 负责新事实 grounding；Manager 负责基于上游结论做综合；Bull 和 Bear
明确形成对立论证；Risk 负责复核风险。Provider SDK、数据库和向量索引不会泄漏
到 Agent 层。

这种组织方式让模型可以替换、Prompt 可以版本化、运行可以审计，也让失败变得
可见。一个非法 Claim 可以被隔离，而不必让整个研究任务静默地产生错误内容。

## 真实验证：不是演示数据，不是收益率

Phase 3 的最终验收使用了真实 SEC、真实 FMP、真实 Alpaca、真实 FRED、真实
Stocktwits 和真实 Qwen。标的是 US:AAPL。

工程侧，默认离线测试是 447 项通过，5 项 live 测试默认隔离。研究组织侧，八个
Agent 全部完成。Agent 产生 54 条 accepted claims，2 条 rejected claims 被正确
隔离。报告中的 56 个唯一引用全部可以追溯，Citation Coverage 和 Citation
Traceability 都是 1.00，Numeric Grounding 是 1.00，Factual Correctness 是
0.97，最终综合 Evaluation 是 0.9675。

必须说明：这些是一次真实 US:AAPL 报告的研究质量指标，不是收益率，不是 Alpha，
也不是策略表现。我们现在证明的是系统能够稳定地产生可审计研究，而不是声称它
已经能够战胜市场。

## Demo：AAPL 的一条研究链

以这次 AAPL 报告为例。

基本面模块把增长、利润率、资本回报、杠杆、流动性和估值放到同一张标准化研究
底图上；技术模块计算趋势、动量、波动率、成交量、回撤以及相对 SPY、QQQ、XLK
的强弱；宏观模块提供利率、通胀、就业、增长与金融压力；情绪模块描述社区多空
分布和关注变化；新闻与事件模块把 SEC 披露和金融新闻带入同一证据链。

接下来，Bull Manager 不是简单说“看多”，而是指出哪些已验证事实支持上行逻辑；
Bear Manager 同样构建反面论证；Risk Manager 再检查供应链、监管、市场相对强弱
和情绪背离。最终报告不仅有结论，也有不确定性、失效条件和数据限制。

变化的本质，是把“碎片数据”变成“可审计投资研究”。

## 为什么是现在

今天有四个条件第一次同时成熟。

第一，大模型已经能够稳定处理结构化推理与长上下文；第二，Agent 系统让复杂任务
可以按照组织职责拆分；第三，金融 API 与现代数据基础设施让异构数据能够低成本
进入统一管道；第四，推理成本下降，使多角色、可重复的研究流程具备工程可行性。

但这些条件不会自动产生金融可信度。真正的机会，在于把它们与数据标准化、时间
控制、Evidence 和评估系统结合起来。DeepInsight 正在做的，就是这层连接。

## 差异：连接语义研究与量化结构

传统 Quant 强在结构和计算，语义研究通常较弱；通用 Financial LLM 强在语言，
但 grounding 和时间控制较弱；许多 Agent Trading Framework 强在多角色叙事，
目标往往直接指向决策或交易。

DeepInsight 选择的是另一条路径：结构化金融数据，加上 evidence-grounded AI
research，再加上 point-in-time architecture，最终搭起通往量化研究的桥。

我们不贬低任何一类系统。它们解决的是不同问题。DeepInsight 的判断是：在金融
领域，研究可信度必须先于自动决策，事实基础设施必须先于策略复杂度。

## 下一阶段：Structured Financial Intelligence

Phase 3 的产品输出是一份 Research Report。下一阶段，我们会把这份研究进一步
结构化为 `ResearchState`：不是重新解析报告文字，而是直接继承已经验证的 Claim
与来源。

演进路径是：

```text
Research Report
        ↓
ResearchState
        ↓
Point-in-Time Dataset
        ↓
Factor Intelligence
        ↓
Market Regime
        ↓
Adaptive Quant Research
```

更远期的研究方向包括 Factor Mining、Strategy Optimization、全天候 MoE Router、
Backtesting，以及面向投研和端到端量化的 SFT、DPO 与 Offline RL 两阶段后训练。
在不同阶段，可以研究冻结预训练模型不同层与任务头参数的训练方法。

这些仍然是未来路线，不是今天已经完成的功能。交易也不是第一步。我们先建立
可信研究基础设施，再讨论如何让系统持续学习和形成策略。

## 商业愿景

DeepInsight 不希望只成为单个策略或单份报告工具。长期目标是成为 AI-native
asset management research operating system：可以支持内部资管研究、研究平台、
机构投研基础设施和策略研发。

当前客户、收入、AUM、融资与团队规模信息：`[待补充]`。

我们不会用尚未发生的商业数字包装技术进展。现在真正完成的是技术地基，以及一条
从真实数据到可审计报告的闭环。

## 结尾：真正可持续的优势

未来的优势，不只是模型预测得更准。

更重要的是，谁能建立更快的数据闭环、更深的研究记忆、更可靠的事实链，以及更
持续的学习系统。

DeepInsight Phase 3 完成的是第一块真正的地基：Research Completeness v1。

我们已经证明，多源真实数据可以进入统一研究语言，八个 Agent 可以在严格 Evidence
约束下协作，一份报告可以从结论一路追溯到来源。

Phase 3 到这里结束。

下一阶段，是 Structured Financial Intelligence。

---

# 技术附录

## A. 当前架构

```text
Providers
  SEC / FMP / Alpaca / FRED / Stocktwits
        ↓
Controlled Ingestion → Normalization → DuckDB
        ↓
ResearchDataBundle → Evidence → Point-in-Time Memory
        ↓
4 Analysts → Research Manager → Bull/Bear → Risk
        ↓
10-section Markdown/JSON Report
        ↓
Deterministic Checks + LLM Judge
```

LLM、Agent、Report、Data 和 Memory 通过 Pydantic v2 contract 与窄 Protocol
连接。Agent 不直接依赖 Provider SDK、DuckDB 或 FAISS。

## B. Provider Matrix

| Provider | 数据能力 | Phase 3 角色 |
|---|---|---|
| SEC EDGAR | Filing、XBRL、公司事件 | 权威披露来源 |
| FMP | 标准化基本面、TTM、估值 | 标准指标主来源 |
| Alpaca | OHLCV、基准、新闻 | 行情与新闻主来源 |
| FRED / ALFRED | 宏观与 vintage | 点时宏观来源 |
| Stocktwits MCP | 社区情绪与关注 | 情绪 Evidence |
| Qwen | 结构化推理与 Judge | 当前 production LLM |

## C. Eight Agents

| 层级 | Agent | 主要职责 |
|---|---|---|
| Analyst | Fundamental | 增长、盈利、资产负债、估值 |
| Analyst | Technical | 趋势、动量、波动、成交、相对强弱 |
| Analyst | Sentiment | 社区情绪、关注与分歧 |
| Analyst | News/Event | 申报、公司事件与新闻 |
| Synthesis | Research Manager | 综合四类 Analyst Claim |
| Debate | Bull Manager | 上行论点与失效条件 |
| Debate | Bear Manager | 下行论点与失效条件 |
| Risk | Risk Manager | 宏观、事件、市场与论点风险 |

## D. Evaluation 方法

正式 Evaluation 包含 12 个维度：结构完整性、事实正确性、引用覆盖率、引用可追溯
性、结论与证据一致性、多空平衡、风险识别、不确定性表达、时间有效性、交易指令
合规、数据缺失披露和可读性。

结构、引用、数值、时间和合规优先使用确定性代码检查；语义质量通过现有
`LLMGateway` 调用真实 Judge。每个评分包含理由和 Evidence 定位，规则版本为
`report_quality_v2`。

## E. Phase 1–3 里程碑

| Phase | 里程碑 | 状态 |
|---|---|---|
| Phase 1 | Research Operating System Foundation | 完成 |
| Phase 2 | Evaluation、Benchmark、真实数据验证 | 完成 |
| Phase 3 | Research Completeness v1 | 完成并冻结 |

## F. Phase 4 Roadmap

- `ResearchStateSnapshot`
- Point-in-Time Research Dataset
- Factor Infrastructure
- Regime Representation

Phase 4 不等于自动交易。所有未来特征必须保留 `source_claim_ids`，未来 Factor
必须追溯到 research feature，避免重新从报告 prose 中抽取事实。
