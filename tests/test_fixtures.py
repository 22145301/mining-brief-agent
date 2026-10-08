"""fixture 仓库自身的不变量 —— 录播集的**完整性**（ADR-0002）。

这一组不测业务逻辑，测的是"回放的前提还在不在"。它挡的是一类很隐蔽的事故：
文件被编辑器改过、被 .gitattributes 的换行符转换改过、抓了新的一批却没更新清单。
这三种坏法都不会让业务测试变红，只会让回放悄悄地和真实抓取脱钩 ——
而"回放 == 真实抓取"正是默认路径敢离线跑的全部依据。

换行符那一条值得单独说：仓库默认 `* text=auto eol=lf`，如果不给 `fixtures/**` 加
`-text`，clone 出来的 HTML 会被 CRLF→LF，sha256 当场对不上，`FixtureStore.raw()`
会在**第一次读数时**抛 `FixtureMissing` —— 报错很响，但陌生人 clone 下来就跑不起来。
所以 `.gitattributes` 里那条 `fixtures/** -text` 是**功能性的**，不是洁癖。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mining_brief.datasources.fixtures import FixtureMissing, FixtureStore


def test_every_entry_in_the_manifest_has_a_file_on_disk(fixture_root: Path) -> None:
    store = FixtureStore(fixture_root)

    for entry in store.manifest.entries:
        assert (fixture_root / entry.path).exists(), f"清单列了 {entry.path}，文件却不在"


def test_every_recorded_body_still_matches_its_sha256(fixture_root: Path) -> None:
    """**逐字节**的承诺在这里被执行。

    `FixtureStore.raw()` 每次读都会校验，所以这条其实在别处已经被覆盖 —— 这里显式
    再跑一遍是为了让"完整性"这件事有个**独立的**报告点：坏了的时候，失败的名字是
    "fixture 校验和不符"，不是某个远处的业务断言。
    """
    store = FixtureStore(fixture_root)

    for entry in store.manifest.entries:
        body = (fixture_root / entry.path).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry.sha256, f"{entry.path} 被改动过"


def test_a_tampered_fixture_is_rejected_instead_of_returned(
    fixture_root: Path, tmp_path: Path
) -> None:
    """把 fixture 复制一份改一个字节，读它就**必须**失败。

    这条是上面那条的反面：只断言"现在是对的"挡不住"读的时候不校验"。
    """
    import shutil

    copy = tmp_path / "fixtures"
    shutil.copytree(fixture_root, copy)
    victim = next(entry for entry in FixtureStore(copy).manifest.entries if not entry.is_binary)
    target = copy / victim.path
    target.write_bytes(target.read_bytes() + b"<!-- tampered -->")

    with pytest.raises(FixtureMissing, match="校验和不符"):
        FixtureStore(copy).raw(victim.url)


def test_the_anchor_is_a_fixed_time_not_now(fixture_root: Path) -> None:
    """锚点是**冻结**的。它一动，所有已有回放的时间基准就跟着动，
    "同一份录播产出同一份日报"当场失效（ADR-0002）。"""
    from datetime import UTC, datetime, timedelta

    anchor = FixtureStore(fixture_root).anchor_at

    assert anchor.tzinfo is not None, "锚点必须带时区，否则窗口计算会跟本机时区走"
    assert anchor < datetime.now(UTC) + timedelta(days=1)
    assert anchor.year >= 2024, "锚点不像一个真实抓取时间"


def test_the_two_news_feeds_are_both_recorded(fixture_root: Path) -> None:
    """新闻是唯一有内容的源。少了一家的 feed，"新闻摘要"就少一半而没人知道。"""
    from mining_brief.config.sources import NEWS_SOURCES

    store = FixtureStore(fixture_root)

    missing = [source.url for source in NEWS_SOURCES if not store.has(source.url)]
    assert missing == [], f"这些新闻源没有录播：{missing}"


def test_the_article_pages_are_all_from_the_hosts_we_can_actually_fetch(fixture_root: Path) -> None:
    """文章页只抓 australianmining —— mining.com 的文章页对本仓库返回 404（实测）。

    抓一张"页面不存在"的 HTML 存成 fixture 比没有更糟：它让"文章取到了"看起来成立。
    反面见 `tests/test_news_tool.py::test_mining_com_articles_are_not_recorded_because_they_404`。
    """
    from mining_brief.config.sources import ARTICLE_HOSTS

    store = FixtureStore(fixture_root)

    hosts = {
        entry.url.split("/")[2]
        for entry in store.manifest.entries
        if entry.path.startswith("articles/")
    }
    assert hosts, "一条文章 fixture 都没有，说明这条断言在空转"
    assert hosts <= ARTICLE_HOSTS, f"有不该抓的主机混进来了：{hosts - ARTICLE_HOSTS}"
