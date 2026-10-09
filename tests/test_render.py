"""Markdown 渲染与落盘。

`render_markdown` 是纯函数，所以"日报长什么样"这一条能在这里被逐字钉死，
不需要跑一遍图、也不需要读一个临时文件。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mining_brief.agent.render import brief_filename, brief_slug, render_markdown, write_brief
from mining_brief.config.archive import ARCHIVE
from mining_brief.contracts import (
    ArchiveEntryRef,
    BriefResult,
    Citation,
    Fact,
    Refusal,
    ReportScope,
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
        "output_path": "briefs/brief-2026-10-08-pilgangoora-7d.md",
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
    """用系统时钟命名的话，同一份 fixture 每天跑出来的产物文件名都不一样。

    回放模式下**不加**运行时刻：那里的 `now` 是冻结锚点，写上去只会得到一个看起来
    像运行时刻、其实不是的常量 —— 而"看起来像真的"是这个项目最不肯要的东西。
    锚点里的 `17:01:57` 因此**不该**出现在文件名里。
    """
    name = brief_filename(datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC), slug="all-7d")

    assert name == "brief-2026-10-08-all-7d.md"
    assert "170157" not in name, "回放的文件名里不该出现运行时刻"


def test_a_live_run_puts_its_wall_clock_time_in_the_filename() -> None:
    """实时模式**要**带上运行时刻，因为实时的产物本质上是**不可复现**的一张快照。

    同一天跑两遍得到的是两张不同的世界快照（数据源每次给的不一样），该各留各的 ——
    这正是 `live-briefs/` 进 `.gitignore` 的理由。时刻是 UTC，与数据时点同源。
    """
    name = brief_filename(
        datetime(2026, 10, 9, 3, 22, 59, tzinfo=UTC), slug="all-7d", include_run_time=True
    )

    assert name == "brief-2026-10-09-032259-all-7d.md"


def _scope(*ids: str, window_days: int = 7) -> ReportScope:
    """按档案条目造一个范围。**id 从 `ARCHIVE` 里查**，不手抄 —— 手抄的 id 一旦
    与档案脱节（档案改了名），这些用例会以"应该相同却不同"的方式红，看不出原因。"""
    by_id = {entry.id: entry for entry in ARCHIVE}
    return ReportScope(
        entries=tuple(
            ArchiveEntryRef(
                id=entry.id,
                project=entry.project,
                company=entry.company,
                commodity=entry.commodity,
                spoken_as=entry.project,
            )
            for entry in (by_id[i] for i in ids)
        ),
        window_days=window_days,
    )


def _slug(scope: ReportScope, request_text: str) -> str:
    """ "出一份简报"这一侧的 slug —— 拒答那一侧单独写字面参数，好与本条区分开。"""
    return brief_slug(scope=scope, refusal=None, request_text=request_text)


def test_two_different_questions_never_land_in_the_same_file() -> None:
    """**这条盯的就是那个坑**：同一天问两座矿，产物必须落在两个文件里。

    按日期命名的旧写法下，先问的那份会被后问的静默盖掉 —— 2026-10-09 的真实验收里
    就这么丢过一次产物（先问 Pilbara、后问全量，两次都写 `brief-2026-10-08.md`）。
    名字的职责是"这是什么"，不是"我哪天跑的"；两个不同的问题不该共用同一个名字。
    """
    day = datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)
    pilbara = brief_filename(day, slug=_slug(_scope("pilgangoora"), "看 Pilbara"))
    wide = brief_filename(day, slug=_slug(_scope(*[e.id for e in ARCHIVE]), "今日简报"))

    assert pilbara != wide
    assert pilbara == "brief-2026-10-08-pilgangoora-7d.md"
    assert wide == "brief-2026-10-08-all-7d.md"


def test_the_same_scope_asked_two_ways_reuses_one_filename() -> None:
    """反过来：**范围相同**时名字必须相同 —— 那时两份产物本来就是同一份。

    "Pilbara 锂矿的简报"与"Pilbara"落到同一个范围，就该落同一个文件；这跟上面那条
    一起，才是"名字 = 身份"的意思：撞名恰好等价于"内容相同"。
    """
    one = _slug(_scope("pilgangoora"), "给我生成一份关于 Pilbara 锂矿的今日简报")
    two = _slug(_scope("pilgangoora"), "Pilbara")

    assert one == two


def test_many_mines_fall_back_to_a_count_instead_of_a_wall_of_ids() -> None:
    """名字是给人认的：点名超过三座矿时退成 `4-mines`，而不是把四个 id 串起来。"""
    assert _slug(_scope("pilgangoora", "wodgina"), "x") == "pilgangoora+wodgina-7d"
    assert _slug(_scope("pilgangoora", "wodgina", "eliwana"), "x") == (
        "eliwana+pilgangoora+wodgina-7d"
    )
    assert _slug(_scope("pilgangoora", "wodgina", "eliwana", "quellaveco"), "x") == "4-mines-7d"


def test_the_window_is_always_written_out_even_when_it_is_the_default() -> None:
    """窗口一律写出来。省掉它，读者只能靠猜"没有这段 = 默认 7 天"。

    同一座矿、窗口不同（7 天 vs 3 天）的新闻窗口不同，是两份不同的产物，必须能分开。
    """
    assert _slug(_scope("pilgangoora"), "x") == "pilgangoora-7d"
    assert _slug(_scope("pilgangoora", window_days=3), "x") == "pilgangoora-3d"


def test_a_refusal_is_named_after_the_request_not_after_its_scope() -> None:
    """**拒答的判据是 `refusal`，不是 `scope is None`** —— 这条是端到端跑出来的教训。

    越界那条拒答（"帮我预测一下明天铜价会涨吗"）会先由品种推出三座铜矿，
    `resolve_entities` 于是给出一个**非空**的 `scope`：`scope` 为 `None` 只在存在
    未覆盖项时才成立。所以按 `scope is None` 判断，会把这条拒答命名成
    `kamoa-kakula+los-pelambres+quellaveco-7d` —— **一份看起来跟真日报一模一样的
    拒答产物**，而它连六节都没有。这里就用"有范围的那条拒答"当输入钉住这一点。
    """
    copper = _scope("kamoa-kakula", "los-pelambres", "quellaveco")
    refusal = Refusal(
        understood="我听懂了：铜；时间窗口 7 天。",
        why="本系统不做预测。",
        usable_phrasings=("出份锂的日报",),
    )

    slug = brief_slug(scope=copper, refusal=refusal, request_text="帮我预测一下明天铜价会涨吗")

    assert slug.startswith("refused-"), "有范围的拒答也必须叫 refused-*"
    assert "kamoa-kakula" not in slug, "拒答不该伪装成一份真日报"
    # 没有范围的那条拒答（未覆盖）走同一分支，两条拒答因此也能各自留档。
    uncovered = brief_slug(scope=None, refusal=refusal, request_text="看看 Escondida 铜矿最近 3 天")
    assert uncovered.startswith("refused-") and uncovered != slug


def test_two_different_refusals_never_collide() -> None:
    """两次**不同**的拒答若同名，就又把这次要修的 bug 请回来了 —— 请求文本是那时
    唯一稳定的身份（它本身就是输入），所以哈希它。同一句话重跑必须得到同一个名字。
    """
    refusal = Refusal(understood="x", why="y", usable_phrasings=("z",))

    def slug(text: str) -> str:
        return brief_slug(scope=None, refusal=refusal, request_text=text)

    assert slug("帮我预测一下明天铜价会涨吗") != slug("看看 Escondida 铜矿最近 3 天")
    assert slug("帮我预测一下明天铜价会涨吗") == slug("帮我预测一下明天铜价会涨吗")


def test_a_state_with_neither_a_scope_nor_a_refusal_loudly_fails() -> None:
    """两者都没有是上游的 bug（`check_scope` 保证只会二选一）。宁可炸，也不编一个
    像模像样的文件名把 bug 藏进产物 —— 那正是这个项目最贵的一类错。
    """
    with pytest.raises(ValueError, match="上游有 bug"):
        brief_slug(scope=None, refusal=None, request_text="随便")


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
