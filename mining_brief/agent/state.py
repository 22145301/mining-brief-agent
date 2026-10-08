"""图的状态（ADR-0007）。

**扁平 `TypedDict`，一个 reducer 都没有。** 三个并行 fetch 节点各写自己的 key
（`news` / `prices` / `resources`），不往共享列表里累积；缺失信息由 `assemble`
从三个信封（ADR-0005）推导。

不要"顺手"加 `Annotated[..., reducer]` —— 只有当某个 key 真的被两个以上并行分支
并发写时才需要，当前没有任何这样的 key。这个文件里一个 `Annotated` 都没有，是刻意的。
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from mining_brief.agent.llm import LLMClient
from mining_brief.agent.toolkit import ToolKit
from mining_brief.config.settings import Settings
from mining_brief.contracts import (
    BriefResult,
    Citation,
    CitationReport,
    Hint,
    NewsSearchResult,
    PriceSeries,
    Refusal,
    ReportScope,
    ResourceExtract,
    RiskSignal,
    Section,
    Slots,
    Uncovered,
)


class BriefState(TypedDict, total=False):
    # --- 输入 ---------------------------------------------------------------
    request_text: str
    now: datetime
    """回放模式下 = fixture 锚点时间，不是系统时钟（ADR-0002）。"""

    settings: Settings
    llm: LLMClient
    toolkit: ToolKit

    # --- 1 / 2 号节点（模型在这里）------------------------------------------
    slots: Slots
    scope: ReportScope | None
    uncovered: tuple[Uncovered, ...]

    # --- 3 号节点：不在覆盖内 → 拒答 → END ----------------------------------
    refusal: Refusal | None

    # --- 4a / 4b / 4c：三个并行 fetch，各写各的 key -------------------------
    news: NewsSearchResult | None
    prices: dict[str, PriceSeries] | None
    resources: ResourceExtract | None

    # --- 5 / 6 / 7 / 8 / 9 号节点 ------------------------------------------
    signals: tuple[RiskSignal, ...]
    hints: tuple[Hint, ...]
    sections: tuple[Section, ...]
    narratives: dict[str, str]
    citations: tuple[Citation, ...]
    citation_report: CitationReport | None
    result: BriefResult | None

    # --- 顺序节点的降级备注（单写者，所以不需要 reducer）--------------------
    notes: tuple[str, ...]
    """每个顺序写者读旧值、返回带新增项的整条元组。这些节点**不并发**，
    所以 LangGraph 的覆盖语义就是对的。三路 fetch 的失败**不进这里** ——
    它们走信封（ADR-0005），避免同一个事实存两处、日后漂移（ADR-0007）。"""
