"""数据源登记表 —— **非密钥配置**（ADR-0008）。

只放 URL、名称、交易所这类公开信息；密钥与代理一律走环境变量。

已实测的网络事实（不要再当成假设，改代码前先复跑一遍）：
- `mining.com/feed/` 在本机**必须走代理**才返回 200，直连被 CloudFront 403。
- `australianmining.com.au/feed/` 直连与走代理都能取到。
- `pls.com.au`（Pilbara Minerals 官网）在本机**域名解析失败**，因此新闻源里没有它。
- `www.dce.com.cn`（大连商品交易所）**抓不到**：整站挂在一套 JS 挑战式 WAF 后面，
  对 urllib / curl / 真 Chrome（Playwright，`channel="chrome"`）**一律**返回 412 并
  附一段挑战脚本 —— 两次有界尝试后停手，这是本环境的实测结论，不是保守估计。
  因此铁矿石的行情改用新浪财经转载的 DCE 合约数据，理由见 `PRICE_SOURCES`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class NewsSource:
    id: str
    """用于 fixture 文件名，也用于简报里标注该条新闻来自哪家。"""

    name: str
    """展示名。原样进入引用块。"""

    url: str


NEWS_SOURCES: tuple[NewsSource, ...] = (
    NewsSource(id="mining-com", name="MINING.COM", url="https://www.mining.com/feed/"),
    NewsSource(
        id="australian-mining",
        name="Australian Mining",
        url="https://www.australianmining.com.au/feed/",
    ),
)

#: 抓**文章页**时只认这几家主机。`mining.com` 的文章页对本仓库返回 404（实测），
#: 抓它只会存下一张"页面不存在"的 HTML —— 那比没有更糟：它让"文章取到了"看起来
#: 成立。列表放在这里而不是抓取脚本里，因为它是**数据源事实**，不是脚本细节。
ARTICLE_HOSTS: frozenset[str] = frozenset({"www.australianmining.com.au"})


# ---------------------------------------------------------------------------
# 价格源
# ---------------------------------------------------------------------------

QuoteFormat = Literal["gfex_daily", "sina_kline"]
"""行情接口的**形状**。它同时决定怎么发请求和怎么解析：

- `gfex_daily`：POST 表单带 `trade_date`，一次只回**一天**的行。
- `sina_kline`：GET，一次回**全部历史**的日 K 线。

把形状做成登记表里的一个字段，而不是在 adapter 里 `if commodity == "lithium"`，
是为了让"加一个品种"只改这张表、不碰逻辑。
"""

#: GFEX 日行情接口。**必须是 POST** —— 同一路径用 GET 会被 WAF 挡成 520（实测）。
GFEX_DAY_QUOTES_URL = "http://www.gfex.com.cn/u/interfacesWebTiDayQuotes/loadList"

#: 新浪财经的日 K 线接口。JSONP 包裹，返回品种的**全部**历史日线。
#:
#: 路径里 `={symbol}` 后面那个 `/` **不能少** —— 少了它服务端会回
#: `{"__ERRORMSG":"Invalid service name"}`，而且**照样是 200**，于是坏 URL 会伪装成
#: "这个品种没数据"。`tests/test_price_parsers.py` 里有一条盯着这个响应体。
SINA_KLINE_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}=/"
    "InnerFuturesNewService.getDailyKLine?symbol={symbol}"
)


@dataclass(frozen=True, slots=True)
class PriceSource:
    """一个品种的行情从哪儿来、怎么取、怎么读。

    `quote_url`（取数接口）与 `page_url`（行情页）**分开**是刻意的：接口地址往往
    不是人能打开的页面 —— GFEX 的接口是 POST 的 JSON，用浏览器点开只会看到报错。
    所以引用块里给人看的是 `page_url`，`quote_url` 只承担"数据取自哪里"的追溯。
    """

    commodity: str
    exchange: str
    """合约所在的交易所。注意它**不一定**等于数据的发布方，见 `PRICE_SOURCES` 的说明。"""

    symbol: str
    """交易所的品种代码（`lc` / `I0`）。GFEX 的合约代码还要拼上交割月。"""

    currency: str
    unit: str
    quote_format: QuoteFormat
    quote_url: str
    page_url: str
    delayed: bool
    """数据源**固有**的延迟披露。不是回退标志 —— 回退一律看 `as_of < requested_date`
    （ADR-0004）。DCE 与 GFEX 的日行情都是当日发布，所以是 `False`。"""


PRICE_SOURCES: dict[str, PriceSource] = {
    "lithium": PriceSource(
        commodity="lithium",
        exchange="GFEX",
        symbol="lc",
        currency="元",
        unit="吨",
        quote_format="gfex_daily",
        quote_url=GFEX_DAY_QUOTES_URL,
        page_url="http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml",
        delayed=False,
    ),
    # 铁矿石：**合约是 DCE 的，数据是新浪财经转载的** —— 这是本仓库对工单 03
    # "铁矿石路由到 DCE" 的一处**实测导致的偏离**，不是随手换源：
    # `www.dce.com.cn` 对本环境的所有 HTTP 客户端（含真 Chrome）返回 412 挑战页，
    # 拿不到官方行情。新浪的日 K 线里载的**就是 DCE 的 i 合约**，且两处可交叉核对：
    # 2026-10-08 的结算价，GFEX 官方 `clearPrice`、新浪 `s` 字段同为 121540
    # （碳酸锂主力 2701，持仓量 409678 两边一致）—— 见 `tests/test_price_parsers.py`。
    # 引用块里 `publisher` 记的是新浪财经，不是 DCE：数据的**发布方**是谁就写谁。
    "iron_ore": PriceSource(
        commodity="iron_ore",
        exchange="DCE",
        symbol="I0",
        currency="元",
        unit="吨",
        quote_format="sina_kline",
        quote_url=SINA_KLINE_URL.format(symbol="I0"),
        page_url="https://finance.sina.com.cn/futures/quotes/I0.shtml",
        delayed=False,
    ),
}
