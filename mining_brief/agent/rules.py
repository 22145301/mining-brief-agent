"""风险规则引擎：把 `docs/risk-rules.md` 冻结的规则集落成触发逻辑。

**规则集不在这里发明。** 每条规则的 `verbatim` 是从权威文件里逐字抄来的原句，
出处与哈希记在 `docs/risk-rules.md` §1；本文件只负责"什么时候该把它拿出来"。
往这里加一条规则之前，必须先往那份文档里补上它的逐字原文与可点开的出处 ——
`tests/test_risk_rules.py::test_the_engine_implements_exactly_the_frozen_rule_set`
盯着这条纪律：它会拿本文件的 `RULES` 去和文档正文比对，对不上就红。

**引擎是纯函数**（ADR-0006）：不重试、**不捕获异常**。上游降级导致没数据时该节留空 ——
那是正常路径，不是失败；它抛异常只可能是代码 bug，就该响亮地炸，不把 bug 伪装成
数据缺失。

**可见面只有 `news.items[*]` 与 `resources[*].extract.table`。** `BriefState` 里没有
文章正文（ADR-0007 的扁平 state 只装 RSS 的 title + summary），所以"没署合资格人""没
提环保"这类**一眼可辨但要看正文**的条件一条都进不了规则集 —— 它们只能进 §4 的提示。
这是规则集收窄的**真实**原因，不是为了省事。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mining_brief.config.archive import entry_by_id
from mining_brief.contracts import (
    Hint,
    NewsItem,
    ReportingStandard,
    ResourceCategory,
    ResourceExtract,
    RiskSignal,
)

if TYPE_CHECKING:
    from mining_brief.agent.state import BriefState, ResourceLookup


# ---------------------------------------------------------------------------
# 出处（与 docs/risk-rules.md §1 的表逐字一致）
# ---------------------------------------------------------------------------

NI_43_101_URL = (
    "https://nssc.novascotia.ca/sites/default/files/docs/csanotice_43-101new08042011.pdf"
)
NI_43_101_LABEL = "NI 43-101（CSA Notice，2011-04-08）"

JORC_URL = "https://www.jorc.org/docs/JORC_code_2012.pdf"
JORC_LABEL = "JORC Code 2012 Edition"

ASX_LR_CH5_URL = (
    "https://www.asx.com.au/content/dam/asx/about/regulations/public-consultations/"
    "2021/listing-rules-chapter-5-consolidated-consultation-response.pdf"
)
ASX_LR_CH5_LABEL = "ASX Listing Rules, Chapter 5"

#: GN31 是旁证，**不得**作为 `source_url` —— 它当时是 `curl -L` 抓的、没留档，
#: 事后无从按哈希复验（`docs/risk-rules.md` §1 末）。记在这里是为了让"别引它"
#: 这件事有一个能搜到的地方。
GN31_NOT_A_SOURCE = "https://www.asx.com.au/documents/rules/gn31_reporting_on_mining_activities.pdf"


# ---------------------------------------------------------------------------
# 文本工具：规则只看这一层的可见面
# ---------------------------------------------------------------------------

_SENTENCE = re.compile(r"[^。！？；.!?;]+[。！？；.!?;]*")
"""切句。终止符**保留在句子里** —— `triggered_by` 要原样引出那一句，把句点吃掉
就是一种加工（"不加工、不截断到失真"，`docs/risk-rules.md` §2 R2）。"""

#: 数量 / 品位形态。**故意宽**：宁可误报（提示"这一句缺类别"读起来仍是正确的
#: 提醒），也不要漏掉一个真的未分类披露。
_QUANTITY = re.compile(r"\d+(?:\.\d+)?\s*(?:Mtpa|Mt|万吨|亿吨|吨|%|g/t)", re.IGNORECASE)

#: NI 43-101 s.1.2 / s.1.3 的法定类别词，中英并收。
_CATEGORY_WORDS = re.compile(
    r"\binferred\b|\bindicated\b|\bmeasured\b|\bproven\b|\bprobable\b"
    r"|mineral\s+resource|\bore\s+reserve|资源量|储量",
    re.IGNORECASE,
)

#: R5 用的两组词。**分两组而不是一个集合**：这条规则报的是"顺序"——
#: "Inferred ... reserve" 这种先把资源量类词说出来、再用储量类词收尾的写法才是混称；
#: "reserve ... indicated" 常见于合规的对比表述，不该报。
_RESOURCE_WORDS = re.compile(r"\binferred\b|\bindicated\b|\bmeasured\b|资源量", re.IGNORECASE)
_RESERVE_WORDS = re.compile(
    r"\bore\s+reserve|\bproven\b|\bprobable\b|\breserve\b|储量", re.IGNORECASE
)

_PEA = re.compile(
    r"\bPEA\b|preliminary\s+economic\s+assessment|初步经济评估|预可行性", re.IGNORECASE
)
_PRODUCTION_TARGET = re.compile(r"production\s+target|产量目标|产出目标", re.IGNORECASE)


def _news_text(item: NewsItem) -> str:
    """规则能看到的全部 `NewsItem` 内容 —— 就是这两个字段，没有第三条路。"""
    return f"{item.title} {item.summary}"


def _sentences(item: NewsItem) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(_news_text(item)) if s.strip()]


def _items(state: BriefState) -> tuple[NewsItem, ...]:
    news = state.get("news")
    return news.items if news is not None else ()


def _tables(state: BriefState) -> tuple[tuple[ResourceLookup, Any], ...]:
    """本次范围内**真的抽到表**的那些矿山。取不到表的矿山不进规则 —— 没有数据
    就没有可判的东西，这是正常路径（而不是"没有风险"）。"""
    pairs: list[tuple[ResourceLookup, Any]] = []
    for lookup in state.get("resources") or ():
        extract: ResourceExtract = lookup.extract
        if extract.table is not None:
            pairs.append((lookup, extract.table))
    return tuple(pairs)


def _first_sentence_where(item: NewsItem, pattern: re.Pattern[str]) -> str | None:
    return next((s for s in _sentences(item) if pattern.search(s)), None)


def _quote(item: NewsItem, sentence: str) -> str:
    """引出原句 + 来源 + 时刻 —— 读者要能自己回去核这句话是不是我们编的。"""
    return f"{item.source}（{item.published_at}）：「{sentence}」"


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    """一条风险规则。

    `applies` / `triggered_by` 是纯函数，只看已冻结的 state —— 规则引擎里
    **没有模型**（PRD §6.2 分工表）。`verbatim` 只允许是从权威文档里逐字抄来的
    原文，不允许改写、不允许概括、不允许补标点。
    """

    rule_id: str
    title: str
    applies: Callable[[BriefState], bool]
    triggered_by: Callable[[BriefState], str]
    verbatim: str
    """逐字抄自权威公开原文。**不许由模型生成，也不许意译。**"""

    source_url: str
    source_label: str


class RuleError(RuntimeError):
    """规则集的声明自身不自洽（如 `applies` 为真而 `triggered_by` 说不出话）。

    刻意**不**继承 `LoudFailure` 的降级路径：这一条永远不会由上游数据触发，
    只会由规则集写错触发。它该炸到调用方，而不是变成一句"数据缺失"。
    """


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RuleError(message)


# --- R1 --------------------------------------------------------------------


def _r1_matches(state: BriefState) -> list[str]:
    """命中 R1 的矿山描述（`standard=NI_43_101` 且 Inferred 与 Indicated/Measured 并存）。"""
    hits: list[str] = []
    for lookup, table in _tables(state):
        if table.standard is not ReportingStandard.NI_43_101:
            continue
        kinds = {row.category for row in table.rows}
        has_inferred = ResourceCategory.INFERRED in kinds
        has_other = bool(kinds & {ResourceCategory.INDICATED, ResourceCategory.MEASURED})
        if has_inferred and has_other:
            hits.append(f"{lookup.entry.project}（{table.report_title}）")
    return hits


def _r1_applies(state: BriefState) -> bool:
    return bool(_r1_matches(state))


def _r1_triggered_by(state: BriefState) -> str:
    hits = _r1_matches(state)
    _require(hits, "R1 的 applies 为真时该至少有一座矿山命中")
    return f"储量表含 Inferred 与 Indicated（NI 43-101，{'、'.join(hits)}）；两者不得相加"


# --- R2 --------------------------------------------------------------------


def _r2_matches(state: BriefState) -> list[tuple[NewsItem, str]]:
    """命中 R2 的（新闻, 原句）：同一句里有数量/品位形态，却不含任何法定类别词。"""
    hits: list[tuple[NewsItem, str]] = []
    for item in _items(state):
        for sentence in _sentences(item):
            if _QUANTITY.search(sentence) and not _CATEGORY_WORDS.search(sentence):
                hits.append((item, sentence))
    return hits


def _r2_applies(state: BriefState) -> bool:
    return bool(_r2_matches(state))


def _r2_triggered_by(state: BriefState) -> str:
    hits = _r2_matches(state)
    _require(hits, "R2 的 applies 为真时该至少有一句命中")
    item, sentence = hits[0]
    extra = f"（另有 {len(hits) - 1} 句同类）" if len(hits) > 1 else ""
    return f"未分类的数字披露{extra}：{_quote(item, sentence)}"


# --- R3 --------------------------------------------------------------------


def _r3_matches(state: BriefState) -> list[tuple[NewsItem, str]]:
    hits: list[tuple[NewsItem, str]] = []
    for item in _items(state):
        sentence = _first_sentence_where(item, _PEA)
        if sentence is not None:
            hits.append((item, sentence))
    return hits


def _r3_applies(state: BriefState) -> bool:
    return bool(_r3_matches(state))


def _r3_triggered_by(state: BriefState) -> str:
    hits = _r3_matches(state)
    _require(hits, "R3 的 applies 为真时该至少有一句命中")
    item, sentence = hits[0]
    extra = f"（另有 {len(hits) - 1} 句同类）" if len(hits) > 1 else ""
    return f"出现初步经济评估{extra}：{_quote(item, sentence)}"


# --- R4 --------------------------------------------------------------------


def _r4_matches(state: BriefState) -> list[tuple[NewsItem, str]]:
    hits: list[tuple[NewsItem, str]] = []
    for item in _items(state):
        sentence = _first_sentence_where(item, _PRODUCTION_TARGET)
        if sentence is not None:
            hits.append((item, sentence))
    return hits


def _r4_applies(state: BriefState) -> bool:
    return bool(_r4_matches(state))


def _r4_triggered_by(state: BriefState) -> str:
    """**唯一一条带条件从句的 `triggered_by`**，刻意如此。

    `BriefState` 里没有"该新闻主体在哪上市"的结构化字段，所以"限 ASX 主体"这条
    前提我们判不了。判不了就**不假装判定**（`docs/risk-rules.md` §2 R4）——
    把它写成"若该主体在 ASX 上市"的提醒，而不是一句我们兑现不了的断言。
    """
    hits = _r4_matches(state)
    _require(hits, "R4 的 applies 为真时该至少有一句命中")
    item, sentence = hits[0]
    extra = f"（另有 {len(hits) - 1} 句同类）" if len(hits) > 1 else ""
    return (
        f"出现产量目标{extra}：{_quote(item, sentence)}；"
        "若该主体在 ASX 上市，须附临近且同等显著的法定警示句"
    )


# --- R5 --------------------------------------------------------------------


def _jorc_in_scope(state: BriefState) -> bool:
    """本次范围内是否有**按 JORC 体系披露**的矿山。

    R5 引的是 JORC 原文，而 NI 43-101 体系下的同一件事有自己的法条（`s.2.2(a)`，
    见 R1 的引文）—— **混引就是引错法条**（`docs/risk-rules.md` §2 R5 末）。

    读的是档案里的 `standard`（这座矿的法定披露体系）而不是抽到的那张表的
    `standard`：**有没有文件可下载**与**这座矿按哪套体系披露**是两件事，
    Fortescue 就属于"JORC 体系、但不单独发项目级技术报告"那一档
    （`docs/risk-rules.md` §3）。按文件判会让它的 R5 永远静默。

    这里查档案而不是读 `scope` 上的字段：`scope` 是线格式，为了规则引擎的方便去
    给它加字段，是拿契约的稳定性换局部便利。档案是模块级常量，所以这条仍是纯函数。
    """
    scope = state.get("scope")
    if scope is None:
        return False
    for ref in scope.entries:
        entry = entry_by_id(ref.id)
        if entry is not None and entry.standard is ReportingStandard.JORC:
            return True
    return False


def _r5_matches(state: BriefState) -> list[tuple[NewsItem, str]]:
    """命中 R5 的（新闻, 原句）：同一句里资源量类词**先于**储量类词出现。

    这是本清单里唯一一条"负向"规则 —— 它报的是**信息源**的措辞问题，不是我们的
    判断。所以它的 `title` 写的是"该表述"而不是"该矿山"，产物里的措辞也必须说清
    是"来源如此表述"，不能让读者以为我们在指控某家公司。

    **已知的误报面**：`资源量与储量分别增长` 这种并列的好句子也满足"资源量类词在前"。
    按 `docs/risk-rules.md` §2 R5 的字面条件实现，不额外加豁免 —— 那条条件就是
    冻结的规则集本身，改了它就不再是"实现"而是"增删规则"。
    """
    hits: list[tuple[NewsItem, str]] = []
    for item in _items(state):
        for sentence in _sentences(item):
            resource = _RESOURCE_WORDS.search(sentence)
            reserve = _RESERVE_WORDS.search(sentence)
            if resource and reserve and resource.start() < reserve.start():
                hits.append((item, sentence))
    return hits


def _r5_applies(state: BriefState) -> bool:
    return _jorc_in_scope(state) and bool(_r5_matches(state))


def _r5_triggered_by(state: BriefState) -> str:
    hits = _r5_matches(state)
    _require(hits, "R5 的 applies 为真时该至少有一句命中")
    item, sentence = hits[0]
    extra = f"（另有 {len(hits) - 1} 句同类）" if len(hits) > 1 else ""
    return f"信息源该句把资源量类词与储量类词连用{extra}：{_quote(item, sentence)}"


#: 规则集。**只实现 `docs/risk-rules.md` 冻结的这五条，不增不减。**
RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="R1",
        title="推断资源量不得与其他类别相加",
        applies=_r1_applies,
        triggered_by=_r1_triggered_by,
        verbatim=(
            "An issuer must not disclose any information about a mineral resource or mineral "
            "reserve unless the disclosure (a) uses only the applicable mineral resource and "
            "mineral reserve categories set out in sections 1.2 and 1.3; (b) reports each "
            "category of mineral resources and mineral reserves separately, and states the "
            "extent, if any, to which mineral reserves are included in total mineral resources; "
            "(c) does not add inferred mineral resources to the other categories of mineral "
            "resources; and (d) states the grade or quality and the quantity for each category "
            "of the mineral resources and mineral reserves if the quantity of contained metal "
            "or mineral is included in the disclosure."
        ),
        source_url=NI_43_101_URL,
        source_label=f"{NI_43_101_LABEL}, Part 2, s. 2.2",
    ),
    Rule(
        rule_id="R2",
        title="未分类的数量或品位不得单独披露",
        applies=_r2_applies,
        triggered_by=_r2_triggered_by,
        verbatim=(
            "(1) An issuer must not disclose (a) the quantity, grade, or metal or mineral "
            "content of a deposit that has not been categorized as an inferred mineral resource, "
            "an indicated mineral resource, a measured mineral resource, a probable mineral "
            "reserve, or a proven mineral reserve;"
        ),
        source_url=NI_43_101_URL,
        source_label=f"{NI_43_101_LABEL}, Part 2, s. 2.3(1)(a)",
    ),
    Rule(
        rule_id="R3",
        title="经济分析含推断资源量时须带法定措辞",
        applies=_r3_applies,
        triggered_by=_r3_triggered_by,
        verbatim=(
            "Despite paragraph (1)(b), an issuer may disclose the results of a preliminary "
            "economic assessment that includes or is based on inferred mineral resources if the "
            "disclosure (a) states with equal prominence that the preliminary economic "
            "assessment is preliminary in nature, that it includes inferred mineral resources "
            "that are considered too speculative geologically to have the economic "
            "considerations applied to them that would enable them to be categorized as mineral "
            "reserves, and there is no certainty that the preliminary economic assessment will "
            "be realized;"
        ),
        source_url=NI_43_101_URL,
        source_label=f"{NI_43_101_LABEL}, Part 2, s. 2.3(3)(a)",
    ),
    Rule(
        rule_id="R4",
        title="生产目标须附临近且同等显著的法定警示句",
        applies=_r4_applies,
        triggered_by=_r4_triggered_by,
        # 原文在规则里是被引号包住的整句，**句末无句点** —— 这里补上句点就是改写了
        # 引用（`docs/risk-rules.md` §2 R4 专门说明了这一点）。
        verbatim=(
            "There is a low level of geological confidence associated with inferred mineral "
            "resources and there is no certainty that further exploration work will result in "
            "the determination of indicated mineral resources or that the production target "
            "itself will be realised"
        ),
        source_url=ASX_LR_CH5_URL,
        source_label=f"{ASX_LR_CH5_LABEL}, Rule 5.16.4",
    ),
    Rule(
        rule_id="R5",
        title="公开报告只能使用法定术语（信息源措辞）",
        applies=_r5_applies,
        triggered_by=_r5_triggered_by,
        verbatim=(
            "Public Reports dealing with Exploration Results, Mineral Resources or Ore Reserves "
            "must only use the terms set out in Figure 1."
        ),
        source_url=JORC_URL,
        source_label=f"{JORC_LABEL}, Clause 12",
    ),
)


# ---------------------------------------------------------------------------
# 提示（`Hint`）：看着像风险、却够不上逐字引权威原文的观察
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HintRule:
    """一条**提示**规则。

    与 `Rule` 的结构差异就是它与风险信号的差异：它没有 `verbatim`、没有 `source_url`
    —— 因为它**引不到**权威原文。这不是省略，是它被降级的理由本身。为了不让"降级"
    变成一句空话，`why_not_a_signal` 是必填的：每条提示都要说清它为什么不是信号。
    """

    hint_id: str
    applies: Callable[[BriefState], bool]
    describe: Callable[[BriefState], str]
    why_not_a_signal: str


_RESOURCE_NEWS = _CATEGORY_WORDS

#: 经营事件词。它们确实是值得知道的事，但**没有任何披露规则**规定这类事件必须带
#: 何种措辞 —— 引不到原文，就只能进提示（`docs/risk-rules.md` §4）。
_OPERATIONAL_EVENT = re.compile(
    r"延期|推迟|暂缓|暂停|搁置|停产|停工|被拒|许可被拒|诉讼|"
    r"\bsuspend(?:ed|s|ing)?\b|\bhalt(?:ed|s|ing)?\b|\bdefer(?:red|s|ring)?\b|"
    r"\bpermits?\s+(?:rejected|refused|denied)\b",
    re.IGNORECASE,
)


def _h1_applies(state: BriefState) -> bool:
    return any(_RESOURCE_NEWS.search(_news_text(item)) for item in _items(state))


def _h1_describe(state: BriefState) -> str:
    count = sum(1 for item in _items(state) if _RESOURCE_NEWS.search(_news_text(item)))
    return (
        f"窗口内有 {count} 条涉及资源量 / 储量类表述的新闻，但它们来自 RSS 的标题与摘要"
        "（不含正文），无法核验是否署了合资格人（Competent / Qualified Person）。"
    )


def _h2_applies(state: BriefState) -> bool:
    return any(_OPERATIONAL_EVENT.search(_news_text(item)) for item in _items(state))


def _h2_describe(state: BriefState) -> str:
    hits = [item for item in _items(state) if _OPERATIONAL_EVENT.search(_news_text(item))]
    listed = "、".join(f"{item.title}（{item.source}）" for item in hits)
    return f"窗口内有经营事件类新闻，值得知道，但本系统不为其定性：{listed}"


HINT_RULES: tuple[HintRule, ...] = (
    HintRule(
        hint_id="H1",
        applies=_h1_applies,
        describe=_h1_describe,
        why_not_a_signal=(
            "署名义务确有成文依据（JORC Clause 9 / NI 43-101 s.2.1 / ASX LR 5.22），"
            "但 RSS 摘要天然不载署名 —— 按这条判定几乎每条资源类新闻都会命中。"
            "那不是信号，是噪声。要真判定必须读一手公告全文，而本系统的图里没有正文。"
        ),
    ),
    HintRule(
        hint_id="H2",
        applies=_h2_applies,
        describe=_h2_describe,
        why_not_a_signal=(
            "项目延期、暂停、许可被拒属于经营事件，没有任何披露规则规定这类事件必须带"
            "何种措辞，因此引不到可以逐字引用的权威原文。它值得知道，但不该占用"
            "「风险信号」这个位置 —— 否则这个词会稀释成「随便什么观察」。"
        ),
    ),
)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


def evaluate(
    rules: tuple[Rule, ...], hint_rules: tuple[HintRule, ...], state: BriefState
) -> dict[str, Any]:
    """逐条判定。纯函数：不重试、不捕获（ADR-0006）。

    `signals` 与 `hints` 是**两个字段**，不是同一个列表里的两种语气（PRD §5.1）——
    把它们混起来，读者就再也分不清"这是监管要求"和"这是我们的观察"，
    而"风险信号"这个词的全部价值就在这个区分上。
    """
    signals: list[RiskSignal] = []
    for rule in rules:
        if not rule.applies(state):
            continue
        signals.append(
            RiskSignal(
                rule_id=rule.rule_id,
                title=rule.title,
                triggered_by=rule.triggered_by(state),
                verbatim=rule.verbatim,
                source_url=rule.source_url,
                source_label=rule.source_label,
            )
        )

    hints: list[Hint] = []
    for hint_rule in hint_rules:
        if not hint_rule.applies(state):
            continue
        hints.append(
            Hint(text=hint_rule.describe(state), why_not_a_signal=hint_rule.why_not_a_signal)
        )

    return {"signals": tuple(signals), "hints": tuple(hints)}
