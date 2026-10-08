"""储量一节在**多座矿山**时怎么说话（工单 06）。

为什么单独一个文件：这一组断言的是**措辞与归属**，不是数据对不对 —— 数据对不对由
`tests/test_resources.py` 管。而当一份日报覆盖八座矿山时，"哪个数字是谁的"本身就是
正确性问题：一行 `Measured（资源量）：19.0 Mt，品位 1.4 %` 不带矿山名，读者无从判断
它是哪座矿的，**而它看起来完全正常**。

这里用手搭的状态而不是真档案跑端到端，是因为要考的是"覆盖两座矿"这个**情形**，
不是"档案里恰好是哪八座矿"这个**事实** —— 后者随档案变、前者不该变。
"""

from __future__ import annotations

from datetime import UTC, datetime

from mining_brief.agent.citations import CitationLedger
from mining_brief.agent.nodes import _resources_section, assemble
from mining_brief.agent.state import BriefState, ResourceLookup
from mining_brief.contracts import (
    ArchiveEntryRef,
    Commodity,
    FetchStatus,
    PageRef,
    ReportingStandard,
    ReportScope,
    ResourceCategory,
    ResourceExtract,
    ResourceRow,
    ResourceTable,
    Section,
    SectionKey,
)

NOW = datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)


def _ref(project: str, commodity: Commodity, company: str = "示例公司") -> ArchiveEntryRef:
    return ArchiveEntryRef(
        id=project.lower(), project=project, company=company, commodity=commodity, spoken_as=project
    )


def _table(project: str, standard: ReportingStandard, report_date: str) -> ResourceTable:
    return ResourceTable(
        pdf_url=f"https://example.invalid/{project}.pdf",
        report_title=f"{project} 技术报告",
        report_date=report_date,
        standard=standard,
        project=project,
        commodity="lithium",
        rows=(
            ResourceRow(
                category=ResourceCategory.MEASURED,
                tonnage_mt=19.0,
                grade=1.4,
                grade_unit="%",
                contained=0.3,
            ),
            ResourceRow(
                category=ResourceCategory.PROBABLE,
                tonnage_mt=7.0,
                grade=1.1,
                grade_unit="%",
                contained=0.1,
            ),
        ),
        page_refs=(PageRef(label="资源量分类表", page=36),),
    )


def _has_table(project: str, standard: ReportingStandard, report_date: str) -> ResourceLookup:
    return ResourceLookup(
        entry=_ref(project, "lithium"),
        extract=ResourceExtract(
            status="ok",
            source_status=FetchStatus.OK,
            retrieved_at=NOW,
            table=_table(project, standard, report_date),
        ),
    )


def _no_table(project: str, reason: str) -> ResourceLookup:
    return ResourceLookup(
        entry=_ref(project, "copper"),
        extract=ResourceExtract(
            status="degraded",
            source_status=FetchStatus.UNAVAILABLE,
            reason=reason,
            retrieved_at=NOW,
            table=None,
        ),
    )


def _state(lookups: tuple[ResourceLookup, ...]) -> BriefState:
    return {
        "now": NOW,
        "scope": ReportScope(entries=tuple(lookup.entry for lookup in lookups), window_days=7),
        "resources": lookups,
        "news": None,
        "prices": {},
        "signals": (),
        "notes": (),
    }


def _section(lookups: tuple[ResourceLookup, ...]) -> Section:
    return _resources_section(_state(lookups), CitationLedger())


# ---------------------------------------------------------------------------
# 归属：多座矿时每一行都要点名
# ---------------------------------------------------------------------------


def test_every_number_carries_its_mine_when_more_than_one_is_in_scope() -> None:
    """八座矿的日报里，一行不带矿山名的数字是**硬错误**，不是风格问题。"""
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
        )
    )

    assert section.facts, "两座矿都有表，这一节不该是空的"
    for fact in section.facts:
        assert fact.text.startswith(("Pilgangoora：", "Shaakichiuwaanaan：")), (
            f"覆盖两座矿时每一行都该带矿山名，这一行没有：{fact.text}"
        )

    # 同一类别在两座矿上出现两次，各自带自己的名字 —— 这正是最容易被合并的一处。
    measured = [fact.text for fact in section.facts if "Measured" in fact.text]
    assert len(measured) == 2, f"两座矿的 Measured 应当各占一行：{measured}"
    assert measured[0].split("：")[0] != measured[1].split("：")[0], "两行指了同一座矿"


def test_reserve_and_resource_are_labelled_apart_even_with_multi_mine_prefixes() -> None:
    """`Probable` 是**储量**、`Measured` 是**资源量** —— 前缀加进来了也不能把这个说混。"""
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
        )
    )
    joined = "\n".join(fact.text for fact in section.facts)
    assert "Measured（资源量）" in joined
    assert "Probable（储量）" in joined


