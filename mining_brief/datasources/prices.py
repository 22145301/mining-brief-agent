"""价格数据源：解析（纯函数）+ adapter（只做编排）。

分层按 ADR-0003：`parse_gfex_daily` / `parse_sina_kline` 都是**纯函数**，拿 fixture
里的逐字节原始响应直接就能单测 —— 不需要网络、不需要 mock。抓到网络的那一段
全在 `Fetcher` 里，所以本模块**不出现任何模式判断**（没有 `if replay`）。

三条链路：锂走 GFEX 官方日行情、铁矿石走新浪转载的 DCE 日 K 线，见本票；
铜走 LME（无头浏览器）见工单 04，此前如实返回"未接入"。

三个容易混的语义在这里各就各位（ADR-0004）：

- **回退**：请求的那天没有行情（周末之外，交易所休市也会这样），就往前找最近
  有行情的一天。只由 `as_of < requested_date` 表达，**不设独立标志位**。
- **未找到**：往前找遍搜索范围都没有，返回 `point=None` —— 不是 0，也不是近似值。
- **`delayed`**：数据源固有的延迟披露（LME 恒为真），和上面两件事无关。
"""

from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mining_brief.config.sources import PRICE_SOURCES, PriceSource
from mining_brief.contracts import FetchStatus, PriceLookup, PricePoint, PriceSeries, RawResponse
from mining_brief.datasources.fetchers import Fetcher
from mining_brief.errors import ReplayMiss

SUPPORTED_COMMODITIES: tuple[str, ...] = ("lithium", "copper", "iron_ore")

#: 哪些品种还没接线，以及为什么。简报第 6 节会原样呈现这句话。
_PENDING: dict[str, str] = {
    "copper": "铜价走 LME 的延迟披露数据，需要无头浏览器（工单 04），本次尚未接入。",
}

#: 回退时最多往前找几个日历日。
#:
#: 它有上界是**刻意的**：交易所最长连续休市（春节、国庆）为 7–8 天，10 天留出余量；
#: 同时把一次查询的请求数封顶（跳掉周末后约 8 次），不至于让一次"查一个远古日期"
#: 变成几百次请求。找不满就如实说"未找到"。
LOOKBACK_DAYS = 10

#: 交易日是中国日历上的日子，**不是 UTC 的日子**。锚点 2026-10-08T17:01Z 正是会
#: 出问题的那种时刻：UTC 日期是 10-08，北京时间已经是 10-09 —— 用 UTC 算会整体
#: 差一天，把"今天"错当成昨天。
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_requested_date(value: str) -> _date:
    """参数非法就抛 —— 这是"工具自己坏了"，按 ADR-0005 该炸，不该混进信封。"""
    try:
        return _date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date 需要是 ISO 日期（如 2026-10-08），收到 {value!r}") from exc


def trading_date(now: datetime) -> _date:
    """ "今天"按北京时间算。见 `_SHANGHAI` 的说明。"""
    return now.astimezone(_SHANGHAI).date()


def candidate_dates(end: _date, span_days: int) -> list[_date]:
    """从 `end` 往前数 `span_days` 个日历日，**跳掉周六周日**，新日期在前。

    周末跳过是安全的：交易所周末恒不开市，**调休补班日也不开市**。证据就在录播里 ——
    新浪的连续合约日 K 线（`fixtures/prices/iron-ore-I0-kline.json`）里 2026-09-26/27
    与 10-03/04 这四天**一行都没有**，而紧邻的工作日都有。所以这不是"猜日历"，
    是从数据里读出来的规律。

    跳周末把一次 7 天窗口的请求数从 8 降到 6 —— 对本接口尤其值：它约 20 次快速
    请求就开始限流（实测 HTTP 567），抓取脚本必须节流跑。
    """
    out: list[_date] = []
    for offset in range(span_days + 1):
        day = end - timedelta(days=offset)
        if day.weekday() < 5:
            out.append(day)
    return out


# ---------------------------------------------------------------------------
# 解析：纯函数，A2 直接断言它们
# ---------------------------------------------------------------------------


def parse_gfex_daily(raw: RawResponse, source: PriceSource, trade_date: str) -> PricePoint | None:
    """GFEX 日行情 JSON → 当日主力合约的一个价格点。**纯函数**。

    返回 `None` 表示**这一天确实没有行情**，不是出错。GFEX 对休市日、上市前、
    未来日期都回 200 加一行汇总占位行（`variety=总计`、价格全 `null`）——
    这种响应与真正的行情在**结构上**可区分：有行情的日子一定有带交割月的合约行。

    "主力"取**持仓量最大**的合约。不用成交量：收盘时成交量可能集中在临月合约上，
    而持仓量才是"市场把仓位押在哪个月"的表达。
    """
    payload = json.loads(raw.text())
    rows = payload.get("data") or []

    contracts = [
        row
        for row in rows
        if str(row.get("delivMonth") or "").strip() and row.get("close") is not None
    ]
    if not contracts:
        return None

    main = max(contracts, key=lambda row: row.get("openInterest") or 0)
    return PricePoint(
        commodity=source.commodity,
        exchange=source.exchange,
        symbol=f"{source.symbol}{main['delivMonth']}",
        value=float(main["close"]),
        currency=source.currency,
        unit=source.unit,
        as_of=trade_date,
        delayed=source.delayed,
        source_url=source.page_url,
        requested_date=trade_date,
    )


