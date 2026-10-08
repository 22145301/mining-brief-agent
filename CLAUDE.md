# 项目约定

- grill me 等技能反问时，须一个一个来，不要一次问我好多。
- 全部回答用中文。

## 交付背景

这是凌天智矿的面试题（题目见 `面试题目.docx`）。交付要求：三选一、代码全程由 Claude Code 编写、满足工程化规范、上传 GitHub。
评审人会直接对着仓库检查，并在面试中追问设计决策 —— 所以"能跑通"只是及格线，"经得起问"才是目标。

## 提交节奏（强制）

**每完成一个独立可验证的部分，立刻提交一次 commit，不要攒到最后一次性提交。**

- 判定标准：这部分自己能跑通或测试通过，且不依赖尚未完成的工作。
- 提交前先看 `git status`，确认本次改动完全可解释，不夹带无关文件。
- commit 信息用祈使句讲清"做了什么、为什么"，禁止 `update` / `fix` / `修改` 这类无信息提交。
- 提交历史是给面试官看的推进记录 —— 他会用它判断这个项目是不是一步步做出来的。

## 工程化规范（硬性）

- **一键可运行**：README 写清安装、运行、测试三条命令；陌生人 clone 下来 5 分钟内必须跑得起来。
- **依赖显式且锁定**：用 `pyproject.toml` 或 `package.json`，提交 lock 文件；不允许依赖"我本地装过"。
- **分层结构**：入口 / 业务逻辑 / 数据访问 / 配置相互分离；禁止把逻辑堆进单个 main 文件。
- **测试**：核心逻辑必须有单元测试，`pytest` 或 `npm test` 全绿。测试与实现一同提交，不事后补。
- **配置外置**：密钥、连接串一律走环境变量；提供 `.env.example`；**任何密钥不得进入 commit**。
- **错误处理与日志**：统一异常处理 + 结构化日志；禁止用裸 `print` / `console.log` 做排查。
- **提交历史**：`.gitignore` 与 `.gitattributes` 到位。提交粒度与信息规范见上方「提交节奏」。

## 工程化规范（加分项）

- Lint / Formatter / 类型检查配置齐全（Ruff + Black 或 ESLint + Prettier，配 mypy 或 tsc）。
- GitHub Actions 跑 lint + test，README 挂状态 badge。
- `Dockerfile` + `docker compose up` 一键起服务。
- 架构说明或 ADR，记录关键设计取舍。

## 与 AI 协作的纪律

- **每一行都要能解释**：追问设计动机、边界情况和失败路径，解释不了的代码比不写更扣分。
- **保持可追溯**：CLAUDE.md 记录约定，提交严格按「提交节奏」执行，不做"一次性大提交"。
- **先确认再生成**：拿不准的设计选择先问清楚，避免生成一大片后再返工。

## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` — this repo has no git remote. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
