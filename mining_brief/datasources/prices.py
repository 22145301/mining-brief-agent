"""价格数据源。**本票（01）只交付契约面**：参数校验是真的，取数链路还没接。

三条链路分别在后面两张票里落地：GFEX（锂）与 DCE（铁矿石）走纯 HTTP 见 03，
LME（铜）走无头浏览器见 04。在此之前它们如实返回不可用信封 —— 这正是 01 号工单
要证明的事：**某个源没接上时，简报照样出，只是那一节标注缺失**。
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

from mining_brief.contracts import FetchStatus, PriceLookup, PriceSeries

SUPPORTED_COMMODITIES: tuple[str, ...] = ("lithium", "copper", "iron_ore")

#: 未接入时写进 `reason` 的说明。它必须说清"为什么缺"，因为简报第 6 节会原样呈现。
_NOT_WIRED = "价格抓取链路尚未接入（锂/铁矿石见工单 03，铜见工单 04）"


def parse_requested_date(value: str) -> _date:
    """参数非法就抛 —— 这是"工具自己坏了"，按 ADR-0005 该炸，不该混进信封。"""
    try:
        return _date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date 需要是 ISO 日期（如 2026-10-08），收到 {value!r}") from exc


class PriceAdapter:
    def __init__(self, fetcher: object | None = None) -> None:
        self._fetcher = fetcher

    def _check(self, commodity: str) -> None:
        if commodity not in SUPPORTED_COMMODITIES:
            raise ValueError(
                f"品种 {commodity!r} 不在覆盖范围内，可选：{'、'.join(SUPPORTED_COMMODITIES)}"
            )

    async def get_price(self, commodity: str, requested_date: str, now: datetime) -> PriceLookup:
        self._check(commodity)
        parse_requested_date(requested_date)
        return PriceLookup(
            status="degraded",
            source_status=FetchStatus.UNAVAILABLE,
            reason=_NOT_WIRED,
            retrieved_at=now,
            commodity=commodity,
            requested_date=requested_date,
            point=None,
        )

    async def get_trend(self, commodity: str, days: int, now: datetime) -> PriceSeries:
        self._check(commodity)
        if days <= 0:
            raise ValueError(f"days 必须为正整数，收到 {days}")
        return PriceSeries(
            status="degraded",
            source_status=FetchStatus.UNAVAILABLE,
            reason=_NOT_WIRED,
            retrieved_at=now,
            commodity=commodity,
            exchange="",
            requested_days=days,
            points=(),
        )
