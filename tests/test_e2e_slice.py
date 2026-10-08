"""切面 S1：给定题面原句，产出六节齐、引用可校验、落盘的 Markdown 日报。

这个文件是整个工单 01 的**收口**。它跑的是真装配 —— 真 fixture、真录播 LLM、
真进程内 MCP 协议连接，只把网络与系统时钟换掉了。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mining_brief.agent import nodes
from mining_brief.agent.llm import LLMClient, LLMError, build_llm_client
from mining_brief.agent.narratives import lead_is_grounded, narrative_payload
from mining_brief.agent.pipeline import run_brief
from mining_brief.agent.toolkit import default_toolkit
from mining_brief.config.archive import ARCHIVE
from mining_brief.config.reports import PILBARA_CET
from mining_brief.config.settings import Settings
from mining_brief.config.sources import NEWS_SOURCES
from mining_brief.contracts import (
    SECTION_TITLES,
    BriefResult,
    FetchStatus,
    NewsCategory,
    NewsItem,
    SectionKey,
)
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.news import parse_feed
from mining_brief.datasources.prices import trading_date
from mining_brief.datasources.resources import LiveResourceSource, ResourceAdapter
from mining_brief.servers import mineral_pdf_server
from mining_brief.servers.runtime import Runtime

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


async def test_all_three_sources_have_content_after_ticket_05(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """工单 05 之后，三个源**全部在位**：新闻有事实、储量有数字、价格有行情。

    这条同时接手了工单 01 留下的那个任务：证明**接通与未接通在同一次装配里各就各位**
    —— 三者不能互相污染（把某一节的降级文案漏进另一节，或反过来）。工单 01 时储量还
    没接通，这条记的是"缺得明明白白"；现在它记的是"接上了，而且数字带着出处"。
    """
    result = await _run(settings, fixture_root, canonical_request)
    by_key = {section.key: section for section in result.sections}

    news = by_key[SectionKey.NEWS]
    assert news.facts, "新闻摘要必须有真内容 —— 否则这一刀没证明引用链路是通的"
    assert all(fact.citation is not None for fact in news.facts)

    prices = by_key[SectionKey.PRICES]
    assert len(prices.facts) == 1, "本次范围内只有锂一个品种（见 config/archive.py）"
    assert "锂" in prices.facts[0].text
    assert "117300.0" in prices.facts[0].text
    assert "GFEX" in prices.facts[0].text
    assert prices.facts[0].citation is not None, "价格也要能回溯到来源"
    # 有内容就不该再挂一句降级说明 —— 空有事实的"数据缺失"是自相矛盾。
    assert prices.note is None
    # **截止时间必须是最后一个交易日，不是"今天"**：锚点在北京时间已是 10-09，
    # 而 10-09 的行情当天尚未发布。把 10-09 写成价格时点就是编了一个还没发生的价。
    assert prices.as_of == "2026-10-08"
    assert prices.as_of != trading_date(FixtureStore(fixture_root).anchor_at).isoformat()

    resources = by_key[SectionKey.RESOURCES]
    assert len(resources.facts) == 3, "Pilgangoora 那张 JORC 表有三行"
    assert all(fact.citation is not None for fact in resources.facts), "储量数字也要能翻回那份 PDF"
    # 事实上的 `citation` 是来源清单里的**序号**（见 `Fact`），要顺着它去清单里取。
    by_index = {citation.index: citation for citation in result.citations}
    cited = by_index[resources.facts[0].citation or 0]
    assert cited.url == PILBARA_CET.pdf_url
    assert cited.publisher == "JORC", "报告体系要跟着引用一起露出来"
    # 报告日期来自**文档**（表下那句 "as at 30 June 2022"），不是我们的抓取时点。
    assert resources.as_of == "2022-06-30"
    # 这一节的 `note` 是**释义**（报告体系 + 资源量与储量之别），不是降级说明 ——
    # 所以这里不能要求 `note is None`，而要钉住"它没在说任何东西缺失"。区分这两类
    # note 是有意义的：把释义误当降级删掉，读者就不知道 Indicated 不是储量；
    # 反过来把降级说明当成释义放过去，一处真缺口就会被一段像模像样的话盖住。
    note = resources.note or ""
    assert "JORC" in note, "报告体系要跟着数字一起露出来"
    assert "资源量" in note, "节内要说清哪些是资源量"
    for missing in ("数据缺失", "未取到", "尚未", "失效"):
        assert missing not in note, f"数字都在，note 里不该出现「{missing}」"

    reserve_text = " ".join(fact.text for fact in resources.facts)
    assert "资源量" in reserve_text, "这三行都是资源量，节内必须标出来"
    assert "储量" not in reserve_text, "Measured / Indicated / Inferred 不是储量，不许混称"

    risks = by_key[SectionKey.RISKS]
    assert risks.facts == ()
    assert "未触发" in (risks.note or "")

    # 第 6 节存在的意义就是"说清缺了什么、为什么缺"，不是一句免责声明。
    integrity = " ".join(fact.text for fact in by_key[SectionKey.INTEGRITY].facts)
    assert integrity.count("已取到") >= 3, "新闻 / 储量 / 价格三个源都该报「已取到」"
    # 锚定时刻三源齐备，所以第 6 节**不该**再说任何东西缺失 —— 一句过期的免责声明
    # 比没有更糟：它会让人以为去看别处也拿不到数。
    assert "数据缺失" not in integrity
    assert "直链未核实到" not in integrity
    assert "尚未接入" not in integrity


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
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """三个 fetch 节点在同一 superstep 并发执行（工单 01 验收）。

    工单 05 之后档案里有了真实的技术报告直链，三路**都会真的去调工具**，所以这条
    断言不再需要临时补一个直链才能观测到 3 —— 观测对象就是生产装配本身。
    """
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
) -> None:
    """ADR-0006：LangGraph 的 superstep 是事务性的，**没有这层兜底整张图会炸**。

    工单 05 之后三个源全部在位，这一条才真正成为 A7 的那一问 —— "三个源都在、人为让
    任一源故障"（工单 05 验收最后一条）。在此之前 `extract_resources` 那一遍是在一个
    假直链上炸的，考不到真实装配。
    """
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


#: 用来扫产物有没有幻觉实体的词。与 `tests/test_archive.py` 的负样本同源但**不共用** ——
#: 那边考的是 `match_entry` 会不会把它们落进档案，这边考的是"编造出来的实体有没有
#: 漏进产物"，两件事，所以两处各写一份、各自演进。
_OUTSIDE_THE_ARCHIVE_PROBES = ("Escondida", "Grasberg", "Olympic Dam", "Bougainville")


async def test_the_uncovered_path_puts_no_invented_entity_into_the_document(
    settings: Settings, fixture_root: Path
) -> None:
    """A9 的第二半：拒答文档**不是**简报，它一个字的事实都不该有。

    上一条断言的是"拒答说对了话"，这一条断言的是"拒答**没有**变成一份简报" ——
    少了它，一个"先拒答、又顺手出一份含幻觉实体的日报"的实现照样能让上一条全绿。
    """
    result = await _run(settings, fixture_root, "看看 Escondida 铜矿最近 3 天")

    text = Path(result.output_path).read_text("utf-8")
    assert result.sections == (), "拒答路径不该产出六节"
    assert result.citations == (), "拒答路径不该产出引用块"

    refusal = result.refusal
    assert refusal is not None

    # 拒绝理由里**当然**会写「Escondida」—— 那正是这次被拒的原因。要证明的不是
    # "这两个字不出现"，而是"它只出现在**说明为什么拒绝**的两个字段里，没有变成事实"。
    # 所以先把这两处摘掉，剩下的任何一次出现都只能是编造出来的内容。
    body = text.split("无法生成矿权日报", 1)[-1]
    residue = body.replace(refusal.understood, "").replace(refusal.why, "")
    leaks = [name for name in _OUTSIDE_THE_ARCHIVE_PROBES if name in residue]
    assert not leaks, (
        f"拒答文档的正文里出现了档案外实体：{leaks} —— 拒绝可以复述使用者说的话，"
        "但不能再吐出任何关于它的内容"
    )


# ---------------------------------------------------------------------------
# 降级缺省：听不懂 ≠ 拒答，它是一次**成功执行**，但必须自曝
# ---------------------------------------------------------------------------


class _IntentDeafLLM:
    """除了 `parse_intent` 一律照常转发给真回放客户端。

    **这不是"伪造一份录播"。** 被模拟的诱因（模型这次答不上来）本来就发生在运行时，
    真实世界里由网络超时或服务端 5xx 触发；这里只是把触发条件换成一个显式的桩子，
    被测的代码路径一字未改 —— `parse_intent` 的 `except` 分支 + 第 6 节的记一笔。
    录播文件不动，所以"回放缺录播会炸"那条纪律也没被绕过。
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.nodes: list[str] = []

    async def complete(
        self, *, node: str, key_input: Mapping[str, Any], system: str, user: str
    ) -> str:
        self.nodes.append(node)
        if node == "parse_intent":
            raise LLMError("模拟：模型服务这次没答上来")
        return await self._inner.complete(node=node, key_input=key_input, system=system, user=user)


