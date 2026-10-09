"""价格一节的**排版**规则：两个品种并排时，各说各话。

这一组之所以要单独存在，是因为它覆盖的那条路径**从端到端跑不到**：
`ReportScope.commodity_in_scope` 是从 `config/archive.py` 推出来的，而档案里
只有 Pilgangoora 一条（锂）。也就是说，铁矿石与铜即使在 `PRICE_SOURCES` 里登记好了、
工具也真能取到数，它们也永远进不了范围 —— 于是「三个品种同时出现在第四节」这件事
在本票的产物里无法被观测。这条缺口由工单 06（把档案补齐到 8 座矿山）打开，不是
04 的代码问题：`fetch_prices` 本来就是按 `scope.commodity_in_scope` 循环的。

工单 03 / 04 的验收里各有一条正是关于这个的（"两项的截止时间…互不相同"、"三项…
截止时间各不相同"）。既然端到端到不了，就把规则拿到单元层面钉住，并在工单与交接
报告里写明这条链路为什么跑不到 —— **不假装它跑到了**。
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
    publisher: str | None = None,
) -> PriceSeries:
    """`last_requested_date` 是**唯一**能造出回退的手段 —— 因为回退就是
    `as_of < requested_date` 这一条式子（ADR-0004），没有独立开关可以拨。
    传它一个更晚的日期，最后一个点就自动成为回退点。

    `publisher` 不传就取 `exchange` —— 这只是**测试夹具**的省事写法，不是契约的
    默认值：GFEX 与 LME 的发布方确实就是它们的交易所，只有铁矿石那条不同，
    而它必须被显式写出来（这正是本文件末尾那条用例在盯的事）。
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
                publisher=publisher if publisher is not None else exchange,
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
                    "iron_ore",
                    "DCE",
                    "I0",
                    ("2026-09-30", 780.5),
                    ("2026-10-08", 791.0),
                    # 合约是 DCE 的，数据是新浪财经转载的 —— 发布方与合约方不是一回事。
                    publisher="新浪财经",
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
    # 铁矿石那条印的是**发布方**新浪财经，不是合约所在的 DCE（ADR-0010）。
    assert {citation.publisher for citation in ledger.citations} == {"GFEX", "新浪财经"}


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
                    # 用**真实**那条说明（prices.py 的 lme_hero 分支），不是随手编一句：
                    # 铜已经接入了，它取不到数的真实原因不是"尚未接入"，而是行情页
                    # 只能给最新一天。测试夹具里留一句过时的理由，等于把这个系统
                    # 说成另一个样子。
                    reason=(
                        "LME 的行情页只提供最新的 3 个月收盘价，"
                        "给不出 2026-09-15 这一天 —— 该源不支持历史查询。"
                    ),
                    retrieved_at=NOW,
                    commodity="copper",
                    exchange="LME",
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
    assert "不支持历史查询" in section.note


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


def test_a_delayed_commodity_that_also_fell_back_prints_both_qualifiers() -> None:
    """铜这一行在产物里的真实样子：**两个限定词同时出现**，因为它们同时成立。

    这是 ADR-0004 那条分界在纸面上的样子：`延迟披露` 说的是**数据源**（LME 的行情页
    自己写着 day-delayed），`回退自 2026-10-06` 说的是**我们这一次的动作**（问了 10-06，
    页面只给到 10-05）。把两者压成一个字段，这一行就只能印出一个 —— 而无论印哪个，
    读者都会得到一个错误印象：印"延迟披露"会让人以为数据是 10-06 的（其实是 10-05），
    印"回退自"会让人以为换一家源就能拿到 10-06 的（LME 就是延迟的）。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "copper": _series(
                    "copper",
                    "LME",
                    "CA 3-month",
                    ("2026-10-05", 14415.0),
                    delayed=True,
                    # 问的是 10-06，页面只给到 10-05。
                    last_requested_date="2026-10-06",
                )
            }
        },
        ledger,
    )

    text = section.facts[0].text
    assert "14415.0" in text
    assert "LME CA 3-month" in text
    assert "2026-10-05" in text, "数据本身的日期"
    assert "延迟披露" in text, "数据源固有的延迟"
    assert "回退自 2026-10-06" in text, "我们这一次往前找了一天"
    assert "当日" not in text, "延迟与非延迟是互斥的两种说法，不能同时印出来"
    assert section.as_of == "2026-10-05"


def test_the_citation_names_the_publisher_not_the_exchange() -> None:
    """引用块的出处写**发布方**，正文的括号里写**合约所在的交易所** —— 两者各说各的。

    这条盯的是产物里真实出现过的一处自相矛盾（2026-10-09 的实时产物，第 [22] 条）：

        铁矿石 682.5 元/吨（DCE I0，2026-10-08，当日）
        **[22]**（价格）DCE I0
          DCE · 2026-10-08
          <https://finance.sina.com.cn/futures/quotes/I0.shtml>

    出处写着 DCE，链接却指向新浪 —— 同一条引用里两个「谁给的」互不相同，读者
    没法判断该信哪一头。根子是 `PricePoint` 契约里只有 `exchange`、没有发布方，
    于是 `nodes.py` 只能把合约方当发布方印出去，而这**违背了 `Citation.publisher`
    自己的契约**（"原样搬运工具返回值" —— 工具当时根本不返回发布方）。

    修法不是印得更含糊，是把它拆成两件事：正文保留 `DCE I0`（读者靠合约名认行情），
    出处改成新浪财经并配上新浪的链接（数据实际是谁给的）。附件两处一起断言，
    免得以后有人把其中一处"顺手统一"了。
    """
    ledger = CitationLedger()
    section = _prices_section(
        {
            "prices": {
                "iron_ore": _series(
                    "iron_ore",
                    "DCE",
                    "I0",
                    ("2026-10-08", 682.5),
                    publisher="新浪财经",
                )
            }
        },
        ledger,
    )

    text = section.facts[0].text
    assert "DCE I0" in text, "正文要留合约名 —— 它才是读者认行情用的东西"
    assert "新浪财经" not in text, "正文不扛出处；出处归引用块，一节一个位置"

    (citation,) = ledger.citations
    assert citation.publisher == "新浪财经", "出处印的必须是发布方"
    assert citation.publisher != "DCE", "印成合约所在的交易所就是这次要修的那个错"
    # 标题留的是**合约**（`DCE I0`），出处是**发布方**（新浪财经）—— 一条引用里
    # 两件事各就各位。把标题也换成发布方会让"这是哪份合约"在来源清单里消失。
    assert citation.title == "DCE I0"
