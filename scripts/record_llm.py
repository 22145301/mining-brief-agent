"""录一次真实 LLM 调用，供之后回放（spec.md 的 R3、ADR-0009）。

**只在需要新录播时手工跑**，不进 CI、不进默认测试路径：

    MINING_LLM_API_KEY=... uv run python scripts/record_llm.py
    MINING_LLM_API_KEY=... uv run python scripts/record_llm.py --only "今日简报"   # 只补一句

它把 `SAMPLE_REQUESTS` 里每句话都跑一遍完整的图（数据层仍是回放 —— 录 LLM
不该顺带把数据源也切到真实抓取，这正是两个开关分开的意义），记录过程中每个模型
节点的响应，写进 `fixtures/llm/<node>.json`。

**已有的录播不会丢**：`LLMRecorder` 先读旧文件再合并写入，所以加一条新请求不会
让老用例失配。反过来，改了 prompt 却没重录，回放时就会以 `LLMReplayMiss` 报错 ——
那是刻意的失败，不是遗漏。

**这个脚本只覆盖产品路径上的这几句样例句。** 测试套件喂进去的数据是几十条用例各造
各的（导读那一步尤其），从这三句话复现不出来 —— 那一半由 `pytest --record-llm`
负责，它让测试**自己**在 live 模式下跑一遍，录下的集合才恰好等于回放需要的集合。
两个入口合起来才是完整的重录动作。
"""

from __future__ import annotations

import argparse
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
#: R4 不指定矿山与品种 —— 范围落到**全部档案**（User Story 3），于是价格那一节
#: 同时出现锂 / 铜 / 铁矿石三行、三个数据时点各不相同，铜那行还带延迟标注。
#: 这四句就是**离线可问的全部说法**：回放只认录过的输入（ADR-0009）。
SAMPLE_REQUESTS: tuple[str, ...] = (
    "给我生成一份关于 Pilbara 锂矿的今日简报",
    "帮我预测一下明天铜价会涨吗",
    "看看 Escondida 铜矿最近 3 天",
    "给我生成一份今日简报",
)

LLM_FIXTURE_ROOT = Path("fixtures/llm")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        metavar="子串",
        help=(
            "只录匹配这个子串的样例句。**加一条新样例时用它**：不带 --only 会把全部"
            "样例句重跑一遍，既有录播被真实响应覆盖 —— 产物哈希与已验证据都绑在那些"
            "字节上，不该为了添一句新话顺带把它们换掉。"
        ),
    )
    return parser.parse_args(argv)


def _selected(only: str | None) -> tuple[str, ...]:
    """选出本次要录的样例句。**整句相等优先于子串**。

    子串匹配会一次带出多句（"今日简报"同时命中"…关于 Pilbara 锂矿的今日简报"），
    于是想补一句的代价变成顺手重录另一句 —— 正是 `--only` 要避免的事。所以：能整句
    对上就只录那一句；对不上再退回子串，并把选中的句子打出来让人自己看。
    """
    if not only:
        return SAMPLE_REQUESTS
    exact = tuple(request for request in SAMPLE_REQUESTS if request == only)
    picked = exact or tuple(request for request in SAMPLE_REQUESTS if only in request)
    if not picked:
        raise SystemExit(f"--only {only!r} 没匹配上任何样例句：{SAMPLE_REQUESTS}")
    return picked


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
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

    selected = _selected(args.only)
    sys.stdout.write(f"本次录 {len(selected)} 句：{'、'.join(selected)}\n")

    for request in selected:
        result = await run_brief(request, settings=live_llm, recorder=recorder, write=False)
        mode = "拒答" if result.refusal else "出报"
        sys.stdout.write(f"ok  {mode}  {request}\n")

    recorder.flush()
    for path in sorted(LLM_FIXTURE_ROOT.glob("*.json")):
        sys.stdout.write(f"写好了 {path}\n")


if __name__ == "__main__":
    asyncio.run(main())
