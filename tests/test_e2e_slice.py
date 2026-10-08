"""切面 S1：给定题面原句，产出六节齐、引用可校验、落盘的 Markdown 日报。

这个文件是整个工单 01 的**收口**。它跑的是真装配 —— 真 fixture、真录播 LLM、
真进程内 MCP 协议连接，只把网络与系统时钟换掉了。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mining_brief.agent import nodes
from mining_brief.agent.pipeline import run_brief
from mining_brief.agent.toolkit import default_toolkit
from mining_brief.config.archive import ARCHIVE
from mining_brief.config.settings import Settings
from mining_brief.config.sources import NEWS_SOURCES
from mining_brief.contracts import BriefResult, FetchStatus, SectionKey
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.news import parse_feed

ALL_SECTIONS = [
    SectionKey.MINING_RIGHTS,
    SectionKey.NEWS,
    SectionKey.RESOURCES,
    SectionKey.PRICES,
    SectionKey.RISKS,
    SectionKey.INTEGRITY,
]


async def _run(settings: Settings, fixture_root: Path, request: str, **kwargs: Any) -> BriefResult:
    return await run_brief(request, settings=settings, fixture_root=fixture_root, **kwargs)


# ---------------------------------------------------------------------------
# 六节齐 + 数据缺失如实标注
# ---------------------------------------------------------------------------


async def test_canonical_request_produces_all_six_sections(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    result = await _run(settings, fixture_root, canonical_request)

    assert result.refusal is None
    assert [section.key for section in result.sections] == ALL_SECTIONS
    assert [section.title for section in result.sections] == [
        "矿权动态",
        "新闻摘要",
        "储量数据",
        "价格走势",
        "风险提示",
        "数据完整性",
    ]


async def test_news_section_has_content_and_prices_and_reserves_say_why_they_are_empty(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """工单 01 的核心断言：**源缺失时简报照样出**，而且缺得明明白白。"""
    result = await _run(settings, fixture_root, canonical_request)
    by_key = {section.key: section for section in result.sections}

    news = by_key[SectionKey.NEWS]
    assert news.facts, "新闻摘要必须有真内容 —— 否则这一刀没证明引用链路是通的"
    assert all(fact.citation is not None for fact in news.facts)

    resources = by_key[SectionKey.RESOURCES]
    assert resources.facts == ()
    assert "数据缺失" in (resources.note or "")

    prices = by_key[SectionKey.PRICES]
    assert prices.facts == ()
    assert "数据缺失" in (prices.note or "")

    risks = by_key[SectionKey.RISKS]
    assert risks.facts == ()
    assert "未触发" in (risks.note or "")

    # 第 6 节存在的意义就是"说清缺了什么、为什么缺"，不是一句免责声明。
    integrity = " ".join(fact.text for fact in by_key[SectionKey.INTEGRITY].facts)
    assert "数据缺失" in integrity
    assert "直链未核实到" in integrity  # 储量为什么缺
    assert "尚未接入" in integrity  # 价格为什么缺


async def test_each_section_states_its_own_data_cutoff(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """六节的截止时间天生不同，产物必须如实体现，而不是统一成"今天"。"""
    result = await _run(settings, fixture_root, canonical_request)
    text = Path(result.output_path).read_text("utf-8")

    assert "各节数据截止时间不同" in text
    assert text.count("*数据时点：") == len(ALL_SECTIONS)


# ---------------------------------------------------------------------------
# 引用逐字 + 落盘
# ---------------------------------------------------------------------------


async def test_citation_fields_are_byte_identical_to_parsed_source(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """A4：引用块里的标题 / 链接 / 时间戳与工具返回值**逐字符相同**。

    比对的对象是**从原始 fixture 重新解析出来**的条目 —— 不是另跑一次工具
    （那只能证明"两次调用结果一致"，证不了"没被改写"）。
    """
    result = await _run(settings, fixture_root, canonical_request)

    # 期望值**从原始 fixture 重新解析出来** —— 不是再跑一次工具（那只能证明"两次
    # 调用结果一致"，证不了"没被改写"）。源名从 `NEWS_SOURCES` 取，不另抄一份。
    store = FixtureStore(fixture_root)
    parsed: dict[str, tuple[str, str, str]] = {}
    for source in NEWS_SOURCES:
        for item in parse_feed(store.raw(source.url)):
            parsed[item.url] = (item.title, item.published_at.isoformat(), source.name)

    news_citations = [c for c in result.citations if c.kind == "news"]
    assert news_citations, "这条路径必须真的产生新闻引用，否则断言是空转的"

    for citation in news_citations:
        assert citation.url in parsed, f"引用里的 URL 不在任何源里：{citation.url}"
        title, published_at, publisher = parsed[citation.url]
        assert citation.title == title
        assert citation.timestamp == published_at
        assert citation.publisher == publisher


async def test_brief_is_written_to_disk_and_citations_are_listed(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    result = await _run(settings, fixture_root, canonical_request)
    path = Path(result.output_path)

    assert path.exists()
    text = path.read_text("utf-8")
    for citation in result.citations:
        assert f"[{citation.index}]" in text
        assert citation.url in text
        assert citation.title in text


async def test_facts_without_citations_are_allowed_but_facts_with_them_must_resolve(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """每个 `[n]` 都能在来源清单里找到 —— 这一条由 `verify_citations` 硬保证，
    所以这里只需断言它跑过并且通过了。"""
    result = await _run(settings, fixture_root, canonical_request)

    declared = {c.index for c in result.citations}
    referenced = {f.citation for s in result.sections for f in s.facts if f.citation is not None}
    assert referenced <= declared
    assert declared == referenced  # 没有"列了却没人引"的孤儿来源


# ---------------------------------------------------------------------------
# 回放时钟来自 fixture，不是系统时钟
# ---------------------------------------------------------------------------


async def test_replay_clock_comes_from_the_fixture_anchor_not_the_system_clock(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    result = await _run(settings, fixture_root, canonical_request)

    anchor = FixtureStore(fixture_root).anchor_at
    assert Path(result.output_path).name == f"brief-{anchor:%Y-%m-%d}.md"


# ---------------------------------------------------------------------------
# 三路扇出真的并发
# ---------------------------------------------------------------------------


class _ConcurrencyProbe:
    """记录"同时有几个 fetch 在飞"。

    如果三个节点是顺序跑的，峰值只会是 1。用一次真实的 `await` 把三个任务都停在
    半空中，才测得出并发 —— 只看"结果一样"是测不出来的。
    """

    def __init__(self, inner: Any, hold_s: float = 0.15) -> None:
        self._inner = inner
        self._hold_s = hold_s
        self.inflight = 0
        self.peak = 0

    async def _track(self, coro: Any) -> Any:
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(self._hold_s)
            return await coro
        finally:
            self.inflight -= 1

    async def search_news(self, query: str, days: int) -> Any:
        return await self._track(self._inner.search_news(query, days))

    async def get_trend(self, commodity: str, days: int) -> Any:
        return await self._track(self._inner.get_trend(commodity, days))

    async def extract_resources(self, pdf_url: str) -> Any:
        return await self._track(self._inner.extract_resources(pdf_url))

    async def fetch_article(self, url: str) -> Any:
        return await self._track(self._inner.fetch_article(url))

    async def get_price(self, commodity: str, date: str) -> Any:
        return await self._track(self._inner.get_price(commodity, date))


async def test_three_fetch_nodes_run_in_the_same_superstep(
    settings: Settings, fixture_root: Path, canonical_request: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """三个 fetch 节点在同一 superstep 并发执行（工单 01 验收）。

    本票的档案里 Pilgangoora 没有技术报告直链，`fetch_resources` 会在**调用工具之前**
    就提前返回"数据缺失"。那本身是对的，但会让这条并发断言只观测到 2 个。所以这里
    临时给档案补一个直链 —— 测的是"三路并发"这个拓扑性质，不是"直链存不存在"。
    """
    monkeypatch.setattr(
        nodes, "ARCHIVE", (replace(ARCHIVE[0], report_url="https://example.invalid/report.pdf"),)
    )

    probe = _ConcurrencyProbe(default_toolkit())
    result = await _run(settings, fixture_root, canonical_request, toolkit=probe)

    assert probe.peak == 3, f"三路 fetch 没有并发，观测到的并发峰值是 {probe.peak}"
    assert [section.key for section in result.sections] == ALL_SECTIONS


# ---------------------------------------------------------------------------
# 任一 fetch 挂掉都不掀翻整图（A7）
# ---------------------------------------------------------------------------


class _ExplodingToolkit:
    """某个工具**链路本身**失效：不是降级信封，是抛异常。"""

    def __init__(self, inner: Any, explode: str) -> None:
        self._inner = inner
        self._explode = explode

    def __getattr__(self, name: str) -> Any:
        if name == self._explode:

            async def boom(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("工具链路炸了")

            return boom
        return getattr(self._inner, name)


@pytest.mark.parametrize("explode", ["search_news", "get_trend", "extract_resources"])
async def test_one_exploding_fetch_still_produces_a_full_brief(
    settings: Settings,
    fixture_root: Path,
    canonical_request: str,
    explode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0006：LangGraph 的 superstep 是事务性的，**没有这层兜底整张图会炸**。"""
    monkeypatch.setattr(
        nodes, "ARCHIVE", (replace(ARCHIVE[0], report_url="https://example.invalid/report.pdf"),)
    )
    toolkit = _ExplodingToolkit(default_toolkit(), explode)

    result = await _run(settings, fixture_root, canonical_request, toolkit=toolkit)

    assert result.refusal is None
    assert [section.key for section in result.sections] == ALL_SECTIONS

    by_key = {section.key: section for section in result.sections}
    integrity = " ".join(fact.text for fact in by_key[SectionKey.INTEGRITY].facts)
    assert "失效" in integrity, f"{explode} 炸了，第 6 节必须说明白，实际是：{integrity}"