def parse_sina_kline(raw: RawResponse, source: PriceSource) -> tuple[PricePoint, ...]:
    """新浪日 K 线（JSONP）→ 全历史价格点。**纯函数**。

    响应长这样：`/*<script>…</script>*/\\nvar _I0=([{"d":"2013-10-18",…}]);`
    所以取**第一个 `([` 与最后一个 `])`** 之间的部分交给 `json` 解析。不按变量名
    匹配：变量名是新浪的回调参数，我们改不了它，也不该依赖它拼得对。

    `close` 取 `c`（收盘价）。它是"当天的价格"最直白的那个数，而且**能跨源核对**：
    2026-10-08 GFEX 官方 `clearPrice` 与新浪 `s` 同为 121540，收盘价则同为 117300。
    """
    text = raw.text()
    start = text.index("([")
    end = text.rindex("])")
    rows = json.loads(text[start + 1 : end + 1])

    points: list[PricePoint] = []
    for row in rows:
        day = str(row["d"])
        points.append(
            PricePoint(
                commodity=source.commodity,
                exchange=source.exchange,
                symbol=source.symbol,
                value=float(row["c"]),
                currency=source.currency,
                unit=source.unit,
                as_of=day,
                delayed=source.delayed,
                source_url=source.page_url,
                # 序列里的每个点**就是**那一天的数据，所以它不构成回退 ——
                # `as_of == requested_date`，`is_fallback` 为假。
                requested_date=day,
            )
        )
    points.sort(key=lambda point: point.as_of)
    return tuple(points)


# ---------------------------------------------------------------------------
# adapter：只做编排
# ---------------------------------------------------------------------------


