"""新闻分流的**关键词规则** —— 数据，不是逻辑（ADR-0008）。

分流把新闻流劈成互补的两类（CONTEXT.md）：

- `mining_rights`（矿权动态）：与矿权取得、变更、争议、政策相关。
- `general`（新闻摘要）：其余全部。

边界靠**用词**划，不靠语义判断 —— 这是它可单测（A5）、且不会被模型的随机性
污染的唯一方式。收录一条词就是缩窄一次 `general`，所以宁可窄：判错了只是把
一条新闻挪进另一节，判宽了会让「矿权动态」节失去存在意义。

_Avoid_：行业动态、政策新闻 —— 都太宽，装进来就等于取消这条分界线。
"""

from __future__ import annotations

#: 标的是"这份矿权本身的状态变了"：许可、权属、争议、监管动作。
MINING_RIGHTS_TERMS: tuple[str, ...] = (
    # 权利本身
    "mining right",
    "mineral right",
    "mining lease",
    "mining licence",
    "mining license",
    "exploration licence",
    "exploration license",
    "exploration permit",
    "prospecting licence",
    "prospecting license",
    "tenement",
    "concession",
    # 权属变更
    "licence granted",
    "license granted",
    "permit granted",
    "licence revoked",
    "license revoked",
    "permit revoked",
    "licence suspended",
    "suspension of licence",
    "suspension of license",
    "revoked",
    "revocation",
    "expropriation",
    "nationalisation",
    "nationalization",
    # 争议与监管
    "court ruling",
    "court order",
    "injunction",
    "tribunal",
    "arbitration",
    "litigation",
    "lawsuit",
    "legal challenge",
    "title dispute",
    "native title",
    "land access",
    "land rights",
    "regulator",
    "regulatory approval",
    "government approval",
    "environmental approval",
    "moratorium",
    "mining ban",
    "freeze on",
)

#: 出现这些词时即便命中了上面的词也不算矿权动态 —— 它们是别的题材。
#: 目前为空集，但把它显式写出来是为了让"要不要加例外"成为一个需要论证的决定，
#: 而不是随手往关键词表里塞词。
MINING_RIGHTS_EXCLUDES: tuple[str, ...] = ()
