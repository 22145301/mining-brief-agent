"""`mineral-pdf-mcp` 的工具返回契约。

术语纪律（CONTEXT.md）在这里**落成类型**：`Measured / Indicated / Inferred` 是
**资源量（Resource）**，`Proven / Probable` 是**储量（Reserve）** —— 两者是不同
类别，不是同一把尺子的不同档。题面把前者称作"储量"是笔误，同一份题面的题 #3
用对了词。把这个区分写成 `kind` 属性而不是一句注释，是为了让"节内按真实类别标注"
这条验收能**被断言**，而不是只能靠人眼。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from mining_brief.contracts.envelope import Envelope


class ResourceKind(StrEnum):
    RESOURCE = "resource"
    """资源量：按地质置信度估算的矿化量。"""

    RESERVE = "reserve"
    """储量：资源量中经修正因素评估后可经济开采的部分。"""


class ResourceCategory(StrEnum):
    """两类体系（NI 43-101 与 JORC）**共用**这套分类词，因此解析层统一处理。"""

    MEASURED = "Measured"
    INDICATED = "Indicated"
    INFERRED = "Inferred"
    PROVEN = "Proven"
    PROBABLE = "Probable"

    @property
    def kind(self) -> ResourceKind:
        if self in (ResourceCategory.PROVEN, ResourceCategory.PROBABLE):
            return ResourceKind.RESERVE
        return ResourceKind.RESOURCE


class ReportingStandard(StrEnum):
    NI_43_101 = "NI 43-101"
    JORC = "JORC"


class ResourceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: ResourceCategory
    tonnage_mt: float | None = None
    """百万吨。拿不到就是 `None` —— 不填 0。"""

    grade: float | None = None
    grade_unit: str | None = None
    contained: float | None = None

    @property
    def kind(self) -> ResourceKind:
        return self.category.kind


class PageRef(BaseModel):
    """某个数字来自 PDF 第几页 —— 让使用者能直接翻过去核对（User Story 17）。"""

    model_config = ConfigDict(frozen=True)

    label: str
    page: int


class ResourceTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    pdf_url: str
    report_title: str
    report_date: str
    standard: ReportingStandard
    project: str
    commodity: str
    rows: tuple[ResourceRow, ...]
    page_refs: tuple[PageRef, ...]


class ResourceExtract(Envelope):
    table: ResourceTable | None = None
