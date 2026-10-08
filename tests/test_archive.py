"""矿权档案与实体解析（工单 06）：档案的**自洽性**与"绝不编造实体"。

这一组全部是纯函数级的：不联网、不调模型、不跑图。它盯的是档案这份**数据**本身的
性质 —— 而档案是全系统唯一能"编造实体"的地方（`match_entry` 是那个入口）。

分两类：

1. **每个名字都能落到自己的条目上**（中文别称 / 英文名 / 交易所代码三种说法）。
   这条**参数化在 `ARCHIVE` 上**，所以档案添一座矿就自动多覆盖一份 —— 而不是写死
   一份清单、档案变了测试还绿着。
2. **档案外的东西一个都落不进来**。少了这一类，上一条再全也说明不了什么：
   一个 `return ARCHIVE[0]` 的实现能让"每个名字都能落地"全绿。
"""

from __future__ import annotations

import pytest

from mining_brief.config.archive import (
    ARCHIVE,
    ArchiveEntry,
    all_ids,
    company_terms,
    entries_for_commodity,
    known_commodities,
    match_entries,
    match_entry,
    project_terms,
)

#: 有意**不在**档案里的真实矿山。选它们是因为它们足够有名 —— 一个"什么都能匹配上"
#: 的实现会在这里翻车，而随便编几个不存在的名字考不出这一点。
OUTSIDE_THE_ARCHIVE = (
    "Escondida",
    "Grasberg",
    "Olympic Dam",
    "Mt Whaleback",
    "Bougainville",
    "Sierra Gorda",
    "Escondida 铜矿",
)


def _entry(entry_id: str) -> ArchiveEntry:
    return next(e for e in ARCHIVE if e.id == entry_id)


def test_the_archive_has_the_scale_the_ticket_asks_for() -> None:
    """8 座矿山 / 3 个品种 —— 门票上的数字，直接断言，免得"补到 8 座"变成一句口号。"""
    assert len(ARCHIVE) == 8, f"档案应当是 8 座矿山，实际 {len(ARCHIVE)}：{all_ids()}"
    assert set(known_commodities()) == {"lithium", "copper", "iron_ore"}
    assert len(all_ids()) == len(set(all_ids())), "id 撞了"


def test_the_archive_is_keyed_by_project_not_by_company() -> None:
    """**以项目为粒度**（CONTEXT.md）：同一家公司可以有多条。

    这条同时是下面"逐条可达"的前提 —— 一家公司只有一条时，按公司名匹配是唯一的；
    有多条时就不唯一了，所以那条测试对"公司名"这一项要另眼看待。
    """
    by_company: dict[str, list[str]] = {}
    for entry in ARCHIVE:
        by_company.setdefault(entry.company, []).append(entry.project)

    multi = {company: projects for company, projects in by_company.items() if len(projects) > 1}
    assert multi, "8 座矿山里应当至少有一家公司占了两个项目，否则这个粒度没有被检验"


@pytest.mark.parametrize("entry_id", all_ids())
def test_each_entry_is_reachable_by_alias_name_and_ticker(entry_id: str) -> None:
    """中文别称 / 英文名 / 交易所代码三种说法都能落到**这条**档案上。

    "落到这条"对两套说法的含义**不同**，所以要分开断言：

    - **项目级**说法（id / 项目名 / 项目别称）必须落到**它自己**那一条。
    - **公司级**说法（公司名 / 交易所代码 / 公司别称）在"一家公司两个项目"时天然不
      唯一，判据因此是"解出来的**正好是这一家公司的全部项目**"—— 少一个是丢矿，
      多一个是串味。**不能**退化成"取第一条就算了"：那等于替使用者在两座矿之间
      挑了一座。
    """
    entry = _entry(entry_id)
    same_company = {e.id for e in ARCHIVE if e.company == entry.company}

    failures: list[str] = []
    for kind, text in [
        ("id", entry.id),
        ("项目名", entry.project),
        *(("项目别称", alias) for alias in entry.aliases),
    ]:
        found = match_entry(text)
        if found is None or found.id != entry.id:
            failures.append(f"{kind}「{text}」→ {found.id if found else 'None'}")

    for kind, text in [
        ("公司名", entry.company),
        *(("代码", ticker) for ticker in entry.tickers),
        *(("公司别称", alias) for alias in entry.company_aliases),
    ]:
        got = {e.id for e in match_entries(text)}
        if got != same_company:
            failures.append(f"{kind}「{text}」→ {sorted(got)}，应为 {sorted(same_company)}")

    assert not failures, f"{entry.project} 的名字没有全部落到自己身上：" + "；".join(failures)


