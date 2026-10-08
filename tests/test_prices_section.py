"""价格一节的**排版**规则：两个品种并排时，各说各话。

这一组之所以要单独存在，是因为它覆盖的那条路径**从端到端跑不到**：
`ReportScope.commodity_in_scope` 是从 `config/archive.py` 推出来的，而档案里
只有 Pilgangoora 一条（锂）。也就是说，铁矿石即使在 `PRICE_SOURCES` 里登记好了、
工具也真能取到数，它也永远进不了范围 —— 于是「两个品种同时出现在第四节」这件事
在 S1 上无法被观测。

工单 03 的验收里有一条正是关于这个的（"两项的截止时间…互不相同"）。既然端到端
到不了，就把规则拿到单元层面钉住，并在工单与交接报告里写明这条链路为什么跑不到 ——
**不假装它跑到了**。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mining_brief.agent.citations import CitationLedger
from mining_brief.agent.nodes import _prices_section
from mining_brief.contracts import FetchStatus, PricePoint, PriceSeries, SectionKey

NOW = datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)


def _series(
    commodity: str,
    exchange: str,
    symbol: str,
    *points: tuple[str, float],
    delayed: bool = False,
    last_requested_date: str | None = None,
) -> PriceSeries:
    """`last_requested_date` 是**唯一**能造出回退的手段 —— 因为回退就是
    `as_of < requested_date` 这一条式子（ADR-0004），没有独立开关可以拨。
    传它一个更晚的日期，最后一个点就自动成为回退点。
    """
    last = len(points) - 1
    return PriceSeries(
        status="ok",
        source_status=FetchStatus.OK,
        retrieved_at=NOW,
        commodity=commodity,
        exchange=exchange,
        requested_days=7,
        points=tuple(
            PricePoint(
                commodity=commodity,
                exchange=exchange,
                symbol=symbol,
                value=value,
                currency="元",
                unit="吨",
                as_of=day,
                delayed=delayed,
                source_url=f"https://example.invalid/{symbol}",
                requested_date=(
                    last_requested_date if index == last and last_requested_date else day
                ),
            )
            for index, (day, value) in enumerate(points)
        ),
    )


def test_two_commodities_each_get_their_own_line_and_their_own_cutoff() -> None:
    """锂与铁矿石各占一行，各自标注**自己的**截止时间，而不是共用一个。

    这条盯的是"合并成一个时点"这个错误：第四节写"数据时点：2026-10-08"看着无害，
    但两个市场的最后交易日不一样时，那句话只对其中一个成立 —— 读者会把另一个
    品种的价格当成 10-08 的，而它其实是更早的。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "lithium": _series(
                    "lithium", "GFEX", "lc2701", ("2026-10-07", 116500.0), ("2026-10-08", 117300.0)
                ),
                "iron_ore": _series(
                    "iron_ore", "DCE", "I0", ("2026-09-30", 780.5), ("2026-10-08", 791.0)
                ),
            }
        },
        ledger,
    )

    assert section.key is SectionKey.PRICES
    assert len(section.facts) == 2

    texts = {fact.text.split()[0]: fact.text for fact in section.facts}
    assert set(texts) == {"锂", "铁矿石"}

    assert "117300.0" in texts["锂"] and "GFEX lc2701" in texts["锂"]
    assert "791.0" in texts["铁矿石"] and "DCE I0" in texts["铁矿石"]
    # 每一行都带着自己的日期，而且都在正文里 —— 不是只靠一节一个的 as_of。
    assert "2026-10-08" in texts["锂"]
    assert "2026-10-08" in texts["铁矿石"]
    # 两个来源各自成一条引用，不能合并 —— 合并了就没法回溯到某一家的行情页。
    assert {citation.publisher for citation in ledger.citations} == {"GFEX", "DCE"}