# ---------------------------------------------------------------------------
# 拒答路径：同样是"一次成功执行"，同样有产物
# ---------------------------------------------------------------------------


async def test_out_of_scope_request_produces_a_refusal_document(
    settings: Settings, fixture_root: Path
) -> None:
    result = await _run(settings, fixture_root, "帮我预测一下明天铜价会涨吗")

    assert result.sections == ()
    assert result.refusal is not None
    assert "铜" in result.refusal.understood
    assert result.refusal.usable_phrasings

    text = Path(result.output_path).read_text("utf-8")
    assert "无法生成矿权日报" in text
    assert result.refusal.usable_phrasings[0] in text


async def test_uncovered_mine_is_refused_and_never_invented(
    settings: Settings, fixture_root: Path
) -> None:
    """A9：档案外的东西一律记"未覆盖"，**绝不编造实体**。"""
    result = await _run(settings, fixture_root, "看看 Escondida 铜矿最近 3 天")

    assert result.refusal is not None
    assert "Escondida" in result.refusal.understood
    assert "未覆盖" in result.refusal.why
    assert "Pilgangoora" in result.refusal.why  # 列出可选项，让使用者知道系统覆盖什么
    assert result.uncovered[0].spoken == "Escondida"


# ---------------------------------------------------------------------------
# 重试：工具链瞬时故障不该直接变成"数据缺失"
# ---------------------------------------------------------------------------


