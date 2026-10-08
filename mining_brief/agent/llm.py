"""LLM 层：`live` 与 `replay` 两个实现，形状对齐 ADR-0003 的数据源两段式。

回放的 key 是 `(节点名, 关键输入字段的规范化哈希)` —— 哈希的是**输入数据**
（`request_text` / `slots` / 冻结的 sections），**不是 prompt**（ADR-0009）。

两条硬规则：

1. **回放时查不到 key 直接报错，绝不 fallback 到真实调用。**
2. 数据层与 LLM 层用两个独立开关 —— 调一句导读的措辞不该被迫把铜价源切到真实抓取。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from mining_brief.config.logging import get_logger
from mining_brief.config.settings import Settings
from mining_brief.errors import ReplayMiss

log = get_logger(__name__)


class LLMError(RuntimeError):
    """LLM 调用失败。节点按 PRD §6.2 的分工降级（intent → 缺省槽位，narrate → 不写导读）。"""


class LLMReplayMiss(ReplayMiss):
    """回放时查不到这个 key 的录播。

    **刻意不继承 `LLMError`。** `parse_intent` / `resolve_entities` 捕获 `LLMError`
    会降级为缺省槽位 —— 对"模型这次没答上来"是对的，对"我们忘了重录"是错的：
    后者会让一份**按缺省值出的**日报看起来像一次正常执行。回放缺录播是开发期的
    不变量被打破，就该一路炸到 CLI（ADR-0009）。
    """


def normalize(value: Any) -> Any:
    """把要哈希的输入规范化：只关心**数据**，不关心键序、空白与浮点写法。"""
    if isinstance(value, Mapping):
        return {str(key): normalize(item) for key, item in sorted(value.items(), key=_key_order)}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _key_order(item: tuple[Any, Any]) -> str:
    return str(item[0])


def replay_key(node: str, key_input: Mapping[str, Any]) -> str:
    payload = json.dumps(normalize(key_input), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{node}:{digest[:16]}"


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        node: str,
        key_input: Mapping[str, Any],
        system: str,
        user: str,
    ) -> str: ...


class ReplayLLMClient:
    """读 `fixtures/llm/<node>.json`。查不到 key 就抛，不回退真实调用。"""

    def __init__(self, root: Path | str = "fixtures/llm") -> None:
        self.root = Path(root)

    def _table(self, node: str) -> dict[str, str]:
        path = self.root / f"{node}.json"
        if not path.exists():
            raise LLMReplayMiss(
                f"没有 {node} 的录播文件：{path}\n"
                "缺录播时**不回退真实调用**。重录有两条路，各管一段："
                "scripts/record_llm.py 管产品路径的内置样例句；"
                "pytest --record-llm 管测试套件碰到的每一段输入。"
            )
        payload = json.loads(path.read_text("utf-8"))
        return {str(key): str(value) for key, value in payload["responses"].items()}

    async def complete(
        self,
        *,
        node: str,
        key_input: Mapping[str, Any],
        system: str,
        user: str,
    ) -> str:
        del system, user  # 回放不看 prompt —— 这正是它敢按输入哈希索引的前提
        key = replay_key(node, key_input)
        table = self._table(node)
        if key not in table:
            known = "、".join(sorted(table)) or "(空)"
            raise LLMReplayMiss(
                f"{node} 的这个输入没有录播：{key}\n"
                f"该节点已有录播：{known}\n"
                "输入数据变了（或新增了用例）就要重录：scripts/record_llm.py 管内置样例句，"
                "pytest --record-llm 管测试套件。这是刻意的失败而非遗漏 —— 回放不回退真实调用。"
            )
        return table[key]


class LiveLLMClient:
    """真实调用。DeepSeek 的 API 与 OpenAI 兼容，因此复用 openai SDK，只换 base_url。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        recorder: LLMRecorder | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "MINING_LLM_MODE=live 但没有 MINING_LLM_API_KEY。"
                "默认模式不需要 key —— 需要真实调用时请先配好。"
            )
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._recorder = recorder

    async def complete(
        self,
        *,
        node: str,
        key_input: Mapping[str, Any],
        system: str,
        user: str,
    ) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        try:
            response = await client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except Exception as exc:
            raise LLMError(f"{node} 调用失败：{type(exc).__name__}: {exc}") from exc

        content = response.choices[0].message.content or ""
        if self._recorder is not None:
            self._recorder.record(node=node, key_input=key_input, response=content)
        return content


class LLMRecorder:
    """把真实响应写进 `fixtures/llm/<node>.json`，供之后回放。"""

    def __init__(self, root: Path | str = "fixtures/llm") -> None:
        self.root = Path(root)
        self._tables: dict[str, dict[str, str]] = {}

    def record(self, *, node: str, key_input: Mapping[str, Any], response: str) -> None:
        table = self._tables.setdefault(node, self._load(node))
        table[replay_key(node, key_input)] = response
        log.info("llm.recorded", node=node, entries=len(table))

    def flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for node, table in self._tables.items():
            path = self.root / f"{node}.json"
            path.write_text(
                json.dumps(
                    {"node": node, "responses": dict(sorted(table.items()))},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            log.info("llm.flushed", node=node, path=str(path))

    def _load(self, node: str) -> dict[str, str]:
        path = self.root / f"{node}.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text("utf-8"))
        return {str(key): str(value) for key, value in payload["responses"].items()}


#: 进程级的"记录器兜底"。**只给重录用**（`pytest --record-llm`）。
#:
#: 为什么需要它：重录要覆盖的是"测试套件关心的每一段输入"，而那些输入散在几十条
#: 用例里（有的还塞了自己造的新闻），从 `scripts/record_llm.py` 里复现不出来。
#: 让测试**自己**在 live 模式下跑一遍、把它们碰到的每个输入都录下来，录出来的集合
#: 才恰好等于回放需要的集合 —— 少一条，回放就会以 `LLMReplayMiss` 当场指出来。
#:
#: 它默认是 `None`，生产路径永远走不到。
_default_recorder: LLMRecorder | None = None


def set_default_recorder(recorder: LLMRecorder | None) -> None:
    """设置进程级兜底记录器。返回 `None` 即清空。"""
    global _default_recorder
    _default_recorder = recorder


def build_llm_client(
    settings: Settings,
    *,
    fixture_root: Path | str = "fixtures/llm",
    recorder: LLMRecorder | None = None,
) -> LLMClient:
    if settings.llm_mode == "replay":
        return ReplayLLMClient(fixture_root)
    return LiveLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        recorder=recorder or _default_recorder,
    )
