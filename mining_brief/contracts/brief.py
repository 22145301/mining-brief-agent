"""简报本身的契约：槽位、范围、六节、风险信号、拒答、引用校验报告。

这些不进 MCP 传输，但它们是**跨节点**共享的形状，按 ADR-0005 的口径与工具信封
放在同一个包（`contracts`）里，避免三份近似类型各自漂移。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

Commodity = Literal["lithium", "copper", "iron_ore"]

DEFAULT_WINDOW_DAYS = 7
""""最近"的缺省含义（User Story 4）。"""


class Intent(StrEnum):
    """用户这句话想干什么。

    PRD §4.1 只规定三个**参数**槽位，但 §4.2 的拒答规则第 1 行要求系统能判出
    "意图不是出简报" —— 这个判断总得落在某个字段上。放在 `Slots` 里是为了让
    `parse_intent` 保持"唯一的意图闸门"：一句话进系统只被模型理解一次。
    """

    BRIEFING = "briefing"
    OUT_OF_SCOPE = "out_of_scope"


class Slots(BaseModel):
    """`parse_intent` 的产物：意图 + 三个槽位（PRD §4.1）。

    LLM 在这里做的是**封闭分类**，不是生成 —— 所以每个字段都有确定的取值域，
    抽不出来就是 `None`，绝不允许模型自创一个矿名。
    """

    model_config = ConfigDict(frozen=True)

    intent: Intent = Intent.BRIEFING
    commodity: Commodity | None = None
    mine: str | None = None
    """用户口中的矿山**原始说法**（可能是中文别称 / 英文名 / 交易所代码）。
    它还不是档案 id —— 落到档案是 `resolve_entities` 的事。"""

    window_days: int = DEFAULT_WINDOW_DAYS


class ArchiveEntryRef(BaseModel):
    """解析后指向档案条目的一条引用。"""

    model_config = ConfigDict(frozen=True)

    id: str
    project: str
    company: str
    commodity: Commodity
    spoken_as: str
    """用户在请求里实际用的是哪种说法 —— 回显给使用者，让他知道系统听懂了什么。"""


class ReportScope(BaseModel):
    """`check_scope` 判定后的覆盖范围。"""

    model_config = ConfigDict(frozen=True)

    entries: tuple[ArchiveEntryRef, ...]
    window_days: int

    @property
    def commodity_in_scope(self) -> tuple[Commodity, ...]:
        seen: list[Commodity] = []
        for entry in self.entries:
            if entry.commodity not in seen:
                seen.append(entry.commodity)
        return tuple(seen)


class Uncovered(BaseModel):
    """ "用户提到了、但档案里没有" —— 这是**一个确定状态**，不是一次查询失败。"""

    model_config = ConfigDict(frozen=True)

    spoken: str
    kind: Literal["mine", "commodity"]


class Refusal(BaseModel):
    """超出系统能力时的唯一正确输出：回显听懂的部分 + 列出可用句式。

    拒答是**一次成功执行**的结果，不是异常（CONTEXT.md）。
    """

    model_config = ConfigDict(frozen=True)

    understood: str
    """回显系统听懂了的那部分，让使用者看出是哪里没被理解（User Story 24）。"""

    why: str
    """为什么这超出能力范围。"""

    usable_phrasings: tuple[str, ...]
    """可用句式示例，让使用者下一次能问对（User Story 23）。"""


class Citation(BaseModel):
    """来源清单里的一条。

    `title` / `url` / `publisher` / `timestamp` 四个字段是**原样搬运**工具返回值，
    不允许任何转述后补链接（PRD §5.2 硬规则 1）。
    """

    model_config = ConfigDict(frozen=True)

    index: int
    kind: Literal["news", "price", "resource"]
    title: str
    url: str
    publisher: str
    timestamp: str


class SectionKey(StrEnum):
    """六节。前四节 + 风险提示是题面要求，后两节是本项目增补（PRD §5.1）。"""

    MINING_RIGHTS = "mining_rights"
    NEWS = "news"
    RESOURCES = "resources"
    PRICES = "prices"
    RISKS = "risks"
    INTEGRITY = "integrity"


SECTION_TITLES: dict[SectionKey, str] = {
    SectionKey.MINING_RIGHTS: "矿权动态",
    SectionKey.NEWS: "新闻摘要",
    SectionKey.RESOURCES: "储量数据",
    SectionKey.PRICES: "价格走势",
    SectionKey.RISKS: "风险提示",
    SectionKey.INTEGRITY: "数据完整性",
}


class Fact(BaseModel):
    """一节里的一行事实。`citation` 指向来源清单的编号，`None` 表示无需引用。"""

    model_config = ConfigDict(frozen=True)

    text: str
    citation: int | None = None


class Section(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: SectionKey
    title: str
    as_of: str | None
    """本节数据实际对应的时点。各节不同是数据的真实形态，不掩饰（PRD §5.2 硬规则 3）。"""

    facts: tuple[Fact, ...] = ()
    lead: str | None = None
    """`narrate` 节点写的一句导读。输入是已冻结的该节数据，模型不参与事实生成。"""

    note: str | None = None
    """本节的补充说明（如"数据缺失"、"本次未触发"）。"""


class RiskSignal(BaseModel):
    """由**规则**触发的风险提示，每条必须能逐字引到权威公开原文。"""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    title: str
    triggered_by: str
    verbatim: str
    """逐字引用的权威原文。"""

    source_url: str
    source_label: str


class Hint(BaseModel):
    """够不上"逐字引权威原文"的观察只能作为提示出现，不进风险信号。"""

    model_config = ConfigDict(frozen=True)

    text: str
    why_not_a_signal: str


class CitationReport(BaseModel):
    """`verify_citations` 的产物。不通过即报错，所以它只会以 `ok=True` 存活。"""

    model_config = ConfigDict(frozen=True)

    ok: bool
    checked: int
    declared: tuple[int, ...]


class BriefResult(BaseModel):
    """`render` 之后返回给 CLI 的最终产物。"""

    model_config = ConfigDict(frozen=True)

    output_path: str
    sections: tuple[Section, ...]
    citations: tuple[Citation, ...]
    refusal: Refusal | None = None
    uncovered: tuple[Uncovered, ...] = ()