def test_the_section_cutoff_cannot_be_earlier_than_the_latest_point() -> None:
    """一节一个的 `as_of` 取窗口内**最新**的那天，取不到就是 `None`。

    它必须不早于任何一个价格点 —— 一个说"本节数据截至 10-07"、行里却印着
    10-08 的报表，会让人怀疑整个时间轴。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "lithium": _series("lithium", "GFEX", "lc2701", ("2026-10-07", 116500.0)),
                "iron_ore": _series(
                    "iron_ore", "DCE", "I0", ("2026-10-08", 791.0), ("2026-10-09", 792.0)
                ),
            }
        },
        ledger,
    )

    assert section.as_of == "2026-10-09"
    # 每一行印的是**自己**那天，不是这一节的 as_of —— 两个市场休市日不同的时候，
    # 把 10-09 印到锂那一行上就是编数据。
    texts = [fact.text for fact in section.facts]
    assert any("2026-10-07" in text for text in texts)
    assert any("2026-10-09" in text for text in texts)
    assert not any("2026-10-09" in text and "锂" in text for text in texts)
    assert section.as_of >= max(
        day for text in texts for day in ("2026-10-07", "2026-10-09") if day in text
    )


def test_a_commodity_with_no_data_says_so_in_the_note_rather_than_as_a_zero() -> None:
    """取不到的品种进 note（"缺了什么"），而不是变成一个 0 的价格事实。

    给 0 是最坏的选择：它看起来完全像真数据，而且 0 元/吨在页面上不会显得离谱到
    让人起疑。缺就是缺，去第六节说。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "lithium": _series("lithium", "GFEX", "lc2701", ("2026-10-08", 117300.0)),
                "copper": PriceSeries(
                    status="degraded",
                    source_status=FetchStatus.UNAVAILABLE,
                    reason="LME 需要无头浏览器（工单 04），本次尚未接入。",
                    retrieved_at=NOW,
                    commodity="copper",
                    exchange="",
                    requested_days=7,
                    points=(),
                ),
            }
        },
        ledger,
    )

    assert len(section.facts) == 1, "只有锂有数 —— 铜不该凭空多出一行"
    assert section.facts[0].text.startswith("锂")
    assert section.note is not None
    assert "铜" in section.note
    assert "尚未接入" in section.note


def test_the_fallback_qualifier_is_printed_only_when_the_value_really_was_fell_back() -> None:
    """发生回退时，正文要把**被问的那一天**也写出来。

    只印 `as_of` 是不够的：读者看到"2026-10-08"会以为那就是当天的行情，而实际上
    他问的是 10-09。两行合起来 —— "2026-10-08，当日，回退自 2026-10-09" —— 才是
    完整的语义：数据是 10-08 的，因为 10-09 没有。少了后半句，回退这条链路在产物上
    就是**不可见**的：日志里对，纸面上错。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "lithium": _series(
                    "lithium",
                    "GFEX",
                    "lc2701",
                    ("2026-10-08", 117300.0),
                    # 要的是 10-09，给的是 10-08 —— 这就是回退，没有别的写法。
                    last_requested_date="2026-10-09",
                )
            }
        },
        ledger,
    )

    text = section.facts[0].text
    # 印的是"数据是哪天的"与"从哪天回退来的"两件事，缺一不可。
    assert "2026-10-08" in text, "数据本身的日期"
    assert "回退自 2026-10-09" in text, "被问的那天 —— 它才是读者真正输入的东西"
    assert "当日" in text, "非延迟数据要标出来，否则读者无从判断该不该拿它当实时价"


@pytest.mark.parametrize("delayed", [True, False])
def test_the_delayed_qualifier_tracks_the_source_not_the_fallback(delayed: bool) -> None:
    """`delayed` 与回退各说各的（ADR-0004）—— 两个限定词互不替代。

    参数化的两遍都在跑同一个函数，但一遍是"延迟且未回退"、一遍是"当日且未回退"，
    所以它们合起来说明：**印哪个词取决于数据源，不取决于有没有回退**。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "lithium": _series(
                    "lithium", "GFEX", "lc2701", ("2026-10-08", 117300.0), delayed=delayed
                )
            }
        },
        ledger,
    )

    text = section.facts[0].text
    assert ("延迟披露" in text) is delayed
    assert ("当日" in text) is not delayed
    assert "回退自" not in text, "这一组没有回退，不该出现回退字样"
