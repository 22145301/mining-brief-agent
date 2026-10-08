"""矿权档案 —— 实体解析的**唯一**依据（CONTEXT.md）。

它不是权威矿权登记簿：没有公开免费源能支撑后者（PRD §2.2 N3）。用户提到档案里
没有的矿名或矿种，系统的正确输出是"未覆盖" + 列出可选项，**绝不**编造实体。

档案以**项目**为粒度，不以公司为粒度 —— 一个公司可以有多个项目（CONTEXT.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mining_brief.config.reports import PILBARA_CET, ReportSource, source_by_pdf_url
from mining_brief.contracts import Commodity, ReportingStandard


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    id: str
    company: str
    project: str
    commodity: Commodity
    tickers: tuple[str, ...]
    aliases: tuple[str, ...]
    """**项目**的中文别称、英文简称等使用者可能脱口而出的说法。"""

    company_aliases: tuple[str, ...] = ()
    """**公司**的中性别称（中文名、业内简称）。

    为什么要和 `aliases` 分开，而不是一股脑塞进一个元组：两者的**归属层级**不同，
    而这个层级决定了同一家公司有两个项目时会发生什么。

    - 项目级说法（`id` / `project` / `aliases`）必须**全局唯一** —— 否则
      `match_entry` 的精确匹配只能命中其中一个，另一个就永远解析不到了。
    - 公司级说法（`company` / `company_aliases` / `tickers`）**本来就该**被同一家公司
      的多个项目共用："Mineral Resources" 指的不是某座矿，而是那家公司，两个项目
      都得进范围。
    `tests/test_archive.py` 按这个分层分别断言，不是靠一句话约好。
    """

    report_url: str | None = None
    """资源量 / 储量数字的**PDF 直链**。`None` 表示**尚未核实到** —— 不是"没有"。

    这里存的是 URL，表本身登记在 `config/reports.py`（列序、单位、报告日期、表头
    标记都在那儿）。两处分开的理由：档案回答"这座矿该看哪份文件"，登记表回答
    "那份文件里的表长什么样、是哪一天生效的"。

    直链拿不到时如实降级为"数据缺失"，**不编一个链接出来**（R2 的处置见工单 05）。"""

    report_gap: str | None = None
    """**为什么**没有直链 —— 一句话，会进产物的降级说明里。

    没有它的话，产物只能说"未核实到"，读者无从判断这是"我们没查到"还是"这家公司
    根本不发这种文件"。两者对读者的含义完全不同：后者是行业事实，前者是我们的活没干完。
    """

    standard: ReportingStandard | None = None
    """这座矿**按哪套体系**披露资源量与储量 —— JORC 还是 NI 43-101。

    与卡片上的 `report_source.standard` **不是同一件事**，两处都留着是有理由的：

    - 这一格说的是"**这座矿**的法定披露体系"，是一桩**行业事实**，在压根没有可下载
      文件时照样成立（Fortescue 就属于"JORC 体系、但不单独发项目级技术报告"这一档）。
    - 卡片那一格说的是"**这份文件里的那张表**是哪套体系"，由人读着页面声明。

    消费者也不同：风险规则引擎按**前者**分流（R1 引 NI 法条、R5 引 JORC 法条，
    混引就是引错法条 —— `docs/risk-rules.md` §2），解析器按**后者**标注引用块。
    两处都在时它们应当一致，`tests/test_archive.py` 有一条盯着这件事。
    """

    @property
    def report_source(self) -> ReportSource | None:
        """这条直链在登记表里的那张卡片；没登记就是 `None`。

        报告日期**只存在卡片上**，档案里不留第二份 —— 两处各存一份早晚会漂移，
        而漂移的表现是"引用块上的日期与档案说的不一致"，一种没人会去查的错。
        """
        return source_by_pdf_url(self.report_url) if self.report_url else None


#: 8 座矿山 / 3 个品种（工单 06 补全 01 留下的最小子集）。
#:
#: **只有亲身下载并确认响应体以 `%PDF` 开头的直链才写进 `report_url`** —— 拿不到就
#: 留 `None` 并写清 `report_gap`，绝不编一个看起来像那么回事的链接（红线：不许编数据）。
#: 因此这张表里"没有直链"的条目占多数，是**如实**的结果，不是漏做。
ARCHIVE: tuple[ArchiveEntry, ...] = (
    ArchiveEntry(
        id="pilgangoora",
        company="Pilbara Minerals",
        project="Pilgangoora",
        commodity="lithium",
        tickers=("ASX:PLS", "PLS"),
        aliases=("Pilbara", "皮尔巴拉", "皮尔甘古拉"),
        company_aliases=("皮尔巴拉矿业",),
        standard=ReportingStandard.JORC,
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
    # --- 锂：同一家公司两个项目（Mount Marion / Wodgina）------------------------
    # 这两条同时承担"以**项目**为粒度、不以公司为粒度"的检验：公司名是两个项目
    # 共用的说法，项目名各自唯一。见 `company_aliases` 的 docstring。
    ArchiveEntry(
        id="mount-marion",
        company="Mineral Resources",
        project="Mount Marion",
        commodity="lithium",
        tickers=("ASX:MIN",),
        aliases=("Mt Marion", "马里恩山"),
        company_aliases=("MinRes",),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司不单独发布项目级技术报告，"
            "JORC 资源量声明载于其年报与季度活动报告，公开渠道未检索到可复现的 PDF 地址。"
        ),
    ),
    ArchiveEntry(
        id="wodgina",
        company="Mineral Resources",
        project="Wodgina",
        commodity="lithium",
        tickers=("ASX:MIN",),
        aliases=("沃吉纳",),
        company_aliases=("MinRes",),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司不单独发布项目级技术报告，"
            "JORC 资源量声明载于其年报与季度活动报告，公开渠道未检索到可复现的 PDF 地址。"
        ),
    ),
    # --- 铜 -------------------------------------------------------------------
    ArchiveEntry(
        id="kamoa-kakula",
        company="Ivanhoe Mines",
        project="Kamoa-Kakula",
        commodity="copper",
        tickers=("TSX:IVN",),
        aliases=("Kamoa", "卡莫阿", "卡库拉"),
        company_aliases=("艾芬豪",),
        standard=ReportingStandard.NI_43_101,
        # 直链**找到了、也下载确认了**，但不登记 —— 登记表要的是"这份文件里的表长什么
        # 样、是哪一天生效的"，那三格（表头标记 / 列序 / 页码）必须由人读着文件写死。
        # 只把 URL 塞进 `report_url` 而不登记卡片，跑到那一步只会得到「没登记」——
        # 比诚实地留空更差。留下原件信息供人工核实：
        #   https://www.ivanhoemines.com/wp-content/uploads/
        #     1025010-Kamoa-Copper-Kamoa-Kakula-MRMR-Update-Technical-Report-31-March-2026_SEDAR-Copy.pdf  # noqa: E501
        #   HTTP 200 · 36,169,167 B · `%PDF-1.7` · sha256(前 12) 29c81fcf304d
        report_gap=(
            "技术报告直链已定位并实际下载确认（2026-03-31 版 MRMR 更新报告，36 MB，"
            "sha256 前 12 位 29c81fcf304d），但其资源量表的**表头标记、列序与页码"
            "尚未由人声明**，因此本轮不登记直链；登记一个抽不出表的链接，"
            "产物只会说「没登记」。"
        ),
    ),
    ArchiveEntry(
        id="quellaveco",
        company="Anglo American",
        project="Quellaveco",
        commodity="copper",
        tickers=("LSE:AAL",),
        aliases=("克亚维科",),
        company_aliases=("英美资源",),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司以年报披露 JORC 资源量，"
            "不为在产项目单独发布技术报告，公开渠道未检索到可复现的 PDF 地址。"
        ),
    ),
    ArchiveEntry(
        id="los-pelambres",
        company="Antofagasta",
        project="Los Pelambres",
        commodity="copper",
        tickers=("LSE:ANTO",),
        aliases=("Pelambres", "洛斯佩兰布雷斯"),
        company_aliases=("安托法加斯塔",),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司以年报披露 JORC 资源量，"
            "项目级技术报告不对外公开，公开渠道未检索到可复现的 PDF 地址。"
        ),
    ),
    # --- 铁矿石 ---------------------------------------------------------------
    ArchiveEntry(
        id="gudai-darri",
        company="Rio Tinto",
        project="Gudai-Darri",
        commodity="iron_ore",
        tickers=("ASX:RIO",),
        aliases=("Gudai Darri", "古戴达里"),
        company_aliases=("力拓",),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司以年报披露 JORC 资源量，"
            "不为在产项目单独发布技术报告，公开渠道未检索到可复现的 PDF 地址。"
        ),
    ),
    ArchiveEntry(
        id="eliwana",
        company="Fortescue",
        project="Eliwana",
        commodity="iron_ore",
        tickers=("ASX:FMG",),
        aliases=("埃利瓦纳",),
        company_aliases=("福特斯库", "FMG"),
        standard=ReportingStandard.JORC,
        report_gap=(
            "本轮未取到可下载的项目级技术报告直链：该公司以年报与季度生产报告披露 "
            "JORC 资源量，不为在产项目单独发布技术报告，公开渠道未检索到可复现的 PDF 地址。"
        ),
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


def project_terms(entry: ArchiveEntry) -> tuple[str, ...]:
    """**项目级**说法 —— 必须全局唯一，否则对应条目永远解析不到。"""
    return (entry.id, entry.project, *entry.aliases)


def company_terms(entry: ArchiveEntry) -> tuple[str, ...]:
    """**公司级**说法 —— 同一家公司的多个项目**共用**，这是有意的（见 `company_aliases`）。"""
    return (entry.company, *entry.company_aliases, *entry.tickers)


def _search_terms(entry: ArchiveEntry) -> tuple[str, ...]:
    return (*project_terms(entry), *company_terms(entry))


def match_entries(spoken: str) -> tuple[ArchiveEntry, ...]:
    """把用户口中的说法落到档案条目上 —— **可能不只一条**。

    这是**纯字符串匹配**，刻意不交给模型：实体解析是全系统唯一"编造实体"的入口，
    交给模型就等于放弃了 A9 的可断言性。LLM 在 `resolve_entities` 里的作用是把
    用户的口语说法**指到这个函数上**，最终的落档判定仍在档案自身。

    为什么返回**元组**而不是单条：档案以**项目**为粒度，而使用者常常说的是**公司**
    （"Mineral Resources 的日报"）。一家公司有两个项目时，把它砍成其中一条，就等于
    替使用者在两座矿之间挑了一座、剩下的静默消失 —— 那正是这个项目最不该犯的错
    （同一个理由写在 `BriefState.resources` 的注释里）。所以公司级说法命中几座矿，
    就返回几座矿。

    匹配规则：先精确定位（忽略大小写与空白），再退到包含关系。
    """
    needle = " ".join(spoken.lower().split())
    if not needle:
        return ()

    terms = {entry.id: {term.lower() for term in _search_terms(entry)} for entry in ARCHIVE}
    exact = tuple(entry for entry in ARCHIVE if needle in terms[entry.id])
    if exact:
        return exact
    return tuple(
        entry
        for entry in ARCHIVE
        if any(needle in term or term in needle for term in terms[entry.id])
    )


def match_entry(spoken: str) -> ArchiveEntry | None:
    """`match_entries` 的**单条**版本 —— 供只需要一个答案的调用方使用。

    多个命中时取最长匹配，避免 `PLS` 把 `Pilbara Minerals` 也吃掉之类的歧义。
    需要"一家公司的所有项目"的调用方请用 `match_entries`，不要在这里取第一条。
    """
    matches = match_entries(spoken)
    if not matches:
        return None
    return max(matches, key=lambda entry: len(entry.project))


@dataclass(frozen=True, slots=True)
class ArchiveOptions:
    """ "未覆盖"时要列给使用者的可选项 —— 让他知道是系统不覆盖，不是这座矿不存在。"""

    mines: tuple[str, ...] = field(default_factory=lambda: tuple(e.project for e in ARCHIVE))
    commodities: tuple[Commodity, ...] = field(default_factory=known_commodities)
