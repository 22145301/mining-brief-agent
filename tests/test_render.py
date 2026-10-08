"""Markdown 渲染与落盘。

`render_markdown` 是纯函数，所以"日报长什么样"这一条能在这里被逐字钉死，
不需要跑一遍图、也不需要读一个临时文件。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from mining_brief.agent.render import brief_filename, render_markdown, write_brief
from mining_brief.contracts import (
    BriefResult,
    Citation,
    Fact,
    Refusal,
    Section,
    SectionKey,
)


def _citation(index: int = 1) -> Citation:
    return Citation(
        index=index,
        kind="news",
        title="Sigma Lithium stock jumps",
        url="https://www.mining.com/sigma-lithium/",
        publisher="MINING.COM",
        timestamp="2026-10-07T10:47:00+00:00",
    )


def _result(**overrides: object) -> BriefResult:
    base: dict[str, object] = {
        "output_path": "briefs/brief-2026-10-08.md",
        "sections": (
            Section(
                key=SectionKey.NEWS,
                title="新闻摘要",
                as_of="2026-10-07T10:47:00+00:00",
                facts=(Fact(text="一条新闻（MINING.COM）", citation=1),),
            ),
        ),
        "citations": (_citation(),),
    }
    base.update(overrides)
    return BriefResult.model_validate(base)


def test_filename_uses_the_data_time_not_the_wall_clock() -> None:
    """用系统时钟命名的话，同一份 fixture 每天跑出来的产物文件名都不一样。"""
    assert brief_filename(datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)) == "brief-2026-10-08.md"


def test_a_fact_with_a_citation_gets_its_number_and_the_source_is_listed() -> None:
    text = render_markdown(_result())

    assert "- 一条新闻（MINING.COM） [1]" in text
    assert "https://www.mining.com/sigma-lithium/" in text
    assert "MINING.COM · 2026-10-07T10:47:00+00:00" in text


def test_every_section_states_a_data_cutoff_even_when_there_is_none() -> None:
    """六节的截止时间各不相同是**数据的真实形态**，产物必须如实体现。"""
    text = render_markdown(
        _result(
            sections=(
                Section(
                    key=SectionKey.RESOURCES,
                    title="储量数据",
                    as_of=None,
                    note="数据缺失 —— 直链未核实到。",
                ),
            )
        )
    )

    assert "各节数据截止时间不同" in text
    assert "*数据时点：无法确定" in text
    assert "数据缺失 —— 直链未核实到。" in text


def test_the_header_says_how_many_sections_and_sources_there_are() -> None:
    text = render_markdown(_result())

    assert "共 1 节（新闻摘要）" in text
    assert "引用来源 1 条" in text


def test_a_brief_with_no_external_sources_says_so_instead_of_showing_nothing() -> None:
    text = render_markdown(_result(sections=(), citations=()))

    assert "本次简报没有需要引用的外部来源。" in text


def test_a_refusal_renders_as_a_document_explaining_itself() -> None:
    """拒答是**一次成功执行的结果**，所以它同样有产物，只是没有六节。"""
    refusal = Refusal(
        understood="我听懂了：铜。",
        why="本系统不做预测。",
        usable_phrasings=("出份锂的日报",),
    )
    text = render_markdown(_result(sections=(), citations=(), refusal=refusal))

    assert text.startswith("# 无法生成矿权日报")
    assert "我听懂了：铜。" in text
    assert "本系统不做预测。" in text
    assert "- 出份锂的日报" in text
    assert "来源清单" not in text


def test_write_brief_creates_parent_directories_and_returns_an_absolute_path(
    tmp_path: Path,
) -> None:
    result = _result(output_path=str(tmp_path / "nested" / "briefs" / "brief.md"))

    returned = write_brief(result)

    assert Path(returned).is_absolute()
    assert Path(returned).read_text("utf-8") == render_markdown(result)


def test_rendering_is_deterministic() -> None:
    """同样一份 `BriefResult` 永远得到同样的字符串 —— 否则端到端断言只能靠"约等于"。"""
    result = _result()

    assert render_markdown(result) == render_markdown(result)


def test_citation_urls_are_rendered_inside_angle_brackets_so_markdown_does_not_mangle_them() -> (
    None
):
    """URL 里有下划线时裸写会被 Markdown 当成强调，<...> 是让它原样显示的标准写法。"""
    text = render_markdown(_result())

    assert re.search(r"<https://www\.mining\.com/sigma-lithium/>", text)
