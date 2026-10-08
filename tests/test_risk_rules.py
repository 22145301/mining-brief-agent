"""风险规则引擎（工单 07）：实现冻结的规则集，且**只**实现它。

这个文件里最要紧的**不是**"五条规则各自能不能触发" —— 那是后半部分的事。最要紧的
是第一条：`RULES` 必须与 `docs/risk-rules.md` 冻结的规则集**一一对应**。少了它，
"只实现、不增删规则"就只是一句口号，而规则集一旦能被代码悄悄改宽，"风险信号"
这个词也就跟着稀释了 —— 那正是工单 02 花一整轮核对要防的事。

所以这个文件分两层：

1. **规则集本身的纪律**（不联网、不构造新闻，直接读文档比对）；
2. **触发逻辑**（手搭 state，逐条断言会 / 不会触发）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mining_brief.agent.rules import HINT_RULES, RULES, evaluate
from mining_brief.agent.state import BriefState, ResourceLookup
from mining_brief.contracts import (
    ArchiveEntryRef,
    FetchStatus,
    NewsCategory,
    NewsItem,
    NewsSearchResult,
    PageRef,
    ReportingStandard,
    ReportScope,
    ResourceCategory,
    ResourceExtract,
    ResourceRow,
    ResourceTable,
)

NOW = datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)
RULES_DOC = Path(__file__).resolve().parents[1] / "docs" / "risk-rules.md"


class _FakeDataset:
    """把 state 手搭出来。规则是纯函数，所以喂给它的世界可以是完全合成的 ——
    这不是"伪造数据"，而是这一层的**输入**本来就该由测试构造（真实数据由回放负责）。
    """

    def __init__(self) -> None:
        self.rows: BriefState = {"now": NOW, "news": None, "resources": None}

    def with_news(self, *items: NewsItem) -> _FakeDataset:
        self.rows["news"] = NewsSearchResult(
            status="ok",
            source_status=FetchStatus.OK,
            retrieved_at=NOW,
            query="q",
            window_days=7,
            window_start="2026-10-02T00:00:00+00:00",
            window_end="2026-10-09T00:00:00+00:00",
            items=items,
        )
        return self

    def with_table(
        self,
        *,
        project: str = "示例矿",
        standard: ReportingStandard = ReportingStandard.NI_43_101,
        categories: tuple[ResourceCategory, ...] = (
            ResourceCategory.INDICATED,
            ResourceCategory.INFERRED,
        ),
    ) -> _FakeDataset:
        table = ResourceTable(
            pdf_url=f"https://example.invalid/{project}.pdf",
            report_title=f"{project} 技术报告",
            report_date="2025-06-20",
            standard=standard,
            project=project,
            commodity="lithium",
            rows=tuple(
                ResourceRow(category=category, tonnage_mt=1.0, grade=1.0, grade_unit="%")
                for category in categories
            ),
            page_refs=(PageRef(label="资源量表", page=1),),
        )
        ref = ArchiveEntryRef(
            id=project, project=project, company="示例公司", commodity="lithium", spoken_as=project
        )
        self.rows["resources"] = (
            ResourceLookup(
                entry=ref,
                extract=ResourceExtract(
                    status="ok", source_status=FetchStatus.OK, retrieved_at=NOW, table=table
                ),
            ),
        )
        self.rows["scope"] = ReportScope(entries=(ref,), window_days=7)
        return self

    def build(self) -> BriefState:
        return self.rows


def _news(
    title: str,
    summary: str = "",
    *,
    source: str = "MINING.COM",
    published_at: str = "2026-10-07T03:00:00+00:00",
) -> NewsItem:
    return NewsItem(
        title=title,
        url="https://example.invalid/a",
        source=source,
        published_at=published_at,
        summary=summary,
        category=NewsCategory.GENERAL,
    )


def _ids(state: BriefState) -> list[str]:
    return [signal.rule_id for signal in evaluate(RULES, HINT_RULES, state)["signals"]]


# ---------------------------------------------------------------------------
# 第一层：规则集必须与冻结的文档一一对应
# ---------------------------------------------------------------------------


def _documented_rule_ids() -> list[str]:
    """文档里 `### R1 — …` 这样的二级标题，就是冻结的规则集本身。"""
    headings = re.findall(r"^### (R\d+)\b", RULES_DOC.read_text("utf-8"), re.MULTILINE)
    assert headings, f"没能从 {RULES_DOC} 里读出任何规则标题 —— 抓取方式得改"
    return headings


def _squash(text: str) -> str:
    return " ".join(text.split())


def _document_blocks() -> dict[str, str]:
    """每条规则小节里那一段 `>` 引文（`verbatim` 的唯一合法来源）。"""
    body = RULES_DOC.read_text("utf-8")
    sections = re.split(r"^### (?=R\d+\b)", body, flags=re.MULTILINE)
    blocks: dict[str, str] = {}
    for section in sections[1:]:
        rule_id = section.split(maxsplit=1)[0]
        quoted = "\n".join(
            line[1:].strip() for line in section.splitlines() if line.startswith(">")
        )
        blocks[rule_id] = _squash(quoted)
    return blocks


def test_the_engine_implements_exactly_the_frozen_rule_set() -> None:
    """`RULES` 与文档的规则集**逐条对应**：不增、不减、不改编号。

    增减在这里没有中间地带 —— 多一条就是"顺手加了个好主意"，少一条就是"这条太麻烦
    先不做"。两者都会让 `docs/risk-rules.md` 从"依据"退化成"参考"。
    """
    documented = _documented_rule_ids()
    implemented = [rule.rule_id for rule in RULES]
    assert implemented == documented, (
        f"代码里的规则集 {implemented} 与文档冻结的 {documented} 不一致 —— "
        "规则集只能由 docs/risk-rules.md 定义，代码只实现"
    )


@pytest.mark.parametrize("rule_id", [rule.rule_id for rule in RULES])
def test_every_verbatim_is_the_one_frozen_in_the_document(rule_id: str) -> None:
    """每条 `verbatim` 必须**是文档里那段引文** —— 一个字都不许自己在代码里改。

    这条挡的是最隐蔽的一种漂移：规则编号没变、触发逻辑没变，只是有人"顺手"把
    `realised` 改成了 `realized`，或者给 `5.16.4` 那句补了个句点。产物上看起来
    毫无差别，但它已经不是原文了 —— 而"逐字引用"是这个字段存在的全部理由。
    """
    rule = next(r for r in RULES if r.rule_id == rule_id)
    block = _document_blocks()[rule_id]
    assert _squash(rule.verbatim) in block, (
        f"{rule_id} 的 verbatim 不在文档的那段引文里 —— 代码里的原文与冻结的那份对不上"
    )


@pytest.mark.parametrize("rule_id", [rule.rule_id for rule in RULES])
def test_every_rule_points_at_a_hash_verified_source(rule_id: str) -> None:
    """每条出处的 URL 都必须在文档 §1 那张**记了 sha256** 的表里。

    为什么值得单测：`docs/risk-rules.md` §1 末写明 GN31 是旁证、**不得**作为
    `source_url`（它当时是 `curl -L` 抓的，没留档、无从按哈希复验）。这条就是那句话
    的执行者 —— 没有它，引一个无法复验的出处不会有人发现。
    """
    rule = next(r for r in RULES if r.rule_id == rule_id)
    body = RULES_DOC.read_text("utf-8")
    section = body.split("## 2. 规则集")[0]
    assert rule.source_url in section, (
        f"{rule_id} 的 source_url 不在 §1 的可复验来源表里：{rule.source_url}"
    )


def test_no_rule_cites_the_unverifiable_gn31() -> None:
    """GN31 是旁证，不是出处 —— 文档说了，这条盯着。"""
    from mining_brief.agent.rules import GN31_NOT_A_SOURCE

    assert all(rule.source_url != GN31_NOT_A_SOURCE for rule in RULES)


def test_the_hints_carry_no_verbatim_field_at_all() -> None:
    """提示**结构上**就没有 `verbatim` / `source_url`。

    这不是省字段，是它被降级的理由本身：它引不到权威原文。把它做成"引文可以为空"的
    风险信号，就等于在同一个字段里容许两种东西 —— 而"这一条到底有没有法条支撑"
    恰恰是读者最需要一眼看清的事。
    """
    assert HINT_RULES, "提示规则集为空的话，降级路径根本没有被实现"
    for hint_rule in HINT_RULES:
        assert not hasattr(hint_rule, "verbatim")
        assert not hasattr(hint_rule, "source_url")
        assert hint_rule.why_not_a_signal.strip(), "每条提示都要说清它为什么不是信号"


def test_the_engine_never_catches_anything() -> None:
    """ADR-0006：规则引擎是**纯函数**，不重试、不捕获。

    这条用源码断言而不是跑一遍 —— 跑一遍只能证明"这次没抛"，证明不了"里面没有
    `except`"。上游降级导致没数据时该节留空是正常路径；引擎抛异常只可能是规则集
    自己写错了，那就该响亮地炸，不把 bug 伪装成"本次未触发"。
    """
    import inspect

    from mining_brief.agent import rules as module

    source = inspect.getsource(module)
    for banned in ("try:", "except ", "retry", "sleep("):
        assert banned not in source, f"规则引擎里出现了 `{banned}` —— 纯函数不该有它"


# ---------------------------------------------------------------------------
# 第二层：逐条触发逻辑
# ---------------------------------------------------------------------------


def test_nothing_triggers_on_an_empty_world() -> None:
    """空世界 → 零信号、零提示。这是本节的**默认产物**，不是失败。"""
    result = evaluate(RULES, HINT_RULES, {"now": NOW, "news": None, "resources": None})
    assert result["signals"] == ()
    assert result["hints"] == ()


def test_r1_fires_on_an_ni_table_with_inferred_and_indicated() -> None:
    state = _FakeDataset().with_table(standard=ReportingStandard.NI_43_101).build()
    assert _ids(state) == ["R1"]
    signal = evaluate(RULES, HINT_RULES, state)["signals"][0]
    assert "不得相加" in signal.triggered_by
    assert "sections 1.2 and 1.3" in signal.verbatim
    assert signal.source_label.endswith("s. 2.2")


def test_r1_does_not_fire_on_a_jorc_table() -> None:
    """同一张表、换成 JORC 体系 → R1 不出现。

    **这就是"按体系分流"的可断言面**（`docs/risk-rules.md` §2 R1）：把 NI 的法条
    套到 JORC 的矿上，引出来的是一份对这座矿没有管辖权的文件。
    """
    state = _FakeDataset().with_table(standard=ReportingStandard.JORC).build()
    assert _ids(state) == []


def test_r1_does_not_fire_when_only_inferred_is_present() -> None:
    """只有 Inferred、没有别的类别 → 没有"相加"可言，不触发。"""
    state = (
        _FakeDataset()
        .with_table(standard=ReportingStandard.NI_43_101, categories=(ResourceCategory.INFERRED,))
        .build()
    )
    assert _ids(state) == []


def test_r2_fires_on_an_uncategorised_number() -> None:
    state = _FakeDataset().with_news(_news("项目发现矿化 2000 万吨")).build()
    assert "R2" in _ids(state)
    signal = next(s for s in evaluate(RULES, HINT_RULES, state)["signals"] if s.rule_id == "R2")
    assert "2000 万吨" in signal.triggered_by, "要原样引出那一句，不能概括"
    assert "has not been categorized" in signal.verbatim


def test_r2_does_not_fire_when_the_same_sentence_names_a_category() -> None:
    """同一句里有法定类别词 → 这是合规披露，不该报。"""
    state = _FakeDataset().with_news(_news("该项目推断资源量 2000 万吨")).build()
    assert _ids(state) == []


def test_r2_reports_the_number_in_a_different_sentence_than_the_category() -> None:
    """类别词在本句之外不算数 —— 判据是**同一句**。

    这是一条**边界**用例：把"整条新闻里出现过类别词"当成判据的话，下面这条合规披露
    会被漏掉，而已知的不合规披露会被放过。两个方向都错，所以要把边界钉死。
    """
    state = (
        _FakeDataset()
        .with_news(_news("公司发布更新。矿化 2000 万吨", "本次更新涵盖多个类别。"))
        .build()
    )
    assert "R2" in _ids(state)


def test_r3_fires_on_a_preliminary_economic_assessment() -> None:
    state = _FakeDataset().with_news(_news("PEA shows robust economics")).build()
    assert _ids(state) == ["R3"]
    signal = evaluate(RULES, HINT_RULES, state)["signals"][0]
    assert "too speculative geologically" in signal.verbatim


def test_r4_carries_its_conditional_clause_instead_of_asserting() -> None:
    """R4 是本清单里唯一一条 `triggered_by` 带条件从句的规则 —— 因为"限 ASX 主体"
    这条前提我们判不了。**判不了就不假装判定**：写成提醒，而不是兑现不了的断言。
    """
    state = _FakeDataset().with_news(_news("Company reaffirms production target")).build()
    assert _ids(state) == ["R4"]
    signal = evaluate(RULES, HINT_RULES, state)["signals"][0]
    assert "若该主体在 ASX 上市" in signal.triggered_by
    assert signal.verbatim.endswith("realised"), "原文句末无句点，补一个就是改写引用"


def test_r5_fires_on_a_jorc_scope_and_stays_silent_on_an_ni_scope() -> None:
    """R5 的**体系分流**：同一句新闻，JORC 范围的矿上触发、NI 范围的不触发。

    这件事本身就是可断言的设计：同一句"把 Inferred 说成 reserve"，在 JORC 的矿上
    引 Clause 12，在 NI 的矿上该引 `s.2.2(a)`（R1 已经引了）。混引就是引错法条。
    """
    said = _news("The inferred resource is expected to become a reserve next year")

    jorc = _FakeDataset().with_table(standard=ReportingStandard.JORC).with_news(said).build()
    jorc["scope"] = ReportScope(
        entries=(
            ArchiveEntryRef(
                id="pilgangoora",
                project="Pilgangoora",
                company="Pilbara Minerals",
                commodity="lithium",
                spoken_as="Pilbara",
            ),
        ),
        window_days=7,
    )
    assert "R5" in _ids(jorc)
    signal = next(s for s in evaluate(RULES, HINT_RULES, jorc)["signals"] if s.rule_id == "R5")
    assert "Figure 1" in signal.verbatim
    assert "信息源" in signal.triggered_by, "要报措辞，不能读成我们在指控某家公司"

    ni = _FakeDataset().with_table(standard=ReportingStandard.NI_43_101).with_news(said).build()
    ni["scope"] = ReportScope(
        entries=(
            ArchiveEntryRef(
                id="kamoa-kakula",
                project="Kamoa-Kakula",
                company="Ivanhoe",
                commodity="copper",
                spoken_as="Kamoa",
            ),
        ),
        window_days=7,
    )
    assert "R5" not in _ids(ni)


def test_r5_does_not_fire_when_the_reserve_word_comes_first() -> None:
    """`reserve ... indicated` 常见于合规的对比表述，不报 —— 判据是**顺序**。"""
    state = (
        _FakeDataset()
        .with_table(standard=ReportingStandard.JORC)
        .with_news(_news("Reserve tonnage grew while indicated resources were unchanged"))
        .build()
    )
    state["scope"] = ReportScope(
        entries=(
            ArchiveEntryRef(
                id="pilgangoora",
                project="Pilgangoora",
                company="Pilbara Minerals",
                commodity="lithium",
                spoken_as="Pilbara",
            ),
        ),
        window_days=7,
    )
    assert "R5" not in _ids(state)


def test_a_rule_that_fires_always_has_something_to_say() -> None:
    """`applies` 为真而 `triggered_by` 说不出话 —— 规则集自己写错了，该炸。

    这不是数据能触发的失败，所以它不该被吸收成"数据缺失"，而是一个**响亮**的
    `RuleError`。这条用例证明那支保护真的在，而不是一句注释里的承诺。
    """
    from mining_brief.agent.rules import RuleError, _r2_triggered_by

    with pytest.raises(RuleError):
        _r2_triggered_by({"now": NOW, "news": None})


# ---------------------------------------------------------------------------
# 提示：只出现在提示里，不出现在风险信号里
# ---------------------------------------------------------------------------


def test_an_observation_without_a_verbatim_lands_in_hints_only() -> None:
    """切面 S3 的否定用例：没有原文支撑的观察**只**出现在提示里。

    "某个项目的许可被拒了"是我们确实看见的事，也确实值得提一句 —— 但它没有任何
    可逐字引用的披露规则。让它出现在 `signals` 里，就等于给"风险信号"这个词掺了水。
    """
    state = _FakeDataset().with_news(_news("Project permit rejected by state regulator")).build()
    result = evaluate(RULES, HINT_RULES, state)

    assert result["signals"] == (), "许可被拒没有可引的原文，不该产生风险信号"
    assert len(result["hints"]) == 1
    hint = result["hints"][0]
    assert "permit rejected" in hint.text.lower(), "提示要引出那条新闻，让人能自己去看"
    assert hint.why_not_a_signal.strip(), "提示必须自曝为什么它不是信号"


def test_hints_and_signals_can_coexist_without_contaminating_each_other() -> None:
    """ "既有信号又有提示"是最容易出错的组合：两者串味，读者就再也分不清。"""
    state = _FakeDataset().with_news(_news("PEA shows robust economics; mine suspended")).build()
    result = evaluate(RULES, HINT_RULES, state)

    signal_ids = {signal.rule_id for signal in result["signals"]}
    assert "R3" in signal_ids
    for signal in result["signals"]:
        assert "提示" not in signal.title
        assert signal.verbatim, "风险信号必须有原文"

    # 串味的具体形态是**判据互串**，不是"两边提到了同一条新闻" —— 提示要引那条新闻
    # 的标题才让人能自己去看，所以"标题同时出现在两处"是**正确**的。要防的是：
    # 提示里塞进法条（那是信号的专属），或信号里塞进无原文的观察。
    signal_texts = " ".join(signal.title + signal.triggered_by for signal in result["signals"])
    for hint in result["hints"]:
        for signal in result["signals"]:
            assert signal.verbatim not in hint.text, "法条只属于风险信号，不该出现在提示里"
        assert hint.why_not_a_signal.strip()
        assert hint.text not in signal_texts, "无原文的观察不该被塞进风险信号"


def test_the_rss_signature_hint_does_not_fire_when_there_is_no_resource_news() -> None:
    """署名那条提示只在窗口内真的**有**资源类新闻时才出。

    不这么收的话，它会变成一条每期都印的样板话 —— 而"每期都印"正是它被降级为
    提示的原因（`docs/risk-rules.md` §4 第一行），把它做成无条件出现就等于把这个
    理由推到了反面。
    """
    state = _FakeDataset().with_news(_news("Truck fleet upgrade completed")).build()
    assert evaluate(RULES, HINT_RULES, state)["hints"] == ()

    with_resource_news = _FakeDataset().with_news(_news("Indicated resource upgraded")).build()
    hints = evaluate(RULES, HINT_RULES, with_resource_news)["hints"]
    assert len(hints) == 1
    assert "合资格人" in hints[0].text
