"""九个节点的实现 —— 整张图的**脊**。

分工的总纲（PRD §6.2）：**模型只出现在第 1、2、7 个节点**（意图解析、实体规范化、
导读措辞），其余全是纯函数。每一个模型的输出都有确定的取值域，越界值被校验挡回去。

关于"失败"的口径（ADR-0006）：

- **fetch 节点**：自己兜底。工具链失效 → 降级信封，简报照样出。
- **纯函数节点**：不重试、不捕获。上游降级时它按契约返回空（"该节留空"），
  它自己抛异常只可能是代码 bug，就该响亮地炸 —— 把 bug 伪装成"数据缺失"
  是这个项目最不该犯的错。
"""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from mining_brief.agent.citations import CitationLedger, verify
from mining_brief.agent.llm import LLMError
from mining_brief.agent.prompts import (
    PARSE_INTENT_SYSTEM,
    PARSE_INTENT_USER,
    RESOLVE_ENTITIES_SYSTEM,
    RESOLVE_ENTITIES_USER,
)
from mining_brief.agent.retry import retry_params, with_retry
from mining_brief.agent.rules import RULES, evaluate
from mining_brief.agent.state import BriefState
from mining_brief.config.archive import (
    ARCHIVE,
    ArchiveEntry,
    entries_for_commodity,
    known_commodities,
    match_entry,
)
from mining_brief.config.logging import get_logger
from mining_brief.contracts import (
    DEFAULT_WINDOW_DAYS,
    SECTION_TITLES,
    ArchiveEntryRef,
    Fact,
    FetchStatus,
    Intent,
    NewsCategory,
    NewsSearchResult,
    PriceSeries,
    Refusal,
    ReportScope,
    ResourceExtract,
    Section,
    SectionKey,
    Slots,
    Uncovered,
)
from mining_brief.errors import ReplayMiss

log = get_logger(__name__)

_COMMODITY_ZH: dict[str, str] = {"lithium": "锂", "copper": "铜", "iron_ore": "铁矿石"}
_COMMODITY_QUERY: dict[str, str] = {
    "lithium": "lithium",
    "copper": "copper",
    "iron_ore": "iron ore",
}

#: 越界请求的可用句式示例。**文案可断言**（A8），所以它是一份常量而不是模型生成的。
USABLE_PHRASINGS: tuple[str, ...] = (
    "出份锂的日报",
    "看看 Pilbara 最近 7 天",
    "给我生成一份关于 Pilbara 锂矿的今日简报",
)


def _note(state: BriefState, text: str) -> tuple[str, ...]:
    """顺序节点往备注里追加一条。

    这些节点不并发，所以"读旧值 → 返回整条新元组"的覆盖语义就是对的（ADR-0007）。
    三路 fetch 的失败**不进这里** —— 它们走信封，避免同一个事实存两处日后漂移。
    """
    return (*state.get("notes", ()), text)


def _envelope_note(envelope: Any) -> str:
    """把一个信封翻成第 6 节里的一句话。四种状态对应四件不同的事。"""
    if envelope is None:
        return "数据缺失（该分支没有返回任何信封）。"
    if envelope.source_status is FetchStatus.OK:
        return "已取到。"
    if envelope.source_status is FetchStatus.EMPTY:
        return "源可达，但本次范围内没有数据。"
    return f"数据缺失 —— {envelope.reason}"


# ---------------------------------------------------------------------------
# 1. parse_intent —— 模型
# ---------------------------------------------------------------------------


def _parse_slots_payload(payload: str) -> Slots:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    commodity = raw.get("commodity")
    if commodity not in _COMMODITY_ZH:
        # 模型给出取值域外的品种时按"没提到"处理 —— 不猜、不映射、不就近匹配。
        commodity = None

    window = raw.get("window_days", DEFAULT_WINDOW_DAYS)
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        window = DEFAULT_WINDOW_DAYS

    mine = raw.get("mine")
    if not isinstance(mine, str) or not mine.strip():
        mine = None

    intent = Intent.OUT_OF_SCOPE if raw.get("intent") == "out_of_scope" else Intent.BRIEFING

    return Slots(
        intent=intent,
        commodity=commodity,
        mine=mine.strip() if mine else None,
        window_days=window,
    )


