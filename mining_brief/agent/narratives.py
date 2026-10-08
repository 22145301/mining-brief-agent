"""导读的**输入构造**与**接地校验**（工单 08）—— 与 `nodes.narrate` 分开放。

分开的理由不是行数，是**可测性**：一句导读要么"只用了该节已经有的东西"，要么没有，
这件事应当是可以在不跑模型、不跑图的情况下逐条断言的。把它埋在节点里，"导读不写
事实"就只能靠跑一遍全图去撞。

两件事在这里：

- `narrative_payload` —— 喂给模型的**就是**该节冻结后的数据。模型看不到别的，
  于是它也写不出别的。
- `lead_is_grounded` —— 导读落进产物**之前**的闸门。模型越界时**丢掉整句**，
  而不是"修一下再用"：一句被我们改写过的导读，就不再是它写的那句了。
"""

from __future__ import annotations

import json
import re
from typing import Any

from mining_brief.contracts import Section

#: 图里这个节点的名字。回放 key 以它打头（`narrate:<哈希>`）。
NARRATE_NODE = "narrate"

#: 数字（含千分位与小数）。`117,300` 与 `117300.0` 是同一条数据的不同写法，
#: 见 `_numbers_agree`。
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

#: 拉丁词（公司名、交易所代码、报告体系代号）。**中文实体名不在此列** —— 见下方
#: "这道闸门挡不住什么"。
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{2,}")


def narrative_payload(section: Section) -> dict[str, Any]:
    """一节导读的全部输入 —— 就是这一节已经冻结的样子。

    刻意**不含** `citation` 序号：那是我们内部给来源清单的编号，模型不该看见，
    更不该在导读里复述（复述出来读者会以为导读在引权威原文）。

    `key_input` 与 `user` prompt 用**同一个** dict，不是巧合：回放的 key 落在
    输入数据上（ADR-0009），而"输入数据"与"模型看到的东西"若是两份，录播就会在
    某个没人注意的日子失配。
    """
    return {
        "section": str(section.key),
        "title": section.title,
        "as_of": section.as_of,
        "facts": [fact.text for fact in section.facts],
        "note": section.note,
    }


def render_payload(payload: dict[str, Any]) -> str:
    """把 payload 渲染成给模型看的那段文字。"""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_lead(raw: str) -> str | None:
    """从模型响应里取那一句导读；取不到就是 `None`（调用方按"没有导读"处理）。"""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    lead = parsed.get("lead")
    if not isinstance(lead, str) or not lead.strip():
        return None
    return lead.strip()


def _numbers_agree(number: str, haystack: str) -> bool:
    """`117,300` 与 `117300` 是同一条数据 —— 千分位不是新事实。"""
    return number in haystack or number.replace(",", "") in haystack


def lead_is_grounded(lead: str, payload: dict[str, Any]) -> bool:
    """导读里的**每一个数字、每一个拉丁词**都必须逐字出现在该节数据里。

    这是本票最要紧的那条验收（"导读里不出现任何不在该节数据里的数字或实体"）
    的**执行者**：模型在这条链上没有任何生成事实的机会，靠的不是 prompt 里那句
    客气的"硬约束"，而是这道落盘前的闸门。

    **这道闸门挡不住什么**（写清楚，免得它被当成万能保证）：中文实体名。模型凭空
    写一个"某钾盐矿"出来，字符串包含关系是看不出来的 —— 那要靠"输入只有这一节
    数据"加上 prompt 的封闭性。所以它是**必要不充分**的一道闸门，不是全部。
    """
    haystack = render_payload(payload)
    return all(_numbers_agree(number, haystack) for number in _NUMBER.findall(lead)) and all(
        word.lower() in haystack.lower() for word in _LATIN_WORD.findall(lead)
    )
