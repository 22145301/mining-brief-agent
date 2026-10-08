"""新闻源：RSS 解析（纯函数）+ adapter（只做编排）。

分层按 ADR-0003：`parse_feed` / `classify` / `parse_article_html` 都是**纯函数**，
拿 fixture 里的逐字节原始响应直接就能单测 —— 不需要网络，不需要起子进程，
不需要 mock 任何东西。抓到网络的那一段全部在 `Fetcher` 里。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree

from mining_brief.config.news_rules import MINING_RIGHTS_EXCLUDES, MINING_RIGHTS_TERMS
from mining_brief.config.sources import NEWS_SOURCES, NewsSource
from mining_brief.contracts import (
    Article,
    ArticleLookup,
    FetchStatus,
    NewsCategory,
    NewsItem,
    NewsSearchResult,
    RawResponse,
)
from mining_brief.datasources.fetchers import Fetcher
from mining_brief.errors import LoudFailure

#: 参与关键词匹配的最小词长。太短的词（`pls`、`ltd`）做子串匹配会把不相关的
#: 新闻全捞进来，得不偿失。
_MIN_TOKEN_LEN = 4

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(rf"[A-Za-z0-9]{{{_MIN_TOKEN_LEN},}}")


@dataclass(frozen=True, slots=True)
class ParsedFeedItem:
    """RSS 的一条。`published_at` 是**解析出来的时间对象**，还没格式化成字符串。"""

    title: str
    url: str
    published_at: datetime
    summary: str


def _plain_text(markup: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", markup))).strip()


def parse_feed(raw: RawResponse) -> tuple[ParsedFeedItem, ...]:
    """RSS 2.0 → 结构化条目。**纯函数**，是整个新闻链路上最密的一段断言所在。"""
    root = ElementTree.fromstring(raw.body)
    channel = root.find("channel")
    if channel is None:
        return ()

    items: list[ParsedFeedItem] = []
    for node in channel.findall("item"):
        title = _plain_text(node.findtext("title") or "")
        url = (node.findtext("link") or "").strip()
        description = node.findtext("description") or ""
        pub_date = (node.findtext("pubDate") or "").strip()
        if not (title and url and pub_date):
            # 缺字段的条目直接跳过：宁可少一条，也不要补一个我猜的时间。
            continue
        items.append(
            ParsedFeedItem(
                title=title,
                url=url,
                published_at=parsedate_to_datetime(pub_date),
                summary=_plain_text(description),
            )
        )
    return tuple(items)


def classify(title: str, summary: str) -> NewsCategory:
    """关键词分流。**纯函数**，A5 直接断言它。"""
    haystack = f"{title}\n{summary}".lower()
    if any(term in haystack for term in MINING_RIGHTS_EXCLUDES):
        return NewsCategory.GENERAL
    if any(term in haystack for term in MINING_RIGHTS_TERMS):
        return NewsCategory.MINING_RIGHTS
    return NewsCategory.GENERAL


def query_tokens(query: str) -> frozenset[str]:
    return frozenset(token.lower() for token in _TOKEN_RE.findall(query))


def _mentions(haystack_lower: str, tokens: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", haystack_lower) for token in tokens)


# ---------------------------------------------------------------------------
# 文章正文：`fetch_article` 用它
# ---------------------------------------------------------------------------


class _ArticleBodyExtractor(HTMLParser):
    """从文章页里取正文文本。

    只认一个约定：正文装在一个 class 含 `entry-content` 的元素里。这个约定是
    实测出来的（Australian Mining 用的是 WordPress 的 `entry-content`），不是猜的。
    认不出来时返回空串，由调用方如实记成"拿不到正文" —— **不退回整页 HTML**，
    那样读起来是一坨导航栏。
    """

    _BODY_MARKER = "entry-content"
    _BLOCK_TAGS = frozenset({"p", "div", "br", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._capturing = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self._capturing and self._BODY_MARKER in (attributes.get("class") or ""):
            self._capturing = True
            self._depth = 1
            return
        if not self._capturing:
            return
        if tag == "div":
            self._depth += 1
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        if tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self._capturing = False
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.parts.append(data)

    @property
    def text(self) -> str:
        joined = "".join(self.parts)
        lines = [_WS_RE.sub(" ", line).strip() for line in joined.split("\n")]
        return "\n".join(line for line in lines if line)


def parse_article_html(raw: RawResponse) -> tuple[str, str, str]:
    """文章页 → `(title, published_at, text)`。**纯函数**。

    时间戳优先取 `article:published_time`（站点自己声明的发布时刻），拿不到就返回空串 ——
    用"抓取时刻"顶上会让引用块里的时间戳变成假话。
    """
    markup = raw.text()
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S | re.I)
    title = _plain_text(title_match.group(1)) if title_match else ""

    time_match = re.search(
        r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']',
        markup,
        re.I,
    )
    published_at = time_match.group(1).strip() if time_match else ""

    extractor = _ArticleBodyExtractor()
    extractor.feed(markup)
    return title, published_at, extractor.text


def _source_name_for(url: str, sources: tuple[NewsSource, ...]) -> str:
    for source in sources:
        if url.startswith(source.url.split("/feed")[0]):
            return source.name
    match = re.match(r"https?://([^/]+)", url)
    return match.group(1) if match else "unknown"


# ---------------------------------------------------------------------------
# adapter：只做编排
# ---------------------------------------------------------------------------


class NewsAdapter:
    """`mining-news-mcp` 背后的业务逻辑。

    它**不判断自己跑在哪种模式下** —— 差异全在注入的 `Fetcher` 上（ADR-0003）。
    """

    def __init__(self, fetcher: Fetcher, sources: tuple[NewsSource, ...] = NEWS_SOURCES) -> None:
        self._fetcher = fetcher
        self._sources = sources

    async def search(self, query: str, days: int, now: datetime) -> NewsSearchResult:
        window_end = now
        window_start = now - timedelta(days=days)
        tokens = query_tokens(query)

        collected: list[NewsItem] = []
        failures: list[str] = []
        for source in self._sources:
            try:
                raw = await self._fetcher.fetch(source.url)
            except LoudFailure:
                # 录播缺失不是"这个源挂了"，是"我们的 fixture 集不全"；缺浏览器同理，
                # 是环境问题不是源问题。降级成 PARTIAL 会让人去查一个根本没坏的网站
                # —— 让它炸穿（ADR-0002）。
                raise
            except Exception as exc:
                failures.append(f"{source.name}（{type(exc).__name__}）")
                continue
            if not raw.ok:
                failures.append(f"{source.name}（HTTP {raw.status}）")
                continue
            collected.extend(
                self._to_items(parse_feed(raw), source, tokens, window_start, window_end)
            )

        collected.sort(key=lambda item: item.published_at, reverse=True)
        return NewsSearchResult(
            status="ok" if not failures else "degraded",
            source_status=self._status(bool(collected), failures, len(self._sources)),
            reason=self._reason(failures),
            retrieved_at=now,
            query=query,
            window_days=days,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            items=tuple(collected),
        )

    async def fetch_article(self, url: str, now: datetime) -> ArticleLookup:
        try:
            raw = await self._fetcher.fetch(url)
        except LoudFailure:
            raise
        except Exception as exc:
            return ArticleLookup(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=f"抓取正文失败：{type(exc).__name__}",
                retrieved_at=now,
                article=None,
            )

        if not raw.ok:
            return ArticleLookup(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=f"抓取正文失败：HTTP {raw.status}",
                retrieved_at=now,
                article=None,
            )

        title, published_at, text = parse_article_html(raw)
        if not text:
            return ArticleLookup(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason="页面取到了，但没能定位正文容器（站点结构可能改版）",
                retrieved_at=now,
                article=None,
            )

        return ArticleLookup(
            status="ok",
            source_status=FetchStatus.OK,
            retrieved_at=now,
            article=Article(
                url=url,
                title=title,
                source=_source_name_for(url, self._sources),
                published_at=published_at,
                text=text,
            ),
        )

    @staticmethod
    def _to_items(
        parsed: tuple[ParsedFeedItem, ...],
        source: NewsSource,
        tokens: frozenset[str],
        window_start: datetime,
        window_end: datetime,
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        for entry in parsed:
            if not (window_start <= entry.published_at <= window_end):
                continue
            haystack = f"{entry.title}\n{entry.summary}".lower()
            if tokens and not _mentions(haystack, tokens):
                continue
            items.append(
                NewsItem(
                    title=entry.title,
                    url=entry.url,
                    source=source.name,
                    published_at=entry.published_at.isoformat(),
                    summary=entry.summary,
                    category=classify(entry.title, entry.summary),
                )
            )
        return items

    @staticmethod
    def _status(has_items: bool, failures: list[str], source_count: int) -> FetchStatus:
        if failures and len(failures) == source_count:
            return FetchStatus.UNAVAILABLE
        if failures:
            return FetchStatus.PARTIAL
        return FetchStatus.OK if has_items else FetchStatus.EMPTY

    @staticmethod
    def _reason(failures: list[str]) -> str | None:
        if not failures:
            return None
        return "以下新闻源本次未取到：" + "、".join(failures)
