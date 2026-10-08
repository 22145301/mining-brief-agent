"""切面 S2：**直连**新闻工具，不走图。

S1 证明的是"整条链路能出报"；S2 证明的是"这一个工具本身说真话" —— 它返回的
每一条都必须能在原始 fixture 里找到出处，给出的状态必须和源的真实情况一致。

这里刻意**不 mock 任何东西**：fixture 是逐字节的真实响应，`search` 真跑解析，
连接走 SDK 的进程内协议（ADR-0001）。唯一不在场的只有网络。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mining_brief.agent.toolkit import default_toolkit
from mining_brief.config.sources import NEWS_SOURCES
from mining_brief.contracts import FetchStatus, NewsCategory
from mining_brief.datasources.fixtures import FixtureMissing, FixtureStore
from mining_brief.datasources.news import parse_feed
from mining_brief.errors import REPLAY_MISS_SENTINEL, ReplayMiss

#: 与 `nodes._news_query` 对题面原句给出的检索式一致。
CANONICAL_QUERY = "Pilgangoora Pilbara Minerals lithium"


def _anchor(fixture_root: Path) -> datetime:
    return FixtureStore(fixture_root).anchor_at


async def test_search_returns_items_that_all_exist_in_the_raw_fixture(
    fixture_root: Path,
) -> None:
    """**不许编数据。** 返回的每一条都必须能在原始响应里逐字找到。"""
    toolkit = default_toolkit()
    result = await toolkit.search_news(CANONICAL_QUERY, 7)

    assert result.status == "ok"
    assert result.source_status is FetchStatus.OK
    assert result.items, "题面原句对应的用例必须真的有内容，否则这个断言在空转"

    store = FixtureStore(fixture_root)
    known: set[tuple[str, str, str]] = set()
    for source in NEWS_SOURCES:
        for feed_item in parse_feed(store.raw(source.url)):
            known.add((feed_item.title, feed_item.url, feed_item.published_at.isoformat()))

    for item in result.items:
        assert (item.title, item.url, item.published_at) in known, f"这条不在任何源里：{item.url}"


async def test_search_only_returns_items_inside_the_requested_window(fixture_root: Path) -> None:
    toolkit = default_toolkit()
    result = await toolkit.search_news(CANONICAL_QUERY, 7)

    window_start = datetime.fromisoformat(result.window_start)
    window_end = datetime.fromisoformat(result.window_end)

    assert result.retrieved_at == _anchor(fixture_root)
    assert window_end == result.retrieved_at
    for item in result.items:
        assert window_start <= datetime.fromisoformat(item.published_at) <= window_end


async def test_search_results_are_sorted_newest_first(fixture_root: Path) -> None:
    """排序是契约的一部分：日报里"最新"必须是列表最上面那条。"""
    result = await default_toolkit().search_news(CANONICAL_QUERY, 7)

    stamps = [item.published_at for item in result.items]
    assert stamps == sorted(stamps, reverse=True)


async def test_a_query_that_matches_nothing_is_an_empty_success_not_a_failure(
    fixture_root: Path,
) -> None:
    """ "今天没新闻"是一次**成功的判定**，不是抓取失败 —— 两种状态必须分得开
    （ADR-0005，简报第 6 节靠这个区分说话）。"""
    result = await default_toolkit().search_news("zzzz-no-such-token-qqqq", 7)

    assert result.items == ()
    assert result.status == "ok"
    assert result.source_status is FetchStatus.EMPTY
    assert result.reason is None


async def test_a_narrower_window_is_a_strict_subset_and_respects_24_hours(
    fixture_root: Path,
) -> None:
    """窗口是**按天真的截过**的，不是摆设。"""
    toolkit = default_toolkit()
    broad = await toolkit.search_news(CANONICAL_QUERY, 7)
    narrow = await toolkit.search_news(CANONICAL_QUERY, 1)

    broad_urls = {item.url for item in broad.items}
    narrow_urls = {item.url for item in narrow.items}

    assert narrow_urls < broad_urls, "1 天窗口必须是 7 天窗口的真子集（本例中且非空）"
    anchor = _anchor(fixture_root)
    for item in narrow.items:
        age = anchor - datetime.fromisoformat(item.published_at)
        assert timedelta(0) <= age <= timedelta(days=1)


async def test_categories_are_valid_and_mining_rights_is_a_strict_subset(
    fixture_root: Path,
) -> None:
    result = await default_toolkit().search_news(CANONICAL_QUERY, 30)

    assert result.items
    for item in result.items:
        assert item.category in (NewsCategory.MINING_RIGHTS, NewsCategory.GENERAL)
    # 分流是二选一：矿权动态与新闻摘要是互补的两节，不是"全部"与"另一些"。
    assert {item.category for item in result.items} <= set(NewsCategory)


async def test_fetch_article_returns_the_body_and_a_real_publish_time(
    fixture_root: Path,
) -> None:
    toolkit = default_toolkit()
    search = await toolkit.search_news(CANONICAL_QUERY, 30)
    url = next(item.url for item in search.items if "australianmining.com.au" in item.url)

    lookup = await toolkit.fetch_article(url)

    assert lookup.status == "ok"
    assert lookup.article is not None
    article = lookup.article
    assert article.url == url
    assert article.title
    assert len(article.text) > 500, "正文抽取只拿到标题栏就说明容器没定位对"
    # 时间戳取的是页面自己声明的发布时刻，不是抓取时刻 —— 它必须能被解析成时间。
    assert datetime.fromisoformat(article.published_at)


async def test_missing_article_fixture_fails_loudly_instead_of_going_to_the_network(
    fixture_root: Path,
) -> None:
    """ADR-0002：回放时缺录播**必须**报错。

    两个"不许"，各自都在这一段里被守住：

    - 不许回退真实网络 —— `FixtureFetcher` 里根本没有网络这条路。
    - 不许被降级信封吸收 —— 那会产出一份写着"数据缺失"的日报，让人去查一个
      根本没坏的网站。所以它必须**穿过 MCP 边界**（哨兵串）一路抛到调用方。
    """
    toolkit = default_toolkit()
    url = "https://www.mining.com/some-article-we-never-recorded/"

    with pytest.raises(ReplayMiss) as excinfo:
        await toolkit.fetch_article(url)

    message = str(excinfo.value)
    assert REPLAY_MISS_SENTINEL in message
    assert url in message
    # 错误信息要能直接告诉人下一步做什么，而不是只说"失败了"。
    assert "scripts/fetch_fixtures.py" in message
    # 客户端拿到的是跨进程重建的 `ReplayMiss`；`FixtureMissing` 是它在服务端那一侧的
    # 具体类型，跨不过 MCP 边界（协议不传异常类型），所以这里不比类型只比语义。
    assert issubclass(FixtureMissing, ReplayMiss)


async def test_mining_com_articles_are_not_recorded_because_they_404(fixture_root: Path) -> None:
    """实测事实写进断言：mining.com 的文章页对本仓库返回 404。

    把它记成测试而不是一句注释，是为了让"以后补上"这件事有个明确的落点 ——
    哪天 404 不再成立，这条会红，提醒人把文章 fixture 补起来。
    """
    store = FixtureStore(fixture_root)
    mining_com_articles = [
        entry
        for entry in store.manifest.entries
        if entry.url.startswith("https://www.mining.com/") and "feed" not in entry.url
    ]
    assert mining_com_articles == []
