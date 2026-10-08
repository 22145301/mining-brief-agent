"""来源清单的装配与校验。

PRD §5.2 的两条硬规则在这里变成代码：

1. **逐字引用**：`Citation` 的四个文本字段全部**原样搬运**工具返回值，不允许任何
   转述后补链接。这也是为什么可被引用的字段一律是 ISO 字符串而不是 `datetime`
   （见 `contracts/__init__.py`）—— 字符串搬运天然逐字相同。
2. **引用可验证**：每个事实标 `[n]`，`[n]` 必须能在来源清单里找到对应条目。
   由代码校验，不通过即报错。
"""

from __future__ import annotations

from collections.abc import Iterable

from mining_brief.contracts import Citation, CitationReport, Section


class CitationError(RuntimeError):
    """引用校验不通过。**这是代码 bug，不是数据缺失** —— 就该响亮地炸（ADR-0006）。"""


class CitationLedger:
    """按**首次出现顺序**给来源编号。

    编号顺序由装配顺序决定，不用集合 —— 否则同一份数据两次跑出来的编号可能不同，
    端到端断言就没法逐字比对了。
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, str], int] = {}
        self._ordered: list[Citation] = []

    def cite(self, *, kind: str, title: str, url: str, publisher: str, timestamp: str) -> int:
        # 编号去重的键是 (类型, URL, 时间戳)：同一条新闻被两个节点引用不该占两个号。
        key = (kind, url, timestamp)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing

        index = len(self._ordered) + 1
        self._by_key[key] = index
        self._ordered.append(
            Citation(
                index=index,
                kind=kind,  # type: ignore[arg-type]
                title=title,
                url=url,
                publisher=publisher,
                timestamp=timestamp,
            )
        )
        return index

    @property
    def citations(self) -> tuple[Citation, ...]:
        return tuple(self._ordered)


def verify(sections: Iterable[Section], citations: tuple[Citation, ...]) -> CitationReport:
    """校验 `[n]` 与来源清单对得上。不通过就抛。"""
    declared = tuple(citation.index for citation in citations)

    if sorted(declared) != list(range(1, len(declared) + 1)):
        raise CitationError(f"来源清单的编号必须是从 1 开始的连续整数，实际是 {declared}")

    known = set(declared)
    referenced: set[int] = set()
    checked = 0
    for section in sections:
        for fact in section.facts:
            checked += 1
            if fact.citation is None:
                continue
            if fact.citation not in known:
                raise CitationError(
                    f"第「{section.title}」节的事实引用了不存在的来源 [{fact.citation}]："
                    f"{fact.text[:60]}"
                )
            referenced.add(fact.citation)

    orphans = sorted(known - referenced)
    if orphans:
        raise CitationError(f"来源清单里有没被任何事实引用的条目：{[f'[{i}]' for i in orphans]}")

    return CitationReport(ok=True, checked=checked, declared=declared)
