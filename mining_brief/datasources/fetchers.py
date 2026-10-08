"""抓取层：`fetch(url)` / `post_form(url, form)` 的几个实现（ADR-0003）。

**adapter 里没有任何 `if replay` 分支** —— 模式差异全部收在"注入哪个 Fetcher"上。
这是这层存在的全部理由：两种模式之间没有可漂移的分支。

为什么要有 `post_form`：GFEX 的日行情接口**只认 POST**，同路径用 GET 会被 WAF 挡成
520（实测）。而回放是按 URL 取录播的（ADR-0002），POST 的参数在请求体里 ——
不把它并进键，所有日期就共用同一个 fixture，回放出来的永远是同一天的数据。
`canonical_post_url` 就是这个键：**两种模式必须用同一个函数算**，否则回放和真实
抓取会对不上，而那是这套设计里唯一不能出错的地方。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import httpx

from mining_brief.contracts import RawResponse
from mining_brief.datasources.fixtures import FixtureStore


def canonical_post_url(url: str, form: Mapping[str, str]) -> str:
    """POST 请求在 fixture 清单里的身份。

    排序是为了让键与参数的书写顺序无关 —— 否则调用方换个顺序写 form，
    回放就查不到了。表单在这里没有密钥（GFEX 的接口不需要认证），所以
    把参数写进键不涉及"密钥入库"。
    """
    return f"{url}?{urlencode(sorted(form.items()))}"


class Fetcher(Protocol):
    async def fetch(self, url: str) -> RawResponse: ...

    async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse: ...


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
        return self._raw(url, response)

    async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
        headers = {"User-Agent": self._user_agent, "Accept": "*/*"}
        async with httpx.AsyncClient(
            timeout=self._timeout_s,
            follow_redirects=True,
            proxy=self._proxy,
            headers=headers,
        ) as client:
            response = await client.post(url, data=dict(form))
        # 返回的 `url` 是**规范化后的** POST 地址（含参数），与回放侧的键逐字符相同。
        return self._raw(canonical_post_url(url, form), response)

    @staticmethod
    def _raw(url: str, response: httpx.Response) -> RawResponse:
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

    async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
        return self._store.raw(canonical_post_url(url, form))


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
