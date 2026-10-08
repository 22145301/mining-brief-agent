# 00: 工程骨架

**What to build:** 一个陌生人 clone 下来，三条命令（装依赖 / 跑测试 / 跑 lint）都能跑通的空壳仓库。

这一刀不切任何用户可见行为——它是预置工作（prefactoring），目的是让后面每一张票都有落脚点：依赖锁定、分层、lint、CI、配置外置、日志，全部一次到位，后续票不必各自补。技能明确要求预置工作先行，因此它排在功能票之前。

**Blocked by:** None (can start immediately)

**Status:** done

**Category:** enhancement

- [x] `pyproject.toml` 声明全部依赖并锁定版本，提交 lock 文件
- [x] 可安装包建好五个子包：`contracts`（信封与共享数据结构）/ `datasources` / `servers` / `agent` / `config`，落实 ADR-0008 的单包布局
- [x] Ruff + Black + mypy 配置齐全且全绿
- [x] `pytest` 能跑，至少含一条真断言（不是空收集）
- [x] GitHub Actions 一条工作流跑 lint + 类型检查 + 测试
- [x] `.gitignore` 排除 `.env` / `.env.*` / `*.pem` / `*.key`；`.gitattributes` 到位
- [x] `.env.example` 列出全部环境变量**名**（含两个模式开关），不含任何真实密钥
- [x] CLI 入口存在，`--help` 有输出
- [x] 结构化日志可用，全仓库无裸 `print`（由 lint 规则挡住，不靠自觉）
- [x] README 骨架到位，写清安装 / 运行 / 测试三条命令（完整版见 10）

## Comments

- **2026-10-09 夜间自主实现** — 全部验收项落地。ruff 关掉 RUF001/002/003：本仓库注释与文案一律中文，全角标点是正确写法，这三条规则是纯噪音。
- 运行入口 `brief` 子命令由 01 号工单落在 `mining_brief/cli.py` 上；本票只交付 `--help` / `--version` 这层参数面外壳。
