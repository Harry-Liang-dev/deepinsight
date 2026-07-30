# Foundation 任务规格

## 目标

建立可安装、可检查、可测试的 Python 3.12 工程基础，使后续模块能够在统一的工具链和目录约束下开发。该任务只建设工程基础，不实现任何投研业务逻辑。

## 范围

- 配置 `uv` 项目元数据和依赖分组。
- 配置 `black`、`ruff`、`mypy`、`pytest` 和 `pytest-asyncio`。
- 保证 `apps/`、`src/`、`tests/` 中的 Python Package 可被正确导入和发现。
- 定义统一的本地开发命令入口。
- 完善基础 `.gitignore`，避免提交密钥、DuckDB 文件、FAISS 索引、缓存和构建产物。
- 明确 Python 3.12 为唯一目标版本。
- 使用当前 Conda 环境提供 Python 解释器，不创建项目内 `.venv`。
- 保留 MASTER_SPEC 已定义的目录结构。

## 非目标

- 不实现配置加载逻辑。
- 不创建数据库表或 Repository。
- 不实现数据源适配器、Memory、LLM Gateway、Agent、报告或 API。
- 不配置 CI/CD 平台。
- 不引入 MASTER_SPEC 和 CODING_GUIDE 之外的框架或服务。

## 输入

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/CODING_GUIDE.md`
- 当前 Repository Scaffold

## 输出

- 可由 `uv` 管理的有效 Python 项目。
- 可执行的格式化、静态检查和测试命令。
- 可导入的 `apps`、`src` 和 `tests` 包。
- 不包含运行数据和密钥的 Git 忽略规则。
- 基础开发说明。

## 允许修改的目录

- 根目录下的 `pyproject.toml`
- 根目录下的 `Makefile`
- 根目录下的 `.gitignore`
- 根目录下的 `README.md`
- `apps/`，仅限包初始化所需内容
- `src/`，仅限包初始化所需内容
- `tests/`，仅限测试发现和基础配置所需内容
- `docs/`

## 禁止修改的目录

- `data/`
- `config/`
- `infra/`
- `src/adapters/` 中的业务实现
- `src/agents/`
- `src/memory/`
- `src/operators/`
- `src/orchestration/`
- `src/reports/`
- `src/repositories/` 中的业务实现
- `src/services/` 中的业务实现
- `src/phase2_reserved/`

## 核心接口

本任务不定义业务接口。

- 安装命令：`uv pip install --python "$CONDA_PREFIX/bin/python" -e ".[dev]"`
- 测试命令：`"$CONDA_PREFIX/bin/python" -m pytest`
- 静态检查命令：`"$CONDA_PREFIX/bin/python" -m ruff check .`
- 类型检查命令：`"$CONDA_PREFIX/bin/python" -m mypy`
- 格式检查命令：`"$CONDA_PREFIX/bin/python" -m black --check .`
- Makefile 目标：`install`、`test`、`lint`、`typecheck`、`format-check`、`check`

## 验收标准

- `pyproject.toml` 是有效配置，不再是空文件。
- 项目声明 Python 3.12。
- 开发依赖包含 CODING_GUIDE 指定的测试和格式工具。
- uv 可以将项目和开发依赖安装到当前 Conda Python。
- 项目根目录不会创建 `.venv`。
- `apps`、`src` 和 `tests` 可以被 Python 正确导入。
- Ruff、mypy、Black 和 pytest 能在无业务代码时正常启动。
- `.gitignore` 排除 `.env`、Python 缓存、测试缓存、构建产物、DuckDB 数据文件和 FAISS 运行索引。
- 未引入额外服务、数据库或 Web 框架。

## 测试要求

- 使用当前 Conda Python 执行 pytest。
- 执行 Ruff 检查。
- 执行 mypy 检查。
- 执行 Black 格式检查。
- 验证主要 Python 包的导入。
- 不得通过测试命令在仓库中留下未忽略的运行产物。

## 依赖的前置任务

- 无。

## 完成后需要更新的文档

- `README.md`
- `docs/MODULE_STATUS.md`
- `docs/operations.md`
- 如果改变既有工程结构或工具选择，更新 `docs/DECISIONS.md`