async def parse_intent(state: BriefState) -> dict[str, Any]:
    """一句话 → 意图 + 三个槽位（PRD §4.1）。

    失败时降级为缺省值**并在第 6 节记一笔** —— 悄悄降级会让"这份简报是按缺省值
    出的"这件事从产物里消失（User Story 25），而使用者只看得到一份看起来很正常的
    日报，看不到它其实没听懂自己。
    """
    request_text = state["request_text"]
    try:
        payload = await state["llm"].complete(
            node="parse_intent",
            key_input={"request_text": request_text},
            system=PARSE_INTENT_SYSTEM,
            user=PARSE_INTENT_USER.format(request_text=request_text),
        )
        return {"slots": _parse_slots_payload(payload)}
    except (LLMError, ValueError, json.JSONDecodeError) as exc:
        log.warning("intent.degraded", error=str(exc))
        return {
            "slots": Slots(),
            "notes": _note(
                state, f"意图解析降级为缺省值（{type(exc).__name__}）：按全档案 + 7 天出报。"
            ),
        }


# ---------------------------------------------------------------------------
# 2. resolve_entities —— 模型提议，档案裁决
# ---------------------------------------------------------------------------


def _candidates_block() -> str:
    return "\n".join(
        f"- {entry.id} — {entry.project} — {entry.company} — 别称：{'、'.join(entry.aliases)}"
        for entry in ARCHIVE
    )


def _resolve_mine(spoken: str, proposed: str | None) -> ArchiveEntry | None:
    """模型给的候选**必须**过档案这一关。

    这是全系统唯一可能"编造实体"的入口，所以最终的落档判定不交给模型：模型说出的
    id 若不在档案里，一律当没说，退回档案自己的字符串匹配（验收 A9）。
    """
    if proposed:
        exact = next((entry for entry in ARCHIVE if entry.id == proposed), None)
        if exact is not None:
            return exact
        log.warning("entity.proposal_rejected", proposed=proposed, spoken=spoken)
    return match_entry(spoken)


async def resolve_entities(state: BriefState) -> dict[str, Any]:
    """矿名 → 档案条目。对不上就记"未覆盖"，**绝不编造**（CONTEXT.md）。"""
    slots = state["slots"]
    uncovered: list[Uncovered] = []
    matched: list[ArchiveEntry] = []

    if slots.mine:
        proposed: str | None = None
        try:
            payload = await state["llm"].complete(
                node="resolve_entities",
                key_input={"mine": slots.mine},
                system=RESOLVE_ENTITIES_SYSTEM,
                user=RESOLVE_ENTITIES_USER.format(
                    candidates=_candidates_block(), spoken=slots.mine
                ),
            )
            candidate = json.loads(payload).get("project")
            proposed = candidate if isinstance(candidate, str) else None
        except (LLMError, ValueError, json.JSONDecodeError, AttributeError) as exc:
            # 模型这层挂了不影响正确性 —— 档案自身的匹配规则照样能兜住。这正是
            # "实体解析交给档案而不是模型"换来的免疫性。
            log.warning("entity.llm_degraded", error=str(exc))

        entry = _resolve_mine(slots.mine, proposed)
        if entry is None:
            uncovered.append(Uncovered(spoken=slots.mine, kind="mine"))
        else:
            matched.append(entry)

    if slots.commodity:
        by_commodity = entries_for_commodity(slots.commodity)
        if not by_commodity:
            uncovered.append(Uncovered(spoken=slots.commodity, kind="commodity"))
        elif matched:
            # 矿山与品种**同时**提到时以矿山为准；两者冲突（如"Pilbara 的铜"）
            # 不在这里消解 —— 交给 check_scope 拒答，因为那是一次真正没听懂。
            narrowed = [entry for entry in matched if entry.commodity == slots.commodity]
            if narrowed:
                matched = narrowed
            else:
                uncovered.append(Uncovered(spoken=slots.commodity, kind="commodity"))
        else:
            matched = list(by_commodity)
    elif not slots.mine:
        matched = list(ARCHIVE)

    entries = tuple(
        ArchiveEntryRef(
            id=entry.id,
            project=entry.project,
            company=entry.company,
            commodity=entry.commodity,
            spoken_as=slots.mine or entry.project,
        )
        for entry in matched
    )
    scope = (
        ReportScope(entries=entries, window_days=slots.window_days)
        if entries and not uncovered
        else None
    )
    return {"scope": scope, "uncovered": tuple(uncovered)}


