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
    """合约所在的交易所。它**不一定**是数据的发布方 —— 见 `publisher`。"""

    publisher: str
    """这条行情**实际的发布方**，引用清单里 `publisher` 印的就是它（ADR-0010）。

    与 `exchange` 分开是因为二者真的会不同：铁矿石的合约是 DCE 的，但数据取自
    新浪财经转载的日 K 线（`www.dce.com.cn` 对本环境返回 412，见 `PRICE_SOURCES`
    的说明）。契约里若只有 `exchange`，引用块就只能印出「发布方写 DCE、链接写新浪」
    这样一个自相矛盾的样子 —— 而 `Citation.publisher` 的契约是**原样搬运工具返回值**
    （`contracts/brief.py:110`），工具不返回它，那一行就搬不出东西来。
    """

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
