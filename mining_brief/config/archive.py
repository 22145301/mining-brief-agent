"""矿权档案 —— 实体解析的**唯一**依据（CONTEXT.md）。

它不是权威矿权登记簿：没有公开免费源能支撑后者（PRD §2.2 N3）。用户提到档案里
没有的矿名或矿种，系统的正确输出是"未覆盖" + 列出可选项，**绝不**编造实体。

档案以**项目**为粒度，不以公司为粒度 —— 一个公司可以有多个项目（CONTEXT.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mining_brief.config.reports import PILBARA_CET
from mining_brief.contracts import Commodity


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    id: str
    company: str
    project: str
    commodity: Commodity
    tickers: tuple[str, ...]
    aliases: tuple[str, ...]
    """中文别称、英文简称等使用者可能脱口而出的说法。"""

    report_url: str | None = None
    """资源量 / 储量数字的**PDF 直链**。`None` 表示**尚未核实到** —— 不是"没有"。

    这里存的是 URL，表本身登记在 `config/reports.py`（列序、单位、表头标记都在那儿）。
    两处分开的理由：档案回答"这座矿该看哪份文件"，登记表回答"那份文件里的表长什么样"。
    直链拿不到时如实降级为"数据缺失"，**不编一个链接出来**（R2 的处置见工单 05）。"""

    report_date: str | None = None
    standard: str | None = None


#: 本票（01）只放解析题面那句所需的最小可用子集；完整 8 座矿山由 06 号工单补齐。
ARCHIVE: tuple[ArchiveEntry, ...] = (
    ArchiveEntry(
        id="pilgangoora",
        company="Pilbara Minerals",
        project="Pilgangoora",
        commodity="lithium",
        tickers=("ASX:PLS", "PLS"),
        aliases=("Pilbara", "Pilbara Minerals", "皮尔巴拉", "皮尔甘古拉", "Pilgangoora"),
        standard="JORC",
        # R2 的处置（工单 05）：ASX 上的 2017 年版技术报告直链已失效（实测 404），
        # 公司官网又整站在 Cloudflare 后面（实测 403）。**不编链接**，改用这份
        # 公开可下载的 CET 演讲材料 —— 它第 36 页原样印着 "Mineral Resource as at
        # 30 June 2022" 的 JORC 分类表，且该页脚注（3.5 Mt Li2O / 71 Mlb Ta2O5）
        # 与表内数字自洽，可交叉核对。
        #
        # 性质必须说清楚：这是**公司自己的演讲材料转引年报**，不是独立技术报告。
        # 已把这个出身写进 `config/reports.py` 的 title，它会随引用一起进产物 ——
        # 读者看到的是这句话，而不是一个含糊的"技术报告"。
        report_url=PILBARA_CET.pdf_url,
    ),
)


def entry_by_id(entry_id: str) -> ArchiveEntry | None:
    return next((entry for entry in ARCHIVE if entry.id == entry_id), None)


def all_ids() -> tuple[str, ...]:
    return tuple(entry.id for entry in ARCHIVE)


def known_commodities() -> tuple[Commodity, ...]:
    seen: list[Commodity] = []
    for entry in ARCHIVE:
        if entry.commodity not in seen:
            seen.append(entry.commodity)
    return tuple(seen)


def entries_for_commodity(commodity: Commodity) -> tuple[ArchiveEntry, ...]:
    return tuple(entry for entry in ARCHIVE if entry.commodity == commodity)


def _search_terms(entry: ArchiveEntry) -> tuple[str, ...]:
    return (entry.id, entry.project, entry.company, *entry.tickers, *entry.aliases)


def match_entry(spoken: str) -> ArchiveEntry | None:
    """把用户口中的矿名落到档案条目上。

    这是**纯字符串匹配**，刻意不交给模型：实体解析是全系统唯一"编造实体"的入口，
    交给模型就等于放弃了 A9 的可断言性。LLM 在 `resolve_entities` 里的作用是把
    用户的口语说法**指到这个函数上**，最终的落档判定仍在档案自身。

    匹配规则：先精确定位（忽略大小写与空白），再退到包含关系；多个命中时取
    最长匹配，避免 `PLS` 把 `Pilbara Minerals` 也吃掉之类的歧义。
    """
    needle = " ".join(spoken.lower().split())
    if not needle:
        return None

    exact = [
        entry for entry in ARCHIVE if needle in {term.lower() for term in _search_terms(entry)}
    ]
    if exact:
        return exact[0]

    partial = [
        entry
        for entry in ARCHIVE
        if any(needle in term.lower() or term.lower() in needle for term in _search_terms(entry))
    ]
    if not partial:
        return None
    return max(partial, key=lambda entry: len(entry.project))


@dataclass(frozen=True, slots=True)
class ArchiveOptions:
    """ "未覆盖"时要列给使用者的可选项 —— 让他知道是系统不覆盖，不是这座矿不存在。"""

    mines: tuple[str, ...] = field(default_factory=lambda: tuple(e.project for e in ARCHIVE))
    commodities: tuple[Commodity, ...] = field(default_factory=known_commodities)