# ---------------------------------------------------------------------------
# 3. check_scope —— 纯函数
# ---------------------------------------------------------------------------


def _understood_echo(slots: Slots) -> str:
    """回显听懂的部分，让使用者看出**是哪里**没被理解（User Story 24）。

    纯函数，所以这段话可被断言 —— 拒答文案是验收项，不能是随手写的字符串。
    """
    parts: list[str] = []
    if slots.commodity:
        parts.append(_COMMODITY_ZH[slots.commodity])
    if slots.mine:
        parts.append(f"矿山「{slots.mine}」")
    if not parts:
        return "我没有从这句话里听出具体的矿种或矿山。"
    return "我听懂了：" + "、".join(parts) + f"；时间窗口 {slots.window_days} 天。"


def _options_line() -> str:
    projects = "、".join(entry.project for entry in ARCHIVE)
    commodities = "、".join(_COMMODITY_ZH[c] for c in known_commodities())
    return f"档案内可选项：矿山 {projects}；矿种 {commodities}。"


def _refusal_for_out_of_scope(slots: Slots) -> Refusal:
    return Refusal(
        understood=_understood_echo(slots),
        why=(
            "这句话超出了本系统的能力范围 —— 本系统只汇总**已发生**的数据，"
            "不做预测、不做估值、不给投资建议。"
        ),
        usable_phrasings=USABLE_PHRASINGS,
    )


def _refusal_for_uncovered(slots: Slots, uncovered: tuple[Uncovered, ...]) -> Refusal:
    missing = "、".join(item.spoken for item in uncovered)
    return Refusal(
        understood=_understood_echo(slots),
        why=(
            f"「{missing}」不在本系统的矿权档案里 —— 这是**未覆盖**，不是「这座矿不存在」。"
            f"本系统不编造实体。{_options_line()}"
        ),
        usable_phrasings=USABLE_PHRASINGS,
    )


def check_scope(state: BriefState) -> dict[str, Any]:
    """不在覆盖内 → 拒答 → END。

    两条拒答路径在这里合流成同一个 `Refusal` 类型，但文案不同：
    **越界**（意图根本不是出简报）与**未覆盖**（档案里没有）是两件事。
    它们的共同点是"系统知道自己不会什么，并且说得清楚"。

    拒答是**一次成功执行**的结果，不是异常（CONTEXT.md）。
    """
    slots = state["slots"]
    uncovered = state.get("uncovered", ())

    if slots.intent is Intent.OUT_OF_SCOPE:
        return {"refusal": _refusal_for_out_of_scope(slots)}
    if uncovered:
        return {"refusal": _refusal_for_uncovered(slots, uncovered)}
    if state.get("scope") is None:
        # 理论上到不了：既没未覆盖、又没范围，只可能是 resolve_entities 的 bug。
        # 与其让下游 assert 炸得莫名其妙，不如在这里给出一个说得清的拒答。
        return {
            "refusal": _refusal_for_uncovered(slots, (Uncovered(spoken="本次请求", kind="mine"),))
        }
    return {"refusal": None}


