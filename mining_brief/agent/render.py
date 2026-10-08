"""把冻结后的 state 渲染成 Markdown 文件。

两条纪律：

- **只写路径，不吐全文**（PRD §5.3）。产物落盘，stdout 上只有一行路径 —— 这样
  日报本身可以被测试逐字断言，而不是只能靠人眼看终端。
- **渲染是纯函数，落盘是副作用**。`render_markdown` 不碰磁盘，`write_brief` 才写。
  分开是为了让"日报长什么样"这一条验收能在不产生文件的情况下被测。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mining_brief.agent.state import BriefState
from mining_brief.config.logging import get_logger
from mining_brief.contracts import BriefResult, Citation, Section
from mining_brief.contracts.brief import SECTION_TITLES

log = get_logger(__name__)

DEFAULT_OUTPUT_DIR = "briefs"

#: `Citation.kind` → 来源清单里的中文标签。
_KIND_ZH: dict[str, str] = {"news": "新闻", "price": "价格", "resource": "技术报告"}


def brief_filename(now: datetime) -> str:
    """日报文件名。

    用**数据时点**（回放时是 fixture 锚点）而不是系统时钟 —— 否则同一份 fixture
    在不同日子跑出来的文件名会变，产物就不确定了（ADR-0002）。
    """
    return f"brief-{now:%Y-%m-%d}.md"


def _output_dir(state: BriefState) -> Path:
    settings = state.get("settings")
    if settings is None:
        return Path(DEFAULT_OUTPUT_DIR)
    return Path(settings.output_dir) if settings.output_dir else Path(DEFAULT_OUTPUT_DIR)


def build_result(state: BriefState) -> BriefResult:
    """把 state 冻成 `BriefResult`。不碰磁盘。"""
    path = str(_output_dir(state) / brief_filename(state["now"]))
    refusal = state.get("refusal")

    if refusal is not None:
        # 拒答路径：没有六节、没有来源清单 —— 产物就是那段话说清楚的东西。
        return BriefResult(
            output_path=path,
            sections=(),
            citations=(),
            refusal=refusal,
            uncovered=state.get("uncovered", ()),
        )

    return BriefResult(
        output_path=path,
        sections=state.get("sections", ()),
        citations=state.get("citations", ()),
        uncovered=state.get("uncovered", ()),
    )


def _fact_line(text: str, citation: int | None) -> str:
    return f"- {text} [{citation}]" if citation is not None else f"- {text}"


def _render_section(section: Section, number: int) -> list[str]:
    lines = [f"## {number}. {section.title}", ""]
    # **每一节都标注数据时点，取不到就明说取不到。** 六节的数据截止时间天然不同
    # （新闻是发布时刻、价格是交易日、储量是报告日期），把它们统一成一个"今天"
    # 是这个产品最容易犯、也最没必要的谎。
    if section.as_of:
        lines.append(f"*数据时点：{section.as_of}*")
    else:
        lines.append("*数据时点：无法确定 —— 本节没有取到任何数据*")
    lines.append("")
    if section.lead:
        lines.append(f"> {section.lead}")
        lines.append("")
    if section.facts:
        lines.extend(_fact_line(fact.text, fact.citation) for fact in section.facts)
        lines.append("")
    if section.note:
        lines.append(f"*{section.note}*")
        lines.append("")
    return lines


def _render_citation(citation: Citation) -> list[str]:
    kind = _KIND_ZH.get(citation.kind, citation.kind)
    return [
        f"**[{citation.index}]**（{kind}）{citation.title}",
        "",
        f"  {citation.publisher} · {citation.timestamp}",
        "",
        f"  <{citation.url}>",
        "",
    ]


def render_markdown(result: BriefResult) -> str:
    """渲染成 Markdown。纯函数 —— 同样的 `BriefResult` 永远得到同样的字符串。"""
    if result.refusal is not None:
        lines = [
            "# 无法生成矿权日报",
            "",
            "## 我听懂了什么",
            "",
            result.refusal.understood,
            "",
            "## 为什么这次不行",
            "",
            result.refusal.why,
            "",
            "## 可以这样问",
            "",
        ]
        lines.extend(f"- {phrasing}" for phrasing in result.refusal.usable_phrasings)
        lines.append("")
        return "\n".join(lines)

    lines = [
        "# 矿权日报",
        "",
        "**各节数据截止时间不同** —— 每节标题下方标注的是该节数据实际对应的时点，"
        "新闻是发布时刻、价格是交易日、技术报告是报告日期，不是同一个「今天」。",
        "",
    ]

    for number, section in enumerate(result.sections, start=1):
        lines.extend(_render_section(section, number))

    lines.extend(["## 来源清单", ""])
    if result.citations:
        for citation in result.citations:
            lines.extend(_render_citation(citation))
    else:
        lines.extend(["本次简报没有需要引用的外部来源。", ""])

    sections_line = "、".join(SECTION_TITLES[s.key] for s in result.sections)
    lines.extend(
        [
            "---",
            "",
            f"本日报共 {len(result.sections)} 节（{sections_line}），"
            f"引用来源 {len(result.citations)} 条。",
            "",
            "每个事实后的 `[n]` 指向文末「来源清单」中的条目；条目里的标题、链接、"
            "发布方、时间戳均为工具返回值的原样搬运。",
            "",
        ]
    )
    return "\n".join(lines)


def write_brief(result: BriefResult) -> str:
    """落盘并返回**绝对路径**。这是本模块唯一的副作用。

    `newline="\n"` 不是可有可无的：不写它，Windows 上 `write_text` 会把每个 `\n`
    翻成 `\r\n`，于是**同一份回放数据在 Windows 与容器里落出不同的字节**
    （实测 4850 B / CRLF vs 4849 B / LF，sha256 因此不同）。产物是我们对外的
    交付物，"同一输入逐字节相同"这句话必须在跨平台时也成立，所以换行符由我们
    钉死成 LF，交给 git / 编辑器按各自习惯处理。
    """
    path = Path(result.output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result), encoding="utf-8", newline="\n")
    log.info("brief.written", path=str(path))
    return str(path.resolve())
