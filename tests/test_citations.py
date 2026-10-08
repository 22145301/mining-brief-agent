"""引用校验与编号（PRD §5.2 硬规则 2）。

这些是纯函数测试，不打网络、不起 MCP、不落盘 —— 引用规则本身值得被单独钉死，
因为它是"每个事实都能回溯"这句承诺的**执行者**。
"""

from __future__ import annotations

import pytest

from mining_brief.agent.citations import CitationError, CitationLedger, verify
from mining_brief.contracts import Fact, Section, SectionKey


def _section(*facts: Fact, key: SectionKey = SectionKey.NEWS) -> Section:
    return Section(key=key, title="测试节", as_of=None, facts=facts)


def test_ledger_numbers_sources_in_first_appearance_order() -> None:
    """编号顺序必须**确定** —— 用集合的话同一份数据两次跑出来的编号会不同，
    端到端断言就没法逐字比对了。"""
    ledger = CitationLedger()
    first = ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")
    second = ledger.cite(kind="news", title="B", url="https://b", publisher="P", timestamp="T2")
    again = ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")

    assert (first, second, again) == (1, 2, 1)
    assert [c.index for c in ledger.citations] == [1, 2]
    assert [c.title for c in ledger.citations] == ["A", "B"]


def test_the_same_url_at_a_different_timestamp_is_a_different_source() -> None:
    """同一个页面被两家源转在两天的两个时刻，是两条不同的来源 —— 时间戳是身份的一部分。"""
    ledger = CitationLedger()
    first = ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")
    second = ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T2")

    assert (first, second) == (1, 2)


def test_verify_passes_when_every_reference_resolves_and_nothing_is_orphaned() -> None:
    ledger = CitationLedger()
    index = ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")

    report = verify([_section(Fact(text="事实", citation=index))], ledger.citations)

    assert report.ok is True
    assert report.checked == 1
    assert report.declared == (1,)


def test_verify_rejects_a_reference_to_a_source_that_does_not_exist() -> None:
    """A2：`[n]` 指不到东西就是**代码 bug**，必须炸，不许降级成一句提示。"""
    ledger = CitationLedger()
    ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")

    with pytest.raises(CitationError, match=r"不存在的来源 \[7\]"):
        verify([_section(Fact(text="凭空引用的", citation=7))], ledger.citations)


def test_verify_rejects_a_source_listed_but_never_referenced() -> None:
    """列了却没人引的来源是垃圾 —— 它会让读者以为某处有据可依。"""
    ledger = CitationLedger()
    ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")
    ledger.cite(kind="news", title="B", url="https://b", publisher="P", timestamp="T2")
    used = ledger.citations[0].index

    with pytest.raises(CitationError, match="没被任何事实引用"):
        verify([_section(Fact(text="只引了第一条", citation=used))], ledger.citations)


def test_verify_rejects_a_gap_in_the_numbering() -> None:
    ledger = CitationLedger()
    ledger.cite(kind="news", title="A", url="https://a", publisher="P", timestamp="T1")
    ledger.cite(kind="news", title="B", url="https://b", publisher="P", timestamp="T2")
    with_index_three = ledger.citations[1].model_copy(update={"index": 3})

    with pytest.raises(CitationError, match="从 1 开始的连续整数"):
        verify([], (ledger.citations[0], with_index_three))


def test_facts_may_have_no_citation_at_all() -> None:
    """有些事实是系统自己的状态（覆盖范围、数据缺失说明），它们不需要外部来源。"""
    report = verify([_section(Fact(text="本次未触发任何风险信号。"))], ())

    assert report.ok is True
    assert report.checked == 1
    assert report.declared == ()


def test_an_empty_brief_with_no_sources_is_valid() -> None:
    report = verify([], ())

    assert report.ok is True
    assert report.checked == 0