def route_after_scope(state: BriefState) -> list[str]:
    """拒答就直接去渲染；否则**静态三路扇出**。

    扇出在这里一次性定死，不靠节点返回值动态决定 —— 图脊的形状是设计决策，
    应该能一眼看出来，而不是运行时才知道。这也是工单 01 的核心意图。
    """
    if state.get("refusal"):
        return ["render"]
    return ["fetch_news", "fetch_prices", "fetch_resources"]


# ---------------------------------------------------------------------------
# 4a / 4b / 4c —— 三个并行 fetch，各自兜底
# ---------------------------------------------------------------------------
#
# ⚠️ **不要把这层 try/except 当冗余删掉。** LangGraph 的 superstep 是事务性的：
# 一个并行分支抛异常会让整个 superstep 回滚、整张图抛错，且没有 checkpointer 时
# 兄弟分支的成功结果也会一起丢掉。"任一 fetch 挂掉，简报照样出"**不是框架默认
# 行为**，是这层兜底换来的。它也没有和信封重复：信封描述**数据源**的状态，
# 这层兜的是**工具链本身**失效（进程起不来、协议不兼容）—— 那时连信封都没人签发。
# 见 ADR-0006。


def _failed_news(state: BriefState, reason: str) -> NewsSearchResult:
    return NewsSearchResult(
        status="degraded",
        source_status=FetchStatus.UNAVAILABLE,
        reason=reason,
        retrieved_at=state["now"],
        query="",
        window_days=state["slots"].window_days,
        window_start=state["now"].isoformat(),
        window_end=state["now"].isoformat(),
        items=(),
    )


def _news_query(state: BriefState) -> str:
    """把范围翻成 `search(query, days)` 要的关键词串。

    矿山名（项目 + 公司）在前、矿种在后 —— 顺序只影响可读性，匹配规则是"命中任一词"。
    """
    scope = state["scope"]
    assert scope is not None  # route_after_scope 已经保证走到这里一定有范围
    terms: list[str] = []
    for entry in scope.entries:
        terms.extend([entry.project, entry.company])
    for commodity in scope.commodity_in_scope:
        terms.append(_COMMODITY_QUERY[commodity])
    return " ".join(dict.fromkeys(terms))


def _retry_logger(label: str) -> Any:
    def report(attempt: int, attempts: int, delay: float, exc: Exception) -> None:
        log.warning(
            "fetch.retry",
            label=label,
            attempt=attempt,
            of=attempts,
            delay_s=round(delay, 3),
            error=f"{type(exc).__name__}: {exc}",
        )

    return report


async def fetch_news(state: BriefState) -> dict[str, Any]:
    attempts, base_delay = retry_params(state)
    query = _news_query(state)
    days = state["slots"].window_days
    try:
        result = await with_retry(
            lambda: state["toolkit"].search_news(query, days),
            attempts=attempts,
            base_delay_s=base_delay,
            label="news",
            on_retry=_retry_logger("news"),
        )
    except ReplayMiss:
        raise  # 录播缺失不是"取不到"，是"我们的录播集不全" —— 不许降级，见 errors.py
    except Exception as exc:
        log.warning("fetch.news.failed", error=str(exc))
        return {"news": _failed_news(state, f"新闻工具链路失效：{type(exc).__name__}")}
    return {"news": result}


def _degraded_series(state: BriefState, commodity: str, reason: str) -> PriceSeries:
    return PriceSeries(
        status="degraded",
        source_status=FetchStatus.UNAVAILABLE,
        reason=reason,
        retrieved_at=state["now"],
        commodity=commodity,
        exchange="",
        requested_days=state["slots"].window_days,
        points=(),
    )