async def test_unparsable_request_degrades_to_defaults_and_says_so(
    settings: Settings, fixture_root: Path, llm_fixture_root: Path
) -> None:
    """参数解析不出来 → 按缺省值出报，**并在第 6 节写明这是缺省值**（User Story 25）。

    后一半才是这条用例的要害。"按缺省值出报"很容易做到，难的是**不装作听懂了** ——
    一份按缺省值出的日报若不留痕，使用者只会看到一份看起来很正常的日报，
    而它其实没听懂自己的问题。
    """
    inner = build_llm_client(settings, fixture_root=llm_fixture_root)
    deaf = _IntentDeafLLM(inner)

    result = await _run(settings, fixture_root, "随便给我来一份", llm=deaf)

    assert deaf.nodes.count("parse_intent") == 1, "parse_intent 应当被调用且只调一次"
    assert result.refusal is None, "降级不是拒答 —— 交不出简报才是拒答"

    integrity = next(s for s in result.sections if s.key is SectionKey.INTEGRITY)
    marked = [fact.text for fact in integrity.facts if "降级" in fact.text]
    assert marked, "第 6 节没有记下降级这笔 —— 缺省值被伪装成了「听懂」"
    assert "LLMError" in marked[0], f"记一笔要说清是哪一类失败：{marked[0]}"

    text = Path(result.output_path).read_text("utf-8")
    assert "降级为缺省值" in text, "缺省值这件事必须出现在**产物**里，而不只在内存里"


