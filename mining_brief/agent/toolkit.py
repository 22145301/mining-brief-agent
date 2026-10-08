"""图与三个 MCP server 之间的唯一通道。

按 ADR-0001，默认（回放）模式**照常走 MCP 协议**，只是用 SDK 的进程内协议连接而
不起子进程 —— 请求响应照常序列化，"走 MCP 协议"与"起子进程"是两件可以分开的事。
`--live` 与回放的差别全在环境变量上，这里一行都不用改。

每次调用各开一次会话是刻意的：会话建立失败（进程起不来、协议不兼容）必须落在
**fetch 节点自己的 try/except 里**（ADR-0006），而不是在图启动时就炸掉整张图。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

import anyio
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

from mining_brief.contracts import (
    ArticleLookup,
    NewsSearchResult,
    PriceLookup,
    PriceSeries,
    ResourceExtract,
)
from mining_brief.errors import REPLAY_MISS_SENTINEL, ReplayMiss, ToolCallFailed


def unwrap_task_group_exception(exc: BaseException) -> BaseException:
    """剥掉 anyio 任务组套上的 `ExceptionGroup` 壳子，返回最里层的那个异常。

    任务组对"异常不要吞掉"是有价值的，但套在这里纯属噪声：调用方写
    `except ReplayMiss` 会因为异常被包了两层而**失效**，于是本该炸穿整张图的
    "我们录播不全"就退化成了别的东西。包两层是常态 —— `ClientSession` 自己也有
    一个任务组。

    只认单叶子的情况：多个叶子说明真的出了两件事，那就该原样保留分组。
    """
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


@asynccontextmanager
async def inprocess_session(server: FastMCP) -> AsyncIterator[ClientSession]:
    """在同一个进程里跑完整 MCP 协议：内存流替代 stdio，其余一模一样。"""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        low_level = server._mcp_server

        async def serve() -> None:
            # **不要传 `raise_exceptions=True`。** 那会把工具的异常直接抛出服务端
            # 任务组，客户端收到的是一个 `ExceptionGroup`，既看不出是哪个工具坏的，
            # 也不符合 ADR-0005 —— 那里说得很清楚：工具自己坏了要**作为错误结果**
            # 返回，由调用方决定降不降级。默认行为（转成 error result）才是对的。
            await low_level.run(
                server_read,
                server_write,
                low_level.create_initialization_options(),
            )

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(serve)
                try:
                    async with ClientSession(client_read, client_write) as session:
                        await session.initialize()
                        yield session
                finally:
                    task_group.cancel_scope.cancel()
        except BaseException as exc:
            unwrapped = unwrap_task_group_exception(exc)
            if unwrapped is exc:
                raise
            raise unwrapped from None


def _error_text(result: Any) -> str:
    parts: list[str] = []
    for item in result.content or ():
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts) or "(没有错误详情)"


async def _call(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """调一次工具并要回结构化结果。

    错误结果分两种，**必须分开**（见 `errors.py`）：回放录播缺失是我们自己的问题，
    原样抛 `ReplayMiss` 让它炸穿整张图；其余工具故障抛 `ToolCallFailed`，由 fetch
    节点降级成信封。MCP 不传异常类型，所以靠 `ReplayMiss` 消息里的哨兵串认它 ——
    这是全仓库唯一一处跨进程的字符串契约，两边引用的是同一个常量。
    """
    result = await session.call_tool(name, arguments)
    if result.isError:
        text = _error_text(result)
        if REPLAY_MISS_SENTINEL in text:
            raise ReplayMiss(f"MCP 工具 {name} {text}")
        raise ToolCallFailed(f"MCP 工具 {name} 报错：{text}")

    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise ToolCallFailed(f"MCP 工具 {name} 没有返回结构化结果")
    return structured


class ToolKit(Protocol):
    """三个 server 的工具按用途归类。图只认这个协议，不认传输方式。"""

    async def search_news(self, query: str, days: int) -> NewsSearchResult: ...
    async def fetch_article(self, url: str) -> ArticleLookup: ...
    async def get_price(self, commodity: str, date: str) -> PriceLookup: ...
    async def get_trend(self, commodity: str, days: int) -> PriceSeries: ...
    async def extract_resources(self, pdf_url: str) -> ResourceExtract: ...


class McpToolKit:
    """默认实现：进程内协议连接。stdio 变体由 09 号工单补（`mcp-config.json` 那条路）。"""

    def __init__(
        self,
        *,
        news: FastMCP,
        prices: FastMCP,
        resources: FastMCP,
    ) -> None:
        self._servers: dict[str, FastMCP] = {
            "news": news,
            "prices": prices,
            "resources": resources,
        }

    def _binder(self, which: str) -> Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]:
        server = self._servers[which]
        open_session = inprocess_session

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            async with open_session(server) as session:
                return await _call(session, name, arguments)

        return call

    async def search_news(self, query: str, days: int) -> NewsSearchResult:
        call = self._binder("news")
        return NewsSearchResult.model_validate(await call("search", {"query": query, "days": days}))

    async def fetch_article(self, url: str) -> ArticleLookup:
        call = self._binder("news")
        return ArticleLookup.model_validate(await call("fetch_article", {"url": url}))

    async def get_price(self, commodity: str, date: str) -> PriceLookup:
        call = self._binder("prices")
        return PriceLookup.model_validate(
            await call("get_price", {"commodity": commodity, "date": date})
        )

    async def get_trend(self, commodity: str, days: int) -> PriceSeries:
        call = self._binder("prices")
        return PriceSeries.model_validate(
            await call("get_trend", {"commodity": commodity, "days": days})
        )

    async def extract_resources(self, pdf_url: str) -> ResourceExtract:
        call = self._binder("resources")
        return ResourceExtract.model_validate(await call("extract_resources", {"pdf_url": pdf_url}))


def default_toolkit() -> McpToolKit:
    """三个 server 的默认装配。延迟 import —— server 模块要读环境变量才能构造。"""
    from mining_brief.servers.mineral_pdf_server import mcp as resources_server
    from mining_brief.servers.news_server import mcp as news_server
    from mining_brief.servers.price_server import mcp as price_server

    return McpToolKit(news=news_server, prices=price_server, resources=resources_server)


__all__ = ["McpToolKit", "ToolKit", "default_toolkit", "inprocess_session"]