async def fetch_prices(state: BriefState) -> dict[str, Any]:
    scope = state["scope"]
    assert scope is not None
    days = state["slots"].window_days
    attempts, base_delay = retry_params(state)
    prices: dict[str, PriceSeries] = {}

    for commodity in scope.commodity_in_scope:
        try:
            prices[commodity] = await with_retry(
                # 用 partial 而不是 `lambda c=commodity: ...`：后者的默认参数会让
                # mypy 推不出返回类型，而 partial 能。
                partial(state["toolkit"].get_trend, commodity, days),
                attempts=attempts,
                base_delay_s=base_delay,
                label=f"prices:{commodity}",
                on_retry=_retry_logger(f"prices:{commodity}"),
            )
        except ReplayMiss:
            raise
        except Exception as exc:
            log.warning("fetch.prices.failed", commodity=commodity, error=str(exc))
            prices[commodity] = _degraded_series(
                state, commodity, f"价格工具链路失效：{type(exc).__name__}"
            )
    return {"prices": prices}


def _resources_entry(scope: ReportScope) -> ArchiveEntry | None:
    first = next((item for item in scope.entries if item.id), None)
    if first is None:
        return None
    return next((entry for entry in ARCHIVE if entry.id == first.id), None)


async def fetch_resources(state: BriefState) -> dict[str, Any]:
    scope = state["scope"]
    assert scope is not None
    archive_entry = _resources_entry(scope)

    if archive_entry is None or not archive_entry.report_url:
        # 档案里没有技术报告直链 —— 这是**已知的数据缺口**，如实记，不编一个 URL 出来。
        # 显示名用档案条目的规范项目名（不是用户的口语说法），避免散文里出现两种叫法。
        who = archive_entry.project if archive_entry else "本次范围"
        return {
            "resources": ResourceExtract(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=f"{who} 的技术报告直链未核实到，本次无法抽取储量数据。",
                retrieved_at=state["now"],
                table=None,
            )
        }

    attempts, base_delay = retry_params(state)
    report_url = archive_entry.report_url
    try:
        extract = await with_retry(
            lambda: state["toolkit"].extract_resources(report_url),
            attempts=attempts,
            base_delay_s=base_delay,
            label="resources",
            on_retry=_retry_logger("resources"),
        )
    except ReplayMiss:
        raise
    except Exception as exc:
        log.warning("fetch.resources.failed", error=str(exc))
        return {
            "resources": ResourceExtract(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=f"PDF 工具链路失效：{type(exc).__name__}",
                retrieved_at=state["now"],
                table=None,
            )
        }
    return {"resources": extract}


# ---------------------------------------------------------------------------
# 5. compute_signals —— 纯函数
# ---------------------------------------------------------------------------


def compute_signals(state: BriefState) -> dict[str, Any]:
    """规则引擎。规则集由 02 号工单冻结，07 号工单接上触发逻辑。

    本票里 `RULES` 是空的，所以这条路径的真实输出就是"本次未触发" —— 一条**真**
    输出，不是待办占位。它不重试、不捕获（ADR-0006）。
    """
    return evaluate(RULES, state)


# ---------------------------------------------------------------------------
# 6. assemble —— 纯函数
# ---------------------------------------------------------------------------


def _news_section(
    state: BriefState, ledger: CitationLedger, *, category: NewsCategory, title: str
) -> Section:
    key = SectionKey.MINING_RIGHTS if category is NewsCategory.MINING_RIGHTS else SectionKey.NEWS
    news = state.get("news")

    if news is None:
        return Section(key=key, title=title, as_of=None, note="数据缺失：本次没有取到新闻源。")

    selected = [item for item in news.items if item.category is category]
    facts = tuple(
        Fact(
            text=f"{item.title}（{item.source}）",
            citation=ledger.cite(
                kind="news",
                title=item.title,
                url=item.url,
                publisher=item.source,
                timestamp=item.published_at,
            ),
        )
        for item in selected
    )

    # 数据时点必须只由**本节真的用到的那几条**决定。用整个信封的最大值会让
    # 「矿权动态」在一条都没选中时也带一个时点，那是在暗示本节有数据。
    as_of = max((item.published_at for item in selected), default=None)

    if facts:
        # 检索式写进产物：一份"Pilbara 简报"里出现阿根廷的锂新闻，读者有权知道
        # 系统到底搜了什么，而不是自己猜这些条目为什么在这儿。
        note = f"检索式：{news.query}（窗口 {news.window_days} 天）。"
    elif news.source_status in (FetchStatus.OK, FetchStatus.EMPTY):
        # "今天没新闻"与"网站挂了"必须长出两句不同的话 —— 这正是 EMPTY 与
        # UNAVAILABLE 分成两个状态的全部理由（ADR-0005）。
        note = f"窗口内（{news.window_days} 天）没有符合范围的{title}。检索式：{news.query}。"
    else:
        note = f"数据缺失 —— {news.reason}"

    return Section(key=key, title=title, as_of=as_of, facts=facts, note=note)


