# 09: stdio 冒烟与宿主挂载

**What to build:** 三个 MCP server 能真的挂进 Claude Desktop / Cursor 手玩，并且 stdio 传输本身有一条会失败的测试守着。

这一刀补的是 ADR-0001 里**刻意接受的取舍**：默认路径走的是进程内协议连接，不覆盖 stdio 传输本身（进程边界、协议编码）。这条取舍的代价正是由本票补上——一个冒烟用例加一次真实的宿主挂载。

**Blocked by:** 04, 05

**Status:** done

**Category:** enhancement

- [x] 仓库根目录的 `mcp-config.json` 与题面同名，Claude Desktop / Cursor 能直接识别并挂载
- [x] 一条 stdio 冒烟用例：**真起子进程**、走 stdio 传输、把每个 server 的每个工具都调通
- [x] 冒烟用例单独标记，不进默认离线套件（否则每条本地测试都要管进程启停与清理）
- [x] 每个工具的返回类型注解即 outputSchema，宿主里能看到结构化参数与返回值
- [x] 工具描述写清"何时用、返回什么"，人在宿主里不问文档也能上手
- [x] stdout 只走协议，日志一律走 stderr（否则协议线被日志污染）
- [ ] 手工验证记录一次：在宿主里实际调用每个工具 —— **只做到一半**，见下「边界」

---

## 完成情况

### 落了什么

- `tests/test_stdio_smoke.py`（7 条用例，标 `stdio`，默认套件排除）。
- 根目录 `mcp-config.json`：三个 server 各一条，`uv run --directory ${workspaceFolder} <名字>`。
- `pyproject.toml` 加了三个控制台脚本（`mining-news-mcp` / `lme-price-mcp` / `mineral-pdf-mcp`），
  名字照题面，不自创。
- `mining_brief/config/paths.py`（新）：默认录播根按**安装位置**推，不按 cwd 推。
- 三个 server 的 `main()` 先 `configure_logging()` 再 `mcp.run()`。
- README 增加「挂进 MCP 宿主」一节（含 Claude Desktop 的替换命令）。

### 实测记录

```
$ env -u MINING_LLM_API_KEY uv run pytest -q -m stdio -p no:randomly
9 passed, 235 deselected, 4 warnings in 18.20s

$ uv run pytest -q            # 默认套件
233 passed, 11 deselected, 4 warnings in 11.42s     # 11 = 9 条 stdio + 2 条 network

$ uv run ruff check . && uv run ruff format --check . && uv run mypy .
All checks passed! / 66 files already formatted / Success: no issues found in 66 source files
```

宿主挂载（真宿主，Claude Code；用完已 `claude mcp remove` 还原）：

```
$ claude mcp add --scope local --transport stdio mining-news-mcp \
    -e MINING_DATA_MODE=replay -e MINING_LLM_MODE=replay \
    -- uv run --directory "D:/cxb/矿产" mining-news-mcp
$ claude mcp list
mining-news-mcp:  uv run --directory D:/cxb/矿产 mining-news-mcp  - ✔ Connected
lme-price-mcp:    uv run --directory D:/cxb/矿产 lme-price-mcp    - ✔ Connected
mineral-pdf-mcp:  uv run --directory D:/cxb/矿产 mineral-pdf-mcp  - ✔ Connected
```

**换个工作目录起得来**（这是宿主场景的真实形状，也是 `config/paths.py` 要守的东西）：

```
$ cd /tmp && for exe in mining-news-mcp lme-price-mcp mineral-pdf-mcp; do
    printf '%s\n' '{...initialize...}' | "D:/cxb/矿产/.venv/Scripts/$exe.exe" | ...
  done
mining-news-mcp / lme-price-mcp / mineral-pdf-mcp          # 三个都回 serverInfo
```

### 边界（这一票没做到的部分）

- **宿主里"逐个工具都调了一遍"记录不下来。** 在真宿主里验到的是**挂载与工具发现**
  （`✔ Connected`，`list_tools` 三个 server 共 5 个工具全部可见、描述与 outputSchema 都在）。
  工具的**调用**记录来自 `tests/test_stdio_smoke.py` —— 真子进程、真 stdio、真协议帧，
  与宿主走的是同一条路，但客户端是我们自己的，不是宿主的模型回路。
  要补上那一半得在宿主里让模型发起调用（`claude -p ...`，会真的走一次外部模型）。
  没做，理由是那会用掉面试人的账号额度、且不产生新的可复现证据 —— 交给人决定。
- **Cursor 侧的替换没实机验过**（只验了 Claude Code）。`${workspaceFolder}` 是 Cursor /
  VS Code 的约定，Claude Desktop 不认，README 里给了 `sed` 一行替换。

### 三处判断

1. **`cwd` 不可信，默认录播根改成按安装位置推。** 宿主拉起 server 时工作目录是宿主的。
   不修的话坏法很隐蔽：进程起得来、工具列得出，第一次取数据才说"找不到清单"。
   顺带把 `llm_root` 也绑到 `fixture_root()` 上 —— 两者分家会造出"数据换了一套、
   LLM 还在读仓库里那份"的坏法，而回放 key 落在数据上，症状看起来像模型的问题。
2. **日志流写进 `main()` 而不是靠"谁先 `get_logger` 谁负责配置"。** `configure_logging()`
   是幂等的，`get_logger()` 会顺手调它 —— 于是"stdout 干净"此前只是**碰巧**成立
   （取决于 server 进程里有没有模块记过日志）。现在它是启动序列的一部分，
   相应用例测的也是这个机制而不是某个 server 的偶然行为。
3. **`mcp-config.json` 用 `${workspaceFolder}` 而不是绝对路径。** 绝对路径对 clone 下来的
   评审人是错的，而这个文件要进 commit。代价是 Claude Desktop 不认变量 —— 那一句
   在 README 里说清楚，并给了一行替换命令。
