"""MCP 工具的统一返回信封（ADR-0005）。

核心主张：**"取到了 / 真的没有数据 / 取数降级"是正常返回的字段，不是异常。**
只有参数非法这类"工具自己坏了"才抛异常。

后果：数据源故障被吸收进信封，于是图只需要隔离"工具链本身失效"这一种情况。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class FetchStatus(StrEnum):
    """上游数据源的状态。四种取值对应四件不同的事，简报第 6 节要如实区分。"""

    OK = "ok"
    """源可达，且拿到了本次请求范围内的数据。"""

    EMPTY = "empty"
    """源可达，但**确实没有**符合范围的数据（如窗口内没有相关新闻）。

    这是**一次成功的判定**，不是降级 —— 把它和"抓取失败"混起来，简报第 6 节就
    再也说不清"到底是今天没新闻，还是网站挂了"。"""

    PARTIAL = "partial"
    """多来源里只有一部分取到了，结果不完整（如两家新闻源挂了一家）。"""

    UNAVAILABLE = "unavailable"
    """拿不到数据：抓取失败 / 源不可达 / 该源尚未接入。"""


EnvelopeStatus = Literal["ok", "degraded"]

#: 哪些状态算"工具跑通了"。EMPTY 在内：判定"没有数据"本身就是一次成功的执行。
_ACCEPTABLE: frozenset[FetchStatus] = frozenset({FetchStatus.OK, FetchStatus.EMPTY})

#: 哪些状态**必须**给出 reason。EMPTY 不需要 —— 它没有坏掉的东西要解释。
_REASON_REQUIRED: frozenset[FetchStatus] = frozenset({FetchStatus.PARTIAL, FetchStatus.UNAVAILABLE})


class Envelope(BaseModel):
    """所有工具返回值的顶层公共部分。"""

    model_config = ConfigDict(frozen=True)

    status: EnvelopeStatus
    """工具对本次结果的自我判定。"""

    source_status: FetchStatus

    reason: str | None = None
    """降级的人话说明 —— 缺什么、为什么缺。`PARTIAL` / `UNAVAILABLE` 时必须有值，
    否则调用方只能打印一句"失败了"，而简报第 6 节存在的意义正是说清为什么。"""

    retrieved_at: datetime
    """本次取数的时点。回放模式下是 fixture 锚点时间，不是系统时钟（ADR-0002）。"""

    @model_validator(mode="after")
    def _check_status_agrees_with_source_status(self) -> Self:
        expected: EnvelopeStatus = "ok" if self.source_status in _ACCEPTABLE else "degraded"
        if self.status != expected:
            raise ValueError(
                f"source_status={self.source_status} 时 status 必须是 {expected}，"
                f"收到 {self.status}"
            )
        if self.source_status in _REASON_REQUIRED and not (self.reason or "").strip():
            raise ValueError(f"source_status={self.source_status} 时必须写清 reason")
        return self

    @property
    def is_ok(self) -> bool:
        """工具跑通了。**注意它不代表有数据** —— 那要看 payload 里的 items / points。"""
        return self.source_status in _ACCEPTABLE
