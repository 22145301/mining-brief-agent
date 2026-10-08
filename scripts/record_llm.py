"""录一次真实 LLM 调用，供之后回放（spec.md 的 R3、ADR-0009）。

**只在需要新录播时手工跑**，不进 CI、不进默认测试路径：

    MINING_LLM_API_KEY=... uv run python scripts/record_llm.py

它把 `SAMPLE_REQUESTS` 里每句话都跑一遍完整的图（数据层仍是回放 —— 录 LLM
不该顺带把数据源也切到真实抓取，这正是两个开关分开的意义），记录过程中每个模型
节点的响应，写进 `fixtures/llm/<node>.json`。

**已有的录播不会丢**：`LLMRecorder` 先读旧文件再合并写入，所以加一条新请求不会
让老用例失配。反过来，改了 prompt 却没重录，回放时就会以 `LLMReplayMiss` 报错 ——
那是刻意的失败，不是遗漏。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mining_brief.agent.llm import LLMRecorder
from mining_brief.agent.pipeline import run_brief
from mining_brief.config.logging import configure_logging
from mining_brief.config.settings import Settings

#: 每句话都覆盖模型路径上的一段：R1 走完两个模型节点，R2 只走 `parse_intent`，
#: R3 走 `parse_intent` + `resolve_entities`（模型会给出 null，档案也匹配不上）。
SAMPLE_REQUESTS: tuple[str, ...] = (
    "给我生成一份关于 Pilbara 锂矿的今日简报",
    "帮我预测一下明天铜价会涨吗",
    "看看 Escondida 铜矿最近 3 天",
)

LLM_FIXTURE_ROOT = Path("fixtures/llm")


async def main() -> None:
    configure_logging()
    settings = Settings.from_env()

    if not settings.llm_api_key:
        raise SystemExit(
            "缺少 MINING_LLM_API_KEY —— 录播需要一次真实调用。"
            "它不会被写进任何文件：录下来的是模型的**响应**，不是密钥。"
        )

    recorder = LLMRecorder(LLM_FIXTURE_ROOT)
    # 只把 LLM 层切到 live；数据层保持 settings 原样（默认 replay）。
    from dataclasses import replace

    live_llm = replace(settings, llm_mode="live")

    for request in SAMPLE_REQUESTS:
        result = await run_brief(request, settings=live_llm, recorder=recorder, write=False)
        mode = "拒答" if result.refusal else "出报"
        sys.stdout.write(f"ok  {mode}  {request}\n")

    recorder.flush()
    for path in sorted(LLM_FIXTURE_ROOT.glob("*.json")):
        sys.stdout.write(f"写好了 {path}\n")


if __name__ == "__main__":
    asyncio.run(main())