def _prices_section(state: BriefState, ledger: CitationLedger) -> Section:
    facts: list[Fact] = []
    notes: list[str] = []
    as_ofs: list[str] = []

    for commodity, series in sorted((state.get("prices") or {}).items()):
        if not series.points:
            notes.append(
                f"{_COMMODITY_ZH.get(commodity, commodity)}：{series.reason or '本次未取到'}"
            )
            continue
        latest = series.points[-1]
        as_ofs.append(latest.as_of)
        qualifiers = ["延迟披露" if latest.delayed else "当日"]
        if latest.is_fallback:
            qualifiers.append(f"回退自 {latest.requested_date}")
        facts.append(
            Fact(
                text=(
                    f"{latest.commodity} {latest.value} {latest.currency}/{latest.unit}"
                    f"（{latest.exchange} {latest.symbol}，"
                    f"{latest.as_of}，{'，'.join(qualifiers)}）"
                ),
                citation=ledger.cite(
                    kind="price",
                    title=f"{latest.exchange} {latest.symbol}",
                    url=latest.source_url,
                    publisher=latest.exchange,
                    timestamp=latest.as_of,
                ),
            )
        )

    return Section(
        key=SectionKey.PRICES,
        title=SECTION_TITLES[SectionKey.PRICES],
        as_of=max(as_ofs) if as_ofs else None,
        facts=tuple(facts),
        note=("数据缺失 —— " + "；".join(notes)) if notes else None,
    )


def _resources_section(state: BriefState, ledger: CitationLedger) -> Section:
    title = SECTION_TITLES[SectionKey.RESOURCES]
    extract = state.get("resources")

    if extract is None:
        return Section(
            key=SectionKey.RESOURCES,
            title=title,
            as_of=None,
            note="数据缺失：本次没有取到储量数据。",
        )
    if extract.table is None:
        return Section(
            key=SectionKey.RESOURCES, title=title, as_of=None, note=f"数据缺失 —— {extract.reason}"
        )

    table = extract.table
    citation = ledger.cite(
        kind="resource",
        title=table.report_title,
        url=table.pdf_url,
        publisher=table.standard.value,
        timestamp=table.report_date,
    )
    facts_list: list[Fact] = []
    for row in table.rows:
        kind_zh = "资源量" if row.kind.value == "resource" else "储量"
        tonnage = "未披露吨位" if row.tonnage_mt is None else f"{row.tonnage_mt} Mt"
        grade = "" if row.grade is None else f"，品位 {row.grade} {row.grade_unit or ''}".rstrip()
        facts_list.append(
            Fact(text=f"{row.category.value}（{kind_zh}）：{tonnage}{grade}", citation=citation)
        )
    facts = tuple(facts_list)
    return Section(
        key=SectionKey.RESOURCES,
        title=title,
        as_of=table.report_date,
        facts=facts,
        note=(
            f"报告体系：{table.standard.value}。"
            "节内严格区分资源量与储量 —— Indicated / Inferred 是资源量，不是储量。"
        ),
    )


