"""把冻结后的 state 渲染成 Markdown 文件。

两条纪律：

- **只写路径，不吐全文**（PRD §5.3）。产物落盘，stdout 上只有一行路径 —— 这样
  日报本身可以被测试逐字断言，而不是只能靠人眼看终端。
- **渲染是纯函数，落盘是副作用**。`render_markdown` 不碰磁盘，`write_brief` 才写。
  分开是为了让"日报长什么样"这一条验收能在不产生文件的情况下被测。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from mining_brief.agent.state import BriefState
from mining_brief.config.archive import ARCHIVE
from mining_brief.config.logging import get_logger
from mining_brief.contracts import BriefResult, Citation, Refusal, ReportScope, Section
from mining_brief.contracts.brief import SECTION_TITLES

log = get_logger(__name__)

DEFAULT_OUTPUT_DIR = "briefs"

#: 显式点名的矿山超过这个数，文件名就退成 `4-mines` —— 见 `brief_slug`。
_MAX_NAMED_MINES = 3

#: 拒答那份文件名里短哈希取几位。
_HASH_LEN = 8

#: `Citation.kind` → 来源清单里的中文标签。
_KIND_ZH: dict[str, str] = {"news": "新闻", "price": "价格", "resource": "技术报告"}


def brief_slug(*, scope: ReportScope | None, refusal: Refusal | None, request_text: str) -> str:
    """这份日报覆盖了**什么** —— 文件名里日期之后的那一段。

    文件名要回答的是"这份日报是什么"，不是"我什么时候按的回车"。所以身份取自
    **范围**：问了哪几座矿、窗口多长。这样两个不同的问题**永远不会撞名**，而撞名
    恰好只发生在"范围完全相同"的时候 —— 那时两份产物本来就该是同一份，覆盖是对的。
    按日期命名做不到这一点：同一天问两座矿会落进同一个文件，后问的静默盖掉先问的。

    四种形态：

    - 拒答 → `refused-<请求文本的短哈希>`；
    - 覆盖整个档案 → `all`（最常见的那一问，也最该短）；
    - 点名了几座矿 → `pilgangoora-7d`（矿与矿之间用 `+` 接）；点名的矿**超过三座**
      就退成 `4-mines` —— 名字是给人认的，塞四个 id 进去就没人认了。

    窗口一律写出来（`-7d`），**不因为等于默认值就省略** —— 省了它，读者只能靠猜
    "没有这段 = 默认 7 天"，而这个仓库的一贯做法是把事实写出来让人看，不让人推断。

    **判"是不是拒答"必须看 `refusal`，不能看 `scope` 是不是 `None`。** 这条是端到端
    跑出来的教训：越界那条拒答（"帮我预测一下明天铜价会涨吗"）会先由品种推出三座
    铜矿，`nodes.resolve_entities` 因此给出了一个**非空**的 `scope`（只有存在未覆盖
    项时它才是 `None`），于是按 `scope is None` 判断会把一条拒答命名成
    `kamoa-kakula+los-pelambres+quellaveco-7d` —— 一份看起来跟真日报一模一样的
    拒答产物。拒答还要按请求文本哈希，因为两次**不同**的越界请求若同名，就又把这次
    要修的 bug 请回来了；请求文本是那时唯一稳定的身份（它本身就是输入）。
    """
    if refusal is not None:
        digest = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
        return f"refused-{digest[:_HASH_LEN]}"

    if scope is None:
        # `check_scope` 保证到不了这里：它要么给出拒答，要么给出范围。真到了这里，
        # 说明上游有 bug —— 与其编一个像模像样的文件名把 bug 藏进产物，不如炸。
        raise ValueError("既没有拒答、又没有范围 —— 这不该发生，说明上游有 bug")

    ids = sorted(entry.id for entry in scope.entries)
    if set(ids) == {entry.id for entry in ARCHIVE}:
        name = "all"
    elif len(ids) <= _MAX_NAMED_MINES:
        name = "+".join(ids)
    else:
        name = f"{len(ids)}-mines"
    return f"{name}-{scope.window_days}d"


def brief_filename(now: datetime, *, slug: str, include_run_time: bool = False) -> str:
    """日报文件名：`brief-<日期>[-<运行时刻>]-<范围>.md`。

    **日期取数据时点，不取系统时钟** —— 否则同一份 fixture 每天跑出来的文件名都
    不一样，产物就不确定了（ADR-0002）。实时模式下 `now` 本来就是运行时刻，所以
    那个括号里的字段是**同一个值**的两种精度，不是第二个时钟。

    实时模式**额外**带上运行时刻（`%H%M%S`）：实时的产物**不可复现**（数据源每次给
    的不一样），一天之内跑两遍就是两张不同的世界快照，该各留各的。回放不加这个字段
    —— 那里 `now` 是冻结锚点，写上去只会得到一个看起来像运行时刻、其实不是的常量，
    而"看起来像真的"正是这个项目最不肯要的东西。

    时刻口径是 **UTC**（与数据时点同源），不是本地时间。
    """
    stamp = f"{now:%Y-%m-%d-%H%M%S}" if include_run_time else f"{now:%Y-%m-%d}"
    return f"brief-{stamp}-{slug}.md"


def _output_dir(state: BriefState) -> Path:
    settings = state.get("settings")
    if settings is None:
        return Path(DEFAULT_OUTPUT_DIR)
    return Path(settings.output_dir) if settings.output_dir else Path(DEFAULT_OUTPUT_DIR)


def build_result(state: BriefState) -> BriefResult:
    """把 state 冻成 `BriefResult`。不碰磁盘。"""
    settings = state.get("settings")
    refusal = state.get("refusal")
    # 实时才带运行时刻：那里的 `now` 是真时钟，产物本质上是**不可复现**的一张快照
    # （正因如此 `live-briefs/` 才进 `.gitignore`）；回放的 `now` 是冻结锚点，带上
    # 它只会得到一个假装是运行时刻的常量。
    live = settings is not None and settings.data_mode == "live"
    name = brief_filename(
        state["now"],
        slug=brief_slug(
            scope=state.get("scope"),
            refusal=refusal,
            request_text=state.get("request_text", ""),
        ),
        include_run_time=live,
    )
    path = str(_output_dir(state) / name)

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
