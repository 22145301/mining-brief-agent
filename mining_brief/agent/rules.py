"""风险规则引擎的骨架。

**为什么规则集在这一票（01）是空的、而且空得理直气壮**：每条风险信号都要求
"逐字引到权威公开原文"（PRD §5.2 硬规则 1）。而权威原文必须先由 02 号工单从
ASX Listing Rule 5.16 / JORC 2012 / NI 43-101 里**逐字核对**出来。在核对完成前
往这里填任何一条规则，都等于让模型或我来编一段"看起来像法条"的原文 —— 那正是
这个项目存在的理由所要反对的事。

所以 02 号工单冻结规则集，07 号工单实现触发逻辑；**本票只把接口和"空"这件事
立起来**，让第 5 节的"本次未触发"是一条真实的输出，而不是一个待办占位。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mining_brief.contracts import Hint, RiskSignal

if TYPE_CHECKING:
    from mining_brief.agent.state import BriefState


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


#: 规则集。02 号工单冻结内容，07 号工单接上触发逻辑。
RULES: tuple[Rule, ...] = ()


def evaluate(rules: tuple[Rule, ...], state: BriefState) -> dict[str, Any]:
    """逐条判定。

    返回 `hints` 的口子是留给"够不上逐字引权威原文、但值得提一句"的观察的
    （PRD §5.1）—— 比如只有行业媒体转载而拿不到一手文件时。本票为空。
    """
    signals: list[RiskSignal] = []
    hints: list[Hint] = []

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

    return {"signals": tuple(signals), "hints": tuple(hints)}
