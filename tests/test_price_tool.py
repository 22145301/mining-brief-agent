"""切面 S2：**直连**价格工具，不走图。

S1 证明"整条链路能出报"；S2 证明"这一个工具本身说真话"。这里刻意**不 mock 任何
东西**：fixture 是逐字节的真实响应，解析真跑，连接走 SDK 的进程内协议（ADR-0001），
唯一不在场的只有网络。

这一组盯得最紧的是**三件不同的事必须分得开**（ADR-0004 / ADR-0005）：

1. **回退** —— 问的那天没行情，给了更早的一天。由 `as_of < requested_date` 表达，
   **不设独立标志位**。
2. **未找到** —— 搜索范围内确实一天都没有。给 `None`，不给 0、不给近似值。
3. **取不到** —— 源挂了/被限流。给降级信封，**不是**"未找到"。

把 1 和 3 混起来，简报就会把"交易所今天还没发布"说成"这个源坏了"；把 2 和 3
混起来，就会让人去查一个根本没坏的网站。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mining_brief.agent.toolkit import default_toolkit
from mining_brief.config.settings import Settings
from mining_brief.config.sources import PRICE_SOURCES
from mining_brief.contracts import FetchStatus
from mining_brief.datasources.fixtures import FixtureMissing, FixtureStore
from mining_brief.datasources.prices import PriceAdapter, trading_date
from mining_brief.errors import REPLAY_MISS_SENTINEL, ReplayMiss
from mining_brief.servers import price_server
from mining_brief.servers.runtime import Runtime

#: 锚点在北京时间是 2026-10-09 凌晨 —— 交易所那天还没发布行情，所以**问 10-09
#: 本身就是回退的触发条件**，不需要人为构造。
ANCHOR_TRADING_DATE = "2026-10-09"
LAST_SESSION = "2026-10-08"


def _anchor(fixture_root: Path) -> datetime:
    return FixtureStore(fixture_root).anchor_at


# ---------------------------------------------------------------------------
# 回退（ADR-0004）
# ---------------------------------------------------------------------------


async def test_get_price_falls_back_to_the_latest_session_at_or_before_the_date(
    fixture_root: Path,
) -> None:
    """问 10-09（还没发布），给 10-08 —— 而且**必须说清这是哪一天**。"""
    lookup = await default_toolkit().get_price("lithium", ANCHOR_TRADING_DATE)

    assert lookup.status == "ok"
    assert lookup.source_status is FetchStatus.OK
    assert lookup.point is not None
    point = lookup.point
    assert point.as_of == LAST_SESSION
    assert point.requested_date == ANCHOR_TRADING_DATE
    assert point.is_fallback is True


async def test_the_fallback_is_expressed_by_as_of_alone_and_not_by_the_delayed_flag(
    fixture_root: Path,
) -> None:
    """回退与 `delayed` 是**两件事**，各自断言（ADR-0004）。

    `delayed` 说的是"这个数据源天生就延迟披露"（LME 恒为真），是交易所的属性；
    回退说的是"本次查询要的那天没有数据"。用一个标志位同时表达两者，简报就没法
    同时说清"这是延迟数据"和"这是前一天的数"。
    """
    fallback = await default_toolkit().get_price("lithium", ANCHOR_TRADING_DATE)
    assert fallback.point is not None

    assert fallback.point.is_fallback is True
    assert fallback.point.delayed is False, "GFEX 日行情当日发布，delayed 不该为真"


async def test_a_date_that_has_data_is_returned_as_is_without_a_fallback(
    fixture_root: Path,
) -> None:
    """反面：问一个有行情的那天，就不该出现回退。

    少了这条，"永远回退一天"这种错也能让上面两条全绿。
    """
    lookup = await default_toolkit().get_price("lithium", LAST_SESSION)

    assert lookup.point is not None
    assert lookup.point.as_of == LAST_SESSION
    assert lookup.point.is_fallback is False


async def test_the_two_commodities_route_to_their_own_sources(fixture_root: Path) -> None:
    """锂走 GFEX 官方日行情，铁矿石走新浪转载的 DCE 合约 —— 登记表说了算。"""
    toolkit = default_toolkit()

    lithium = await toolkit.get_price("lithium", LAST_SESSION)
    iron_ore = await toolkit.get_price("iron_ore", LAST_SESSION)

    assert lithium.point is not None and iron_ore.point is not None
    assert lithium.point.exchange == "GFEX"
    assert lithium.point.symbol.startswith("lc")
    assert iron_ore.point.exchange == "DCE"
    assert iron_ore.point.symbol == "I0"
    # 报价单位两边都是元/吨 —— 同一份日报里出现两种单位会让人读错量级。
    assert (lithium.point.currency, lithium.point.unit) == ("元", "吨")
    assert (iron_ore.point.currency, iron_ore.point.unit) == ("元", "吨")


# ---------------------------------------------------------------------------
# 未找到：**不是** 0，也不是近似值
# ---------------------------------------------------------------------------


async def test_a_date_before_the_series_starts_is_not_found_rather_than_approximated(
    fixture_root: Path,
) -> None:
    """I0 的日线从 2013-10-18 开始，问 2013-01-01 就该说"没有"。

    这是**一次成功的判定**（`EMPTY`，信封 `status=ok`），不是降级 ——
    源是好的，只是那段历史不存在。退回 `UNAVAILABLE` 会让人以为新浪挂了。
    """
    lookup = await default_toolkit().get_price("iron_ore", "2013-01-01")

    assert lookup.status == "ok"
    assert lookup.source_status is FetchStatus.EMPTY
    assert lookup.point is None
    assert lookup.reason is None, "没坏掉的东西不需要理由"


async def test_the_recorded_window_edge_is_a_loud_gap_not_a_silent_not_found(
    fixture_root: Path,
) -> None:
    """问 10-05：搜索**穿过了**两个休市日 10-05、10-02（占位行 → `None`），
    在 10-01 撞上录播空洞 —— 于是炸，而不是给一个"未找到"。

    这两件事被这一条同时钉住：

    - **跳过占位日是有发生的**。断言里那个 `20261001` 只有一种解释：循环先消化了
      10-05 与 10-02 却没拿到价格，才轮到 10-01。若哪次改动让占位行解析出一个价格，
      搜索会提前停在 10-05 而根本不问 10-01，这条立刻红。
    - **录播不全时绝不静默降级**（ADR-0002）。空洞就在回退链路的中段，最容易被人
      用"找不到就说找不到"糊过去 —— 那样日报会写"碳酸锂最近没有行情"，而真相是
      我们的 fixture 集缺了一天。
    """
    with pytest.raises(ReplayMiss) as excinfo:
        await default_toolkit().get_price("lithium", "2026-10-05")

    assert "20261001" in str(excinfo.value), "搜索应当在 10-01 停下，说明 10-05/10-02 已被跳过"


# ---------------------------------------------------------------------------
# 走势
# ---------------------------------------------------------------------------


async def test_get_trend_returns_an_ascending_series_inside_the_window(
    fixture_root: Path,
) -> None:
    """窗口内的价格序列，由旧到新，且**一点不越界**。"""
    series = await default_toolkit().get_trend("iron_ore", 30)

    assert series.source_status is FetchStatus.OK
    assert len(series.points) > 5, "30 天的窗口里应该有多个交易日，否则这条断言在空转"

    stamps = [point.as_of for point in series.points]
    assert stamps == sorted(stamps), "序列必须由旧到新 —— 图省事倒着给会让人读反趋势"
    assert stamps[0] < stamps[-1], "两端相等说明只有一天，窗口语义没被执行"

    # 窗口起点与终点都由工具的**同一个定义**算出：`trading_date(now) - days`。
    # 这里把定义重算一遍而不是调工具，是为了让"越界"这件事有个独立的参照物 ——
    # 直接信工具给的 points，就等于用被检查的东西证明它自己。
    anchor_day = trading_date(_anchor(fixture_root))
    window_start = (anchor_day - timedelta(days=30)).isoformat()
    assert all(window_start <= point.as_of <= anchor_day.isoformat() for point in series.points)


async def test_a_trend_never_reaches_into_the_future(fixture_root: Path) -> None:
    """数据的末日不能超过"现在" —— 否则就是编了一个还没发生的价格。"""
    anchor_day = trading_date(_anchor(fixture_root)).isoformat()

    for commodity in ("lithium", "iron_ore"):
        series = await default_toolkit().get_trend(commodity, 7)
        assert series.points, f"{commodity} 的窗口里应该有至少一个交易日"
        assert all(point.as_of <= anchor_day for point in series.points)


async def test_a_trend_point_is_not_a_fallback(fixture_root: Path) -> None:
    """序列里的每一点就是那一天的数据，所以它不是"回退"。

    回退是**单点查询**的语义。把序列里的点标成回退，简报就会说
    "2026-10-08（回退自 2026-10-08）"这种胡话。
    """
    series = await default_toolkit().get_trend("lithium", 7)

    assert series.points
    assert all(point.as_of == point.requested_date for point in series.points)


# ---------------------------------------------------------------------------
# 源取不到（A7）：一份**真实录下来的** 503
# ---------------------------------------------------------------------------


class _RuntimeWithARealOutage(Runtime):
    """把铁矿石的取值地址换成**录下来的那个真 503**，其余照旧。

    只换 `quote_url` 一个字段，不动任何代码路径 —— 所以它证明的是"适配器对上游
    拒绝服务的反应"，不是"我们给测试开了个后门"。手写一条 `status=503` 的清单
    条目也能让测试变绿，但那证明不了任何事。
    """

    def __init__(self, settings: Settings, fault_url: str) -> None:
        super().__init__(settings)
        self._fault_url = fault_url

    def prices(self) -> PriceAdapter:
        return PriceAdapter(
            self.fetcher(),
            {
                **PRICE_SOURCES,
                "iron_ore": replace(PRICE_SOURCES["iron_ore"], quote_url=self._fault_url),
            },
        )


async def test_a_real_upstream_503_degrades_instead_of_pretending(
    settings: Settings, fault_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上游回 503 时给**降级信封**，而不是"未找到"，更不是 0。

    "这个源现在取不到"和"这天没有数据"是两件事。把 503 说成"未找到"，简报第 6 节
    就会写着"铁矿石：最近没有行情"，而真实情况是新浪挂了 —— 查错方向。
    """
    monkeypatch.setattr(
        price_server,
        "_runtime_override",
        _RuntimeWithARealOutage(settings, fault_url),
    )

    lookup = await default_toolkit().get_price("iron_ore", LAST_SESSION)

    assert lookup.status == "degraded"
    assert lookup.source_status is FetchStatus.UNAVAILABLE
    assert lookup.point is None
    assert "503" in (lookup.reason or ""), "理由里要带上那个状态码，否则没法排查"


# ---------------------------------------------------------------------------
# ADR-0002：缺录播就炸穿，不静默降级
# ---------------------------------------------------------------------------


async def test_a_date_without_a_recording_fails_loudly_instead_of_going_to_the_network(
    fixture_root: Path,
) -> None:
    """回放时缺录播**必须**报错。

    两个"不许"，各自都在这一段里被守住：

    - 不许回退真实网络 —— `FixtureFetcher` 里根本没有网络这条路。
    - 不许被降级信封吸收 —— 那会产出一份写着"数据缺失"的日报，让人去查一个
      根本没坏的交易所。所以它必须**穿过 MCP 边界**（哨兵串）一路抛到调用方。

    取一个录播窗口之外的日期：往前找会依次问到没录过的那几天。
    """
    with pytest.raises(ReplayMiss) as excinfo:
        await default_toolkit().get_price("lithium", "2026-09-28")

    message = str(excinfo.value)
    assert REPLAY_MISS_SENTINEL in message
    assert "20260928" in message, "错误信息要指出是哪一个请求缺录播"
    assert "scripts/fetch_fixtures.py" in message
    assert issubclass(FixtureMissing, ReplayMiss)
