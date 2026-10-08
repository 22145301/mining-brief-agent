"""`lme-price-mcp` —— 题面点名的三个 server 之一（server 名照题面，不自创）。

**薄壳**（ADR-0008）：参数校验 → adapter → 信封。品种路由（锂 → GFEX 碳酸锂、
铜 → LME、铁矿石 → DCE）写在 adapter 里，不在这里。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mining_brief.contracts import PriceLookup, PriceSeries
from mining_brief.datasources.prices import SUPPORTED_COMMODITIES
from mining_brief.servers.runtime import Runtime, default_runtime

mcp = FastMCP("lme-price-mcp")

_runtime_override: Runtime | None = None


def _runtime() -> Runtime:
    return _runtime_override or default_runtime()


def set_runtime(runtime: Runtime | None) -> None:
    """给测试用的注入点。生产路径上没人调用它。"""
    global _runtime_override
    _runtime_override = runtime


@mcp.tool()
async def get_price(commodity: str, date: str) -> PriceLookup:
    """取某个品种在指定日期的价格，**不晚于该日期**的最近一个可得值。

    **何时用**：需要"某一天的铜价/锂价/铁矿石价"时。

    **参数**：`commodity` 取 `lithium` / `copper` / `iron_ore`（各自会自动路由到
    GFEX 碳酸锂 / LME / DCE）；`date` 是 ISO 日期字符串，如 `2026-10-08`。

    **返回**：`PriceLookup` 信封。`point.as_of` 是数据实际对应日，`point.requested_date`
    是你传的日期 —— **两者不等即表示本次回退到了更早的日期**（跳过非交易日或尚未
    披露的日子）。`point.delayed` 是另一件事：它表示**数据源固有**的延迟披露
    （LME 恒为 true），不是回退标志。确实查不到时 `point` 为 `None`，**不会给 0 或近似值**。
    """
    runtime = _runtime()
    return await runtime.prices().get_price(
        commodity=commodity, requested_date=date, now=runtime.now()
    )


@mcp.tool()
async def get_trend(commodity: str, days: int) -> PriceSeries:
    """取某个品种最近 `days` 天的价格序列。

    **何时用**：要看走势而不只是单点时。

    **参数**：`commodity` 同上；`days` 是回溯天数（正整数）。

    **返回**：`PriceSeries` 信封，`points` 按时间排列，每个点带自己的一天。
    窗口内一天都没有时 `points` 为空且 `source_status` 说明原因。
    """
    runtime = _runtime()
    return await runtime.prices().get_trend(commodity=commodity, days=days, now=runtime.now())


__all__ = ["SUPPORTED_COMMODITIES", "mcp", "set_runtime"]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
