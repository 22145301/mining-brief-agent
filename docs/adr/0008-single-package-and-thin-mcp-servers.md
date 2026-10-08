# 单包布局：mining_brief/ 子包分层，MCP server 只做薄壳

代码放在**一个**可安装包 `mining_brief/` 里，按层分子包（`contracts` / `datasources` / `servers` / `agent` / `config`），而不是顶层并列四个包。

三个 MCP server 是**薄壳**：只做"参数校验 → 调 adapter → 包成信封（ADR-0005）"，业务逻辑一行都不留在 server 里。`fixtures/` 与 `scripts/` 刻意留在包外 —— 它们是数据与工具，不是产品代码。

## Considered Options

- **顶层并列 `servers/` `agent/` `datasources/` `config/`**（PRD §11 原样）：一眼看到分层，路径更短。否决 —— 顶层包名 `config` 与 `agent` 容易与第三方包撞名，且 pytest 会把仓库根塞进 `sys.path`，顶层目录会被当作包误捕获。
- **多包工作区**：否决，对一个 24h 面试任务不成比例（同一取舍也出现在 ADR-0005）。

## Consequences

- **server 薄壳是一条纪律，不是描述。** 往 server 里搬业务逻辑会让 A2 的工具级单测退化成"逻辑的复制品测试"—— 同一份逻辑在 server 和 adapter 各测一遍。被问"为什么 server 这么薄"时，答案在这里。
- `config/` 只放**非密钥**配置（矿山档案、交易所表、窗口缺省与超时重试参数）；密钥与 LLM key 走环境变量 + `.env.example`（CLAUDE.md 硬性要求）。
- `fixtures/` 与 `scripts/` 在包外，因此 `pyproject.toml` 的打包规则保持简单。