def test_a_company_name_puts_every_one_of_its_mines_in_scope() -> None:
    """公司名 → **该公司名下全部项目**，不是其中一座。

    这条是"以项目为粒度"真正的执行者。少了它，`match_entry` 取最长匹配那条捷径
    会让 `match_entries("Mineral Resources")` 静默退化成一座矿 —— 而产物上看起来
    完全正常：一份只有 Mount Marion 的日报，读者不会知道 Wodgina 被丢了。
    """
    multi = [
        company
        for company in {e.company for e in ARCHIVE}
        if sum(1 for e in ARCHIVE if e.company == company) > 1
    ]
    assert multi, "档案里没有一家公司占两个项目，这条断言等于空转"

    for company in multi:
        expected = {e.id for e in ARCHIVE if e.company == company}
        assert {e.id for e in match_entries(company)} == expected
        for ticker in {t for e in ARCHIVE if e.company == company for t in e.tickers}:
            assert {e.id for e in match_entries(ticker)} == expected, (
                f"{company} 的代码「{ticker}」只解出了部分项目"
            )


def test_no_two_entries_share_a_search_term() -> None:
    """没有一个词同时属于两条**不该共用它**的档案。

    上一条测试要能成立，靠的就是这条：只要 `PLS` 既属于 A 又属于 B，"说法能落到
    自己的条目上"就是不可能的。但**共用并不总是错的**，判据按层级分：

    - 项目级说法共享 → 必错。精确匹配只能命中一个，另一个永远解析不到。
    - 公司级说法在同一家公司的两个项目之间共享 → **本就如此**，这正是"以项目为
      粒度"的代价（见 `ArchiveEntry.company_aliases`）。跨公司共享仍然必错。

    把这两条分开写，是为了让"为什么 `Mineral Resources` 可以出现两次"有据可查，
    而不是靠一句"这是特例"糊过去。
    """
    seen: dict[str, str] = {}
    collisions: list[str] = []

    def claim(term: str, entry: ArchiveEntry, *, level: str) -> None:
        key = " ".join(term.lower().split())
        owner = seen.get(key)
        if owner is not None and owner != entry.id:
            other = _entry(owner)
            shared_within_company = level == "公司级" and other.company == entry.company
            if not shared_within_company:
                collisions.append(f"「{term}」同时属于 {owner} 与 {entry.id}（{level}）")
        seen[key] = entry.id

    for entry in ARCHIVE:
        for term in project_terms(entry):
            claim(term, entry, level="项目级")
    for entry in ARCHIVE:
        for term in company_terms(entry):
            claim(term, entry, level="公司级")

    assert not collisions, "；".join(collisions)


@pytest.mark.parametrize("spoken", OUTSIDE_THE_ARCHIVE)
def test_a_mine_outside_the_archive_does_not_resolve(spoken: str) -> None:
    """档案外的矿名**必须**落空 —— 落进来就会变成一次幻觉（A9）。"""
    assert match_entry(spoken) is None, f"「{spoken}」不在档案里，却匹配到了东西"