def _risks_section(state: BriefState) -> Section:
    signals = state.get("signals", ())
    hints = state.get("hints", ())

    facts = tuple(
        Fact(
            text=(
                f"[{signal.rule_id}] {signal.title} —— {signal.triggered_by}；"
                f"原文：{signal.verbatim}"
            )
        )
        for signal in signals
    )
    note = None if facts else "本次未触发任何风险信号。"
    if hints:
        note = (
            note + " " if note else ""
        ) + f"另有 {len(hints)} 条提示（未达到逐字引权威原文的门槛）。"

    return Section(
        key=SectionKey.RISKS,
        title=SECTION_TITLES[SectionKey.RISKS],
        as_of=state["now"].isoformat(),
        facts=facts,
        note=note,
    )


def _integrity_section(state: BriefState) -> Section:
    scope = state["scope"]
    assert scope is not None

    projects = "、".join(f"{entry.project}（{entry.company}）" for entry in scope.entries)
    facts: list[Fact] = [
        Fact(text=f"覆盖范围：{projects}；窗口 {scope.window_days} 天。"),
        Fact(text=f"新闻：{_envelope_note(state.get('news'))}"),
        Fact(text=f"储量：{_envelope_note(state.get('resources'))}"),
    ]

    prices = state.get("prices") or {}
    if not prices:
        facts.append(Fact(text="价格：本次范围内没有需要取价的品种。"))
    for commodity, series in sorted(prices.items()):
        label = _COMMODITY_ZH.get(commodity, commodity)
        if series.points:
            facts.append(Fact(text=f"价格（{label}）：已取到 {len(series.points)} 个数据点。"))
        else:
            facts.append(
                Fact(text=f"价格（{label}）：数据缺失 —— {series.reason or '本次未取到'}。")
            )

    for extra in state.get("notes", ()):
        facts.append(Fact(text=extra))

    return Section(
        key=SectionKey.INTEGRITY,
        title=SECTION_TITLES[SectionKey.INTEGRITY],
        as_of=state["now"].isoformat(),
        facts=tuple(facts),
        note="本节记录的是事实，不是免责声明。",
    )


def assemble(state: BriefState) -> dict[str, Any]:
    """搭六节骨架。**逐字引用块由代码塞入**，不由模型生成（PRD §6.2）。"""
    ledger = CitationLedger()
    sections = (
        _news_section(
            state,
            ledger,
            category=NewsCategory.MINING_RIGHTS,
            title=SECTION_TITLES[SectionKey.MINING_RIGHTS],
        ),
        _news_section(
            state, ledger, category=NewsCategory.GENERAL, title=SECTION_TITLES[SectionKey.NEWS]
        ),
        _resources_section(state, ledger),
        _prices_section(state, ledger),
        _risks_section(state),
        _integrity_section(state),
    )
    return {"sections": sections, "citations": ledger.citations}


# ---------------------------------------------------------------------------
# 7. narrate —— 模型（08 号工单实现）
# ---------------------------------------------------------------------------


async def narrate(state: BriefState) -> dict[str, Any]:
    """每节一句导读。

    **08 号工单**把它接上模型：输入是已冻结的该节数据，输出只能写措辞、不能写事实。
    本票是空操作 —— 图脊先立起来，措辞后面补；顺序反过来会返工两次。
    """
    del state
    return {}


# ---------------------------------------------------------------------------
# 8. verify_citations —— 纯函数
# ---------------------------------------------------------------------------


def verify_citations(state: BriefState) -> dict[str, Any]:
    """`[n]` 必须指回真实工具返回值。不通过 → 抛错（PRD §5.2 硬规则 2）。"""
    return {"citation_report": verify(state["sections"], state.get("citations", ()))}


# ---------------------------------------------------------------------------
# 9. render —— 纯函数（不碰磁盘，落盘由 pipeline 做）
# ---------------------------------------------------------------------------


def render(state: BriefState) -> dict[str, Any]:
    """把 state 冻成最终产物对象。

    刻意**不在这里写文件**：渲染逻辑与副作用分开，测试才能在不碰磁盘的情况下
    逐字断言产物内容。落盘是 `pipeline.run_brief` 的事。
    """
    from mining_brief.agent.render import build_result

    return {"result": build_result(state)}