# ---------------------------------------------------------------------------
# 重试：工具链瞬时故障不该直接变成"数据缺失"
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 风险提示：触发路径与未触发路径（工单 07 的两条端到端验收）
# ---------------------------------------------------------------------------


class _NewsWith:
    """把新闻工具换成一份**指定的**结果，其余照旧。

    这不绕过任何被测代码：被换掉的是"上游给了什么"，而这一节要考的是"拿到这样一份
    新闻之后，图说了什么"。规则的可见面本来就只有 `news.items[*]`，所以把那一份
    喂准了，测的才是规则引擎而不是今天的 RSS 恰好写了什么。
    """

    def __init__(self, inner: Any, items: tuple[NewsItem, ...]) -> None:
        self._inner = inner
        self._items = items

    async def search_news(self, query: str, days: int) -> Any:
        envelope = await self._inner.search_news(query, days)
        return envelope.model_copy(update={"items": self._items})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _item(title: str, summary: str = "", category: NewsCategory = NewsCategory.GENERAL) -> NewsItem:
    return NewsItem(
        title=title,
        url="https://example.invalid/story",
        source="MINING.COM",
        published_at="2026-10-07T03:00:00+00:00",
        summary=summary,
        category=category,
    )


async def test_a_triggering_rule_reaches_the_document_with_its_verbatim(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """切面 S1 的触发路径：一条规则被触发时，产物里能看到**规则 + 逐字原文 + 出处**。

    尾部那句"若该主体在 ASX 上市"是 R4 刻意留下的**条件从句** —— 我们判不了该新闻
    主体在哪上市，所以写成提醒而不是断言。这条把它钉住，免得日后有人"顺手"把它
    改写成一句看起来很确定的结论。
    """
    toolkit = _NewsWith(
        default_toolkit(),
        (
            _item(
                "Company reaffirms production target at Pilgangoora",
                "The company said it will hit guidance.",
            ),
            _item(
                "PEA shows robust economics at the project",
                "Initial capital cost estimate released.",
            ),
        ),
    )
    result = await _run(settings, fixture_root, canonical_request, toolkit=toolkit)
    risks = next(s for s in result.sections if s.key is SectionKey.RISKS)

    assert risks.facts, "这两条新闻该各触发一条规则"
    ids = {fact.text.split("]")[0].lstrip("[") for fact in risks.facts}
    assert ids == {"R3", "R4"}, f"触发的规则集不对：{ids}"

    body = "\n".join(fact.text for fact in risks.facts)
    assert "too speculative geologically" in body, "R3 的逐字原文没进产物"
    assert "low level of geological confidence" in body, "R4 的逐字原文没进产物"

    text = Path(result.output_path).read_text("utf-8")
    assert "若该主体在 ASX 上市" in text, "R4 的条件从句必须原样出现在产物里"
    assert "nssc.novascotia.ca" in text or "asx.com.au" in text, "出处要跟着一起露出来"
    assert not (risks.note or "").startswith("本次未触发"), "触发了就不该再说未触发"


async def test_a_run_with_no_triggering_news_says_so_explicitly(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """切面 S1 的未触发路径：**明说**未触发，而不是留一片空白。

    空白会被读成"今天没有风险"。而真实情况是"今天没有一条规则被触发" —— 这两句话
    对读者的含义完全不同，且后者才是我们知道的。
    """
    result = await _run(settings, fixture_root, canonical_request)
    risks = next(s for s in result.sections if s.key is SectionKey.RISKS)

    assert risks.facts == ()
    assert risks.note is not None
    assert "本次未触发任何风险信号" in risks.note

    text = Path(result.output_path).read_text("utf-8")
    assert "本次未触发任何风险信号" in text, "这件事必须出现在产物里，而不只在内存里"


async def test_hints_appear_in_the_document_separately_from_signals(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """切面 S3 的正向面：**提示**要出现在产物里，且与风险信号分开。

    "分开"不是排版洁癖：读者扫这一节时看的是行首 —— 风险信号每行带 `[R#]` 与法条，
    提示不带。把无原文的观察混进 `facts`，两者就再也分不清了，而"这一条到底有没有
    法条支撑"正是这一节唯一的价值所在。
    """
    toolkit = _NewsWith(
        default_toolkit(),
        (_item("Pilbara project suspended pending permit review"),),
    )
    result = await _run(settings, fixture_root, canonical_request, toolkit=toolkit)
    risks = next(s for s in result.sections if s.key is SectionKey.RISKS)

    assert risks.facts == (), "这条观察引不到原文，不该变成风险信号"
    assert risks.note is not None
    assert "提示（并非风险信号）" in risks.note
    assert "project suspended" in risks.note, "提示要引出那条新闻"
    assert "为什么它只是提示" in risks.note, "提示必须自曝为什么它不是信号"

    text = Path(result.output_path).read_text("utf-8")
    assert "提示（并非风险信号）" in text
    # 行首判据：`facts` 里的每一行都要带 `[R` 前缀，提示不在 `facts` 里。
    assert "[R" not in risks.note, "提示行不该带规则编号 —— 它不是信号"


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


class _RuntimeWithABrokenReport(Runtime):
    """把技术报告的观测地址换成清单里那条**真实录下来的** 503，其余照旧。

    手法与 `test_price_tool` 里的同款，理由也一样：只换一个地址、不动任何代码路径，
    所以它证明的是"链路对上游拒绝服务的反应"，不是"我们给测试开了个后门"。

    这里绕开了 `build_resource_source` 的模式分支（回放模式下它给的是
    `FrozenResourceSource`，压根不碰网络），直接构造 `LiveResourceSource` ——
    而它接的仍是回放的 `FixtureFetcher`，读的是那只录下来的 503。
    """

    def __init__(self, settings: Settings, fault_url: str) -> None:
        super().__init__(settings)
        self._fault_url = fault_url

    def resources(self) -> ResourceAdapter:
        return ResourceAdapter(
            LiveResourceSource(
                self.fetcher(),
                {PILBARA_CET.slug: replace(PILBARA_CET, pdf_url=self._fault_url)},
            )
        )


async def test_a_source_that_cannot_deliver_names_itself_and_its_reason(
    settings: Settings,
    fixture_root: Path,
    canonical_request: str,
    fault_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一个"取不到"的源要说清**为什么**，而不是一句干巴巴的"数据缺失"。

    样本是清单里那条**真实录下来的** 503：把储量源的观测地址换成它，跑完整一次日报。
    工单 05 之后三个源全部在位，所以这一条同时是 A7 的一条实证 —— 源故障不掀翻整张图，
    缺口被如实记进第六节。

    这个理由必须**同时**出现在它自己那一节和第六节里，而且是同一句话：只在一处
    出现，读者就得在两节之间来回翻，翻不到就会怀疑是漏了还是坏了。
    """
    monkeypatch.setattr(nodes, "ARCHIVE", (replace(ARCHIVE[0], report_url=fault_url),))
    monkeypatch.setattr(
        mineral_pdf_server, "_runtime_override", _RuntimeWithABrokenReport(settings, fault_url)
    )

    result = await _run(settings, fixture_root, canonical_request)
    by_key = {section.key: section for section in result.sections}

    assert result.refusal is None
    assert [section.key for section in result.sections] == ALL_SECTIONS
    assert by_key[SectionKey.NEWS].facts, "新闻是好的 —— 否则下面缺的就不止一处，断言会失焦"

    note = by_key[SectionKey.RESOURCES].note or ""
    assert note.startswith("数据缺失"), "缺就是缺，开头不许含糊"
    # 理由按分隔符切出来，不做字符集 strip —— 那会把理由里本来就有的标点一起啃掉。
    reason = note.split("——", 1)[-1].strip()
    assert len(reason) > 8, "光说'数据缺失'等于没说：读者无法据此去查任何一个地方"
    assert "503" in reason, "理由要指到具体那一步（这里：技术报告源回了 503）"

    integrity = " ".join(fact.text for fact in by_key[SectionKey.INTEGRITY].facts)
    assert reason in integrity, "同一个理由要在第六节里原样再出现一次，不能让读者去猜"

    assert FetchStatus.UNAVAILABLE.value == "unavailable"


# ---------------------------------------------------------------------------
# 导读：每节一句，且模型在这条链上没有生成事实的机会（工单 08）
# ---------------------------------------------------------------------------


async def test_every_section_carries_a_lead(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """六节各有一句导读，且落在**产物里** —— 不是只在内存的 state 上。

    这条同时是"忘了重录"的看门人（见 `nodes.narrate` 的第 2 条注释）：`LLMReplayMiss`
    刻意不被捕获，所以缺录播会在跑图时炸；而万一哪天有人把它改成降级，这条断言会
    立刻变红 —— 一份导读**全线消失**的日报不该看起来像一次正常执行。
    """
    result = await _run(settings, fixture_root, canonical_request)

    missing = [section.title for section in result.sections if not section.lead]
    assert not missing, f"这些节没有导读：{missing}"

    text = Path(result.output_path).read_text("utf-8")
    for section in result.sections:
        assert section.lead is not None
        assert f"> {section.lead}" in text, f"{section.title} 的导读没进产物"


async def test_a_lead_says_nothing_the_section_does_not_already_say(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """导读里的每个数字、每个拉丁词都能在该节数据里找到 —— 逐字，不做推断。

    这是"模型不参与事实生成"的可断言面。导读是**措辞**：它可以概括、可以排序，
    但不能引入任何一个该节没有的数字或外部名称。
    """
    result = await _run(settings, fixture_root, canonical_request)

    checked = 0
    for section in result.sections:
        assert section.lead is not None
        payload = narrative_payload(section)
        assert lead_is_grounded(section.lead, payload), (
            f"{section.title} 的导读里出现了该节数据以外的东西：{section.lead}"
        )
        checked += 1
    assert checked == len(ALL_SECTIONS), "六节都要被检查到，否则这条断言是空转的"


class _NarrateDeafLLM:
    """除了 `narrate` 一律照常转发给真回放客户端。

    与 `_IntentDeafLLM` 同一个道理：被模拟的诱因（模型这次没答上来）本来就发生在
    运行时，真实世界里由网络超时或服务端 5xx 触发。这里只是把触发条件换成一个显式
    的桩子，**录播文件不动** —— 所以"回放缺录播会炸"那条纪律没有被绕过。
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.nodes: list[str] = []

    async def complete(
        self, *, node: str, key_input: Mapping[str, Any], system: str, user: str
    ) -> str:
        self.nodes.append(node)
        if node == "narrate":
            raise LLMError("模拟：模型服务这次没答上来")
        return await self._inner.complete(node=node, key_input=key_input, system=system, user=user)


async def test_a_dead_narrator_costs_the_leads_and_nothing_else(
    settings: Settings, fixture_root: Path, llm_fixture_root: Path, canonical_request: str
) -> None:
    """模型挂了 → **只**损失导读，六节与引用全都在，第六节记一笔。

    这条是导读这个节点唯一允许的失败姿态。反过来做（没导读就不出报、或悄悄留空）
    都会让一次模型抖动升级成"今天没有日报"或"今天没有内容"。
    """
    deaf = _NarrateDeafLLM(build_llm_client(settings, fixture_root=llm_fixture_root))

    result = await _run(settings, fixture_root, canonical_request, llm=deaf)

    assert deaf.nodes.count("narrate") == len(ALL_SECTIONS), (
        "每一节都该试过一次 —— 一次失败不该连累其余五节"
    )
    assert result.refusal is None
    assert [section.key for section in result.sections] == ALL_SECTIONS, "六节一个都不能少"
    assert all(section.lead is None for section in result.sections), "导读应当整体欠奉"

    # 内容一字未变。逐节点名而不是 `all(section.facts)`：风险那节**本来就**可以是空的
    # （本次未触发任何规则），把它算成"内容丢了"是把一条正常的产物当成故障。
    by_key = {section.key: section for section in result.sections}
    for key in (SectionKey.NEWS, SectionKey.RESOURCES, SectionKey.PRICES, SectionKey.INTEGRITY):
        assert by_key[key].facts, f"{key} 的内容被导读的失败连带丢掉了"
    assert "本次未触发任何风险信号" in (by_key[SectionKey.RISKS].note or "")

    integrity = next(s for s in result.sections if s.key is SectionKey.INTEGRITY)
    marked = [fact.text for fact in integrity.facts if "没有导读" in fact.text]
    assert marked, "第 6 节没有记下这笔 —— 导读全线消失被伪装成了「本节就这么空」"
    # 三种失败姿态在产物里的措辞各不相同（调用失败 / 没给出可用的导读 / 越界），
    # 所以读者不必看日志也能知道是"模型没答上来"还是"模型编了东西"。
    assert "模型调用失败" in marked[0], f"记一笔要说清是哪一类失败：{marked[0]}"

    text = Path(result.output_path).read_text("utf-8")
    assert "没有导读" in text, "这件事必须出现在**产物**里，而不只在内存里"
    assert "本次未触发任何风险信号" in text, "其余各节照常，包括风险那节"


class _FabricatingLLM:
    """只在一节上编数字，其余照常转给回放客户端。

    用来钉住"接地校验读到越界时**只**丢那一节"：如果实现把它当成整条链的失败，
    另外五节的导读会被连带丢掉 —— 而那种写法在只看"有没有导读"的用例下看不出来。
    """

    def __init__(self, inner: LLMClient, *, title: str, invented: str) -> None:
        self._inner = inner
        self._title = title
        self._invented = invented

    async def complete(
        self, *, node: str, key_input: Mapping[str, Any], system: str, user: str
    ) -> str:
        if node == "narrate" and key_input.get("title") == self._title:
            return json.dumps({"lead": self._invented}, ensure_ascii=False)
        return await self._inner.complete(node=node, key_input=key_input, system=system, user=user)


async def test_an_invented_number_costs_only_that_one_section_its_lead(
    settings: Settings, fixture_root: Path, llm_fixture_root: Path, canonical_request: str
) -> None:
    """模型在一节里编了个该节没有的数字 → 那一节没有导读，其余五节照留。"""
    fabricating = _FabricatingLLM(
        build_llm_client(settings, fixture_root=llm_fixture_root),
        title=SECTION_TITLES[SectionKey.PRICES],
        invented="锂价收于 999999 元/吨。",
    )

    result = await _run(settings, fixture_root, canonical_request, llm=fabricating)

    by_key = {section.key: section for section in result.sections}
    assert by_key[SectionKey.PRICES].lead is None, "编了数字的那一节不该留下导读"
    for key in (SectionKey.NEWS, SectionKey.RESOURCES, SectionKey.RISKS, SectionKey.INTEGRITY):
        assert by_key[key].lead, f"{key} 被别节的越界连带丢掉了导读"

    integrity = by_key[SectionKey.INTEGRITY]
    marked = [fact.text for fact in integrity.facts if "没有导读" in fact.text]
    assert marked and SECTION_TITLES[SectionKey.PRICES] in marked[0]
    assert "越界" not in marked[0] and "以外的东西" in marked[0], marked[0]


# ---------------------------------------------------------------------------
# 不指定矿山与品种时，范围是整个档案（User Story 3）
# ---------------------------------------------------------------------------


async def test_an_unspecified_request_covers_the_whole_archive(
    settings: Settings, fixture_root: Path, llm_fixture_root: Path
) -> None:
    """**一句话里什么都不指定** → 8 座矿全在范围内，价格一节三项齐、各带自己的数据时点。

    这条补的是 03 / 04 两张工单各留了半格的验收项。当时档案里只有 Pilgangoora 一条，
    单矿请求的范围推出来只有锂，那半格写的是"在当前端到端路径上做不到"—— 06 号工单把
    档案补到 8 座矿 / 3 个品种之后它就能做到了，于是用**同一句已录播的话**把它补上：
    这句话不经过任何人工拼装的状态，走的就是 `parse_intent → … → render` 整条路。

    断言的是**数据**不是措辞：三行价格的事实文本由 `compute_signals` 从价格序列拼出
    （品种、数值、单位、交易所与合约、数据时点、延迟/回退限定词），与模型写什么无关，
    所以 `pytest --record-llm` 重录之后这条断言照样成立。
    """
    request = "给我生成一份今日简报"

    result = await _run(settings, fixture_root, request)

    assert result.refusal is None

    # 范围本身不进 `BriefResult`（契约里没有 scope 字段），但第六节会把"覆盖范围"
    # 如实写出来 —— 那是产物里"这次到底覆盖了谁"的**唯一**书面凭据，所以就在那里断言。
    integrity = next(s for s in result.sections if s.key is SectionKey.INTEGRITY)
    coverage = [fact.text for fact in integrity.facts if "覆盖范围" in fact.text]
    assert len(coverage) == 1, coverage
    assert len(ARCHIVE) == 8, "档案规模变了就要重看这条用例的前提"
    for entry in ARCHIVE:
        assert entry.project in coverage[0], f"{entry.project} 不在覆盖范围里：{coverage[0]}"

    prices = next(s for s in result.sections if s.key is SectionKey.PRICES)
    lines = [fact.text for fact in prices.facts]
    assert len(lines) == 3, lines

    lithium = _only(lines, "锂 ")
    copper = _only(lines, "铜 ")
    iron = _only(lines, "铁矿石 ")

    # 三个品种各自的数值与数据时点 —— 铜比另两项早三天，因为 LME 只给延迟收盘价。
    assert "117300.0" in lithium and "2026-10-08" in lithium
    assert "682.5" in iron and "2026-10-08" in iron
    assert "14415.0" in copper and "2026-10-05" in copper
    assert "延迟披露" in copper, "铜的延迟属性必须在产物里看得见"
    assert "延迟披露" not in lithium and "延迟披露" not in iron
    # 两处"当日"是同一天，不是回退：10-01…10-07 国庆休市，两个市场都在 10-08 恢复。
    assert "当日" in lithium and "当日" in iron
    assert "回退" not in lithium and "回退" not in iron

    # 范围大不等于某一节可以空着 —— 第六节之外每节都得有内容。
    for section in result.sections:
        assert section.facts or section.note, f"{section.title} 既没事实也没说明"


def _only(lines: list[str], prefix: str) -> str:
    """按品种前缀取那一行。三行里恰好一行匹配，多一行少一行都说明拼装坏了。"""
    matched = [line for line in lines if line.startswith(prefix)]
    assert len(matched) == 1, f"{prefix!r} 命中 {len(matched)} 行：{lines}"
    return matched[0]
