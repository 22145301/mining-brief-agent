"""抓取层的原始响应。

ADR-0003 的两段式里，`Fetcher` 的返回就是它 —— **不含任何解析结果**。
存进 fixture 的也是它（逐字节），所以它必须能无损序列化（ADR-0002）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RawResponse(BaseModel):
    """一次抓取的原始产物：**body 是逐字节原文**，不做任何归一化。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    url: str
    status: int
    content_type: str
    body: bytes = Field(repr=False)
    fetched_at: datetime

    @property
    def ok(self) -> bool:
        """HTTP 语义上的成功。注意它**只**说传输层，不说内容对不对。"""
        return 200 <= self.status < 300

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")
