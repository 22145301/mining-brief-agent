# 每个 fetch 节点各自 try/except 兜底，失败返回降级信封

三个并行 fetch 节点（`fetch_news` / `fetch_prices` / `fetch_resources`）都写成 `async def`，各自 `try/except` 捕获后返回 `source_status="failed"` 的信封（ADR-0005）。

- `RetryPolicy(max_attempts=3, backoff_factor=2.0)` 负责瞬时故障（子进程冷启动失败、网络抖动）。
- **纯函数节点不重试也不捕获**（`check_scope` / `compute_signals` / `assemble` / `verify_citations` / `render`）—— 它们失败就是 bug，应该炸出来，吞掉只会让简报静默出错。
- LLM 节点重试 API 层错误（`max_attempts=2`，别把配额烧在确定性错误上）；降级按 PRD 既有约定：intent → 缺省槽位，narrate → 不写导读。

## 为什么不是"少写几个 try/except"

LangGraph 的 superstep 是**事务性**的：三个并行分支里任一分支抛异常，同一 superstep 内已成功的那两个结果也一起丢，整图报错。我们不用 checkpointer，所以"已成功节点会被保存、恢复时不重跑"这个例外不适用。

因此 PRD §6.2 的"任一 fetch 挂掉，简报照样出"**不是框架默认行为**，fetch 节点里的兜底是必需的，不是防御性编程。**不要把它当冗余删掉。**

## 为什么不用图层 error_handler

`error_handler`（需 langgraph ≥ 1.2）能在重试耗尽后路由到降级路径，但降级值恰好就是 ADR-0005 的信封形状 —— 放在节点内只需构造一次；放进 handler 则要在图接线处再构造一遍，将来给信封加字段必漏一处。

## Consequences

- 三个 fetch 节点必须是 `async def`：节点级 `timeout` **只支持 async 节点**，给 sync 节点配 timeout 会在 compile 时直接报错。
- 超时值走配置、不硬编码。起点值：HTTP 类 15s，浏览器类（LME）45s（冷启动 + 页面导航 + 过 Cloudflare 挑战页）。这两个数是**起点而非实测值**，首次跑通后校准。
