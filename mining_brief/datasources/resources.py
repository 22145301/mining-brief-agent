"""储量数据源。**本票（01）只交付契约面**：参数校验是真的，PDF 解析链路还没接。

05 号工单把它接上，并在那里处理 R2 与 ground truth 的人工核对卡点。
"""

from __future__ import annotations

from datetime import datetime

from mining_brief.contracts import FetchStatus, ResourceExtract

_NOT_WIRED = "技术报告 PDF 解析链路尚未接入（见工单 05）"


class ResourceAdapter:
    def __init__(self, fetcher: object | None = None) -> None:
        self._fetcher = fetcher

    async def extract_resources(self, pdf_url: str, now: datetime) -> ResourceExtract:
        if not pdf_url.strip():
            raise ValueError("pdf_url 不能为空")
        return ResourceExtract(
            status="degraded",
            source_status=FetchStatus.UNAVAILABLE,
            reason=_NOT_WIRED,
            retrieved_at=now,
            table=None,
        )