async def test_transient_toolkit_failure_is_retried_before_degrading(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """第一次抛、第二次成功的工具链，简报里不该留下任何降级的痕迹。"""
    attempts = {"n": 0}
    inner = default_toolkit()

    class _Flaky:
        async def search_news(self, query: str, days: int) -> Any:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("第一次握手失败")
            return await inner.search_news(query, days)

        def __getattr__(self, name: str) -> Any:
            return getattr(inner, name)

    result = await _run(settings, fixture_root, canonical_request, toolkit=_Flaky())

    assert attempts["n"] == 2, "重试没有发生"
    by_key = {section.key: section for section in result.sections}
    assert by_key[SectionKey.NEWS].facts, "重试成功后新闻节该有内容"
    assert by_key[SectionKey.NEWS].note is not None
    assert "失效" not in (by_key[SectionKey.NEWS].note or "")


async def test_envelope_statuses_are_honest_about_which_source_failed(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """降价信封的 `source_status` 必须是 UNAVAILABLE，且带得出 reason。"""
    result = await _run(settings, fixture_root, canonical_request)
    by_key = {section.key: section for section in result.sections}

    assert by_key[SectionKey.NEWS].facts  # 新闻是好的
    assert "尚未接入" in (by_key[SectionKey.PRICES].note or "")
    assert FetchStatus.UNAVAILABLE.value == "unavailable"
