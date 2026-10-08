"""导读的接地校验（工单 08）：模型可以写措辞，不能写事实。

这一层不跑模型、不跑图 —— 它盯的是**闸门本身**。导读是这条链上唯一一处"自由文本"
进入产物，所以这道闸门要么是断言得到的，要么它只是一句注释。

分三类：

1. **payload 是封闭的**：喂给模型的只有该节冻结后的数据，没有 `[n]` 序号、没有别人那一节。
2. **闸门认识越界**：凭空多出来的数字、$随机公司名$、外部日期，都要被拦下。
3. **闸门不误伤**：同一件事的不同写法（千分位、大小写、单位）不该被当成新事实。
"""

from __future__ import annotations

from mining_brief.agent.narratives import (
    NARRATE_NODE,
    extract_lead,
    lead_is_grounded,
    narrative_payload,
)
from mining_brief.contracts import Fact, Section, SectionKey


def _section(**overrides: object) -> Section:
    base: dict[str, object] = {
        "key": SectionKey.PRICES,
        "title": "价格走势",
        "as_of": "2026-10-08",
        "facts": (
            Fact(text="锂（GFEX 碳酸锂主力合约）：收盘 117300.0 元/吨。", citation=1),
            Fact(text="铜（LME 3个月）：收盘 10850.0 美元/吨。", citation=None),
        ),
        "note": None,
    }
    base.update(overrides)
    return Section(**base)  # type: ignore[arg-type]


def test_the_payload_is_only_this_section_and_no_citation_numbers() -> None:
    """喂给模型的**就是**这一节：别节的东西进不来，`[n]` 也不该看见。

    为什么连 `[n]` 都要挡：那是我们给来源清单编的内部号。让模型看见，它就会在导读里
    复述 —— 而读者看到 "见 [1]" 会以为导读在引权威原文，导读**从来不是**。
    """
    payload = narrative_payload(_section())

    assert payload["title"] == "价格走势"
    assert payload["as_of"] == "2026-10-08"
    assert len(payload["facts"]) == 2
    assert "储" not in str(payload), "别节的关键词不该出现在这里的任何角落"
    assert "citation" not in str(payload), "内部编号不该喂给模型"
    assert "117300.0" in str(payload), "该有的数字一个都不能少 —— 否则导读反而写不出来了"


def test_the_node_name_is_the_replay_key_prefix() -> None:
    """回放 key 以节点名打头（`narrate:<哈希>`）。改名字 = 全部录播失效，所以钉住。"""
    assert NARRATE_NODE == "narrate"


def test_extract_lead_takes_the_string_and_rejects_everything_else() -> None:
    """取不到就是 `None` —— 由调用方按"这一节没有导读"处理，不在这里猜。"""
    assert extract_lead('{"lead": "  锂价收于 117300 元/吨。  "}') == "锂价收于 117300 元/吨。"
    for bad in ("不是 JSON", "[1, 2]", '{"lead": ""}', '{"lead": 42}', '{"lead": null}', "{}"):
        assert extract_lead(bad) is None, f"{bad!r} 不该被当成一句导读"


# ---------------------------------------------------------------------------
# 闸门：认识越界
# ---------------------------------------------------------------------------


def test_a_number_the_section_never_had_is_caught() -> None:
    """凭空多出来的数字 —— 这是"模型不参与事实生成"最容易被戳破的地方。

    导读里写一个该节没有的价格，读者没有任何办法分辨它是不是真的：它和真数字
    长得一模一样，还排在同样一个位置。
    """
    payload = narrative_payload(_section())
    assert not lead_is_grounded("锂价收于 120000 元/吨，铜价持稳。", payload)
    assert lead_is_grounded("锂价收于 117300.0 元/吨，铜价持稳。", payload)


def test_an_outside_company_name_is_caught() -> None:
    """外来的拉丁词（公司名 / 交易所 / 术语代号）必须逐字出自该节数据。"""
    payload = narrative_payload(_section())
    assert not lead_is_grounded("对比 Albemarle 的报价，锂价持稳。", payload)
    assert lead_is_grounded("GFEX 的锂价与 LME 的铜价今日各有一笔。", payload)


def test_an_invented_date_is_caught() -> None:
    """日期也是数字。写一个该节没有的日期，同样是编。"""
    payload = narrative_payload(_section())
    assert not lead_is_grounded("数据截至 2026-09-01。", payload)
    assert lead_is_grounded("本节数据时点为 2026-10-08。", payload)


# ---------------------------------------------------------------------------
# 闸门：不误伤同一条数据的另一种写法
# ---------------------------------------------------------------------------


def test_the_same_number_written_differently_is_not_a_new_fact() -> None:
    """千分位不是新事实。`117,300` 与 `117300.0` 是同一条数据。

    不这么放宽的话，闸门会开始**惩罚正确的措辞** —— 而一个会误伤的闸门迟早被关掉，
    那才是这条纪律真正的死法。
    """
    payload = narrative_payload(_section())
    assert lead_is_grounded("锂价收于 117,300 元/吨。", payload)


def test_the_same_word_in_another_case_is_not_a_new_fact() -> None:
    """大小写不是新事实：模型写 `Gfex` 不该被判成编了个新机构。"""
    payload = narrative_payload(_section())
    assert lead_is_grounded("Gfex 与 lme 各有一笔。", payload)


def test_nothing_but_plumbing_is_rejected() -> None:
    """全中文、不含任何数字与拉丁词的导读**总是**通过。

    **这道闸门挡不住什么，写在这里免得它被当成万能保证**：模型凭空编一个中文实体名
    （"某钾盐矿"），字符串包含关系看不出来。挡它靠的是"输入只有这一节数据"加上
    prompt 的封闭性 —— 闸门是**必要不充分**的一道，不是全部。
    """
    payload = narrative_payload(_section())
    assert lead_is_grounded("本节只有两个品种的收盘价，看不出走势。", payload)
