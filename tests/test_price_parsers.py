"""价格解析层：**纯函数**，拿录播的逐字节原文直接跑（ADR-0003）。

这一组不碰网络、不碰 adapter、不碰 MCP —— 它回答的是"这份响应读对了吗"。
读错一个字段是本项目最贵的一类 bug：它不会让任何东西变红，只会让日报印出一个
错误的数字，而那个数字看起来和真的一模一样。

所以这里最关键的一条是 `test_sina_agrees_with_the_gfex_official_number`：
两个**互不相干**的来源（交易所自己的日行情接口 / 第三方的历史日 K 线）必须给出
同一个数。对不上就说明我们的解析错了一边 —— 这是不靠人眼能拿到的最强证据。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from mining_brief.config.sources import PRICE_SOURCES, PriceSource
from mining_brief.contracts import RawResponse
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.prices import (
    candidate_dates,
    parse_gfex_daily,
    parse_sina_kline,
    trading_date,
)


def _recorded(store: FixtureStore, suffix: str) -> RawResponse:
    """按文件名后缀取一份录播。用后缀而不是 URL：URL 里带着百分号编码，
    写在测试里又长又容易抄错，而文件名是人起的、稳定的。"""
    entry = next(e for e in store.manifest.entries if e.path.endswith(suffix))
    return store.raw(entry.url)


def _source(commodity: str) -> PriceSource:
    return PRICE_SOURCES[commodity]


# ---------------------------------------------------------------------------
# GFEX：官方日行情
# ---------------------------------------------------------------------------


def test_gfex_daily_picks_the_contract_with_the_largest_open_interest(
    fixture_root: Path,
) -> None:
    """主力合约取**持仓量**最大的那个，价格取它的收盘价。

    2026-10-08 那份录播里持仓量最大的是 2701（409678 手），所以结果必须是
    `lc2701` 与 117300.0 —— 这两个数都不是我算出来的，是响应里读出来的。
    """
    raw = _recorded(FixtureStore(fixture_root), "lithium-2026-10-08.json")

    point = parse_gfex_daily(raw, _source("lithium"), "2026-10-08")

    assert point is not None
    assert point.symbol == "lc2701"
    assert point.value == 117300.0
    assert point.as_of == "2026-10-08"
    assert (point.currency, point.unit) == ("元", "吨")
    assert point.delayed is False
    # 引用块里给人看的是**行情页**，不是那个只认 POST 的接口地址。
    assert point.source_url == "http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml"


def test_a_holiday_response_yields_no_point_instead_of_a_zero(fixture_root: Path) -> None:
    """休市日的响应是 **HTTP 200 + 一行全 `null` 的汇总占位行**，不是错误。

    它必须变成 `None`，不能变成 0，也不能变成"上一交易日的价格"——
    把占位行读成一个价格，日报就会印出"碳酸锂 undefined 元/吨"这类东西。
    把"没有数据"和"有数据"分开，是 ADR-0004 回退链路的起点。
    """
    store = FixtureStore(fixture_root)

    # 国庆假期，以及锚点那天（北京时间 10-09 凌晨，交易所尚未收盘结算、还没发布）。
    for trade_date in ("2026-10-05", "2026-10-09"):
        raw = _recorded(store, f"lithium-{trade_date}.json")
        assert raw.ok, "占位行是 200 —— 这正是它危险的地方"
        assert parse_gfex_daily(raw, _source("lithium"), trade_date) is None


def test_the_placeholder_row_is_distinguishable_by_structure(fixture_root: Path) -> None:
    """占位行与真行在**结构上**可分：真行一定有交割月。

    这条断言直接盯着解析依据本身。哪天 GFEX 改了这份 JSON 的结构，"休市日 =
    None"就不再成立，这条会红 —— 而不是让别的测试以一种看不懂的方式红。
    """
    store = FixtureStore(fixture_root)
    empty = json.loads(_recorded(store, "lithium-2026-10-05.json").text())
    filled = json.loads(_recorded(store, "lithium-2026-10-08.json").text())

    assert all(not (row.get("delivMonth") or "").strip() for row in empty["data"])
    assert any((row.get("delivMonth") or "").strip() for row in filled["data"])


# ---------------------------------------------------------------------------
# 新浪：日 K 线
# ---------------------------------------------------------------------------


def test_the_recorded_sina_response_is_real_data_not_a_service_error(
    fixture_root: Path,
) -> None:
    """这个接口连 URL 写错都**回 200**，错误藏在响应体里。

    少了回调路径上那个 `/` 时，它会回 `{"__ERRORMSG":"Invalid service name"}` ——
    于是坏 URL 会被解析成"这个品种一天数据都没有"，静默地变成简报里的一句
    "数据缺失"。所以录下来的这一份必须是真数据。
    """
    raw = _recorded(FixtureStore(fixture_root), "iron_ore-I0-kline.json")

    assert raw.ok
    assert "__ERROR" not in raw.text()
    assert parse_sina_kline(raw, _source("iron_ore"))


def test_sina_kline_is_parsed_into_the_whole_history_oldest_first(
    fixture_root: Path,
) -> None:
    raw = _recorded(FixtureStore(fixture_root), "iron_ore-I0-kline.json")

    points = parse_sina_kline(raw, _source("iron_ore"))

    assert len(points) > 1000, "I0 的历史日线有上千根，只有几根说明解析取错了地方"
    stamps = [point.as_of for point in points]
    assert stamps == sorted(stamps)
    assert stamps[0] < stamps[-1]
    # 序列里的每一点就是那一天的数据，所以它不构成回退（ADR-0004）。
    assert not any(point.is_fallback for point in points)
    assert all(point.symbol == "I0" and point.exchange == "DCE" for point in points)


def test_sina_agrees_with_the_gfex_official_number(fixture_root: Path) -> None:
    """**跨源核对**：两个互不相干的来源，在三个字段上都要给出同一个数。

    左边是 GFEX 官方日行情接口（POST 表单、按日索取）；右边是新浪财经的历史日
    K 线（GET、一次给全史）。两边读出来对不上，只可能是我们某一边解析错了 ——
    而单看任何一边都发现不了。

    对的是**同一天、同一个品种**（碳酸锂主力合约 2026-10-08）。新浪的 `lc0` 是
    "主力连续"，它跟的是持仓量最大的那个月，正是 GFEX 那行 2701。

    **为什么核三个字段而不是一个**：一个数巧合相等是可能的（都读错成同一个别的
    数、或者恰好都取了整数位）。收盘价、结算价、持仓量三个**量纲完全不同**的字段
    同时相等，巧合的解释就基本站不住了 —— 而且它就是 README 里那张核对表的依据。

    我们**只用**收盘价（`c` / `close`），另外两个字段没有对应的生产解析器。它们
    在这里的作用不是"顺便断言一下"，而是给收盘价那个数当旁证。
    """
    store = FixtureStore(fixture_root)
    official = parse_gfex_daily(
        _recorded(store, "lithium-2026-10-08.json"), _source("lithium"), "2026-10-08"
    )
    assert official is not None

    # 同一份登记表、只换请求形状 —— 免得手抄一遍品种/单位，抄错就核对了个寂寞。
    sina_source = replace(_source("lithium"), quote_format="sina_kline")
    sina = parse_sina_kline(_recorded(store, "lithium-lc0-kline.json"), sina_source)
    same_day = next(point for point in sina if point.as_of == "2026-10-08")

    assert same_day.value == official.value, "收盘价：官方口径与第三方转载对不上，说明有一边读错了"

    # 另外两个字段直接读原始响应 —— 生产代码不解析它们，所以这里也没有解析器可复用。
    sina_text = _recorded(store, "lithium-lc0-kline.json").text()
    sina_rows = json.loads(sina_text[sina_text.index("([") + 1 : sina_text.rindex("])") + 1])
    sina_day = next(row for row in sina_rows if row["d"] == "2026-10-08")

    gfex_text = _recorded(store, "lithium-2026-10-08.json").text()
    gfex_main = max(
        (
            row
            for row in json.loads(gfex_text)["data"]
            if str(row.get("delivMonth") or "").strip() and row.get("close") is not None
        ),
        key=lambda row: row.get("openInterest") or 0,
    )
    assert gfex_main["delivMonth"] == "2701", "主力是哪个月也得先对上，否则比的不是同一个合约"

    assert float(sina_day["s"]) == float(gfex_main["clearPrice"]), "结算价对不上"
    assert float(sina_day["p"]) == float(gfex_main["openInterest"]), "持仓量对不上"

    # 顺带钉住"收盘 ≠ 结算"：把两者搞混，日报会印出一个每天都偏一两千的价。
    assert official.value != float(gfex_main["clearPrice"]), "117300 是收盘价，121540 是结算价"


# ---------------------------------------------------------------------------
# 交易日历：我们**申请**了哪些日子
# ---------------------------------------------------------------------------


def test_candidate_dates_skip_the_weekend(fixture_root: Path) -> None:
    """周末不申请 —— 交易所周末恒不开市，调休补班日也不开市。

    跳掉它不是为了省事：GFEX 接口约 20 次快速请求就限流（实测 HTTP 567），
    每少一次请求都是实打实的余量。规律本身在录播里可见：新浪的连续合约日 K 线
    里 2026-09-26/27 与 10-03/04 这四天一行都没有。
    """
    days = candidate_dates(date(2026, 10, 9), 7)

    assert days == [
        date(2026, 10, 9),
        date(2026, 10, 8),
        date(2026, 10, 7),
        date(2026, 10, 6),
        date(2026, 10, 5),
        date(2026, 10, 2),
    ]
    assert all(day.weekday() < 5 for day in days)

    kline = parse_sina_kline(
        _recorded(FixtureStore(fixture_root), "iron_ore-I0-kline.json"), _source("iron_ore")
    )
    weekends = {point.as_of for point in kline if date.fromisoformat(point.as_of).weekday() >= 5}
    assert weekends == set(), "录播里一个周末都没有，上面那条「跳过周末」才有依据"


def test_the_trading_date_is_the_beijing_date_not_the_utc_one(fixture_root: Path) -> None:
    """锚点在 UTC 是 10-08，在北京时间已经是 **10-09** —— 差一天。

    用 UTC 日期算"今天"，整条回退链就会整体偏移，而且错得毫无征兆
    （10-08 恰好有数据，于是看上去一切正常）。
    """
    anchor = FixtureStore(fixture_root).anchor_at

    assert anchor.date() == date(2026, 10, 8)
    assert trading_date(anchor) == date(2026, 10, 9)


def test_candidates_are_bounded_so_a_far_off_date_cannot_hammer_the_source() -> None:
    """往前找是有上界的：交易所最长连续休市 7–8 天，10 天留余量。

    没有上界的话，"查一个 2030 年的日期"会变成几百次请求 —— 对一个约 20 次
    就限流的接口来说，那是一次自伤。
    """
    days = candidate_dates(date(2030, 1, 1), 10)

    assert len(days) <= 8
    assert days[0] == date(2030, 1, 1)
    assert (days[0] - days[-1]).days <= 10


@pytest.mark.parametrize("commodity", ["lithium", "iron_ore"])
def test_no_registered_source_is_left_without_a_known_shape(commodity: str) -> None:
    """登记表里的形状必须是解析器认识的那两种。

    这条挡的是"加了品种但没加解析分支" —— 那种情况下 adapter 会把它当成
    另一种形状去解析，读出一堆看起来合理的错数字。
    """
    source = PRICE_SOURCES[commodity]

    assert source.quote_format in ("gfex_daily", "sina_kline")
    assert source.quote_url and source.page_url and source.quote_url != source.page_url