class PriceAdapter:
    """`lme-price-mcp` 背后的业务逻辑。

    它**不判断自己跑在哪种模式下** —— 差异全在注入的 `Fetcher` 上（ADR-0003）。
    品种路由、请求形状、解析函数全部来自 `PRICE_SOURCES` 这张登记表。
    """

    def __init__(
        self,
        fetcher: Fetcher,
        sources: dict[str, PriceSource] | None = None,
        *,
        lookback_days: int = LOOKBACK_DAYS,
    ) -> None:
        self._fetcher = fetcher
        self._sources = sources if sources is not None else PRICE_SOURCES
        self._lookback_days = lookback_days

    # -- 工具入口 ----------------------------------------------------------

    async def get_price(self, commodity: str, requested_date: str, now: datetime) -> PriceLookup:
        self._check(commodity)
        requested = parse_requested_date(requested_date)
        source = self._sources.get(commodity)
        if source is None:
            return self._not_wired(commodity, requested_date, now)

        point, failure = await self._latest_at_or_before(source, requested)
        if failure is not None:
            return PriceLookup(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=failure,
                retrieved_at=now,
                commodity=commodity,
                requested_date=requested_date,
                point=None,
            )
        if point is None:
            # **一次成功的判定**：源是好的，确实是这个搜索范围内没有数据。
            return PriceLookup(
                status="ok",
                source_status=FetchStatus.EMPTY,
                retrieved_at=now,
                commodity=commodity,
                requested_date=requested_date,
                point=None,
            )
        return PriceLookup(
            status="ok",
            source_status=FetchStatus.OK,
            retrieved_at=now,
            commodity=commodity,
            requested_date=requested_date,
            # 把"被问的那天"写进这一条 —— 回退与否由 `as_of < requested_date` 表达
            # （ADR-0004），所以这个字段必须在离开工具前补上。
            point=point.model_copy(update={"requested_date": requested_date}),
        )

    async def _latest_at_or_before(
        self, source: PriceSource, requested: _date
    ) -> tuple[PricePoint | None, str | None]:
        """往前找**第一个有行情**的日子，找到就停。

        找到即停很要紧：逐日接口每个日历日一次请求，而绝大多数查询第一次就命中。
        """
        if source.quote_format == "sina_kline":
            raw = await self._fetch(source, None)
            if isinstance(raw, str):
                return None, raw
            if not raw.ok:
                return None, f"{source.exchange} 行情接口返回 HTTP {raw.status}，本次未能取到数据。"
            earlier = [
                point
                for point in parse_sina_kline(raw, source)
                if point.as_of <= requested.isoformat()
            ]
            return (earlier[-1] if earlier else None), None

        for day in candidate_dates(requested, self._lookback_days):
            stamp = day.strftime("%Y%m%d")
            raw = await self._fetch(source, stamp)
            if isinstance(raw, str):
                return None, raw
            if not raw.ok:
                # 非 200 是"源取不到"，不是"这天没行情" —— 立刻停手，不要
                # 把一次源故障放大成"往前找了十天都没有"。A7 压在这条分界线上。
                return None, f"{source.exchange} 行情接口返回 HTTP {raw.status}，本次未能取到数据。"
            point = parse_gfex_daily(raw, source, day.isoformat())
            if point is not None:
                return point, None
        return None, None

    async def get_trend(self, commodity: str, days: int, now: datetime) -> PriceSeries:
        self._check(commodity)
        if days <= 0:
            raise ValueError(f"days 必须为正整数，收到 {days}")
        source = self._sources.get(commodity)
        if source is None:
            return PriceSeries(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=_PENDING.get(commodity, f"{commodity} 的价格源尚未接入"),
                retrieved_at=now,
                commodity=commodity,
                exchange="",
                requested_days=days,
                points=(),
            )

        window_start = (trading_date(now) - timedelta(days=days)).isoformat()
        points, failure = await self._series(
            source, candidates=candidate_dates(trading_date(now), days)
        )
        points = tuple(point for point in points if point.as_of >= window_start)
        if failure is not None:
            return PriceSeries(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=failure,
                retrieved_at=now,
                commodity=commodity,
                exchange=source.exchange,
                requested_days=days,
                points=(),
            )

        return PriceSeries(
            status="ok",
            source_status=FetchStatus.OK if points else FetchStatus.EMPTY,
            reason=None if points else f"最近 {days} 天内没有取到 {commodity} 的行情。",
            retrieved_at=now,
            commodity=commodity,
            exchange=source.exchange,
            requested_days=days,
            points=points,
        )

    # -- 内部 --------------------------------------------------------------

    def _check(self, commodity: str) -> None:
        if commodity not in SUPPORTED_COMMODITIES:
            raise ValueError(
                f"品种 {commodity!r} 不在覆盖范围内，可选：{'、'.join(SUPPORTED_COMMODITIES)}"
            )

    def _not_wired(self, commodity: str, requested_date: str, now: datetime) -> PriceLookup:
        return PriceLookup(
            status="degraded",
            source_status=FetchStatus.UNAVAILABLE,
            reason=_PENDING.get(commodity, f"{commodity} 的价格源尚未接入"),
            retrieved_at=now,
            commodity=commodity,
            requested_date=requested_date,
            point=None,
        )

    async def _series(
        self, source: PriceSource, *, candidates: list[_date]
    ) -> tuple[tuple[PricePoint, ...], str | None]:
        """窗口内的价格点，由旧到新。失败时返回 `(空, 说明)`。

        逐日接口要把窗口里每个候选日都问一遍 —— 这是它的形状决定的，躲不掉；
        跳掉周末后，7 天窗口是 6 次请求。全历史接口则一次请求本地裁。
        """
        if source.quote_format == "sina_kline":
            raw = await self._fetch(source, None)
            if isinstance(raw, str):
                return (), raw
            if not raw.ok:
                return (), f"{source.exchange} 行情接口返回 HTTP {raw.status}，本次未能取到数据。"
            return parse_sina_kline(raw, source), None

        points: list[PricePoint] = []
        for day in reversed(candidates):  # 由旧到新，结果天然是升序
            raw = await self._fetch(source, day.strftime("%Y%m%d"))
            if isinstance(raw, str):
                return (), raw
            if not raw.ok:
                return (), f"{source.exchange} 行情接口返回 HTTP {raw.status}，本次未能取到数据。"
            point = parse_gfex_daily(raw, source, day.isoformat())
            if point is not None:
                points.append(point)
        return tuple(points), None

    async def _fetch(self, source: PriceSource, trade_date: str | None) -> RawResponse | str:
        """取一次数据。返回 `str` 表示取数失败，内容是给用户看的说明。"""
        try:
            if trade_date is not None:
                return await self._fetcher.post_form(
                    source.quote_url,
                    {"trade_date": trade_date, "trade_type": "0", "variety": source.symbol},
                )
            return await self._fetcher.fetch(source.quote_url)
        except ReplayMiss:
            # 录播缺失不是"这个源挂了"，是"我们的 fixture 集不全"。降级成"数据缺失"
            # 会让人去查一个根本没坏的交易所 —— 让它炸穿（ADR-0002）。
            raise
        except Exception as exc:
            return f"{source.exchange} 行情接口取数失败：{type(exc).__name__}"
