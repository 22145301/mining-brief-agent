"""数据源登记表 —— **非密钥配置**（ADR-0008）。

只放 URL、名称、交易所这类公开信息；密钥与代理一律走环境变量。

已实测的网络事实（不要再当成假设，改代码前先复跑一遍）：
- `mining.com/feed/` 在本机**必须走代理**才返回 200，直连被 CloudFront 403。
- `australianmining.com.au/feed/` 直连与走代理都能取到。
- `pls.com.au`（Pilbara Minerals 官网）在本机**域名解析失败**，因此新闻源里没有它。
"""

from __future__ import annotations

from dataclasses import dataclass


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