@pytest.mark.parametrize("commodity_word", ["锂", "铜", "铁矿石", "lithium", "copper"])
def test_a_bare_commodity_word_is_not_a_mine(commodity_word: str) -> None:
    """品种词不该被当成矿名。

    不然使用者说"出份铜的日报"时，品种槽位填铜、矿名槽位空着 —— 而万一矿名槽位被
    模型塞了"铜"，它就会"匹配"到某座铜矿上，于是这份日报静默地只报那一座。
    别名里含"铜"字（如"卡莫阿铜矿"）是不行的，这条就是那条纪律的看门人。
    """
    assert match_entry(commodity_word) is None, (
        f"「{commodity_word}」是品种词，却被当成了矿名 —— 检查档案里的别名是否过长"
    )


def test_every_entry_says_what_covers_or_why_nothing_does() -> None:
    """票面第 4 格"每条含…技术报告 URL、报告日期"的**诚实版本**。

    两条路都必须是**说得出口**的：
    - 有直链的，直链要能在登记表里翻到那张卡片（日期、体系、列序都在卡片上）；
    - 没有直链的，要留下**为什么没有**（`report_gap`）—— 否则产物只会说"未核实到"，
      读者无从判断是"我们没查到"还是"这家公司根本不发这种文件"，而这两件事对
      读者的含义完全不同。
    """
    with_report = [entry for entry in ARCHIVE if entry.report_url]
    assert with_report, "一条报告直链都没有的话，储量一节就没有任何东西可抽"
    for entry in with_report:
        source = entry.report_source
        assert source is not None, (
            f"{entry.id} 的直链不在登记表里 —— 跑到那一步只会得到「没登记」，比诚实地留 None 更差"
        )
        assert source.report_date and source.standard

    without = [entry for entry in ARCHIVE if not entry.report_url]
    for entry in without:
        assert entry.report_gap, f"{entry.id} 没有直链，却没说清楚为什么"


def test_the_mine_regime_and_the_document_standard_agree_when_both_are_known() -> None:
    """档案里的"这座矿按哪套体系"与卡片上的"这份文件里那张表是哪套体系"必须一致。

    这是**两处刻意留下的重复**（见 `ArchiveEntry.standard` 的 docstring）：一处答
    "这座矿的法定披露体系"（行业事实，没有文件时也成立），一处答"这份文件的表是哪套"。
    消费者不同（规则引擎按前者分流、解析器按后者标注），所以不能合并成一处 ——
    但它们**在同时存在时绝不能不一致**：不一致的表现是"引用块标 JORC、风险信号却
    引加拿大法条"，一种没人会去查的错。这条就是那句"绝不能"的执行者。
    """
    both_known = [
        entry for entry in ARCHIVE if entry.standard is not None and entry.report_source is not None
    ]
    assert both_known, "没有一条同时有两个体系的条目，这条断言等于空转"
    for entry in both_known:
        source = entry.report_source
        assert source is not None
        assert entry.standard is source.standard, (
            f"{entry.id}：档案说这座矿是 {entry.standard}，"
            f"但它那份报告的卡片说是 {source.standard} —— 两处漂移了"
        )


def test_every_entry_declares_a_reporting_regime() -> None:
    """8 座矿山各自按哪套体系披露，是**已知事实**，不许留空。

    留 `None` 的后果不是"少一个标注"，而是规则引擎静默失效：R5 只在 JORC 范围的矿上
    触发（`docs/risk-rules.md` §2 R5），一个没写体系的矿山会被当成非 JORC 而永远
    不触发 —— 而且**看起来一切正常**。
    """
    missing = [entry.id for entry in ARCHIVE if entry.standard is None]
    assert not missing, f"这些条目没说自己是哪套报告体系：{missing}"


def test_commodity_lookup_returns_every_mine_of_that_commodity() -> None:
    """按品种取矿山 —— 三个品种都要有人，否则"覆盖 3 个品种"是空的。"""
    for commodity in known_commodities():
        assert entries_for_commodity(commodity), f"{commodity} 一座矿都没有"


def test_an_empty_string_does_not_match_anything() -> None:
    """空输入落空。`"" in term` 恒为真，所以这条防的是"包含关系"被写成无条件真。"""
    for spoken in ("", "   ", "\t\n"):
        assert match_entry(spoken) is None
