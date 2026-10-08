"""`mining-news-mcp` —— 题面点名的三个 server 之一。

**薄壳**（ADR-0008）：只做"参数校验 → 调 adapter → 包成信封"。业务逻辑一行都不
留在这里 —— 往 server 里搬逻辑，A2 的工具级单测就退化成同一份逻辑的第二次复制。

返回类型注解即 outputSchema：宿主（Claude Desktop / Cursor）里能看到结构化的
参数与返回值，人不需要翻文档就知道 `search` 会给他什么。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mining_brief.config.logging import configure_logging
from mining_brief.contracts import ArticleLookup, NewsSearchResult
from mining_brief.servers.runtime import Runtime, default_runtime

mcp = FastMCP("mining-news-mcp")

_runtime_override: Runtime | None = None


def _runtime() -> Runtime:
    return _runtime_override or default_runtime()


def set_runtime(runtime: Runtime | None) -> None:
    """给测试用的注入点。生产路径上没人调用它。"""
    global _runtime_override
    _runtime_override = runtime


@mcp.tool()
async def search(query: str, days: int) -> NewsSearchResult:
    """按关键词搜索窗口内的矿业新闻，并把每条分成「矿权动态」或「普通新闻」。

    **何时用**：需要某座矿山 / 某个矿种在最近一段时间内的新闻时。

    **参数**：`query` 是空格分隔的关键词（如 `Pilgangoora Pilbara lithium`），
    命中标题或摘要里任一词即算匹配；`days` 是回溯天数。

    **返回**：`NewsSearchResult` 信封。`items` 是命中的新闻，每条带 `category`；
    `source_status` 说明本次是否取全（`partial` 表示有新闻源没取到，`reason` 里写明是哪家）。
    """
    runtime = _runtime()
    return await runtime.news().search(query=query, days=days, now=runtime.now())


@mcp.tool()
async def fetch_article(url: str) -> ArticleLookup:
    """抓取一篇新闻的正文全文。

    **何时用**：`search` 返回的摘要不够，需要读原文时。

    **参数**：`url` 必须是 `search` 返回值里的 `url`，原样传入。

    **返回**：`ArticleLookup` 信封。正文在 `article.text`；取不到时 `article` 为
    `None` 且 `reason` 说明原因（站点改版、抓取失败等）—— **不会**退回一整页 HTML。
    """
    runtime = _runtime()
    return await runtime.news().fetch_article(url=url, now=runtime.now())


def main() -> None:
    """stdio 入口 —— `mcp-config.json` 挂的就是它。"""
    # 先把日志锁到 stderr 再开跑：stdio 传输下 stdout 只归协议所有，
    # 一条日志写进去，客户端看到的就是一段解不开的 JSON（工单 09 验收项）。
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