def test_a_single_mine_keeps_the_bare_wording() -> None:
    """只覆盖一座矿时**不加**前缀 —— 那时整节都是它的，加前缀是噪音。

    这条同时是回归护栏：工单 05 的端到端用例断言过 `数据缺失 —— <理由>` 这个精确
    字面，而"顺手给所有情形都加前缀"会让那条断言红。两处要的其实是同一件事。
    """
    section = _section((_has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),))
    for fact in section.facts:
        assert not fact.text.startswith("Pilgangoora："), f"单座矿不该带前缀：{fact.text}"


def test_a_single_mine_with_no_table_keeps_the_exact_gap_wording() -> None:
    """单座矿、没表时，note 就是 `数据缺失 —— <理由>`，一个字不改。"""
    section = _section((_no_table("Escondida", "技术报告直链未核实到，本次无法抽取储量数据。"),))
    assert section.note == "数据缺失 —— 技术报告直链未核实到，本次无法抽取储量数据。"
    assert section.facts == ()


# ---------------------------------------------------------------------------
# 缺口：有内容也有缺口时，缺口不能被内容的数量盖过去
# ---------------------------------------------------------------------------


def test_a_missing_mine_is_named_in_the_section_not_only_in_the_integrity_section() -> None:
    """一份"两座矿有表、一座矿没有"的日报里，只读储量一节的读者也要看得到那座缺的。

    只在第 6 节点名是不够的：第 6 节是流水账，这一节才是决策时看的那一页。
    """
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
            _no_table("Mt Whaleback", "本公司不公开技术报告，直链未核实到。"),
        )
    )

    assert section.note is not None
    assert "Mt Whaleback" in section.note, f"缺口那座矿没被点名：{section.note}"
    assert "本公司不公开技术报告" in section.note, "只说了缺、没说为什么缺"


def test_the_section_as_of_is_the_earliest_report_date() -> None:
    """`as_of` 取最早的那份报告日期 —— 取最晚会**夸大**这一节的新鲜度。"""
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
        )
    )
    assert section.as_of == "2022-06-30", f"应当是保守下界，实际取了 {section.as_of}"
    assert section.note is not None
    assert "2025-06-20" in section.note and "2022-06-30" in section.note, (
        "两座矿的日期不同这件事要说出来，并说清本节取的是哪一份"
    )


def test_both_standards_are_listed_when_the_section_mixes_them() -> None:
    """一节里可能出现两种报告体系 —— note 列的是**出现过的**全集，不是某一个。"""
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
        )
    )
    assert section.note is not None
    assert "JORC" in section.note and "NI 43-101" in section.note


def test_every_mine_gets_its_own_citation() -> None:
    """两座矿的表各有各的引用块 —— 合并成一个编号会让"翻到那一页去核"落空。"""
    section = _section(
        (
            _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
            _has_table("Shaakichiuwaanaan", ReportingStandard.NI_43_101, "2025-06-20"),
        )
    )
    numbers = {fact.citation for fact in section.facts}
    assert len(numbers) == 2, f"两座矿该有两个引用编号，实际 {numbers}"


# ---------------------------------------------------------------------------
# 第 6 节：逐矿一行
# ---------------------------------------------------------------------------


def test_the_integrity_section_reports_resources_one_mine_per_line() -> None:
    """一句笼统的"储量：已取到"会让缺的那几座藏在一句真话后面。"""
    lookups = (
        _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
        _no_table("Mt Whaleback", "本公司不公开技术报告，直链未核实到。"),
    )
    state = _state(lookups)
    state["refusal"] = None
    sections = assemble(state)
    integrity = next(s for s in sections["sections"] if s.key is SectionKey.INTEGRITY)

    per_mine = [fact.text for fact in integrity.facts if fact.text.startswith("储量（")]
    assert len(per_mine) == 2, f"两座矿该各占一行：{per_mine}"
    assert "Pilgangoora" in per_mine[0] and "Mt Whaleback" in per_mine[1]
    assert "已取到" not in per_mine[1], "取不到的那座不能被写成取到了"


def test_the_scale_of_the_document_is_visible_in_the_scope_line() -> None:
    """第 6 节第一行要写清本次覆盖了哪些矿山 —— 否则读者无法判断"缺的那座"是不是
    根本没被问过。"""
    lookups = (
        _has_table("Pilgangoora", ReportingStandard.JORC, "2022-06-30"),
        _no_table("Mt Whaleback", "本公司不公开技术报告，直链未核实到。"),
    )
    state = _state(lookups)
    state["refusal"] = None
    sections = assemble(state)
    integrity = next(s for s in sections["sections"] if s.key is SectionKey.INTEGRITY)

    first = integrity.facts[0].text
    assert first.startswith("覆盖范围：")
    assert "Pilgangoora" in first and "Mt Whaleback" in first
    assert "7 天" in first
