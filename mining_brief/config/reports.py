"""技术报告登记表 —— 每份要找的 PDF 长什么样、表在哪一页、列是什么顺序。

为什么需要它：**PDF 表格没有机器可读的 schema**。同一个项目换个年份、换家评估机构，
列的顺序、单位、表头措辞都会变。硬写一套"通用表格识别"是在假装这件事已经解决，
而它没有 —— 通用方案在这种版式上要么抽错、要么静默抽少。

所以这里的取舍是：**表的身份由人声明，解析器只负责两件事** —— 在一页文本里
认出"以法定类别词开头、后面跟着恰好 N 个数字"的行，再按声明好的列序把数字映射成
吨位 / 品位 / 含金属量。声明与页面不符时（表头标记找不到、行里的数字个数对不上）
**返回抽不到**，而不是凑一个看起来合理的表出来。

这与 `config/sources.py` 的 `QuoteFormat` 是同一个思路：把"数据长什么样"这件事
放进登记表，代码里就没有 `if project == "pilgangoora"`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mining_brief.contracts import ReportingStandard

ColumnRole = Literal["tonnage", "grade", "contained", "other"]
"""这一列在 `ResourceRow` 里落到哪个字段。

只有前三者有归宿 —— `ResourceRow` 按题面要求只承载"吨位 / 品位 / 品位单位 /
含金属量"。其余列（同一张表里的 Ta2O5、Fe2O3 之类）声明成 `other`：它们仍然
参与"这一行有几个数字"的核对（少一个就说明我们认错了行），但不进产物。
"""


@dataclass(frozen=True, slots=True)
class ReportColumn:
    """表里的一列。**在元组里的顺序 = 页面上的从左到右**。"""

    name: str
    """列名，给人看的（进 `PageRef.label`，让人翻到那一页能逐列核）。"""

    unit: str
    """这一列的单位，按**页面上的表头**抄下来。"""

    role: ColumnRole

    scale: float = 1.0
    """页面上的数字 × scale = 该列 `unit` 下的值。

    存在的唯一理由：有的报告吨位写 `Mdmt`（百万吨），有的写 `t`（吨）。
    把换算放进声明、而不是放进代码，是因为"这份报告用的是哪个量纲"是关于
    **这一份文件**的事实，不是关于解析算法的。
    """


@dataclass(frozen=True, slots=True)
class ReportSource:
    """一份技术报告里的资源量 / 储量表。"""

    slug: str
    """fixture 文件名，也是这份报告在本仓库里的身份。"""

    project: str
    company: str
    commodity: str
    standard: ReportingStandard
    """报告体系。**不参与解析** —— 两套体系共用 Measured / Indicated / Inferred
    这套分类词，所以解析路径是同一条，体系只是一份标注（题面注）。"""

    title: str
    report_date: str
    pdf_url: str

    header_marker: str
    """必须**在同一页**出现的字样，用来确认"这页确实是那张表所在的那页"。

    没有它的话，一页别的正文里只要碰巧有一行以 `Indicated` 开头、后面跟着刚好
    合适个数的数字，就会被读成一行资源量。
    """

    columns: tuple[ReportColumn, ...]

    page_hint: int | None = None
    """已知在第几页。**不参与解析**，只写进工单与报告里给人核对用 ——
    解析器仍然逐页扫描，因为页码会随版本变。"""


PILBARA_CET = ReportSource(
    slug="pilgangoora-cet-2022",
    project="Pilgangoora",
    company="Pilbara Minerals",
    commodity="lithium",
    standard=ReportingStandard.JORC,
    title="Pilgangoora Exploration Geology（CET 演讲材料，资源量引自 2022 年报）",
    report_date="2022-06-30",
    pdf_url="https://cet.edu.au/wp-content/uploads/Talk-6-Holmes_Pilgangoora-Exploration-Geology.pdf",
    header_marker="Mineral Resource as at",
    columns=(
        # 页面表头逐字是：Tonnes(Mdmt) Li2O(%) Ta2O5(ppm) Fe2O3(%) Li2O(Mt) Ta2O5(Mlb)
        ReportColumn("吨位", "Mt", "tonnage"),
        ReportColumn("Li2O 品位", "%", "grade"),
        ReportColumn("Ta2O5 品位", "ppm", "other"),
        ReportColumn("Fe2O3 品位", "%", "other"),
        ReportColumn("Li2O 含量", "Mt", "contained"),
        ReportColumn("Ta2O5 含量", "Mlb", "other"),
    ),
    page_hint=36,
)

PMET_CV5_CV13 = ReportSource(
    slug="pmet-shaakichiuwaanaan-2025",
    project="Shaakichiuwaanaan (CV5 + CV13)",
    company="PMET Resources",
    commodity="lithium",
    standard=ReportingStandard.NI_43_101,
    title="PMET Resources Site Visit — NI 43-101 Mineral Resource Statement",
    report_date="2025-06-20",
    pdf_url="https://www.pmet.ca/wp-content/uploads/2026/04/PMET_Site_Visit_September_2026_Final_to_lodge-1.pdf",
    header_marker="NI 43-101 Mineral Resource Statement",
    columns=(
        # 页面表头逐字是：Tonnes(t) Li2O(%) Cs2O(%) Ta2O5(ppm) Ga(ppm) Contained LCE(Mt)
        ReportColumn("吨位", "Mt", "tonnage", scale=1e-6),
        ReportColumn("Li2O 品位", "%", "grade"),
        ReportColumn("Cs2O 品位", "%", "other"),
        ReportColumn("Ta2O5 品位", "ppm", "other"),
        ReportColumn("Ga 品位", "ppm", "other"),
        ReportColumn("LCE 含量", "Mt", "contained"),
    ),
    page_hint=41,
)

REPORT_SOURCES: dict[str, ReportSource] = {
    source.slug: source for source in (PILBARA_CET, PMET_CV5_CV13)
}


def source_by_pdf_url(pdf_url: str) -> ReportSource | None:
    """按直链反查登记项 —— 档案里存的是 URL，工具收到的是 URL。"""
    return next((s for s in REPORT_SOURCES.values() if s.pdf_url == pdf_url), None)
