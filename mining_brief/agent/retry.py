"""fetch 节点的有界重试。

**只有 fetch 节点重试。** 纯函数节点不重试（ADR-0006）—— 它们没有"重试"这个
概念，同样的输入永远得到同样的结果，抛异常就是 bug。

重试的是**工具链本身**的瞬时故障：进程没起来、管道断了、协议握手失败。数据源
自己的故障（源挂了、页面改版）不在这里重试 —— 那些已经被 adapter 吸收进降级
信封，是**一次成功的工具调用**，重试它们只是白等（ADR-0005）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from mining_brief.errors import LoudFailure

T = TypeVar("T")


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay_s: float,
    label: str,
    on_retry: Callable[[int, int, float, Exception], None] | None = None,
) -> T:
    """跑 `operation`，失败则按指数退避重试，直到用完 `attempts` 次再抛最后一次的异常。

    退避是为了让"重试"真的有用 —— 立刻重试三次对"进程冷启动失败"毫无帮助。
    `base_delay_s=0` 时不 sleep，测试里走这条。
    """
    if attempts < 1:
        raise ValueError(f"attempts 至少为 1，收到 {attempts}")

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except LoudFailure:
            # 录播缺失重试一万次也还是缺失；缺浏览器同理 —— 立刻上抛，不浪费退避的时间。
            raise
        except Exception as exc:
            last = exc
            if attempt >= attempts:
                break
            delay = base_delay_s * (2 ** (attempt - 1))
            if on_retry is not None:
                on_retry(attempt, attempts, delay, exc)
            if delay > 0:
                await asyncio.sleep(delay)

    assert last is not None  # attempts >= 1 保证循环至少进过一次
    raise last


def retry_params(state: Mapping[str, Any]) -> tuple[int, float]:
    """从 state 里读重试参数。`settings` 缺席时用保守的缺省值。

    收 `Mapping` 而不是 `dict`：调用方传进来的是 `BriefState`（TypedDict），
    它**不是** `dict` 的子类型，但可以是 `Mapping`。
    """
    settings = state.get("settings")
    if settings is None:
        return 3, 0.0
    return settings.fetch_attempts, settings.retry_base_delay_s
