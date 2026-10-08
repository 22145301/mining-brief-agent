"""`lme-price-mcp` 的工具返回契约。

两个容易混的语义，这里分开（ADR-0004）：

- `delayed`：**数据源固有**的延迟披露（LME 恒为 `True`），是交易所的属性。
- 回退：本次查询要的那天没有数据，所以给了更早的一天 —— 一律由
  `as_of < requested_date` 表达，**不设独立标志位**。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mining_brief.contracts.envelope import Envelope


class PricePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    commodity: str
    exchange: str
    symbol: str
    value: float
    currency: str
    unit: str
    as_of: str
    """数据实际对应的日期，ISO-8601 字符串。"""

    delayed: bool
    """数据源固有延迟，**不是**回退标志。"""

    source_url: str
    requested_date: str
    """调用方要的日期。它不等于 `as_of` 时，本次发生了回退（ADR-0004）。"""

    @property
    def is_fallback(self) -> bool:
        """本次是否回退到了更早的日期。"""
        return self.as_of < self.requested_date


class PriceLookup(Envelope):
    """`get_price(commodity, date)` 的返回。"""

    commodity: str
    requested_date: str
    point: PricePoint | None = None
    """`None` 表示确实查不到 —— **不是 0，也不是近似值**（User Story 29）。"""


class PriceSeries(Envelope):
    """`get_trend(commodity, days)` 的返回。"""

    commodity: str
    exchange: str
    requested_days: int
    points: tuple[PricePoint, ...]
