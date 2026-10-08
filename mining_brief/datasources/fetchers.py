"""抓取层：`fetch(url) -> RawResponse` 的几个实现（ADR-0003）。

**adapter 里没有任何 `if replay` 分支** —— 模式差异全部收在"注入哪个 Fetcher"上。
这是这层存在的全部理由：两种模式之间没有可漂移的分支。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from mining_brief.contracts import RawResponse
from mining_brief.datasources.fixtures import FixtureStore


class Fetcher(Protocol):
    async def fetch(self, url: str) -> RawResponse: ...


class HttpFetcher:
    """真实 HTTP 抓取。GFEX / DCE / 新闻 RSS / 技术报告 PDF 都走它。

    注意它**抓不到 LME**（Cloudflare 拦掉全部普通 HTTP 客户端）—— LME 要浏览器，
    见工单 04。这是实测事实，不是保守估计。
    """

    def __init__(self, *, timeout_s: float, user_agent: str, proxy: str = "") -> None:
        self._timeout_s = timeout_s
        self._user_agent = user_agent
        self._proxy = proxy or None

    async def fetch(self, url: str) -> RawResponse:
        headers = {"User-Agent": self._user_agent, "Accept": "*/*"}
        async with httpx.AsyncClient(
            timeout=self._timeout_s,
            follow_redirects=True,
            proxy=self._proxy,
            headers=headers,
        ) as client:
            response = await client.get(url)
        return RawResponse(
            url=url,
            status=response.status_code,
            content_type=response.headers.get("content-type", ""),
            body=response.content,
            fetched_at=datetime.now(UTC),
        )


class FixtureFetcher:
    """回放：按 URL 从 fixture 清单里取出**逐字节原文**（ADR-0002）。

    查不到就抛 `FixtureMissing`，**绝不静默去打真实网络**（User Story 35）。
    """

    def __init__(self, store: FixtureStore) -> None:
        self._store = store

    async def fetch(self, url: str) -> RawResponse:
        return self._store.raw(url)


def build_fetcher(
    *,
    data_mode: str,
    fixture_root: Path | str = "fixtures",
    timeout_s: float,
    user_agent: str,
    proxy: str = "",
) -> Fetcher:
    """按模式挑一个 Fetcher —— 这是整个数据层里**唯一**出现模式判断的地方。"""
    if data_mode == "replay":
        return FixtureFetcher(FixtureStore(fixture_root))
    return HttpFetcher(timeout_s=timeout_s, user_agent=user_agent, proxy=proxy)
