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

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

import httpx

from mining_brief.contracts import RawResponse
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.errors import BrowserUnavailable

#: 页面渲染前要等到的事件。`domcontentloaded` 而不是 `load`：LME 的行情数字是
#: 服务端渲染在 HTML 里的（实测），不需要等齐全部图片与埋点脚本。
_RENDER_WAIT_UNTIL: Literal["domcontentloaded"] = "domcontentloaded"

#: 导航之后再等一会儿，给前端脚本把首屏数据填进去的时间。这是"起点值"
#: （ADR-0006），真跑通了按实测校准 —— 45s 的浏览器超时里它占很小一块。
_RENDER_SETTLE_MS = 4000


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


class BrowserFetcher:
    """真实**无头浏览器**抓取。只有 LME 走它 —— 它整站挂在 Cloudflare 后面，
    普通 HTTP 客户端一律 403（实测），curl 与真 Chrome 的差别就在这里。

    **它返回的是页面渲染后的 DOM，不是解析结果。** 这一点是刻意的：取回一串
    HTML 与"从 HTML 里读出那个 span"是两件事，前者在这里、后者在解析层的纯函数
    里（ADR-0003）。于是"怎么读"能被 fixture 直接单测，不需要浏览器、不需要网络。

    与 `HttpFetcher` **同接口**是这条链路能被注入的前提：adapter 一行都不用改，
    它只知道自己在调 `fetch(url)`。

    `channel=""` 用 playwright 自带的 chromium（`playwright install chromium`）；
    填 `"chrome"` 用系统 Chrome —— 省一次下载，代价是这台机器得装了 Chrome。
    """

    def __init__(
        self, *, timeout_s: float, user_agent: str, proxy: str = "", channel: str = ""
    ) -> None:
        self._timeout_s = timeout_s
        self._user_agent = user_agent
        self._proxy = proxy or ""
        self._channel = channel or None

    async def fetch(self, url: str) -> RawResponse:
        # playwright 是可选依赖，且它的同步 API 会阻塞事件循环 —— 丢进线程跑。
        status, html = await asyncio.to_thread(self._render, url)
        return RawResponse(
            url=url,
            status=status,
            content_type="text/html; charset=utf-8",
            body=html.encode("utf-8"),
            fetched_at=datetime.now(UTC),
        )

    async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
        # 没有浏览器源是按表单 POST 取数的。留一个响亮的 NotImplementedError，
        # 而不是悄悄退化成 GET —— 退化会让"这个源是 POST 的"这个事实消失。
        raise NotImplementedError(
            f"浏览器抓取不支持表单 POST（{url}）。目前只有 GET 形页面走这条路。"
        )

    def _launch_kwargs(self) -> dict[str, Any]:
        """给 `chromium.launch` 的参数。

        单独拆出来是为了让 mypy 看得舒服：playwright 的 `launch` 是重载签名
        （`channel` 与 `proxy` 各有各的类型），用 `**kwargs` 展开会被判成不兼容。
        """
        kwargs: dict[str, Any] = {"channel": self._channel}
        if self._proxy:
            kwargs["proxy"] = {"server": self._proxy}
        return kwargs

    def _render(self, url: str) -> tuple[int, str]:
        """导航 + 取 DOM。**同步**，由调用方丢进线程。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 取决于环境是否装了 extra
            raise BrowserUnavailable(
                "需要无头浏览器，但 playwright 没装。请 `uv sync --extra browser` "
                "并 `uv run playwright install chromium`。"
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(**self._launch_kwargs())
                try:
                    page = browser.new_page(user_agent=self._user_agent)
                    response = page.goto(
                        url, timeout=self._timeout_s * 1000, wait_until=_RENDER_WAIT_UNTIL
                    )
                    page.wait_for_timeout(_RENDER_SETTLE_MS)
                    status = response.status if response is not None else 0
                    return status, page.content()
                finally:
                    browser.close()
        except BrowserUnavailable:
            raise
        except Exception as exc:
            # 浏览器**起不来**（二进制缺失、channel 名写错）与环境问题同源，
            # 都让调用方响亮地失败 —— 详见 `_is_launch_failure`。
            if _is_launch_failure(exc):
                raise BrowserUnavailable(
                    f"无头浏览器起不来（channel={self._channel or 'bundled'}）：{exc}"
                ) from exc
            # 页面本身打不开（超时、被断开）是**源侧**的失败，照常上抛，
            # 由 adapter 按"取不到"降级。
            raise


def _is_launch_failure(exc: BaseException) -> bool:
    """判断异常是"浏览器起不来"还是"这个页面打不开"。

    分界的现实意义：前者要炸穿整张图（配置/环境问题），后者要降级成"取不到"
    （源暂时不可达）。playwright 对这两种情况给的**都是** `Error` 类，靠消息里的
    措辞区分 —— 所以这里是一个显式白名单，而不是"看它像不像 Error"。
    """
    text = str(exc)
    markers = (
        "Executable doesn't exist",  # 浏览器二进制没装
        "Looks like Playwright was just installed",
        "playwright install",
        "channel",  # channel="chrome" 但系统没装 Chrome
        "Cannot find module",
    )
    return any(marker.lower() in text.lower() for marker in markers)


class RoutingFetcher:
    """按 URL 分流：登记表里标了"要浏览器"的源走 `BrowserFetcher`，其余走 HTTP。

    分流为什么在这里、而不在 adapter 里：adapter 是整个数据层里唯一**不许**出现
    模式判断的地方（ADR-0003），而"LME 要浏览器"是关于**数据源**的事实，不是关于
    运行模式的事实。所以它随 `browser_urls` 一路传进来，adapter 从头到尾不知情。
    """

    def __init__(self, *, http: Fetcher, browser: Fetcher, browser_urls: frozenset[str]) -> None:
        self._http = http
        self._browser = browser
        self._browser_urls = browser_urls

    async def fetch(self, url: str) -> RawResponse:
        if url in self._browser_urls:
            return await self._browser.fetch(url)
        return await self._http.fetch(url)

    async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
        # 表单源（GFEX）都是 HTTP —— 分流只作用于 GET。
        return await self._http.post_form(url, form)


def build_fetcher(
    *,
    data_mode: str,
    fixture_root: Path | str = "fixtures",
    timeout_s: float,
    browser_timeout_s: float,
    user_agent: str,
    proxy: str = "",
    browser_urls: frozenset[str] = frozenset(),
    browser_channel: str = "",
) -> Fetcher:
    """按模式挑一个 Fetcher —— 这是整个数据层里**唯一**出现模式判断的地方。

    **回放模式完全不碰浏览器**：LME 的录播是一份存下来的 HTML，与别的 fixture
    一样逐字节回放（ADR-0002）。所以"离线跑全套测试"不需要装浏览器，也不需要网络。
    """
    if data_mode == "replay":
        return FixtureFetcher(FixtureStore(fixture_root))
    http = HttpFetcher(timeout_s=timeout_s, user_agent=user_agent, proxy=proxy)
    if not browser_urls:
        return http
    return RoutingFetcher(
        http=http,
        browser=BrowserFetcher(
            timeout_s=browser_timeout_s,
            user_agent=user_agent,
            proxy=proxy,
            channel=browser_channel,
        ),
        browser_urls=browser_urls,
    )
