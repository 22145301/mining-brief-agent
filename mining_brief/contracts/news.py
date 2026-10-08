"""`mining-news-mcp` 的工具返回契约。签名照题面（PRD §6.1），不自创。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from mining_brief.contracts.envelope import Envelope


class NewsCategory(StrEnum):
    """新闻分流结果。

    **关键词规则**分出来的，不是模型判断的（PRD §6.1）—— 所以它是可单测的纯函数产物。
    """

    MINING_RIGHTS = "mining_rights"
    """与矿权取得、变更、争议、政策相关的新闻。"""

    GENERAL = "general"
    """其余全部。与「矿权动态」互补，不是"所有新闻"的同义词（见 CONTEXT.md）。"""


class NewsItem(BaseModel):
    """字段与 PRD §6.1 逐字一致，不加不减。"""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    source: str
    published_at: str
    """ISO-8601 字符串。**可被引用进简报的字段一律是字符串** —— 这样"引用块与
    工具返回值逐字符相同"（A4）是构造上成立的，而不是靠两处各自格式化后碰巧一致。"""

    summary: str
    category: NewsCategory


class NewsSearchResult(Envelope):
    query: str
    window_days: int
    window_start: str
    window_end: str
    items: tuple[NewsItem, ...]


class Article(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str
    source: str
    published_at: str
    text: str


class ArticleLookup(Envelope):
    article: Article | None = None
