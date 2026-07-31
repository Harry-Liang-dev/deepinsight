# DeepInsight

DeepInsight 是面向多市场的 AI 投资研究平台。Phase One 的唯一产品输出是带有
来源追踪的标准化研究报告。

当前版本不包含交易、订单执行、组合优化、回测、策略生成、强化学习或模型训练。

## 当前最小闭环

已打通的单资产离线流程：

```text
FastAPI 研究请求
→ Fake Provider 固定数据
→ 标准化与 DuckDB 持久化
→ 文档分块与 Fake Embedding/FAISS
→ Memory 检索
→ 四个 Analyst Agent
→ Research/Bull/Bear/Risk Manager
→ 十章节 Markdown/JSON 报告
→ DuckDB、L3 Memory 和 API 查询
```

离线入口使用固定测试数据、`FakeLLMProvider` 和
`FakeEmbeddingService`，不读取或调用真实 OpenAI API。

## 目录

- `apps/`：API 及后续 Worker、Scheduler、Web 应用入口
- `config/`：Provider 元数据和版本化 Agent Prompt
- `data/`：本地 DuckDB、FAISS、原文、快照和备份目录
- `docs/`：系统规格、任务规格和运维文档
- `infra/`：Docker、Compose 和预留基础设施目录
- `scripts/`：数据库初始化及维护脚本
- `src/`：领域模型、Repository、Service、Agent 和编排代码
- `tests/`：单元、集成和固定测试数据

## 安装

系统要求 Ubuntu、Conda 和 Python 3.12。Conda 只提供解释器，`uv` 根据
`pyproject.toml` 安装依赖；不要创建项目内 `.venv`。

```bash
conda env create --file environment.yml
conda activate deepinsight
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

已有环境可使用：

```bash
conda env update --name deepinsight --file environment.yml
conda activate deepinsight
uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"
```

## 启动

启动安全默认 API：

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn apps.api.main:app \
  --host 127.0.0.1 \
  --port 8000
```

默认入口提供健康检查和完整 OpenAPI，但不会在导入时擅自连接数据库、FAISS
或外部 Provider。未完成部署装配的研究和 Memory 操作会明确返回不可用状态。

健康检查：

```bash
curl --fail http://127.0.0.1:8000/health
```

## 离线端到端演示

启动不需要任何密钥的临时离线 API：

```bash
"$CONDA_PREFIX/bin/python" -m uvicorn apps.api.offline_main:app \
  --host 127.0.0.1 \
  --port 8001
```

提交固定的单资产研究请求：

```bash
curl --fail \
  -H "Content-Type: application/json" \
  -d '{
    "report_date": "2026-07-31",
    "market_scope": "US",
    "report_type": "single_asset",
    "asset_ids": ["US:AAPL"],
    "language": "en",
    "include_sections": [
      "executive_view",
      "macro_context",
      "fundamentals",
      "technical_text",
      "sentiment",
      "news_events",
      "bull_case",
      "bear_case",
      "risk_review",
      "final_synthesis"
    ],
    "force_refresh": false
  }' \
  http://127.0.0.1:8001/v1/reports/generate
```

第一次演示请求使用 `job_demo_1` 和 `rep_demo_1`：

```bash
curl --fail http://127.0.0.1:8001/v1/reports/jobs/job_demo_1
curl --fail http://127.0.0.1:8001/v1/reports/rep_demo_1
```

离线入口使用进程生命周期内的临时目录，停止进程后自动清理；它仅用于演示和
集成验证，不是生产数据入口。

## 测试和静态检查

```bash
"$CONDA_PREFIX/bin/python" -m pytest
"$CONDA_PREFIX/bin/python" -m ruff check .
"$CONDA_PREFIX/bin/python" -m mypy
"$CONDA_PREFIX/bin/python" -m black --check .
```

只运行完整离线闭环：

```bash
"$CONDA_PREFIX/bin/python" -m pytest \
  tests/integration/test_research_workflow_e2e.py -q
```

也可以运行：

```bash
make check
```

默认 pytest 不访问真实网络、不需要商业 Provider 凭据，也不会消耗 OpenAI
额度。真实 OpenAI 冒烟尚未作为自动测试或默认入口启用。

## 当前运行边界

- 报告仅支持 `single_asset`。
- API 任务状态保存在单进程内，重启后不保留。
- Redis 消息协议、持久化 Job 表和多进程 DuckDB 写锁策略仍待确认。
- Worker、Scheduler、Web、Docker Compose、快照与恢复尚未完成。
- 商业及官方数据连接器仍为显式不可用的网络隔离边界。

详细说明见 [运维文档](docs/operations.md)、[API 文档](docs/api.md) 和
[模块状态](docs/MODULE_STATUS.md)。
