"""共享契约包（ADR-0005 / ADR-0008）。

两个用途，同一份定义，避免三份近似类型各自漂移：

1. 三个 MCP server 的**返回信封**（跨进程传输的那部分）。
2. agent 内部**跨节点**共享的形状。

一条贯穿的规矩：**可被引用进简报的字段一律是 ISO-8601 字符串**，不是 `datetime`。
否则"引用块里的时间戳与工具返回值逐字符相同"（验收 A4）就只能靠两处各自格式化
后碰巧一致，而这种"碰巧"迟早会破。
"""

from mining_brief.contracts.brief import (
    DEFAULT_WINDOW_DAYS,
    SECTION_TITLES,
    ArchiveEntryRef,
    BriefResult,
    Citation,
    CitationReport,
    Commodity,
    Fact,
    Hint,
    Intent,
    Refusal,
    ReportScope,
    RiskSignal,
    Section,
    SectionKey,
    Slots,
    Uncovered,
)
from mining_brief.contracts.envelope import Envelope, FetchStatus
from mining_brief.contracts.news import (
    Article,
    ArticleLookup,
    NewsCategory,
    NewsItem,
    NewsSearchResult,
)
from mining_brief.contracts.prices import PriceLookup, PricePoint, PriceSeries
from mining_brief.contracts.raw import RawResponse
from mining_brief.contracts.resources import (
    PageRef,
    ReportingStandard,
    ResourceCategory,
    ResourceExtract,
    ResourceKind,
    ResourceRow,
    ResourceTable,
)

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "SECTION_TITLES",
    "ArchiveEntryRef",
    "Article",
    "ArticleLookup",
    "BriefResult",
    "Citation",
    "CitationReport",
    "Commodity",
    "Envelope",
    "Fact",
    "FetchStatus",
    "Hint",
    "Intent",
    "NewsCategory",
    "NewsItem",
    "NewsSearchResult",
    "PageRef",
    "PriceLookup",
    "PricePoint",
    "PriceSeries",
    "RawResponse",
    "Refusal",
    "ReportScope",
    "ReportingStandard",
    "ResourceCategory",
    "ResourceExtract",
    "ResourceKind",
    "ResourceRow",
    "ResourceTable",
    "RiskSignal",
    "Section",
    "SectionKey",
    "Slots",
    "Uncovered",
]
