# DeepInsight Research Benchmark

`research_benchmark_v1` 是一个小规模、多市场、完全离线的固定投研报告质量数据集。
它不代表任何真实公司的当前状态，也不构成投资建议。

## 数据边界

- `synthetic`：为测试某个质量边界专门编写的合成文本。
- `public_excerpt`：允许保存的公开来源短摘录。
- `deidentified`：移除实体和敏感字段的固定样本。

当前 CN/HK Provider 尚未完成真实闭环，因此首版 CN/HK 案例均明确标记为
`synthetic`。案例中的规范化标的只用于市场和 Schema 验证，案例陈述不得解释为该
证券的真实事实。

每个案例独立保存来源定位、采集日期、发布日期、使用依据、预期事实、允许缺失项、
禁止结论和最低阈值。报告材料会确定性物化为现有十章节报告模型，但不会调用
Provider、Memory、Agent 或网络。

## 默认运行

```bash
python -m src.benchmark.cli \
  --benchmark-root benchmarks \
  --rules-root config/evaluation \
  --output benchmarks/results/default_v1.json
```

退出码为 `0` 表示全部案例通过，`1` 表示至少一个案例低于阈值。JSON 中的每个失败
都包含指标、实际值、阈值和理由。

默认运行使用 `FakeReportJudge` 以完成现有十二维评估结构，但默认通过门只依赖：

- 生命周期；
- 确定性总分和指定确定性检查；
- 预期事实覆盖；
- 禁止结论合规。

因此 Fake Judge 的固定语义分数不能单独使案例通过。

## Live 边界

Live Benchmark 必须由独立组合显式注入 `LLMReportJudge` 和现有 `LLMGateway`，
并选择 `BenchmarkRunMode.LIVE`。它可以启用案例中的 `live_dimension_minimums`，
必须写入不同结果文件，且不得进入默认 pytest。真实 Judge 失败时不允许回退到
Fake Judge。

## Live Agent Benchmark

`live_agent_benchmark_v1` 与上述离线语料职责完全分离。它读取
`benchmarks/live_agent/v1/snapshot.yaml`，先核验 detached SHA-256，再把同一
固定 US:AAPL SEC/Alpaca 快照投影为六个场景。运行时不会重新访问 SEC 或 Alpaca，
因此 baseline/candidate 的市场输入保持一致。

它只允许真实 OpenAI/Qwen Provider 和真实 `LLMReportJudge`，继续复用现有八
Agent、`ReportAssembler` 和 `ReportEvaluationService`。首版市场覆盖仅为 US；
CN/HK 没有被合成数据冒充为 live 输入。

显式运行：

```bash
source ~/.local/bin/load_deepinsight_keys.sh
env -u ALL_PROXY -u all_proxy \
  "$CONDA_PREFIX/bin/python" -m scripts.live_agent_benchmark
```

可用 `--model` 和 `--prompt-root` 选择 candidate。A/B 比较把 baseline 的
`summary.json` 传给 `--baseline`；比较器只输出差值，不宣称 Prompt 效果改善。
所有产物写入 Git 忽略的 `data/live_agent_benchmark/<run_id>/`。
